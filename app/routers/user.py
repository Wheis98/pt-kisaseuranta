from app.utils import hash_salasana, vaadi_admin
import uuid
from fastapi import APIRouter, HTTPException, Header
from app import db, sessions, AsetaSalasanaIn, UserIn

router = APIRouter()

@router.get("/api/user/tarkista")
def tarkista_user(nimi: str):
    # Tarkistaa onko käyttäjä olemassa ja onko salasana asetettu — käytetään kirjautumislomakkeen vaiheistukseen
    row = db.execute("SELECT salasana_hash FROM users WHERE nimi=?", (nimi.strip(),)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Käyttäjää ei löydy — pyydä adminia luomaan tunnus")
    return {"salasana_asetettu": row["salasana_hash"] is not None}


@router.post("/api/user/aseta_salasana")
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


@router.post("/api/user")
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


@router.get("/api/users")
def get_users(x_admin_token: str = Header(None)):
    # Palauttaa kaikki käyttäjät adminille — näyttää onko salasana asetettu
    vaadi_admin(x_admin_token)
    rows = db.execute("SELECT id, nimi, salasana_hash FROM users ORDER BY nimi").fetchall()
    return [{"id": r["id"], "nimi": r["nimi"], "salasana_asetettu": r["salasana_hash"] is not None} for r in rows]


@router.post("/api/user/{user_id}/reset_salasana")
def reset_salasana(user_id: int, x_admin_token: str = Header(None)):
    # Nollaa käyttäjän salasanan — seuraavalla kirjautumisella pyydetään valitsemaan uusi
    vaadi_admin(x_admin_token)
    row = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Käyttäjää ei löydy")
    db.execute("UPDATE users SET salasana_hash=NULL WHERE id=?", (user_id,))
    db.commit()
    return {"ok": True}


@router.delete("/api/user/{user_id}")
def delete_user(user_id: int, x_admin_token: str = Header(None)):
    # Poistaa käyttäjän
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    return {"ok": True}