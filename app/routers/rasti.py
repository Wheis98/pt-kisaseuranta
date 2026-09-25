from app.utils import vaadi_admin, laske_siirtyma_mediaanit
from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import FileResponse
import sqlite3
from app import db, RastiIn, RastiJarjestysIn, STATIC_DIR

router = APIRouter()

@router.get("/rasti.html")
def rasti_page():
    return FileResponse(STATIC_DIR / "rasti.html")

@router.get("/rastit.html")
def rastit_page():
    return FileResponse(STATIC_DIR / "rastit.html")

@router.get("/api/rastit")
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

@router.post("/api/rasti")
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

@router.post("/api/rastit/jarjestys")
def paivita_jarjestys(data: RastiJarjestysIn, x_admin_token: str = Header(None)):
    # Tallentaa rastien uuden järjestyksen drag-and-drop-listan perusteella
    vaadi_admin(x_admin_token)
    for i, rasti_id in enumerate(data.jarjestys):
        db.execute("UPDATE rastit SET jarjestys=? WHERE id=?", (i, rasti_id))
    db.commit()
    return {"ok": True}

@router.put("/api/rasti/{rasti_id}")
def update_rasti(rasti_id: int, r: RastiIn, x_admin_token: str = Header(None)):
    # Päivittää rastin nimen ja aika-arviot
    vaadi_admin(x_admin_token)
    db.execute("UPDATE rastit SET numero=?, kesto_min=?, siirtyma_min=? WHERE id=?",
               (r.numero.strip(), r.kesto_min, r.siirtyma_min, rasti_id))
    db.commit()
    return {"ok": True}

@router.delete("/api/rasti/{rasti_id}")
def delete_rasti(rasti_id: int, x_admin_token: str = Header(None)):
    # Poistaa rastin ja sen sarjakohtaiset reittimerkinnät
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM sarja_rastit WHERE rasti_id=?", (rasti_id,))
    db.execute("DELETE FROM rastit WHERE id=?", (rasti_id,))
    db.commit()
    return {"ok": True}

@router.get("/api/siirtyma_mediaanit")
def get_siirtyma_mediaanit():
    # Palauttaa lasketut siirtymämediaanit — käytetään rastit.html-sivulla datan näyttöön
    return laske_siirtyma_mediaanit()

@router.put("/api/rasti/{rasti_id}/pisteytys")
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