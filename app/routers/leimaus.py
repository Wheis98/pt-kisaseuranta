from datetime import datetime
from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, sessions, admin_sessions, LeimausIn, JonoIn, AjastinIn, STATIC_DIR
from app.utils import vaadi_admin, ryhman_rastit, rastin_nimi, AUTOMAATTINEN_ULOS

router = APIRouter()

def _nyt_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _pysayta_ajastin(numero: str, vartio: str) -> None:
    # Kirjaa lopetusajan käynnissä olevalle ajastimelle (ei tee mitään jos ajastinta ei ole tai se on jo pysäytetty)
    db.execute("UPDATE ajastimet SET loppu=? WHERE numero=? AND vartio=? AND loppu IS NULL", (_nyt_iso(), numero, vartio))

def kirjaa_jono(numero: str, vartio: str, tapahtuma: str, aika: str, kayttaja: str):
    # Kirjaa jonon tapahtuman (jonoon / rastille / poistettu) — jono-taulusta rivi poistuu, loki jää
    db.execute("INSERT INTO jono_loki (numero, vartio, tapahtuma, aika, kayttaja) VALUES (?,?,?,?,?)",
               (numero, vartio, tapahtuma, aika, kayttaja))

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
    automaattisesti_ulos = []
    if l.tyyppi == "sisaan":
        viimeisin = db.execute(
            "SELECT numero, tyyppi FROM leimaukset WHERE vartio=? ORDER BY id DESC LIMIT 1",
            (l.vartio.strip(),)
        ).fetchone()
        if viimeisin and viimeisin["tyyppi"] == "sisaan":
            edellinen = ryhman_rastit(viimeisin["numero"])
            if l.rastinumero.strip() in edellinen:
                raise HTTPException(status_code=409, detail=f"{l.vartio.strip()} on jo tällä rastilla")
            if not l.pakota:
                # Leimaussivu kysyy varmistuksen ja lähettää pyynnön uudelleen pakota=True
                raise HTTPException(status_code=409, detail=f"jo_rastilla:{rastin_nimi(edellinen[0])}")
            automaattisesti_ulos = edellinen[1:] + edellinen[:1]  # edustaja viimeisenä kuten ulosleimauksessa
        if not l.uudelleen:
            aiempi_ulos = db.execute(
                "SELECT id FROM leimaukset WHERE vartio=? AND numero=? AND tyyppi='ulos'",
                (l.vartio.strip(), l.rastinumero.strip())
            ).fetchone()
            if aiempi_ulos:
                raise HTTPException(status_code=409, detail=f"uudelleen_kaynti:{l.vartio.strip()}")
    # Rastiryhmässä (esim. yörastit) vartio leimataan samalla kertaa kaikille ryhmän rasteille. Edustajan rivi
    # kirjataan sisäänleimauksessa ensimmäisenä ja ulosleimauksessa viimeisenä, jotta siirtymäaikojen mediaanit
    # (edellinen rasti -> edustaja -> seuraava rasti) lasketaan ryhmälle oikein.
    # Vartio oli vielä sisällä toisella rastilla: kirjataan sieltä ulos samalla ajalla. Merkintä leimaajan nimessä
    # jättää siirtymän pois mediaaneista, koska oikeaa lähtöaikaa ei tiedetä.
    for numero in automaattisesti_ulos:
        db.execute("INSERT INTO leimaukset (kayttaja, numero, vartio, aika, tyyppi) VALUES (?,?,?,?,'ulos')",
                   (session["nimi"] + AUTOMAATTINEN_ULOS, numero, l.vartio.strip(), l.aika))
        _pysayta_ajastin(numero, l.vartio.strip())
    rastit = ryhman_rastit(l.rastinumero.strip())
    if l.tyyppi == "ulos":
        rastit = rastit[1:] + rastit[:1]
    for numero in rastit:
        db.execute(
            "INSERT INTO leimaukset (kayttaja, numero, vartio, aika, tyyppi) VALUES (?,?,?,?,?)",
            (session["nimi"], numero, l.vartio.strip(), l.aika, l.tyyppi),
        )
        if l.tyyppi == "sisaan":
            # Rastille otettu vartio poistuu tämän rastin jonosta
            poistettu = db.execute("DELETE FROM jono WHERE numero=? AND vartio=?", (numero, l.vartio.strip())).rowcount
            if poistettu:
                kirjaa_jono(numero, l.vartio.strip(), "rastille", l.aika, session["nimi"])
            # Uusi käynti aloittaa puhtaalta ajastimelta (edellisen käynnin ajat on jo tallennettu pisteisiin)
            db.execute("DELETE FROM ajastimet WHERE numero=? AND vartio=?", (numero, l.vartio.strip()))
        else:
            _pysayta_ajastin(numero, l.vartio.strip())
    db.commit()
    return {"ok": True}

