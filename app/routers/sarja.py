from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import FileResponse
import sqlite3
from app import db, SarjaIn, SarjaRastitIn, STATIC_DIR
from app.utils import vaadi_admin

router = APIRouter()

@router.get("/sarjat.html")
def sarjat_page():
    return FileResponse(STATIC_DIR / "sarjat.html")

@router.get("/api/sarjat")
def get_sarjat():
    # Palauttaa kaikki sarjat aakkosjärjestyksessä
    rows = db.execute("SELECT id, nimi FROM sarjat ORDER BY nimi").fetchall()
    return [dict(r) for r in rows]

@router.post("/api/sarja")
def create_sarja(s: SarjaIn, x_admin_token: str = Header(None)):
    # Luo uuden sarjan
    vaadi_admin(x_admin_token)
    if not s.nimi.strip():
        raise HTTPException(status_code=400, detail="Sarjan nimi vaaditaan")
    try:
        db.execute("INSERT INTO sarjat (nimi) VALUES (?)", (s.nimi.strip(),))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Sarja on jo olemassa")
    return {"ok": True}

@router.put("/api/sarja/{sarja_id}")
def update_sarja(sarja_id: int, s: SarjaIn, x_admin_token: str = Header(None)):
    # Nimeää sarjan uudelleen
    vaadi_admin(x_admin_token)
    if not s.nimi.strip():
        raise HTTPException(status_code=400, detail="Sarjan nimi vaaditaan")
    try:
        db.execute("UPDATE sarjat SET nimi=? WHERE id=?", (s.nimi.strip(), sarja_id))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Sarja on jo olemassa")
    return {"ok": True}

@router.delete("/api/sarja/{sarja_id}")
def delete_sarja(sarja_id: int, x_admin_token: str = Header(None)):
    # Poistaa sarjan ja sen reittimäärityksen — ei koske vartioiden sarja-kenttää
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM sarja_rastit WHERE sarja_id=?", (sarja_id,))
    db.execute("DELETE FROM sarjat WHERE id=?", (sarja_id,))
    db.commit()
    return {"ok": True}

@router.get("/api/sarja/{sarja_id}/rastit")
def get_sarja_rastit(sarja_id: int):
    # Palauttaa sarjan reitin: mukana olevat rastit järjestyksessä sekä reitiltä puuttuvat rastit
    if not db.execute("SELECT 1 FROM sarjat WHERE id=?", (sarja_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Sarjaa ei löydy")
    mukana = db.execute("""
        SELECT r.id, r.numero FROM sarja_rastit sr
        JOIN rastit r ON r.id = sr.rasti_id
        WHERE sr.sarja_id=? ORDER BY sr.jarjestys, sr.id
    """, (sarja_id,)).fetchall()
    mukana_idt = {r["id"] for r in mukana}
    puuttuu = db.execute("SELECT id, numero FROM rastit ORDER BY jarjestys, id").fetchall()
    return {
        "mukana": [dict(r) for r in mukana],
        "puuttuu": [dict(r) for r in puuttuu if r["id"] not in mukana_idt],
    }

@router.post("/api/sarja/{sarja_id}/rastit")
def paivita_sarja_rastit(sarja_id: int, data: SarjaRastitIn, x_admin_token: str = Header(None)):
    # Tallentaa sarjan reitin: annetut rasti-id:t järjestyksessä, muut rastit eivät kuulu reittiin
    vaadi_admin(x_admin_token)
    if not db.execute("SELECT 1 FROM sarjat WHERE id=?", (sarja_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Sarjaa ei löydy")
    db.execute("DELETE FROM sarja_rastit WHERE sarja_id=?", (sarja_id,))
    for i, rasti_id in enumerate(data.jarjestys):
        db.execute("INSERT INTO sarja_rastit (sarja_id, rasti_id, jarjestys) VALUES (?,?,?)", (sarja_id, rasti_id, i))
    db.commit()
    return {"ok": True}
