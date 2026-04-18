from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import uuid
import hashlib

app = FastAPI()

db = sqlite3.connect("kipa.db", check_same_thread=False)
db.row_factory = sqlite3.Row

db.executescript("""
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL UNIQUE,
  token TEXT UNIQUE NOT NULL
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

sessions: dict = {
    row["token"]: {"nimi": row["nimi"]}
    for row in db.execute("SELECT token, nimi FROM users").fetchall()
}

admin_sessions: set = set()


def hash_salasana(salasana: str) -> str:
    return hashlib.sha256(salasana.encode()).hexdigest()


def vaadi_admin(x_admin_token: str = Header(None)):
    if not x_admin_token or x_admin_token not in admin_sessions:
        raise HTTPException(status_code=403, detail="Vaatii admin-oikeudet")


class UserIn(BaseModel):
    nimi: str


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
    jarjestys: list[int]


class AdminIn(BaseModel):
    kayttajanimi: str
    salasana: str


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


@app.post("/api/admin/setup")
def admin_setup(a: AdminIn):
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
    maara = db.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    return {"tarvitaan": maara == 0}


@app.post("/api/admin/login")
def admin_login(a: AdminIn):
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


@app.post("/api/user")
def register(u: UserIn):
    if not u.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    nimi = u.nimi.strip()
    existing = db.execute("SELECT token FROM users WHERE nimi=?", (nimi,)).fetchone()
    if existing:
        token = existing["token"]
    else:
        token = str(uuid.uuid4())
        db.execute("INSERT INTO users (nimi, token) VALUES (?, ?)", (nimi, token))
        db.commit()
    sessions[token] = {"nimi": nimi}
    return {"token": token, "nimi": nimi}


@app.get("/api/rastit")
def get_rastit():
    rows = db.execute("SELECT id, numero, jarjestys, kesto_min, siirtyma_min FROM rastit ORDER BY jarjestys, id").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/rasti")
def create_rasti(r: RastiIn, x_admin_token: str = Header(None)):
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
    vaadi_admin(x_admin_token)
    for i, rasti_id in enumerate(data.jarjestys):
        db.execute("UPDATE rastit SET jarjestys=? WHERE id=?", (i, rasti_id))
    db.commit()
    return {"ok": True}


@app.put("/api/rasti/{rasti_id}")
def update_rasti(rasti_id: int, r: RastiIn, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("UPDATE rastit SET numero=?, kesto_min=?, siirtyma_min=? WHERE id=?",
               (r.numero.strip(), r.kesto_min, r.siirtyma_min, rasti_id))
    db.commit()
    return {"ok": True}


@app.delete("/api/rasti/{rasti_id}")
def delete_rasti(rasti_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM rastit WHERE id=?", (rasti_id,))
    db.commit()
    return {"ok": True}


@app.post("/api/leimaus")
def leimaus(l: LeimausIn):
    session = sessions.get(l.token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    if not l.vartio.strip():
        raise HTTPException(status_code=400, detail="Vartion nimi vaaditaan")
    if not l.rastinumero.strip():
        raise HTTPException(status_code=400, detail="Rastinumero vaaditaan")
    if l.tyyppi not in ("sisaan", "ulos"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    db.execute(
        "INSERT INTO leimaukset (kayttaja, numero, vartio, jasenet, aika, tyyppi) VALUES (?,?,?,?,?,?)",
        (session["nimi"], l.rastinumero.strip(), l.vartio.strip(), l.jasenet, l.aika, l.tyyppi),
    )
    db.commit()
    return {"ok": True}


@app.get("/api/aktiiviset")
def aktiiviset(numero: str):
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


@app.get("/api/vartiot")
def get_vartiot():
    rows = db.execute("SELECT id, nimi, jasenet, token FROM vartiot ORDER BY nimi").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/vartio")
def create_vartio(v: VartioIn, x_admin_token: str = Header(None)):
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
    vaadi_admin(x_admin_token)
    if not v.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    db.execute("UPDATE vartiot SET nimi=?, jasenet=? WHERE id=?",
               (v.nimi.strip(), v.jasenet, vartio_id))
    db.commit()
    return {"ok": True}


@app.delete("/api/vartio/{vartio_id}")
def delete_vartio(vartio_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM vartiot WHERE id=?", (vartio_id,))
    db.commit()
    return {"ok": True}


@app.get("/api/vartio/{token}")
def get_vartio(token: str):
    row = db.execute("SELECT nimi, jasenet FROM vartiot WHERE token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Vartiota ei löydy")
    return dict(row)


@app.get("/api/tilanne")
def tilanne(numero: str = ""):
    from datetime import datetime, timedelta

    rastit_rows = db.execute("SELECT numero, siirtyma_min FROM rastit ORDER BY jarjestys, id").fetchall()
    rasti_lista = [r["numero"] for r in rastit_rows]
    siirtyma_map = {r["numero"]: r["siirtyma_min"] for r in rastit_rows}

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
                siirtyma = siirtyma_map.get(lahto_rasti, 5)
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
        })

    return result


@app.get("/api/data")
def get_data():
    rows = db.execute(
        "SELECT kayttaja, numero, vartio, jasenet, aika, tyyppi FROM leimaukset ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]
