from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import uuid
import hashlib

app = FastAPI()

# Yhdistetään SQLite-tietokantaan. check_same_thread=False sallii saman yhteyden eri säikeistä.
db = sqlite3.connect("kipa.db", check_same_thread=False)
db.row_factory = sqlite3.Row  # palauttaa rivit dict-tyylisesti nimen perusteella

# Luodaan taulut jos niitä ei vielä ole
db.executescript("""
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL UNIQUE,
  token TEXT UNIQUE NOT NULL,
  salasana_hash TEXT
);
CREATE TABLE IF NOT EXISTS rastit (
  id INTEGER PRIMARY KEY,
  numero TEXT NOT NULL UNIQUE,
  jarjestys INTEGER NOT NULL DEFAULT 0,
  kesto_min INTEGER NOT NULL DEFAULT 10,
  siirtyma_min INTEGER NOT NULL DEFAULT 5
);
CREATE TABLE IF NOT EXISTS leimaukset (
  id INTEGER PRIMARY KEY,
  kayttaja TEXT NOT NULL,
  numero TEXT NOT NULL,
  vartio TEXT NOT NULL,
  jasenet INTEGER NOT NULL,
  aika TEXT NOT NULL,
  tyyppi TEXT NOT NULL DEFAULT 'sisaan'
);
CREATE TABLE IF NOT EXISTS vartiot (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL,
  jasenet INTEGER NOT NULL,
  token TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
  id INTEGER PRIMARY KEY,
  kayttajanimi TEXT NOT NULL UNIQUE,
  salasana_hash TEXT NOT NULL
);
""")

# Migraatio: poistetaan virheellisesti lisätty rastinumero users-taulusta
try:
    db.execute("ALTER TABLE users DROP COLUMN rastinumero")
    db.commit()
except Exception:
    pass

# Migraatio: lisätään salasana_hash users-tauluun jos puuttuu
try:
    db.execute("ALTER TABLE users ADD COLUMN salasana_hash TEXT")
    db.commit()
except Exception:
    pass

# Migraatio: lisätään puuttuvat sarakkeet vanhoihin tietokantoihin (ALTER TABLE epäonnistuu hiljaa jos sarake on jo olemassa)
for col, definition in [
    ("tyyppi", "TEXT NOT NULL DEFAULT 'sisaan'"),
    ("jarjestys", "INTEGER NOT NULL DEFAULT 0"),
    ("kesto_min", "INTEGER NOT NULL DEFAULT 10"),
    ("siirtyma_min", "INTEGER NOT NULL DEFAULT 5"),
]:
    try:
        db.execute(f"ALTER TABLE leimaukset ADD COLUMN {col} {definition}")
        db.commit()
    except Exception:
        pass
    try:
        db.execute(f"ALTER TABLE rastit ADD COLUMN {col} {definition}")
        db.commit()
    except Exception:
        pass

# Ladataan käyttäjien tokenit muistiin käynnistyksen yhteydessä nopean autentikoinnin vuoksi
sessions: dict = {
    row["token"]: {"nimi": row["nimi"]}
    for row in db.execute("SELECT token, nimi FROM users").fetchall()
}

# Admin-sessiot pidetään pelkästään muistissa — palvelimen uudelleenkäynnistys kirjaa adminit ulos
admin_sessions: set = set()


def hash_salasana(salasana: str) -> str:
    # Hashataan salasana SHA-256:lla ennen tallennusta
    return hashlib.sha256(salasana.encode()).hexdigest()


def vaadi_admin(x_admin_token: str = Header(None)):
    # Tarkistaa että pyynnössä on voimassa oleva admin-token, muuten 403
    if not x_admin_token or x_admin_token not in admin_sessions:
        raise HTTPException(status_code=403, detail="Vaatii admin-oikeudet")


# ── Pyyntömallit ──────────────────────────────────────────────────────────────

class UserIn(BaseModel):
    nimi: str