def _ajastin_dict(r) -> dict:
    # Ajastimen tiedot näytettäväksi: kellonajat hh:mm:ss, samat sekunteina vuorokauden alusta (kaavan
    # aika-syötteitä varten) ja kesto sekunteina — käynnissä olevalle kesto tähän hetkeen asti.
    alku = datetime.fromisoformat(r["alku"])
    loppu = datetime.fromisoformat(r["loppu"]) if r["loppu"] else None
    sek = lambda d: d.hour * 3600 + d.minute * 60 + d.second
    return {
        "vartio": r["vartio"],
        "alku": alku.strftime("%H:%M:%S"),
        "loppu": loppu.strftime("%H:%M:%S") if loppu else None,
        "alku_sek": sek(alku),
        "loppu_sek": sek(loppu) if loppu else None,
        "kesto": int(((loppu or datetime.now()) - alku).total_seconds()),
        "kaynnissa": loppu is None,
    }

@router.get("/api/ajastimet")
def hae_ajastimet(numero: str = "", rasti_id: int = 0, vartio: str = ""):
    # Rastin ajastimet (rastinumerolla tai rasti_id:llä), valinnaisesti yhdelle vartiolle
    if not numero and rasti_id:
        r = db.execute("SELECT numero FROM rastit WHERE id=?", (rasti_id,)).fetchone()
        numero = r["numero"] if r else ""
    query, params = "SELECT vartio, alku, loppu FROM ajastimet WHERE numero=?", [numero]
    if vartio:
        query += " AND vartio=?"; params.append(vartio)
    return [_ajastin_dict(r) for r in db.execute(query, params).fetchall()]

