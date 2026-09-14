from fastapi import APIRouter, HTTPException
from app import db, LoginIn, sessions
from app.utils import hash_salasana

router = APIRouter()

@router.post("/api/login")
def login(l: LoginIn):
    # Kirjaa käyttäjän sisään nimellä ja salasanalla
    row = db.execute("SELECT token, nimi, salasana_hash FROM users WHERE nimi=?", (l.nimi.strip(),)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Käyttäjää ei löydy")
    if row["salasana_hash"] != hash_salasana(l.salasana):
        raise HTTPException(status_code=401, detail="Väärä salasana")
    sessions[row["token"]] = {"nimi": row["nimi"]}
    return {"token": row["token"], "nimi": row["nimi"]}