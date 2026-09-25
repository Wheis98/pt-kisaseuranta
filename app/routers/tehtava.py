from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, TehtavaIn, OsatehtavaIn, SyoteMaariteIn, KaavaTestIn, STATIC_DIR
from app.utils import vaadi_admin
from app.kaava import evaluoi, KaavaVirhe

router = APIRouter()

TYYPIT = ("pisteet", "oikein_vaarin", "ajanotto", "kaava")


def _hae_syotteet(taso, kohde_id):
    rows = db.execute(
        "SELECT id, taso, kohde_id, nimi, kuvaus, tyyppi, jarjestys FROM syotemaaritteet WHERE taso=? AND kohde_id=? ORDER BY jarjestys, id",
        (taso, kohde_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/tehtavat.html")
def tehtavat_page():
    return FileResponse(STATIC_DIR / "tehtavat.html")

@router.get("/api/tehtavat")
def get_tehtavat(rasti_id: int):
    # Palauttaa rastin kaikki tehtävät osatehtavineen
    tehtavat_rows = db.execute(
        "SELECT id, rasti_id, nimi, tyyppi, max_pisteet, jarjestys, kaava FROM tehtavat WHERE rasti_id=? ORDER BY jarjestys, id",
        (rasti_id,)
    ).fetchall()
    result = []
    for t in tehtavat_rows:
        d = dict(t)
        d["syotteet"] = _hae_syotteet("tehtava", t["id"])
        osa_rows = db.execute(
            "SELECT id, tehtava_id, nimi, tyyppi, max_pisteet, jarjestys, kaava FROM osatehtavat WHERE tehtava_id=? ORDER BY jarjestys, id",
            (t["id"],)
        ).fetchall()
        osatehtavat = []
        for o in osa_rows:
            od = dict(o)
            od["syotteet"] = _hae_syotteet("osatehtava", o["id"])
            osatehtavat.append(od)
        d["osatehtavat"] = osatehtavat
        result.append(d)
    return result


@router.post("/api/tehtava")
def create_tehtava(t: TehtavaIn, x_admin_token: str = Header(None)):
    # Luo uuden tehtävän rastille
    vaadi_admin(x_admin_token)
    if not t.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    if t.tyyppi not in TYYPIT:
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    max_j = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM tehtavat WHERE rasti_id=?", (t.rasti_id,)).fetchone()[0]
    db.execute("INSERT INTO tehtavat (rasti_id, nimi, tyyppi, max_pisteet, jarjestys, kaava) VALUES (?,?,?,?,?,?)",
               (t.rasti_id, t.nimi.strip(), t.tyyppi, t.max_pisteet, max_j + 1, t.kaava))
    db.commit()
    return {"id": db.execute("SELECT last_insert_rowid()").fetchone()[0], "ok": True}

@router.put("/api/tehtava/{tehtava_id}")
def update_tehtava(tehtava_id: int, t: TehtavaIn, x_admin_token: str = Header(None)):
    # Päivittää tehtävän nimen, tyypin ja maksimipisteet
    vaadi_admin(x_admin_token)
    if not t.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    if t.tyyppi not in TYYPIT:
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    db.execute("UPDATE tehtavat SET nimi=?, tyyppi=?, max_pisteet=?, kaava=? WHERE id=?",
               (t.nimi.strip(), t.tyyppi, t.max_pisteet, t.kaava, tehtava_id))
    db.commit()
    return {"ok": True}

@router.delete("/api/tehtava/{tehtava_id}")
def delete_tehtava(tehtava_id: int, x_admin_token: str = Header(None)):
    # Poistaa tehtävän ja sen kaikki osatehtavat, tulokset ja syotemaaritteet
    vaadi_admin(x_admin_token)
    osa_idt = [r["id"] for r in db.execute("SELECT id FROM osatehtavat WHERE tehtava_id=?", (tehtava_id,)).fetchall()]
    db.execute("DELETE FROM osatehtava_tulokset WHERE osatehtava_id IN (SELECT id FROM osatehtavat WHERE tehtava_id=?)", (tehtava_id,))
    for osa_id in osa_idt:
        db.execute("DELETE FROM syote_arvot WHERE syotemaarite_id IN (SELECT id FROM syotemaaritteet WHERE taso='osatehtava' AND kohde_id=?)", (osa_id,))
        db.execute("DELETE FROM syotemaaritteet WHERE taso='osatehtava' AND kohde_id=?", (osa_id,))
    db.execute("DELETE FROM osatehtavat WHERE tehtava_id=?", (tehtava_id,))
    db.execute("DELETE FROM tehtava_tulokset WHERE tehtava_id=?", (tehtava_id,))
    db.execute("DELETE FROM syote_arvot WHERE syotemaarite_id IN (SELECT id FROM syotemaaritteet WHERE taso='tehtava' AND kohde_id=?)", (tehtava_id,))
    db.execute("DELETE FROM syotemaaritteet WHERE taso='tehtava' AND kohde_id=?", (tehtava_id,))
    db.execute("DELETE FROM tehtavat WHERE id=?", (tehtava_id,))
    db.commit()
    return {"ok": True}

@router.post("/api/osatehtava")
def create_osatehtava(o: OsatehtavaIn, x_admin_token: str = Header(None)):
    # Luo uuden osatehtävän tehtävälle
    vaadi_admin(x_admin_token)
    if not o.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    if o.tyyppi not in TYYPIT:
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    max_j = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM osatehtavat WHERE tehtava_id=?", (o.tehtava_id,)).fetchone()[0]
    db.execute("INSERT INTO osatehtavat (tehtava_id, nimi, tyyppi, max_pisteet, jarjestys, kaava) VALUES (?,?,?,?,?,?)",
               (o.tehtava_id, o.nimi.strip(), o.tyyppi, o.max_pisteet, max_j + 1, o.kaava))
    db.commit()
    return {"id": db.execute("SELECT last_insert_rowid()").fetchone()[0], "ok": True}

@router.put("/api/osatehtava/{osa_id}")
def update_osatehtava(osa_id: int, o: OsatehtavaIn, x_admin_token: str = Header(None)):
    # Päivittää osatehtävän tiedot
    vaadi_admin(x_admin_token)
    if not o.nimi.strip():
        raise HTTPException(status_code=400, detail="Nimi vaaditaan")
    if o.tyyppi not in TYYPIT:
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    db.execute("UPDATE osatehtavat SET nimi=?, tyyppi=?, max_pisteet=?, kaava=? WHERE id=?",
               (o.nimi.strip(), o.tyyppi, o.max_pisteet, o.kaava, osa_id))
    db.commit()
    return {"ok": True}

@router.delete("/api/osatehtava/{osa_id}")
def delete_osatehtava(osa_id: int, x_admin_token: str = Header(None)):
    # Poistaa osatehtävän, sen tulokset ja syotemaaritteet
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM osatehtava_tulokset WHERE osatehtava_id=?", (osa_id,))
    db.execute("DELETE FROM syote_arvot WHERE syotemaarite_id IN (SELECT id FROM syotemaaritteet WHERE taso='osatehtava' AND kohde_id=?)", (osa_id,))
    db.execute("DELETE FROM syotemaaritteet WHERE taso='osatehtava' AND kohde_id=?", (osa_id,))
    db.execute("DELETE FROM osatehtavat WHERE id=?", (osa_id,))
    db.commit()
    return {"ok": True}


# ── Kaava-tyypin syötemääritteet ────────────────────────────────────────────

@router.post("/api/tehtava/{tehtava_id}/syote")
def lisaa_tehtavan_syote(tehtava_id: int, s: SyoteMaariteIn, x_admin_token: str = Header(None)):
    return _lisaa_syote("tehtava", tehtava_id, s, x_admin_token)

@router.post("/api/osatehtava/{osa_id}/syote")
def lisaa_osatehtavan_syote(osa_id: int, s: SyoteMaariteIn, x_admin_token: str = Header(None)):
    return _lisaa_syote("osatehtava", osa_id, s, x_admin_token)

def _lisaa_syote(taso, kohde_id, s, x_admin_token):
    vaadi_admin(x_admin_token)
    if not s.nimi.strip():
        raise HTTPException(status_code=400, detail="Syötteen nimi vaaditaan")
    if s.tyyppi not in ("aika", "piste"):
        raise HTTPException(status_code=400, detail="Virheellinen syötteen tyyppi")
    max_j = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM syotemaaritteet WHERE taso=? AND kohde_id=?", (taso, kohde_id)).fetchone()[0]
    try:
        db.execute("INSERT INTO syotemaaritteet (taso, kohde_id, nimi, kuvaus, tyyppi, jarjestys) VALUES (?,?,?,?,?,?)",
                   (taso, kohde_id, s.nimi.strip(), s.kuvaus.strip(), s.tyyppi, max_j + 1))
        db.commit()
    except Exception:
        raise HTTPException(status_code=400, detail="Syöte tällä nimellä on jo olemassa")
    return {"id": db.execute("SELECT last_insert_rowid()").fetchone()[0], "ok": True}

@router.put("/api/syote/{syote_id}")
def paivita_syote(syote_id: int, s: SyoteMaariteIn, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    if not s.nimi.strip():
        raise HTTPException(status_code=400, detail="Syötteen nimi vaaditaan")
    if s.tyyppi not in ("aika", "piste"):
        raise HTTPException(status_code=400, detail="Virheellinen syötteen tyyppi")
    db.execute("UPDATE syotemaaritteet SET nimi=?, kuvaus=?, tyyppi=? WHERE id=?",
               (s.nimi.strip(), s.kuvaus.strip(), s.tyyppi, syote_id))
    db.commit()
    return {"ok": True}

@router.delete("/api/syote/{syote_id}")
def poista_syote(syote_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM syote_arvot WHERE syotemaarite_id=?", (syote_id,))
    db.execute("DELETE FROM syotemaaritteet WHERE id=?", (syote_id,))
    db.commit()
    return {"ok": True}


@router.post("/api/kaava/testaa")
def testaa_kaava(data: KaavaTestIn, x_admin_token: str = Header(None)):
    # Ajaa kaavan annetuilla esimerkkiarvoilla ilman kaikki()-vertailudataa — käytetään admin-UI:n esikatseluun
    vaadi_admin(x_admin_token)
    try:
        tulos = evaluoi(data.kaava, data.muuttujat, [])
        return {"ok": True, "tulos": tulos}
    except KaavaVirhe as e:
        return {"ok": False, "virhe": str(e)}
