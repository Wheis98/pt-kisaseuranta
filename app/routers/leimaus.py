from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, sessions, admin_sessions, LeimausIn, JonoIn, STATIC_DIR
from app.utils import vaadi_admin

router = APIRouter()

@router.get("/leimaus.html")
def leimaus_page():
    return FileResponse(STATIC_DIR / "leimaus.html")

@router.get("/data.html")
def data_page():
    return FileResponse(STATIC_DIR / "data.html")

@router.post("/api/leimaus")
def leimaus(l: LeimausIn):
    # Tallentaa sisään- tai ulosleimauksen. Estää kaksoisleimauksen sisään ilman välistä ulosta.
    session = sessions.get(l.token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    if not l.vartio.strip():
        raise HTTPException(status_code=400, detail="Vartion nimi vaaditaan")
    vartio_row = db.execute("SELECT id FROM vartiot WHERE nimi=?", (l.vartio.strip(),)).fetchone()
    if not vartio_row:
        raise HTTPException(status_code=404, detail=f"Vartiota '{l.vartio.strip()}' ei löydy — pyydä adminia luomaan vartio ensin")
    if not l.rastinumero.strip():
        raise HTTPException(status_code=400, detail="Rastinumero vaaditaan")
    if l.tyyppi not in ("sisaan", "ulos"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    if l.tyyppi == "sisaan":
        viimeisin = db.execute(
            "SELECT numero, tyyppi FROM leimaukset WHERE vartio=? ORDER BY id DESC LIMIT 1",
            (l.vartio.strip(),)
        ).fetchone()
        if viimeisin and viimeisin["tyyppi"] == "sisaan":
            raise HTTPException(status_code=409, detail=f"{l.vartio.strip()} on jo rastilla {viimeisin['numero']} — leimaa ensin ulos")
        if not l.uudelleen:
            aiempi_ulos = db.execute(
                "SELECT id FROM leimaukset WHERE vartio=? AND numero=? AND tyyppi='ulos'",
                (l.vartio.strip(), l.rastinumero.strip())
            ).fetchone()
            if aiempi_ulos:
                raise HTTPException(status_code=409, detail=f"uudelleen_kaynti:{l.vartio.strip()}")
    db.execute(
        "INSERT INTO leimaukset (kayttaja, numero, vartio, aika, tyyppi) VALUES (?,?,?,?,?)",
        (session["nimi"], l.rastinumero.strip(), l.vartio.strip(), l.aika, l.tyyppi),
    )
    if l.tyyppi == "sisaan":
        # Rastille otettu vartio poistuu tämän rastin jonosta
        db.execute("DELETE FROM jono WHERE numero=? AND vartio=?", (l.rastinumero.strip(), l.vartio.strip()))
    db.commit()
    return {"ok": True}

@router.post("/api/jono")
def lisaa_jonoon(j: JonoIn):
    # Lisää vartion rastin jonoon odottamaan rastille pääsyä
    if not sessions.get(j.token):
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    vartio = j.vartio.strip()
    numero = j.rastinumero.strip()
    if not vartio or not numero:
        raise HTTPException(status_code=400, detail="Vartion nimi ja rastinumero vaaditaan")
    if not db.execute("SELECT id FROM vartiot WHERE nimi=?", (vartio,)).fetchone():
        raise HTTPException(status_code=404, detail=f"Vartiota '{vartio}' ei löydy — pyydä adminia luomaan vartio ensin")
    viimeisin = db.execute(
        "SELECT numero, tyyppi FROM leimaukset WHERE vartio=? ORDER BY id DESC LIMIT 1", (vartio,)
    ).fetchone()
    if viimeisin and viimeisin["tyyppi"] == "sisaan":
        raise HTTPException(status_code=409, detail=f"{vartio} on jo rastilla {viimeisin['numero']}")
    if db.execute("SELECT id FROM jono WHERE numero=? AND vartio=?", (numero, vartio)).fetchone():
        raise HTTPException(status_code=409, detail=f"{vartio} on jo jonossa")
    db.execute("INSERT INTO jono (numero, vartio, aika) VALUES (?,?,?)", (numero, vartio, j.aika))
    db.commit()
    return {"ok": True}

@router.get("/api/jono")
def hae_jono(numero: str):
    rows = db.execute("SELECT id, vartio, aika FROM jono WHERE numero=? ORDER BY id", (numero,)).fetchall()
    return [dict(r) for r in rows]

@router.delete("/api/jono/{jono_id}")
def poista_jonosta(jono_id: int, token: str):
    if not sessions.get(token):
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    db.execute("DELETE FROM jono WHERE id=?", (jono_id,))
    db.commit()
    return {"ok": True}

@router.get("/api/aktiiviset")
def aktiiviset(numero: str):
    # Palauttaa vartiot jotka ovat tällä hetkellä sisään leimattuina tietylle rastille.
    # Subquery varmistaa että otetaan vain viimeisin leimaus per vartio+rasti-pari.
    rows = db.execute("""
        SELECT vartio, aika FROM leimaukset l1
        WHERE numero = ? AND tyyppi = 'sisaan'
        AND id = (
            SELECT MAX(id) FROM leimaukset l2
            WHERE l2.vartio = l1.vartio AND l2.numero = l1.numero
        )
        ORDER BY id DESC
    """, (numero,)).fetchall()
    return [dict(r) for r in rows]

@router.get("/api/pisteita-odottavat")
def pisteita_odottavat(numero: str):
    # Palauttaa vartiot jotka on leimattu ulos tältä rastilta mutta joiden kaikkia tehtäviä ei ole vielä pisteytetty.
    # Tehtävä on pisteytetty kun sillä on tulos, tai osatehtävällisellä tehtävällä kun jokaisella osatehtävällä on tulos.
    # Vain viimeisin leimaus per vartio ratkaisee (uudelleen sisään leimattu vartio ei ole vielä valmis).
    # Kun vartio tuodaan rastille uudelleen ja leimataan taas ulos, se nousee listalle vaikka kaikki tehtävät
    # olisi pisteytetty ensimmäisellä käynnillä, kunnes pisteet on tallennettu uudestaan.
    rows = db.execute("""
        SELECT l.vartio, l.aika FROM leimaukset l
        JOIN rastit r ON r.numero = l.numero
        WHERE l.numero = ? AND l.tyyppi = 'ulos'
        AND l.id = (SELECT MAX(id) FROM leimaukset l2 WHERE l2.vartio = l.vartio AND l2.numero = l.numero)
        AND (
            -- vartio on käynyt rastilla uudelleen sen jälkeen kun pisteet tallennettiin viimeksi.
            -- Vanhalla datalla (ei tallennettua käyntiä) oletetaan pisteet annetuksi ensimmäisellä käynnillä.
            COALESCE((SELECT p.leimaus_id FROM pisteytetyt_kaynnit p
                      WHERE p.vartio = l.vartio AND p.rasti_id = r.id),
                     (SELECT MIN(l4.id) FROM leimaukset l4
                      WHERE l4.vartio = l.vartio AND l4.numero = l.numero AND l4.tyyppi = 'ulos')) < l.id
            -- tehtävä ilman osatehtäviä, jolle ei ole tulosta
            OR EXISTS (
                SELECT 1 FROM tehtavat t
                WHERE t.rasti_id = r.id
                AND NOT EXISTS (SELECT 1 FROM osatehtavat o WHERE o.tehtava_id = t.id)
                AND NOT EXISTS (
                    SELECT 1 FROM tehtava_tulokset tt JOIN suoritukset s ON s.id = tt.suoritus_id
                    WHERE s.vartio = l.vartio AND s.rasti_id = r.id AND tt.tehtava_id = t.id)
            )
            -- osatehtävä, jolle ei ole tulosta
            OR EXISTS (
                SELECT 1 FROM osatehtavat o JOIN tehtavat t ON t.id = o.tehtava_id
                WHERE t.rasti_id = r.id
                AND NOT EXISTS (
                    SELECT 1 FROM osatehtava_tulokset ot JOIN suoritukset s ON s.id = ot.suoritus_id
                    WHERE s.vartio = l.vartio AND s.rasti_id = r.id AND ot.osatehtava_id = o.id)
            )
        )
        ORDER BY l.id
    """, (numero,)).fetchall()
    return [{"vartio": r["vartio"], "aika": r["aika"]} for r in rows]

@router.get("/api/data")
def get_data(token: str = "", numero: str = "", vartio: str = "", x_admin_token: str = Header(None)):
    if x_admin_token and x_admin_token in admin_sessions:
        query = "SELECT id, kayttaja, numero, vartio, aika, tyyppi FROM leimaukset WHERE 1=1"
        params: list = []
        if numero:
            query += " AND numero=?"; params.append(numero)
        if vartio:
            query += " AND vartio=?"; params.append(vartio)
        query += " ORDER BY id DESC"
    elif token:
        session = sessions.get(token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
        if not numero:
            raise HTTPException(status_code=400, detail="Rastinumero vaaditaan")
        query = "SELECT id, kayttaja, numero, vartio, aika, tyyppi FROM leimaukset WHERE numero=? ORDER BY id DESC"
        params = [numero]
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]

@router.delete("/api/leimaus/{leimaus_id}")
def delete_leimaus(leimaus_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM leimaukset WHERE id=?", (leimaus_id,))
    db.commit()
    return {"ok": True}