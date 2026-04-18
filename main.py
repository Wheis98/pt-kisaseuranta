from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import uuid

app = FastAPI()

db = sqlite3.connect("kipa.db", check_same_thread=False)
db.row_factory = sqlite3.Row

db.executescript("""
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL,
  rastinumero TEXT NOT NULL,
  token TEXT UNIQUE NOT NULL
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
""")

try:
    db.execute("ALTER TABLE leimaukset ADD COLUMN tyyppi TEXT NOT NULL DEFAULT 'sisaan'")
    db.commit()
except Exception:
    pass

sessions: dict = {
    row["token"]: {"nimi": row["nimi"], "rastinumero": row["rastinumero"]}
    for row in db.execute("SELECT token, nimi, rastinumero FROM users").fetchall()
}


class UserIn(BaseModel):
    nimi: str
    rastinumero: str


class LeimausIn(BaseModel):
    token: str
    vartio: str
    jasenet: int
    aika: str
    tyyppi: str = "sisaan"


@app.get("/")
def root():
    return FileResponse("static/index.html")

@app.get("/leimaus.html")
def leimaus_page():
    return FileResponse("static/leimaus.html")

@app.get("/data.html")
def data_page():
    return FileResponse("static/data.html")


@app.post("/api/user")
def register(u: UserIn):
    if not u.nimi.strip() or not u.rastinumero.strip():
        raise HTTPException(status_code=400, detail="Nimi ja rastinumero vaaditaan")
    nimi = u.nimi.strip()
    rastinumero = u.rastinumero.strip()
    existing = db.execute(
        "SELECT token FROM users WHERE nimi=? AND rastinumero=?", (nimi, rastinumero)
    ).fetchone()
    if existing:
        token = existing["token"]
    else:
        token = str(uuid.uuid4())
        db.execute(
            "INSERT INTO users (nimi, rastinumero, token) VALUES (?, ?, ?)",
            (nimi, rastinumero, token),
        )
        db.commit()
    sessions[token] = {"nimi": nimi, "rastinumero": rastinumero}
    return {"token": token, "nimi": nimi, "rastinumero": rastinumero}


@app.post("/api/leimaus")
def leimaus(l: LeimausIn):
    session = sessions.get(l.token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    if not l.vartio.strip():
        raise HTTPException(status_code=400, detail="Vartion nimi vaaditaan")
    if l.tyyppi not in ("sisaan", "ulos"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    db.execute(
        "INSERT INTO leimaukset (kayttaja, numero, vartio, jasenet, aika, tyyppi) VALUES (?,?,?,?,?,?)",
        (session["nimi"], session["rastinumero"], l.vartio.strip(), l.jasenet, l.aika, l.tyyppi),
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


@app.get("/api/data")
def get_data():
    rows = db.execute(
        "SELECT kayttaja, numero, vartio, jasenet, aika, tyyppi FROM leimaukset ORDER BY id DESC"
    ).fetchall()
    return [dict(r) for r in rows]
