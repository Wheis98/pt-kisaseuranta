from datetime import datetime
from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, LahtoIn, STATIC_DIR
from app.utils import vaadi_admin
from app.routers.leimaus import kirjaa_jono

router = APIRouter()

@router.get("/lahdot.html")
def lahdot_page():
    return FileResponse(STATIC_DIR / "lahdot.html")

def _lahdon_vartiot(lahto_id: int) -> list:
    # Lähdön sarjoihin kuuluvat vartiot (vartion sarja-kenttä = sarjan nimi)
    return [r["nimi"] for r in db.execute("""
        SELECT v.nimi FROM vartiot v
        JOIN sarjat s ON s.nimi = v.sarja
        JOIN lahto_sarjat ls ON ls.sarja_id = s.id
        WHERE ls.lahto_id=? ORDER BY v.nimi
    """, (lahto_id,)).fetchall()]

@router.get("/api/lahdot")
def get_lahdot(x_admin_token: str = Header(None)):
    # Lähdöt sarjoineen, lähtörasteineen ja vartiomäärineen
    vaadi_admin(x_admin_token)
    tulos = []
    for l in db.execute("""
        SELECT l.id, l.nimi, l.rasti_id, r.numero AS rasti_numero, l.kaynnistetty
        FROM lahdot l LEFT JOIN rastit r ON r.id = l.rasti_id ORDER BY l.jarjestys, l.id
    """).fetchall():
        d = dict(l)
        d["sarjat"] = [dict(s) for s in db.execute(
            "SELECT s.id, s.nimi FROM lahto_sarjat ls JOIN sarjat s ON s.id = ls.sarja_id WHERE ls.lahto_id=? ORDER BY s.nimi",
            (l["id"],)).fetchall()]
        d["vartiot"] = _lahdon_vartiot(l["id"])
        tulos.append(d)
    return tulos

def _tallenna_sarjat(lahto_id: int, sarja_idt: list) -> None:
    # Sarja voi kuulua vain yhteen lähtöön: siirretään valitut sarjat tähän lähtöön
    db.execute("DELETE FROM lahto_sarjat WHERE lahto_id=?", (lahto_id,))
    for sarja_id in sarja_idt:
        db.execute("DELETE FROM lahto_sarjat WHERE sarja_id=?", (sarja_id,))
        db.execute("INSERT INTO lahto_sarjat (lahto_id, sarja_id) VALUES (?,?)", (lahto_id, sarja_id))

@router.post("/api/lahto")
def create_lahto(l: LahtoIn, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    if not l.nimi.strip():
        raise HTTPException(status_code=400, detail="Lähdön nimi vaaditaan")
    max_j = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM lahdot").fetchone()[0]
    lahto_id = db.execute("INSERT INTO lahdot (nimi, rasti_id, jarjestys) VALUES (?,?,?)",
                          (l.nimi.strip(), l.rasti_id, max_j + 1)).lastrowid
    _tallenna_sarjat(lahto_id, l.sarja_idt)
    db.commit()
    return {"id": lahto_id, "ok": True}

@router.put("/api/lahto/{lahto_id}")
def update_lahto(lahto_id: int, l: LahtoIn, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    if not l.nimi.strip():
        raise HTTPException(status_code=400, detail="Lähdön nimi vaaditaan")
    db.execute("UPDATE lahdot SET nimi=?, rasti_id=? WHERE id=?", (l.nimi.strip(), l.rasti_id, lahto_id))
    _tallenna_sarjat(lahto_id, l.sarja_idt)
    db.commit()
    return {"ok": True}

@router.delete("/api/lahto/{lahto_id}")
def delete_lahto(lahto_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM lahto_sarjat WHERE lahto_id=?", (lahto_id,))
    db.execute("DELETE FROM lahdot WHERE id=?", (lahto_id,))
    db.commit()
    return {"ok": True}

@router.post("/api/lahto/{lahto_id}/kaynnista")
def kaynnista_lahto(lahto_id: int, uudelleen: bool = False, x_admin_token: str = Header(None)):
    # Käynnistää lähdön: kaikki lähdön vartiot leimataan sisään lähtörastille ja niiden ajastin käynnistyy
    # samalla sekunnilla. Jo lähtörastilla oleva vartio (esim. uusintalähtö) saa vain uuden aloitusajan.
    # Muulla rastilla sisällä olevaa vartiota ei siirretä, vaan se raportoidaan ohitettuna.
    # Jo käynnistetty lähtö käynnistetään uudelleen vain erikseen vahvistettuna (uudelleen=true), jottei
    # vanhentunut sivu (toinen admin, vanha välilehti) nollaa käynnissä olevan kisan aloitusaikoja.
    vaadi_admin(x_admin_token)
    lahto = db.execute("""
        SELECT l.nimi, l.kaynnistetty, r.numero FROM lahdot l LEFT JOIN rastit r ON r.id = l.rasti_id WHERE l.id=?
    """, (lahto_id,)).fetchone()
    if not lahto:
        raise HTTPException(status_code=404, detail="Lähtöä ei löydy")
    if lahto["kaynnistetty"] and not uudelleen:
        raise HTTPException(status_code=409, detail=f"jo_kaynnistetty:{lahto['kaynnistetty']}")
    if not lahto["numero"]:
        raise HTTPException(status_code=400, detail="Valitse lähdölle lähtörasti ennen käynnistystä")
    vartiot = _lahdon_vartiot(lahto_id)
    if not vartiot:
        raise HTTPException(status_code=400, detail="Lähdössä ei ole yhtään vartiota — valitse sarjat")

    nyt = datetime.now()
    iso = nyt.isoformat(timespec="seconds")
    leima = f"{nyt.day}.{nyt.month}.{nyt.year} klo {nyt.hour}.{nyt.minute:02d}.{nyt.second:02d}"  # kuten selaimen fi-FI-aika
    kayttaja = f"Admin: {lahto['nimi']}"
    numero = lahto["numero"]
    leimattu, uusittu, ohitettu = [], [], []
    for vartio in vartiot:
        viimeisin = db.execute("SELECT numero, tyyppi FROM leimaukset WHERE vartio=? ORDER BY id DESC LIMIT 1", (vartio,)).fetchone()
        if viimeisin and viimeisin["tyyppi"] == "sisaan":
            if viimeisin["numero"] != numero:
                ohitettu.append({"vartio": vartio, "syy": f"on rastilla {viimeisin['numero']}"})
                continue
            uusittu.append(vartio)
        else:
            db.execute("INSERT INTO leimaukset (kayttaja, numero, vartio, aika, tyyppi) VALUES (?,?,?,?,'sisaan')",
                       (kayttaja, numero, vartio, leima))
            if db.execute("DELETE FROM jono WHERE numero=? AND vartio=?", (numero, vartio)).rowcount:
                kirjaa_jono(numero, vartio, "rastille", leima, kayttaja)
            leimattu.append(vartio)
        db.execute("DELETE FROM ajastimet WHERE numero=? AND vartio=?", (numero, vartio))
        db.execute("INSERT INTO ajastimet (numero, vartio, alku, kayttaja) VALUES (?,?,?,?)", (numero, vartio, iso, kayttaja))
    db.execute("UPDATE lahdot SET kaynnistetty=? WHERE id=?", (iso, lahto_id))
    db.commit()
    return {"ok": True, "kaynnistetty": iso, "rasti": numero,
            "leimattu": leimattu, "uusittu": uusittu, "ohitettu": ohitettu}