def _ajastin_istunto(a: AjastinIn) -> dict:
    session = sessions.get(a.token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    return session

@router.post("/api/ajastin/aloita")
def aloita_ajastin(a: AjastinIn):
    # Kirjaa aloitusajan palvelimen kellosta. Jo käynnistettyä ajastinta ei aloiteta uudelleen (nollaa ensin).
    session = _ajastin_istunto(a)
    numero, vartio = a.rastinumero.strip(), a.vartio.strip()
    if db.execute("SELECT id FROM ajastimet WHERE numero=? AND vartio=?", (numero, vartio)).fetchone():
        raise HTTPException(status_code=409, detail="Ajastin on jo käynnistetty — nollaa se ensin")
    alku = _nyt_iso()
    for n in ryhman_rastit(numero):  # rastiryhmässä sama ajastin kaikille ryhmän rasteille
        db.execute("INSERT OR REPLACE INTO ajastimet (numero, vartio, alku, kayttaja) VALUES (?,?,?,?)",
                   (n, vartio, alku, session["nimi"]))
    db.commit()
    return {"ok": True}

@router.post("/api/ajastin/pysayta")
def pysayta_ajastin(a: AjastinIn):
    _ajastin_istunto(a)
    for n in ryhman_rastit(a.rastinumero.strip()):
        _pysayta_ajastin(n, a.vartio.strip())
    db.commit()
    return {"ok": True}

@router.post("/api/ajastin/nollaa")
def nollaa_ajastin(a: AjastinIn):
    _ajastin_istunto(a)
    for n in ryhman_rastit(a.rastinumero.strip()):
        db.execute("DELETE FROM ajastimet WHERE numero=? AND vartio=?", (n, a.vartio.strip()))
    db.commit()
    return {"ok": True}

@router.post("/api/jono")
def lisaa_jonoon(j: JonoIn):
    # Lisää vartion rastin jonoon odottamaan rastille pääsyä
    session = sessions.get(j.token)
    if not session:
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
        raise HTTPException(status_code=409, detail=f"{vartio} on jo rastilla {rastin_nimi(viimeisin['numero'])}")
    if db.execute("SELECT id FROM jono WHERE numero=? AND vartio=?", (numero, vartio)).fetchone():
        raise HTTPException(status_code=409, detail=f"{vartio} on jo jonossa")
    db.execute("INSERT INTO jono (numero, vartio, aika) VALUES (?,?,?)", (numero, vartio, j.aika))
    kirjaa_jono(numero, vartio, "jonoon", j.aika, session["nimi"])
    db.commit()
    return {"ok": True}

@router.get("/api/jono")
def hae_jono(numero: str):
    rows = db.execute("SELECT id, vartio, aika FROM jono WHERE numero=? ORDER BY id", (numero,)).fetchall()
    return [dict(r) for r in rows]

@router.delete("/api/jono/{jono_id}")
def poista_jonosta(jono_id: int, token: str, aika: str = ""):
    session = sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    rivi = db.execute("SELECT numero, vartio FROM jono WHERE id=?", (jono_id,)).fetchone()
    if rivi:
        db.execute("DELETE FROM jono WHERE id=?", (jono_id,))
        kirjaa_jono(rivi["numero"], rivi["vartio"], "poistettu", aika or datetime.now().strftime("%d.%m.%Y klo %H.%M.%S"), session["nimi"])
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

def _nakyy_vartiolle(sarake: str) -> str:
    # SQL-ehto: sarjarajaus (JSON-lista sarja-id:istä tai NULL) sallii vartion l.vartio. Vartio, jonka sarjaa
    # ei ole sarjat-taulussa, näkee kaiken (kuten pistesivulla ja tuloslaskennassa).
    return f"""({sarake} IS NULL
        OR NOT EXISTS (SELECT 1 FROM vartiot v JOIN sarjat sj ON sj.nimi = v.sarja WHERE v.nimi = l.vartio)
        OR EXISTS (SELECT 1 FROM vartiot v JOIN sarjat sj ON sj.nimi = v.sarja, json_each({sarake}) je
                   WHERE v.nimi = l.vartio AND je.value = sj.id))"""

def _syotteita_nakyvissa(taso: str, kohde: str) -> str:
    # SQL-ehto: kohteella ei ole syötteitä, tai ainakin yksi niistä näkyy vartion sarjalle. Jos kaikki syötteet
    # on piilotettu, pistesivu ei näytä kohdetta eikä sille voi tallentaa tulosta, joten sitä ei odoteta.
    return f"""(NOT EXISTS (SELECT 1 FROM syotemaaritteet sm WHERE sm.taso = '{taso}' AND sm.kohde_id = {kohde})
        OR EXISTS (SELECT 1 FROM syotemaaritteet sm WHERE sm.taso = '{taso}' AND sm.kohde_id = {kohde}
                   AND {_nakyy_vartiolle("sm.sarjat")}))"""

@router.get("/api/pisteita-odottavat")
def pisteita_odottavat(numero: str):
    # Rastiryhmässä vartio odottaa pisteitä, jos jokin ryhmän rasteista on pisteyttämättä
    tulos: dict = {}
    for n in ryhman_rastit(numero):
        for v in _pisteita_odottavat_rastilla(n):
            tulos.setdefault(v["vartio"], v)
    return list(tulos.values())

def _pisteita_odottavat_rastilla(numero: str):
    # Palauttaa vartiot jotka on leimattu ulos tältä rastilta mutta joiden kaikkia tehtäviä ei ole vielä pisteytetty.
    # Tehtävä on pisteytetty kun sillä on tulos, tai osatehtävällisellä tehtävällä kun jokaisella osatehtävällä on tulos.
    # Vain viimeisin leimaus per vartio ratkaisee (uudelleen sisään leimattu vartio ei ole vielä valmis).
    # Kun vartio tuodaan rastille uudelleen ja leimataan taas ulos, se nousee listalle vaikka kaikki tehtävät
    # olisi pisteytetty ensimmäisellä käynnillä, kunnes pisteet on tallennettu uudestaan.
    rows = db.execute(f"""
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
                AND {_syotteita_nakyvissa("tehtava", "t.id")}
                AND NOT EXISTS (
                    SELECT 1 FROM tehtava_tulokset tt JOIN suoritukset s ON s.id = tt.suoritus_id
                    WHERE s.vartio = l.vartio AND s.rasti_id = r.id AND tt.tehtava_id = t.id)
            )
            -- osatehtävä, jolle ei ole tulosta (vartion sarjalta piilotettuja ei odoteta)
            OR EXISTS (
                SELECT 1 FROM osatehtavat o JOIN tehtavat t ON t.id = o.tehtava_id
                WHERE t.rasti_id = r.id
                AND {_nakyy_vartiolle("o.sarjat")}
                AND {_syotteita_nakyvissa("osatehtava", "o.id")}
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