class LoginIn(BaseModel):
    nimi: str
    salasana: str


class AsetaSalasanaIn(BaseModel):
    nimi: str
    salasana: str


class LeimausIn(BaseModel):
    token: str
    rastinumero: str
    vartio: str
    jasenet: int
    aika: str
    tyyppi: str = "sisaan"


class VartioIn(BaseModel):
    nimi: str
    jasenet: int


class RastiIn(BaseModel):
    numero: str
    kesto_min: int = 10
    siirtyma_min: int = 5


class RastiJarjestysIn(BaseModel):
    jarjestys: list[int]  # lista rasti-id:istä halutussa järjestyksessä


class AdminIn(BaseModel):
    kayttajanimi: str
    salasana: str


# ── Staattiset sivut ──────────────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse("static/index.html")

@app.get("/rasti.html")
def rasti_page():
    return FileResponse("static/rasti.html")

@app.get("/leimaus.html")
def leimaus_page():
    return FileResponse("static/leimaus.html")

@app.get("/data.html")
def data_page():
    return FileResponse("static/data.html")

@app.get("/qr.html")
def qr_page():
    return FileResponse("static/qr.html")

@app.get("/tilanne.html")
def tilanne_page():
    return FileResponse("static/tilanne.html")

@app.get("/rastit.html")
def rastit_page():
    return FileResponse("static/rastit.html")

@app.get("/style.css")
def style():
    return FileResponse("static/style.css")

@app.get("/admin.html")
def admin_page():
    return FileResponse("static/admin.html")


# ── Admin-hallinta ────────────────────────────────────────────────────────────

@app.post("/api/admin/setup")
def admin_setup(a: AdminIn):
    # Luo ensimmäisen adminin — toimii vain jos admintaulu on tyhjä
    maara = db.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if maara > 0:
        raise HTTPException(status_code=403, detail="Admin on jo luotu")
    if not a.kayttajanimi.strip() or not a.salasana:
        raise HTTPException(status_code=400, detail="Käyttäjänimi ja salasana vaaditaan")
    db.execute("INSERT INTO admins (kayttajanimi, salasana_hash) VALUES (?,?)",
               (a.kayttajanimi.strip(), hash_salasana(a.salasana)))
    db.commit()
    return {"ok": True}


@app.get("/api/admin/setup_tarvitaan")
def admin_setup_tarvitaan():
    # Palauttaa tarvitaan:true jos yhtään adminia ei ole luotu — käytetään setup-sivun näyttämiseen
    maara = db.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    return {"tarvitaan": maara == 0}


@app.post("/api/admin/login")
def admin_login(a: AdminIn):
    # Kirjaa adminin sisään ja palauttaa session-tokenin muistiin tallennettavaksi
    row = db.execute(
        "SELECT salasana_hash FROM admins WHERE kayttajanimi=?", (a.kayttajanimi.strip(),)
    ).fetchone()
    if not row or row["salasana_hash"] != hash_salasana(a.salasana):
        raise HTTPException(status_code=401, detail="Väärä käyttäjänimi tai salasana")
    token = str(uuid.uuid4())
    admin_sessions.add(token)
    return {"admin_token": token}


@app.post("/api/admin/luo")
def luo_admin(a: AdminIn, x_admin_token: str = Header(None)):
    # Luo uuden adminin — vaatii olemassa olevan admin-session
    vaadi_admin(x_admin_token)
    if not a.kayttajanimi.strip() or not a.salasana:
        raise HTTPException(status_code=400, detail="Käyttäjänimi ja salasana vaaditaan")
    try:
        db.execute("INSERT INTO admins (kayttajanimi, salasana_hash) VALUES (?,?)",
                   (a.kayttajanimi.strip(), hash_salasana(a.salasana)))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Käyttäjänimi on jo käytössä")
    return {"ok": True}


# ── Käyttäjät ─────────────────────────────────────────────────────────────────

