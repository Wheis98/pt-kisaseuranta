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
CREATE TABLE IF NOT EXISTS asetukset (
  avain TEXT PRIMARY KEY,
  arvo TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tehtavat (
  id INTEGER PRIMARY KEY,
  rasti_id INTEGER NOT NULL,
  nimi TEXT NOT NULL,
  tyyppi TEXT NOT NULL CHECK(tyyppi IN ('pisteet','oikein_vaarin','ajanotto')),
  max_pisteet REAL,
  jarjestys INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS osatehtavat (
  id INTEGER PRIMARY KEY,
  tehtava_id INTEGER NOT NULL,
  nimi TEXT NOT NULL,
  tyyppi TEXT NOT NULL CHECK(tyyppi IN ('pisteet','oikein_vaarin','ajanotto')),
  max_pisteet REAL,
  jarjestys INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS suoritukset (
  id INTEGER PRIMARY KEY,
  vartio TEXT NOT NULL,
  rasti_id INTEGER NOT NULL,
  kommentti TEXT,
  luotu TEXT NOT NULL,
  UNIQUE(vartio, rasti_id)
);
CREATE TABLE IF NOT EXISTS tehtava_tulokset (
  id INTEGER PRIMARY KEY,
  suoritus_id INTEGER NOT NULL,
  tehtava_id INTEGER NOT NULL,
  pisteet REAL,
  oikein INTEGER,
  aika_sekuntia REAL,
  paivitetty TEXT NOT NULL,
  UNIQUE(suoritus_id, tehtava_id)
);
CREATE TABLE IF NOT EXISTS osatehtava_tulokset (
  id INTEGER PRIMARY KEY,
  suoritus_id INTEGER NOT NULL,
  osatehtava_id INTEGER NOT NULL,
  pisteet REAL,
  oikein INTEGER,
  aika_sekuntia REAL,
  paivitetty TEXT NOT NULL,
  UNIQUE(suoritus_id, osatehtava_id)
);
CREATE TABLE IF NOT EXISTS kayttaja_pyynnot (
  id INTEGER PRIMARY KEY,
  etunimi TEXT NOT NULL,
  sukunimi TEXT NOT NULL,
  rasti_id INTEGER,
  aika TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rasti_oikeudet (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  rasti_id INTEGER NOT NULL,
  UNIQUE(user_id, rasti_id)
);
CREATE TABLE IF NOT EXISTS oikeus_pyynnot (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  rasti_id INTEGER NOT NULL,
  aika TEXT NOT NULL,
  UNIQUE(user_id, rasti_id)
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
# Migraatio: lisätään pisteytys_kaytos rastit-tauluun
try:
    db.execute("ALTER TABLE rastit ADD COLUMN pisteytys_kaytos INTEGER NOT NULL DEFAULT 1")
    db.commit()
except Exception:
    pass

# Oletusasetus pisteytystilalle jos ei vielä asetettu
db.execute("INSERT OR IGNORE INTO asetukset VALUES ('pisteytys_tila','kaikki_pois')")
db.commit()

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
    uudelleen: bool = False  # True = toinen käynti samalla rastilla hyväksytty


class TehtavaIn(BaseModel):
    rasti_id: int
    nimi: str
    tyyppi: str
    max_pisteet: float | None = None
    jarjestys: int = 0


class OsatehtavaIn(BaseModel):
    tehtava_id: int
    nimi: str
    tyyppi: str
    max_pisteet: float | None = None
    jarjestys: int = 0


class TulosIn(BaseModel):
    suoritus_id: int
    tehtava_id: int | None = None
    osatehtava_id: int | None = None
    pisteet: float | None = None
    oikein: int | None = None
    aika_sekuntia: float | None = None
    token: str | None = None
    aika: str


class SuoritusKommenttiIn(BaseModel):
    kommentti: str | None = None
    token: str | None = None


class AsetusIn(BaseModel):
    arvo: str


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

@app.get("/tehtavat.html")
def tehtavat_page():
    return FileResponse("static/tehtavat.html")

@app.get("/pisteet.html")
def pisteet_page():
    return FileResponse("static/pisteet.html")

@app.get("/tulokset.html")
def tulokset_page():
    return FileResponse("static/tulokset.html")


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
    # Palauttaa kaikki rastit järjestysnumeron mukaan, sisältää pisteytys_aktiivinen-kentän
    asetus = db.execute("SELECT arvo FROM asetukset WHERE avain='pisteytys_tila'").fetchone()
    pisteytys_tila = asetus["arvo"] if asetus else "kaikki_pois"
    rows = db.execute("SELECT id, numero, jarjestys, kesto_min, siirtyma_min, pisteytys_kaytos FROM rastit ORDER BY jarjestys, id").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if pisteytys_tila == "kaikki_paalla":
            d["pisteytys_aktiivinen"] = True
        elif pisteytys_tila == "yksittain":
            d["pisteytys_aktiivinen"] = bool(r["pisteytys_kaytos"])
        else:
            d["pisteytys_aktiivinen"] = False
        result.append(d)
    return result


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
    vartio_row = db.execute("SELECT id FROM vartiot WHERE nimi=?", (l.vartio.strip(),)).fetchone()
    if not vartio_row:
        raise HTTPException(status_code=404, detail=f"Vartiota '{l.vartio.strip()}' ei löydy — pyydä adminia luomaan vartio ensin")
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
        if not l.uudelleen:
            aiempi_ulos = db.execute(
                "SELECT id FROM leimaukset WHERE vartio=? AND numero=? AND tyyppi='ulos'",
                (l.vartio.strip(), l.rastinumero.strip())
            ).fetchone()
            if aiempi_ulos:
                raise HTTPException(status_code=409, detail=f"uudelleen_kaynti:{l.vartio.strip()}")
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
def get_data(token: str = "", numero: str = "", vartio: str = "", x_admin_token: str = Header(None)):
    if x_admin_token and x_admin_token in admin_sessions:
        query = "SELECT id, kayttaja, numero, vartio, jasenet, aika, tyyppi FROM leimaukset WHERE 1=1"
        params: list = []
        if numero:
            query += " AND numero=?"; params.append(numero)
        if vartio:
            query += " AND vartio=?"; params.append(vartio)
        query += " ORDER BY id DESC"
    elif token:
        session = sessions.get(token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
        if not numero:
            raise HTTPException(status_code=400, detail="Rastinumero vaaditaan")
        query = "SELECT id, kayttaja, numero, vartio, jasenet, aika, tyyppi FROM leimaukset WHERE numero=? ORDER BY id DESC"
        params = [numero]
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/leimaus/{leimaus_id}")
def delete_leimaus(leimaus_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM leimaukset WHERE id=?", (leimaus_id,))
    db.commit()
    return {"ok": True}


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

    kaynneet_set = set()
    if numero:
        kaynneet_set = set(row["vartio"] for row in db.execute(
            "SELECT DISTINCT vartio FROM leimaukset WHERE numero=? AND tyyppi='ulos'", (numero,)
        ).fetchall())

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
                sijainti = lahto_rasti

        result.append({
            "nimi": v["nimi"],
            "jasenet": v["jasenet"],
            "status": status,
            "sijainti": sijainti,
            "aika": aika,
            "arvioitu_saapuminen": arvioitu_saapuminen,
            "siirtyma_lahde": siirtyma_lahde if status == "tulossa" else None,
            "kaynut_talla_rastilla": v["nimi"] in kaynneet_set,
        })

    return result


# ── Käyttäjäpyynnöt ───────────────────────────────────────────────────────────

@app.post("/api/kayttaja/pyynto")
def tee_kayttaja_pyynto(data: dict):
    etunimi = (data.get("etunimi") or "").strip()
    sukunimi = (data.get("sukunimi") or "").strip()
    rasti_id = data.get("rasti_id")
    if not etunimi or not sukunimi:
        raise HTTPException(status_code=400, detail="Etu- ja sukunimi vaaditaan")
    from datetime import datetime
    aika = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    db.execute("INSERT INTO kayttaja_pyynnot (etunimi, sukunimi, rasti_id, aika) VALUES (?,?,?,?)",
               (etunimi, sukunimi, rasti_id, aika))
    db.commit()
    return {"ok": True}

@app.get("/api/kayttaja/pyynnot")
def get_kayttaja_pyynnot(x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    rows = db.execute("""
        SELECT p.id, p.etunimi, p.sukunimi, p.rasti_id, r.numero, p.aika
        FROM kayttaja_pyynnot p
        LEFT JOIN rastit r ON r.id=p.rasti_id
        ORDER BY p.id DESC
    """).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/kayttaja/pyynto/{pyynto_id}/hyvaksy")
def hyvaksy_kayttaja_pyynto(pyynto_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    pyynto = db.execute("SELECT * FROM kayttaja_pyynnot WHERE id=?", (pyynto_id,)).fetchone()
    if not pyynto:
        raise HTTPException(status_code=404, detail="Pyyntöä ei löydy")
    nimi = pyynto["etunimi"] + " " + pyynto["sukunimi"]
    if db.execute("SELECT id FROM users WHERE nimi=?", (nimi,)).fetchone():
        raise HTTPException(status_code=409, detail=f"Käyttäjä '{nimi}' on jo olemassa")
    token = str(uuid.uuid4())
    db.execute("INSERT INTO users (nimi, token) VALUES (?,?)", (nimi, token))
    db.commit()
    user = db.execute("SELECT id FROM users WHERE nimi=?", (nimi,)).fetchone()
    if pyynto["rasti_id"] and user:
        db.execute("INSERT OR IGNORE INTO rasti_oikeudet (user_id, rasti_id) VALUES (?,?)",
                   (user["id"], pyynto["rasti_id"]))
        db.commit()
    db.execute("DELETE FROM kayttaja_pyynnot WHERE id=?", (pyynto_id,))
    db.commit()
    return {"ok": True, "nimi": nimi}

@app.delete("/api/kayttaja/pyynto/{pyynto_id}")
def poista_kayttaja_pyynto(pyynto_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM kayttaja_pyynnot WHERE id=?", (pyynto_id,))
    db.commit()
    return {"ok": True}


# ── Käyttöoikeudet ────────────────────────────────────────────────────────────

@app.get("/api/oikeudet")
def get_oikeudet(token: str = ""):
    session = sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto")
    user = db.execute("SELECT id FROM users WHERE token=?", (token,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Tuntematon käyttäjä")
    rows = db.execute("SELECT rasti_id FROM rasti_oikeudet WHERE user_id=?", (user["id"],)).fetchall()
    if not rows:
        return {"kaikki": True, "oikeudet": []}
    return {"kaikki": False, "oikeudet": [r["rasti_id"] for r in rows]}

@app.get("/api/oikeudet/admin")
def get_oikeudet_admin(x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    users = db.execute("SELECT id, nimi FROM users ORDER BY nimi").fetchall()
    result = []
    for u in users:
        rows = db.execute("SELECT rasti_id FROM rasti_oikeudet WHERE user_id=?", (u["id"],)).fetchall()
        result.append({"id": u["id"], "nimi": u["nimi"], "oikeudet": [r["rasti_id"] for r in rows]})
    return result

@app.put("/api/oikeudet/{user_id}")
def set_oikeudet(user_id: int, data: dict, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    rasti_ids = data.get("rasti_ids", [])
    db.execute("DELETE FROM rasti_oikeudet WHERE user_id=?", (user_id,))
    for rid in rasti_ids:
        db.execute("INSERT OR IGNORE INTO rasti_oikeudet (user_id, rasti_id) VALUES (?,?)", (user_id, rid))
    db.commit()
    # Poista hyväksytyt pyynnöt
    if rasti_ids:
        db.execute("DELETE FROM oikeus_pyynnot WHERE user_id=? AND rasti_id IN ({})".format(",".join("?"*len(rasti_ids))), [user_id]+rasti_ids)
        db.commit()
    return {"ok": True}

@app.post("/api/oikeus/pyynto")
def tee_pyynto(data: dict, token: str = ""):
    session = sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto")
    user = db.execute("SELECT id FROM users WHERE token=?", (token,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Tuntematon käyttäjä")
    rasti_id = data.get("rasti_id")
    if not rasti_id:
        raise HTTPException(status_code=400, detail="rasti_id vaaditaan")
    from datetime import datetime
    aika = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    db.execute("INSERT OR IGNORE INTO oikeus_pyynnot (user_id, rasti_id, aika) VALUES (?,?,?)", (user["id"], rasti_id, aika))
    db.commit()
    return {"ok": True}

@app.get("/api/oikeus/pyynnot")
def get_pyynnot(x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    rows = db.execute("""
        SELECT p.id, p.user_id, u.nimi, p.rasti_id, r.numero, p.aika
        FROM oikeus_pyynnot p
        JOIN users u ON u.id=p.user_id
        JOIN rastit r ON r.id=p.rasti_id
        ORDER BY p.id DESC
    """).fetchall()
    return [dict(r) for r in rows]

@app.delete("/api/oikeus/pyynto/{pyynto_id}")
def poista_pyynto(pyynto_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM oikeus_pyynnot WHERE id=?", (pyynto_id,))
    db.commit()
    return {"ok": True}


# ── Asetukset ─────────────────────────────────────────────────────────────────

@app.get("/api/asetukset")
def get_asetukset():
    # Palauttaa kaikki asetukset — käytetään pisteytystilan tarkistukseen
    rows = db.execute("SELECT avain, arvo FROM asetukset").fetchall()
    return {r["avain"]: r["arvo"] for r in rows}


@app.put("/api/asetus/{avain}")
def set_asetus(avain: str, a: AsetusIn, x_admin_token: str = Header(None)):
    # Asettaa tai päivittää asetuksen arvon
    vaadi_admin(x_admin_token)
    db.execute("INSERT OR REPLACE INTO asetukset (avain, arvo) VALUES (?,?)", (avain, a.arvo))
    db.commit()
    return {"ok": True}


@app.put("/api/rasti/{rasti_id}/pisteytys")
def toggle_rasti_pisteytys(rasti_id: int, x_admin_token: str = Header(None)):
    # Vaihtaa rastin pisteytys_kaytos-arvon 0↔1
    vaadi_admin(x_admin_token)
    row = db.execute("SELECT pisteytys_kaytos FROM rastit WHERE id=?", (rasti_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rastia ei löydy")
    uusi = 0 if row["pisteytys_kaytos"] else 1
    db.execute("UPDATE rastit SET pisteytys_kaytos=? WHERE id=?", (uusi, rasti_id))
    db.commit()
    return {"pisteytys_kaytos": uusi}


# ── Tehtävät ──────────────────────────────────────────────────────────────────

@app.get("/api/tehtavat")
def get_tehtavat(rasti_id: int):
    # Palauttaa rastin kaikki tehtävät osatehtavineen
    tehtavat_rows = db.execute(
        "SELECT id, rasti_id, nimi, tyyppi, max_pisteet, jarjestys FROM tehtavat WHERE rasti_id=? ORDER BY jarjestys, id",
        (rasti_id,)
    ).fetchall()
    result = []
    for t in tehtavat_rows:
        d = dict(t)
        osa_rows = db.execute(
            "SELECT id, tehtava_id, nimi, tyyppi, max_pisteet, jarjestys FROM osatehtavat WHERE tehtava_id=? ORDER BY jarjestys, id",
            (t["id"],)
        ).fetchall()
        d["osatehtavat"] = [dict(o) for o in osa_rows]
        result.append(d)
    return result


@app.post("/api/tehtava")
def create_tehtava(t: TehtavaIn, x_admin_token: str = Header(None)):
    # Luo uuden tehtävän rastille
    vaadi_admin(x_admin_token)
    if not t.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    if t.tyyppi not in ("pisteet", "oikein_vaarin", "ajanotto"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    max_j = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM tehtavat WHERE rasti_id=?", (t.rasti_id,)).fetchone()[0]
    db.execute("INSERT INTO tehtavat (rasti_id, nimi, tyyppi, max_pisteet, jarjestys) VALUES (?,?,?,?,?)",
               (t.rasti_id, t.nimi.strip(), t.tyyppi, t.max_pisteet, max_j + 1))
    db.commit()
    return {"id": db.execute("SELECT last_insert_rowid()").fetchone()[0], "ok": True}


@app.put("/api/tehtava/{tehtava_id}")
def update_tehtava(tehtava_id: int, t: TehtavaIn, x_admin_token: str = Header(None)):
    # Päivittää tehtävän nimen, tyypin ja maksimipisteet
    vaadi_admin(x_admin_token)
    if not t.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    if t.tyyppi not in ("pisteet", "oikein_vaarin", "ajanotto"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    db.execute("UPDATE tehtavat SET nimi=?, tyyppi=?, max_pisteet=? WHERE id=?",
               (t.nimi.strip(), t.tyyppi, t.max_pisteet, tehtava_id))
    db.commit()
    return {"ok": True}


@app.delete("/api/tehtava/{tehtava_id}")
def delete_tehtava(tehtava_id: int, x_admin_token: str = Header(None)):
    # Poistaa tehtävän ja sen kaikki osatehtavat ja tulokset
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM osatehtava_tulokset WHERE osatehtava_id IN (SELECT id FROM osatehtavat WHERE tehtava_id=?)", (tehtava_id,))
    db.execute("DELETE FROM osatehtavat WHERE tehtava_id=?", (tehtava_id,))
    db.execute("DELETE FROM tehtava_tulokset WHERE tehtava_id=?", (tehtava_id,))
    db.execute("DELETE FROM tehtavat WHERE id=?", (tehtava_id,))
    db.commit()
    return {"ok": True}


@app.post("/api/osatehtava")
def create_osatehtava(o: OsatehtavaIn, x_admin_token: str = Header(None)):
    # Luo uuden osatehtävän tehtävälle
    vaadi_admin(x_admin_token)
    if not o.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    if o.tyyppi not in ("pisteet", "oikein_vaarin", "ajanotto"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    max_j = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM osatehtavat WHERE tehtava_id=?", (o.tehtava_id,)).fetchone()[0]
    db.execute("INSERT INTO osatehtavat (tehtava_id, nimi, tyyppi, max_pisteet, jarjestys) VALUES (?,?,?,?,?)",
               (o.tehtava_id, o.nimi.strip(), o.tyyppi, o.max_pisteet, max_j + 1))
    db.commit()
    return {"id": db.execute("SELECT last_insert_rowid()").fetchone()[0], "ok": True}


@app.put("/api/osatehtava/{osa_id}")
def update_osatehtava(osa_id: int, o: OsatehtavaIn, x_admin_token: str = Header(None)):
    # Päivittää osatehtävän tiedot
    vaadi_admin(x_admin_token)
    if not o.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    if o.tyyppi not in ("pisteet", "oikein_vaarin", "ajanotto"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    db.execute("UPDATE osatehtavat SET nimi=?, tyyppi=?, max_pisteet=? WHERE id=?",
               (o.nimi.strip(), o.tyyppi, o.max_pisteet, osa_id))
    db.commit()
    return {"ok": True}


@app.delete("/api/osatehtava/{osa_id}")
def delete_osatehtava(osa_id: int, x_admin_token: str = Header(None)):
    # Poistaa osatehtävän ja sen tulokset
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM osatehtava_tulokset WHERE osatehtava_id=?", (osa_id,))
    db.execute("DELETE FROM osatehtavat WHERE id=?", (osa_id,))
    db.commit()
    return {"ok": True}


# ── Suoritukset ja tulokset ───────────────────────────────────────────────────

@app.get("/api/suoritus")
def get_or_create_suoritus(vartio: str, rasti_id: int, token: str = "", x_admin_token: str = Header(None)):
    # Hakee tai luo suorituksen vartio+rasti-parille, palauttaa myös tallennetut tulokset
    if token:
        session = sessions.get(token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    if not db.execute("SELECT id FROM vartiot WHERE nimi=?", (vartio,)).fetchone():
        raise HTTPException(status_code=404, detail=f"Vartiota '{vartio}' ei löydy")
    row = db.execute("SELECT id, kommentti FROM suoritukset WHERE vartio=? AND rasti_id=?", (vartio, rasti_id)).fetchone()
    if not row:
        from datetime import datetime
        nyt = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        db.execute("INSERT OR IGNORE INTO suoritukset (vartio, rasti_id, kommentti, luotu) VALUES (?,?,NULL,?)", (vartio, rasti_id, nyt))
        db.commit()
        row = db.execute("SELECT id, kommentti FROM suoritukset WHERE vartio=? AND rasti_id=?", (vartio, rasti_id)).fetchone()
    sid = row["id"]
    tt = db.execute("SELECT tehtava_id, pisteet, oikein, aika_sekuntia FROM tehtava_tulokset WHERE suoritus_id=?", (sid,)).fetchall()
    ot = db.execute("SELECT osatehtava_id, pisteet, oikein, aika_sekuntia FROM osatehtava_tulokset WHERE suoritus_id=?", (sid,)).fetchall()
    return {
        "id": sid,
        "kommentti": row["kommentti"],
        "tehtava_tulokset": [dict(r) for r in tt],
        "osatehtava_tulokset": [dict(r) for r in ot],
    }


@app.put("/api/suoritus/{suoritus_id}")
def update_suoritus(suoritus_id: int, s: SuoritusKommenttiIn, x_admin_token: str = Header(None)):
    # Päivittää suorituksen kommentin
    if s.token:
        session = sessions.get(s.token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    db.execute("UPDATE suoritukset SET kommentti=? WHERE id=?", (s.kommentti, suoritus_id))
    db.commit()
    return {"ok": True}


@app.post("/api/tulos")
def save_tulos(t: TulosIn, x_admin_token: str = Header(None)):
    # Tallentaa tai päivittää yksittäisen tehtävän tai osatehtävän tuloksen
    if t.token:
        session = sessions.get(t.token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    suoritus = db.execute("SELECT id FROM suoritukset WHERE id=?", (t.suoritus_id,)).fetchone()
    if not suoritus:
        raise HTTPException(status_code=404, detail="Suoritusta ei löydy")
    if t.tehtava_id is not None:
        db.execute("""
            INSERT INTO tehtava_tulokset (suoritus_id, tehtava_id, pisteet, oikein, aika_sekuntia, paivitetty)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(suoritus_id, tehtava_id) DO UPDATE SET
              pisteet=excluded.pisteet, oikein=excluded.oikein,
              aika_sekuntia=excluded.aika_sekuntia, paivitetty=excluded.paivitetty
        """, (t.suoritus_id, t.tehtava_id, t.pisteet, t.oikein, t.aika_sekuntia, t.aika))
    elif t.osatehtava_id is not None:
        db.execute("""
            INSERT INTO osatehtava_tulokset (suoritus_id, osatehtava_id, pisteet, oikein, aika_sekuntia, paivitetty)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(suoritus_id, osatehtava_id) DO UPDATE SET
              pisteet=excluded.pisteet, oikein=excluded.oikein,
              aika_sekuntia=excluded.aika_sekuntia, paivitetty=excluded.paivitetty
        """, (t.suoritus_id, t.osatehtava_id, t.pisteet, t.oikein, t.aika_sekuntia, t.aika))
    else:
        raise HTTPException(status_code=400, detail="tehtava_id tai osatehtava_id vaaditaan")
    db.commit()
    return {"ok": True}


@app.get("/api/tulokset")
def get_tulokset(x_admin_token: str = Header(None)):
    # Palauttaa kaikkien vartioiden tulokset — käytetään tuloslistauksessa
    vaadi_admin(x_admin_token)
    vartiot_rows = db.execute("SELECT DISTINCT vartio FROM suoritukset ORDER BY vartio").fetchall()
    return [_vartio_tulokset(v["vartio"]) for v in vartiot_rows]


@app.get("/api/tulokset/{vartio}")
def get_tulokset_vartio(vartio: str, x_admin_token: str = Header(None)):
    # Palauttaa yhden vartion tulokset kaikilla rasteilla
    vaadi_admin(x_admin_token)
    return _vartio_tulokset(vartio)


def _vartio_tulokset(vartio: str) -> dict:
    suoritukset = db.execute(
        "SELECT s.id, s.rasti_id, r.numero, s.kommentti FROM suoritukset s JOIN rastit r ON r.id=s.rasti_id WHERE s.vartio=? ORDER BY r.jarjestys, r.id",
        (vartio,)
    ).fetchall()
    rasti_data = []
    for s in suoritukset:
        tt = db.execute("""
            SELECT t.id, t.nimi, t.tyyppi, t.max_pisteet,
                   tt.pisteet, tt.oikein, tt.aika_sekuntia
            FROM tehtavat t
            LEFT JOIN tehtava_tulokset tt ON tt.tehtava_id=t.id AND tt.suoritus_id=?
            WHERE t.rasti_id=? ORDER BY t.jarjestys, t.id
        """, (s["id"], s["rasti_id"])).fetchall()
        tehtavat_data = []
        for t in tt:
            osa_rows = db.execute("""
                SELECT o.id, o.nimi, o.tyyppi, o.max_pisteet,
                       ot.pisteet, ot.oikein, ot.aika_sekuntia
                FROM osatehtavat o
                LEFT JOIN osatehtava_tulokset ot ON ot.osatehtava_id=o.id AND ot.suoritus_id=?
                WHERE o.tehtava_id=? ORDER BY o.jarjestys, o.id
            """, (s["id"], t["id"])).fetchall()
            td = dict(t)
            td["osatehtavat"] = [dict(o) for o in osa_rows]
            tehtavat_data.append(td)
        rasti_data.append({
            "suoritus_id": s["id"],
            "rasti_id": s["rasti_id"],
            "rasti_numero": s["numero"],
            "kommentti": s["kommentti"],
            "tehtavat": tehtavat_data,
        })
    return {"vartio": vartio, "rastit": rasti_data}
