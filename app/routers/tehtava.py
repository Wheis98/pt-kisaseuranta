from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, TehtavaIn, OsatehtavaIn, STATIC_DIR
from app.utils import vaadi_admin

router = APIRouter()

@router.get("/tehtavat.html")
def tehtavat_page():
    return FileResponse(STATIC_DIR / "tehtavat.html")

@router.get("/api/tehtavat")
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


@router.post("/api/tehtava")
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

@router.put("/api/tehtava/{tehtava_id}")
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

@router.delete("/api/tehtava/{tehtava_id}")
def delete_tehtava(tehtava_id: int, x_admin_token: str = Header(None)):
    # Poistaa tehtävän ja sen kaikki osatehtavat ja tulokset
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM osatehtava_tulokset WHERE osatehtava_id IN (SELECT id FROM osatehtavat WHERE tehtava_id=?)", (tehtava_id,))
    db.execute("DELETE FROM osatehtavat WHERE tehtava_id=?", (tehtava_id,))
    db.execute("DELETE FROM tehtava_tulokset WHERE tehtava_id=?", (tehtava_id,))
    db.execute("DELETE FROM tehtavat WHERE id=?", (tehtava_id,))
    db.commit()
    return {"ok": True}

@router.post("/api/osatehtava")
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

@router.put("/api/osatehtava/{osa_id}")
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

@router.delete("/api/osatehtava/{osa_id}")
def delete_osatehtava(osa_id: int, x_admin_token: str = Header(None)):
    # Poistaa osatehtävän ja sen tulokset
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM osatehtava_tulokset WHERE osatehtava_id=?", (osa_id,))
    db.execute("DELETE FROM osatehtavat WHERE id=?", (osa_id,))
    db.commit()
    return {"ok": True}