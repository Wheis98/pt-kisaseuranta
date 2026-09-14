from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
import uuid
from app import db, VartioIn, STATIC_DIR
from app.utils import vaadi_admin

router = APIRouter()

@router.get("/qr.html")
def qr_page():
    return FileResponse(STATIC_DIR / "qr.html")

@router.get("/vartiot-tulosta.html")
def vartiot_tulosta_page():
    return FileResponse(STATIC_DIR / "vartiot-tulosta.html")

@router.get("/api/vartiot")
def get_vartiot():
    # Palauttaa kaikki vartiot aakkosjärjestyksessä
    rows = db.execute("SELECT id, nimi, token, numero, sarja, lippukunta, piiri FROM vartiot ORDER BY nimi").fetchall()
    return [dict(r) for r in rows]

@router.post("/api/vartio")
def create_vartio(v: VartioIn, x_admin_token: str = Header(None)):
    # Luo uuden vartion ja generoi sille QR-koodia varten uniikin tokenin
    vaadi_admin(x_admin_token)
    if not v.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    token = str(uuid.uuid4())
    db.execute("INSERT INTO vartiot (nimi, token, numero, sarja, lippukunta, piiri) VALUES (?, ?, ?, ?, ?, ?)",
               (v.nimi.strip(), token, v.numero.strip(), v.sarja.strip(), v.lippukunta.strip(), v.piiri.strip()))
    db.commit()
    return {"id": db.execute("SELECT last_insert_rowid()").fetchone()[0],
            "nimi": v.nimi.strip(), "token": token,
            "numero": v.numero.strip(), "sarja": v.sarja.strip(),
            "lippukunta": v.lippukunta.strip(), "piiri": v.piiri.strip()}

@router.put("/api/vartio/{vartio_id}")
def update_vartio(vartio_id: int, v: VartioIn, x_admin_token: str = Header(None)):
    # Päivittää vartion nimen, numeron, sarjan, lippukunnan ja piirin
    vaadi_admin(x_admin_token)
    if not v.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    db.execute("UPDATE vartiot SET nimi=?, numero=?, sarja=?, lippukunta=?, piiri=? WHERE id=?",
               (v.nimi.strip(), v.numero.strip(), v.sarja.strip(), v.lippukunta.strip(), v.piiri.strip(), vartio_id))
    db.commit()
    return {"ok": True}

@router.delete("/api/vartio/{vartio_id}")
def delete_vartio(vartio_id: int, x_admin_token: str = Header(None)):
    # Poistaa vartion
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM vartiot WHERE id=?", (vartio_id,))
    db.commit()
    return {"ok": True}

@router.get("/api/vartio/{token}")
def get_vartio(token: str):
    # Hakee vartion QR-tokenin perusteella — käytetään QR-skannauksen jälkeen nimen täyttöön
    row = db.execute("SELECT nimi, numero, sarja, lippukunta, piiri FROM vartiot WHERE token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Vartiota ei löydy")
    return dict(row)