@app.get("/api/user/tarkista")
def tarkista_user(nimi: str):
    # Tarkistaa onko käyttäjä olemassa ja onko salasana asetettu — käytetään kirjautumislomakkeen vaiheistukseen
    row = db.execute("SELECT salasana_hash FROM users WHERE nimi=?", (nimi.strip(),)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Käyttäjää ei löydy — pyydä adminia luomaan tunnus")
    return {"salasana_asetettu": row["salasana_hash"] is not None}


@app.post("/api/login")
def login(l: LoginIn):
    # Kirjaa käyttäjän sisään nimellä ja salasanalla
    row = db.execute("SELECT token, nimi, salasana_hash FROM users WHERE nimi=?", (l.nimi.strip(),)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Käyttäjää ei löydy")
    if row["salasana_hash"] != hash_salasana(l.salasana):
        raise HTTPException(status_code=401, detail="Väärä salasana")
    sessions[row["token"]] = {"nimi": row["nimi"]}
    return {"token": row["token"], "nimi": row["nimi"]}


@app.post("/api/user/aseta_salasana")
def aseta_salasana(a: AsetaSalasanaIn):
    # Asettaa salasanan ensimmäistä kertaa — toimii vain jos salasanaa ei ole vielä asetettu
    row = db.execute("SELECT id, token, nimi, salasana_hash FROM users WHERE nimi=?", (a.nimi.strip(),)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Käyttäjää ei löydy")
    if row["salasana_hash"] is not None:
        raise HTTPException(status_code=400, detail="Salasana on jo asetettu — kirjaudu normaalisti")
    if not a.salasana:
        raise HTTPException(status_code=400, detail="Salasana vaaditaan")
    db.execute("UPDATE users SET salasana_hash=? WHERE id=?", (hash_salasana(a.salasana), row["id"]))
    db.commit()
    sessions[row["token"]] = {"nimi": row["nimi"]}
    return {"token": row["token"], "nimi": row["nimi"]}


@app.post("/api/user")
def create_user(u: UserIn, x_admin_token: str = Header(None)):
    # Luo uuden käyttäjän (ilman salasanaa) — vain admin voi luoda käyttäjiä
    vaadi_admin(x_admin_token)
    if not u.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    nimi = u.nimi.strip()
    existing = db.execute("SELECT id FROM users WHERE nimi=?", (nimi,)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Käyttäjä on jo olemassa")
    token = str(uuid.uuid4())
    db.execute("INSERT INTO users (nimi, token) VALUES (?, ?)", (nimi, token))
    db.commit()
    return {"ok": True, "nimi": nimi}


@app.get("/api/users")
def get_users(x_admin_token: str = Header(None)):
    # Palauttaa kaikki käyttäjät adminille — näyttää onko salasana asetettu
    vaadi_admin(x_admin_token)
    rows = db.execute("SELECT id, nimi, salasana_hash FROM users ORDER BY nimi").fetchall()
    return [{"id": r["id"], "nimi": r["nimi"], "salasana_asetettu": r["salasana_hash"] is not None} for r in rows]


@app.post("/api/user/{user_id}/reset_salasana")
def reset_salasana(user_id: int, x_admin_token: str = Header(None)):
    # Nollaa käyttäjän salasanan — seuraavalla kirjautumisella pyydetään valitsemaan uusi
    vaadi_admin(x_admin_token)
    row = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Käyttäjää ei löydy")
    db.execute("UPDATE users SET salasana_hash=NULL WHERE id=?", (user_id,))
    db.commit()
    return {"ok": True}


@app.delete("/api/user/{user_id}")
def delete_user(user_id: int, x_admin_token: str = Header(None)):
    # Poistaa käyttäjän
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    return {"ok": True}


# ── Rastit ────────────────────────────────────────────────────────────────────

@app.get("/api/rastit")
def get_rastit():
    # Palauttaa kaikki rastit järjestysnumeron mukaan
    rows = db.execute("SELECT id, numero, jarjestys, kesto_min, siirtyma_min FROM rastit ORDER BY jarjestys, id").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/rasti")
def create_rasti(r: RastiIn, x_admin_token: str = Header(None)):
    # Luo uuden rastin ja asettaa sen listan viimeiseksi
    vaadi_admin(x_admin_token)
    if not r.numero.strip():
        raise HTTPException(status_code=400, detail="Rastinumero vaaditaan")
    max_j = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM rastit").fetchone()[0]
    try:
        db.execute("INSERT INTO rastit (numero, jarjestys, kesto_min, siirtyma_min) VALUES (?,?,?,?)",
                   (r.numero.strip(), max_j + 1, r.kesto_min, r.siirtyma_min))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Rasti on jo olemassa")
    return {"ok": True}


@app.post("/api/rastit/jarjestys")
def paivita_jarjestys(data: RastiJarjestysIn, x_admin_token: str = Header(None)):
    # Tallentaa rastien uuden järjestyksen drag-and-drop-listan perusteella
    vaadi_admin(x_admin_token)
    for i, rasti_id in enumerate(data.jarjestys):
        db.execute("UPDATE rastit SET jarjestys=? WHERE id=?", (i, rasti_id))
    db.commit()
    return {"ok": True}


@app.put("/api/rasti/{rasti_id}")
def update_rasti(rasti_id: int, r: RastiIn, x_admin_token: str = Header(None)):
    # Päivittää rastin nimen ja aika-arviot
    vaadi_admin(x_admin_token)
    db.execute("UPDATE rastit SET numero=?, kesto_min=?, siirtyma_min=? WHERE id=?",
               (r.numero.strip(), r.kesto_min, r.siirtyma_min, rasti_id))
    db.commit()
    return {"ok": True}


@app.delete("/api/rasti/{rasti_id}")
def delete_rasti(rasti_id: int, x_admin_token: str = Header(None)):
    # Poistaa rastin
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM rastit WHERE id=?", (rasti_id,))
    db.commit()
    return {"ok": True}


# ── Leimaukset ────────────────────────────────────────────────────────────────

@app.post("/api/leimaus")
def leimaus(l: LeimausIn):
    # Tallentaa sisään- tai ulosleimauksen. Estää kaksoisleimauksen sisään ilman välistä ulosta.
    session = sessions.get(l.token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    if not l.vartio.strip():
        raise HTTPException(status_code=400, detail="Vartion nimi vaaditaan")
    if not l.rastinumero.strip():
        raise HTTPException(status_code=400, detail="Rastinumero vaaditaan")
    if l.tyyppi not in ("sisaan", "ulos"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    if l.tyyppi == "sisaan":
        viimeisin = db.execute(
            "SELECT numero, tyyppi FROM leimaukset WHERE vartio=? ORDER BY id DESC LIMIT 1",
            (l.vartio.strip(),)
        ).fetchone()
        if viimeisin and viimeisin["tyyppi"] == "sisaan":
            raise HTTPException(status_code=409, detail=f"{l.vartio.strip()} on jo rastilla {viimeisin['numero']} — leimaa ensin ulos")
    db.execute(
        "INSERT INTO leimaukset (kayttaja, numero, vartio, jasenet, aika, tyyppi) VALUES (?,?,?,?,?,?)",
        (session["nimi"], l.rastinumero.strip(), l.vartio.strip(), l.jasenet, l.aika, l.tyyppi),
    )
    db.commit()
    return {"ok": True}


@app.get("/api/aktiiviset")
def aktiiviset(numero: str):
    # Palauttaa vartiot jotka ovat tällä hetkellä sisään leimattuina tietylle rastille.
    # Subquery varmistaa että otetaan vain viimeisin leimaus per vartio+rasti-pari.
    rows = db.execute("""
        SELECT vartio, jasenet, aika FROM leimaukset l1
        WHERE numero = ? AND tyyppi = 'sisaan'
        AND id = (
            SELECT MAX(id) FROM leimaukset l2
            WHERE l2.vartio = l1.vartio AND l2.numero = l1.numero
        )
        ORDER BY id DESC
    """, (numero,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/data")
def get_data():
    # Palauttaa kaikki leimaukset uusimmasta vanhimpaan — käytetään data.html-näkymässä
    rows = db.execute(
        "SELECT kayttaja, numero, vartio, jasenet, aika, tyyppi FROM leimaukset ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Vartiot ───────────────────────────────────────────────────────────────────

@app.get("/api/vartiot")
def get_vartiot():
    # Palauttaa kaikki vartiot aakkosjärjestyksessä
    rows = db.execute("SELECT id, nimi, jasenet, token FROM vartiot ORDER BY nimi").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/vartio")
def create_vartio(v: VartioIn, x_admin_token: str = Header(None)):
    # Luo uuden vartion ja generoi sille QR-koodia varten uniikin tokenin
    vaadi_admin(x_admin_token)
    if not v.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    token = str(uuid.uuid4())
    db.execute("INSERT INTO vartiot (nimi, jasenet, token) VALUES (?, ?, ?)",
               (v.nimi.strip(), v.jasenet, token))
    db.commit()
    return {"id": db.execute("SELECT last_insert_rowid()").fetchone()[0],
            "nimi": v.nimi.strip(), "jasenet": v.jasenet, "token": token}


@app.put("/api/vartio/{vartio_id}")
def update_vartio(vartio_id: int, v: VartioIn, x_admin_token: str = Header(None)):
    # Päivittää vartion nimen ja jäsenmäärän
    vaadi_admin(x_admin_token)
    if not v.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    db.execute("UPDATE vartiot SET nimi=?, jasenet=? WHERE id=?",
               (v.nimi.strip(), v.jasenet, vartio_id))
    db.commit()
    return {"ok": True}


@app.delete("/api/vartio/{vartio_id}")
def delete_vartio(vartio_id: int, x_admin_token: str = Header(None)):
    # Poistaa vartion
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM vartiot WHERE id=?", (vartio_id,))
    db.commit()
    return {"ok": True}


@app.get("/api/vartio/{token}")
def get_vartio(token: str):
    # Hakee vartion QR-tokenin perusteella — käytetään QR-skannauksen jälkeen nimen täyttöön
    row = db.execute("SELECT nimi, jasenet FROM vartiot WHERE token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Vartiota ei löydy")
    return dict(row)


# ── Siirtymäajat ──────────────────────────────────────────────────────────────

def laske_siirtyma_mediaanit():
    # Laskee mediaanisiirtymäajan jokaiselle rasti→rasti-parille toteutuneiden leimausten perusteella.
    # Palauttaa dict: "A→B" -> {mediaani: float, n: int}. Alle 2 havaintoa ei riitä ennusteeseen.
    from datetime import datetime
    FORMATS = ["%d.%m.%Y klo %H.%M.%S", "%d.%m.%Y %H.%M.%S", "%d.%m.%Y %H:%M:%S"]
    def parse_aika(s):
        for fmt in FORMATS:
            try: return datetime.strptime(s, fmt)
            except: pass
        return None

    vartiot = db.execute("SELECT DISTINCT vartio FROM leimaukset").fetchall()
    siirtymat: dict = {}
    for v in vartiot:
        leimaukset = db.execute(
            "SELECT numero, tyyppi, aika FROM leimaukset WHERE vartio=? ORDER BY id",
            (v["vartio"],)
        ).fetchall()
        for i in range(len(leimaukset) - 1):
            curr, nxt = leimaukset[i], leimaukset[i + 1]
            if curr["tyyppi"] == "ulos" and nxt["tyyppi"] == "sisaan":
                t1, t2 = parse_aika(curr["aika"]), parse_aika(nxt["aika"])
                if t1 and t2:
                    diff = (t2 - t1).total_seconds() / 60
                    if 0 < diff < 300:  # hylätään yli 5 tunnin poikkeamat virheellisinä
                        key = curr["numero"] + "→" + nxt["numero"]
                        siirtymat.setdefault(key, []).append(diff)

    mediaanit = {}
    for key, times in siirtymat.items():
        times.sort()
        n = len(times)
        med = times[n // 2] if n % 2 == 1 else (times[n // 2 - 1] + times[n // 2]) / 2
        mediaanit[key] = {"mediaani": round(med, 1), "n": n}
    return mediaanit


@app.get("/api/siirtyma_mediaanit")
def get_siirtyma_mediaanit():
    # Palauttaa lasketut siirtymämediaanit — käytetään rastit.html-sivulla datan näyttöön
    return laske_siirtyma_mediaanit()


# ── Tilanne ───────────────────────────────────────────────────────────────────

@app.get("/api/tilanne")
def tilanne(numero: str = ""):
    # Palauttaa kaikkien vartioiden tilanteen tietyltä rastilta katsottuna.
    # Status-arvot: rastilla_oma, rastilla_muu, tulossa, matkalla, ei_aloitettu.
    # Jos vartio lähti edelliseltä rastilta, lasketaan arvioitu saapumisaika
    # mediaanin tai manuaalisen arvion perusteella.
    from datetime import datetime, timedelta

    rastit_rows = db.execute("SELECT numero, siirtyma_min FROM rastit ORDER BY jarjestys, id").fetchall()
    rasti_lista = [r["numero"] for r in rastit_rows]
    siirtyma_map = {r["numero"]: r["siirtyma_min"] for r in rastit_rows}
    mediaanit = laske_siirtyma_mediaanit()

    # Selvitetään mikä rasti on järjestyksessä ennen pyydettävää rastia
    prev_rasti = None
    if numero and numero in rasti_lista:
        idx = rasti_lista.index(numero)
        prev_rasti = rasti_lista[idx - 1] if idx > 0 else None

    vartiot_rows = db.execute("SELECT nimi, jasenet FROM vartiot ORDER BY nimi").fetchall()

    result = []
    for v in vartiot_rows:
        last = db.execute(
            "SELECT numero, tyyppi, aika FROM leimaukset WHERE vartio=? ORDER BY id DESC LIMIT 1",
            (v["nimi"],)
        ).fetchone()

        arvioitu_saapuminen = None
        siirtyma_lahde = None

        if not last:
            status = "ei_aloitettu"
            sijainti = None
            aika = None
        elif last["tyyppi"] == "sisaan":
            sijainti = last["numero"]
            aika = last["aika"]
            status = "rastilla_oma" if sijainti == numero else "rastilla_muu"
        else:
            sijainti = None
            aika = last["aika"]
            lahto_rasti = last["numero"]
            if prev_rasti and lahto_rasti == prev_rasti:
                status = "tulossa"
                mediaani_key = lahto_rasti + "→" + numero
                if mediaani_key in mediaanit and mediaanit[mediaani_key]["n"] >= 2:
                    siirtyma = mediaanit[mediaani_key]["mediaani"]
                    siirtyma_lahde = "mediaani"
                else:
                    siirtyma = siirtyma_map.get(lahto_rasti, 5)
                    siirtyma_lahde = "arvio"
                for fmt in ("%d.%m.%Y klo %H.%M.%S", "%d.%m.%Y %H.%M.%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y klo %H.%M"):
                    try:
                        lahto_aika = datetime.strptime(aika, fmt)
                        arvioitu_saapuminen = (lahto_aika + timedelta(minutes=siirtyma)).strftime("%H:%M")
                        break
                    except Exception:
                        pass
            else:
                status = "matkalla"

        result.append({
            "nimi": v["nimi"],
            "jasenet": v["jasenet"],
            "status": status,
            "sijainti": sijainti,
            "aika": aika,
            "arvioitu_saapuminen": arvioitu_saapuminen,
            "siirtyma_lahde": siirtyma_lahde if status == "tulossa" else None,
        })

    return result
