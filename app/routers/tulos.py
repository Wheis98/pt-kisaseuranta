from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, admin_sessions, sessions, SuoritusKommenttiIn, TulosIn
from app.utils import vaadi_admin

router = APIRouter()

@router.get("/pisteet.html")
def pisteet_page():
    return FileResponse("static/pisteet.html")

@router.get("/tulokset.html")
def tulokset_page():
    return FileResponse("static/tulokset.html")

@router.get("/api/suoritus")
def get_or_create_suoritus(vartio: str, rasti_id: int, token: str = "", x_admin_token: str = Header(None)):
    # Hakee tai luo suorituksen vartio+rasti-parille, palauttaa myös tallennetut tulokset
    if token:
        session = sessions.get(token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    if not db.execute("SELECT id FROM vartiot WHERE nimi=?", (vartio,)).fetchone():
        raise HTTPException(status_code=404, detail=f"Vartiota '{vartio}' ei löydy")
    row = db.execute("SELECT id, kommentti FROM suoritukset WHERE vartio=? AND rasti_id=?", (vartio, rasti_id)).fetchone()
    if not row:
        from datetime import datetime
        nyt = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        db.execute("INSERT OR IGNORE INTO suoritukset (vartio, rasti_id, kommentti, luotu) VALUES (?,?,NULL,?)", (vartio, rasti_id, nyt))
        db.commit()
        row = db.execute("SELECT id, kommentti FROM suoritukset WHERE vartio=? AND rasti_id=?", (vartio, rasti_id)).fetchone()
    sid = row["id"]
    tt = db.execute("SELECT tehtava_id, pisteet, oikein, aika_sekuntia FROM tehtava_tulokset WHERE suoritus_id=?", (sid,)).fetchall()
    ot = db.execute("SELECT osatehtava_id, pisteet, oikein, aika_sekuntia FROM osatehtava_tulokset WHERE suoritus_id=?", (sid,)).fetchall()
    return {
        "id": sid,
        "kommentti": row["kommentti"],
        "tehtava_tulokset": [dict(r) for r in tt],
        "osatehtava_tulokset": [dict(r) for r in ot],
    }

@router.put("/api/suoritus/{suoritus_id}")
def update_suoritus(suoritus_id: int, s: SuoritusKommenttiIn, x_admin_token: str = Header(None)):
    # Päivittää suorituksen kommentin
    if s.token:
        session = sessions.get(s.token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    db.execute("UPDATE suoritukset SET kommentti=? WHERE id=?", (s.kommentti, suoritus_id))
    db.commit()
    return {"ok": True}

@router.post("/api/tulos")
def save_tulos(t: TulosIn, x_admin_token: str = Header(None)):
    # Tallentaa tai päivittää yksittäisen tehtävän tai osatehtävän tuloksen
    if t.token:
        session = sessions.get(t.token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    suoritus = db.execute("SELECT id FROM suoritukset WHERE id=?", (t.suoritus_id,)).fetchone()
    if not suoritus:
        raise HTTPException(status_code=404, detail="Suoritusta ei löydy")
    if t.tehtava_id is not None:
        db.execute("""
            INSERT INTO tehtava_tulokset (suoritus_id, tehtava_id, pisteet, oikein, aika_sekuntia, paivitetty)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(suoritus_id, tehtava_id) DO UPDATE SET
              pisteet=excluded.pisteet, oikein=excluded.oikein,
              aika_sekuntia=excluded.aika_sekuntia, paivitetty=excluded.paivitetty
        """, (t.suoritus_id, t.tehtava_id, t.pisteet, t.oikein, t.aika_sekuntia, t.aika))
    elif t.osatehtava_id is not None:
        db.execute("""
            INSERT INTO osatehtava_tulokset (suoritus_id, osatehtava_id, pisteet, oikein, aika_sekuntia, paivitetty)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(suoritus_id, osatehtava_id) DO UPDATE SET
              pisteet=excluded.pisteet, oikein=excluded.oikein,
              aika_sekuntia=excluded.aika_sekuntia, paivitetty=excluded.paivitetty
        """, (t.suoritus_id, t.osatehtava_id, t.pisteet, t.oikein, t.aika_sekuntia, t.aika))
    else:
        raise HTTPException(status_code=400, detail="tehtava_id tai osatehtava_id vaaditaan")
    db.commit()
    return {"ok": True}

@router.get("/api/tulokset")
def get_tulokset(x_admin_token: str = Header(None)):
    # Palauttaa kaikkien vartioiden tulokset — käytetään tuloslistauksessa
    vaadi_admin(x_admin_token)
    vartiot_rows = db.execute("SELECT DISTINCT vartio FROM suoritukset ORDER BY vartio").fetchall()
    return [_vartio_tulokset(v["vartio"]) for v in vartiot_rows]

@router.get("/api/tulokset/{vartio}")
def get_tulokset_vartio(vartio: str, x_admin_token: str = Header(None)):
    # Palauttaa yhden vartion tulokset kaikilla rasteilla
    vaadi_admin(x_admin_token)
    return _vartio_tulokset(vartio)

def _vartio_tulokset(vartio: str) -> dict:
    suoritukset = db.execute(
        "SELECT s.id, s.rasti_id, r.numero, s.kommentti FROM suoritukset s JOIN rastit r ON r.id=s.rasti_id WHERE s.vartio=? ORDER BY r.jarjestys, r.id",
        (vartio,)
    ).fetchall()
    rasti_data = []
    for s in suoritukset:
        tt = db.execute("""
            SELECT t.id, t.nimi, t.tyyppi, t.max_pisteet,
                   tt.pisteet, tt.oikein, tt.aika_sekuntia
            FROM tehtavat t
            LEFT JOIN tehtava_tulokset tt ON tt.tehtava_id=t.id AND tt.suoritus_id=?
            WHERE t.rasti_id=? ORDER BY t.jarjestys, t.id
        """, (s["id"], s["rasti_id"])).fetchall()
        tehtavat_data = []
        for t in tt:
            osa_rows = db.execute("""
                SELECT o.id, o.nimi, o.tyyppi, o.max_pisteet,
                       ot.pisteet, ot.oikein, ot.aika_sekuntia
                FROM osatehtavat o
                LEFT JOIN osatehtava_tulokset ot ON ot.osatehtava_id=o.id AND ot.suoritus_id=?
                WHERE o.tehtava_id=? ORDER BY o.jarjestys, o.id
            """, (s["id"], t["id"])).fetchall()
            td = dict(t)
            td["osatehtavat"] = [dict(o) for o in osa_rows]
            tehtavat_data.append(td)
        rasti_data.append({
            "suoritus_id": s["id"],
            "rasti_id": s["rasti_id"],
            "rasti_numero": s["numero"],
            "kommentti": s["kommentti"],
            "tehtavat": tehtavat_data,
        })
    return {"vartio": vartio, "rastit": rasti_data}