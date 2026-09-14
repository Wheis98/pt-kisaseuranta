from fastapi import APIRouter, Header
from app import db, AsetusIn
from app.utils import vaadi_admin

router = APIRouter()

@router.get("/api/asetukset")
def get_asetukset():
    # Palauttaa kaikki asetukset — käytetään pisteytystilan tarkistukseen
    rows = db.execute("SELECT avain, arvo FROM asetukset").fetchall()
    return {r["avain"]: r["arvo"] for r in rows}

@router.put("/api/asetus/{avain}")
def set_asetus(avain: str, a: AsetusIn, x_admin_token: str = Header(None)):
    # Asettaa tai päivittää asetuksen arvon
    vaadi_admin(x_admin_token)
    db.execute("INSERT OR REPLACE INTO asetukset (avain, arvo) VALUES (?,?)", (avain, a.arvo))
    db.commit()
    return {"ok": True}