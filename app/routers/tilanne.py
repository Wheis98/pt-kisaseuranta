from fastapi import APIRouter, Header
from fastapi.responses import FileResponse
from app import db, STATIC_DIR
from app.utils import laske_siirtyma_mediaanit, vaadi_admin

router = APIRouter()

@router.get("/tilanne.html")
def tilanne_page():
    return FileResponse(STATIC_DIR / "tilanne.html")

@router.get("/yleistilanne.html")
def yleistilanne_page():
    return FileResponse(STATIC_DIR / "yleistilanne.html")

def _parse_aika(s):
    from datetime import datetime
    for fmt in ("%d.%m.%Y klo %H.%M.%S", "%d.%m.%Y %H.%M.%S", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            pass
    return None

@router.get("/api/yleistilanne")
def yleistilanne(x_admin_token: str = Header(None)):
    # Admin-yleisnäkymä: jokaisen rastin vartiot rastilla ja jonossa sekä viimeisimmän kirjauksen aikaleima.
    vaadi_admin(x_admin_token)
    rastit = db.execute("SELECT numero FROM rastit ORDER BY jarjestys, id").fetchall()
    # Vartio on rastilla, jos sen viimeisin leimaus on sisäänleimaus
    sisalla = db.execute("""
        SELECT l.numero, l.vartio, l.aika FROM leimaukset l
        WHERE l.tyyppi='sisaan' AND l.id = (SELECT MAX(id) FROM leimaukset l2 WHERE l2.vartio = l.vartio)
        ORDER BY l.id
    """).fetchall()
    # Vartio on matkalla, jos sen viimeisin leimaus on ulosleimaus (lähti rastilta, ei vielä sisäänleimausta seuraavalla)
    matkalla = db.execute("""
        SELECT l.numero, l.vartio, l.aika FROM leimaukset l
        WHERE l.tyyppi='ulos' AND l.id = (SELECT MAX(id) FROM leimaukset l2 WHERE l2.vartio = l.vartio)
        ORDER BY l.id
    """).fetchall()
    jonossa = db.execute("SELECT numero, vartio, aika FROM jono ORDER BY id").fetchall()
    viimeisin = {r["numero"]: r["aika"] for r in db.execute(
        "SELECT numero, aika FROM leimaukset WHERE id IN (SELECT MAX(id) FROM leimaukset GROUP BY numero)")}
    loki_rows = db.execute("SELECT numero, vartio, tapahtuma, aika, kayttaja FROM jono_loki ORDER BY id DESC").fetchall()
    tulos = []
    for r in rastit:
        n = r["numero"]
        matkalla_talta = [{"vartio": x["vartio"], "aika": x["aika"]} for x in matkalla if x["numero"] == n]
        rastilla = [{"vartio": x["vartio"], "aika": x["aika"]} for x in sisalla if x["numero"] == n]
        jono = [{"vartio": x["vartio"], "aika": x["aika"]} for x in jonossa if x["numero"] == n]
        # Viimeisin muutos = uusin aikaleima leimauksista ja jonoon lisäyksistä
        loki = [dict(x) for x in loki_rows if x["numero"] == n][:5]
        ehdokkaat = [a for a in [viimeisin.get(n)] + [j["aika"] for j in jono] + [x["aika"] for x in loki] if a]
        ehdokkaat.sort(key=lambda a: _parse_aika(a) or _parse_aika("01.01.1970 00.00.00"))
        tulos.append({"numero": n, "rastilla": rastilla, "jonossa": jono,
                      "jono_loki": loki, "matkalla": matkalla_talta,
                      "viimeisin_muutos": ehdokkaat[-1] if ehdokkaat else None})
    return tulos

@router.get("/api/tilanne")
def tilanne(numero: str = ""):
    # Palauttaa kaikkien vartioiden tilanteen tietyltä rastilta katsottuna.
    # Status-arvot: rastilla_oma, rastilla_muu, tulossa, matkalla, ei_aloitettu.
    # Jos vartio lähti edelliseltä rastilta, lasketaan arvioitu saapumisaika
    # mediaanin tai manuaalisen arvion perusteella.
    from datetime import datetime, timedelta

    rastit_rows = db.execute("SELECT numero, siirtyma_min FROM rastit ORDER BY jarjestys, id").fetchall()
    rasti_lista = [r["numero"] for r in rastit_rows]
    siirtyma_map = {r["numero"]: r["siirtyma_min"] for r in rastit_rows}
    mediaanit = laske_siirtyma_mediaanit()

    # Selvitetään mikä rasti on järjestyksessä ennen pyydettävää rastia
    prev_rasti = None
    if numero and numero in rasti_lista:
        idx = rasti_lista.index(numero)
        prev_rasti = rasti_lista[idx - 1] if idx > 0 else None

    vartiot_rows = db.execute("SELECT nimi FROM vartiot ORDER BY nimi").fetchall()

    kaynneet_set = set()
    if numero:
        kaynneet_set = set(row["vartio"] for row in db.execute(
            "SELECT DISTINCT vartio FROM leimaukset WHERE numero=? AND tyyppi='ulos'", (numero,)
        ).fetchall())

    result = []
    for v in vartiot_rows:
        last = db.execute(
            "SELECT numero, tyyppi, aika FROM leimaukset WHERE vartio=? ORDER BY id DESC LIMIT 1",
            (v["nimi"],)
        ).fetchone()

        arvioitu_saapuminen = None
        siirtyma_lahde = None

        if not last:
            status = "ei_aloitettu"
            sijainti = None
            aika = None
        elif last["tyyppi"] == "sisaan":
            sijainti = last["numero"]
            aika = last["aika"]
            status = "rastilla_oma" if sijainti == numero else "rastilla_muu"
        else:
            sijainti = None
            aika = last["aika"]
            lahto_rasti = last["numero"]
            if prev_rasti and lahto_rasti == prev_rasti:
                status = "tulossa"
                mediaani_key = lahto_rasti + "→" + numero
                if mediaani_key in mediaanit and mediaanit[mediaani_key]["n"] >= 2:
                    siirtyma = mediaanit[mediaani_key]["mediaani"]
                    siirtyma_lahde = "mediaani"
                else:
                    siirtyma = siirtyma_map.get(lahto_rasti, 5)
                    siirtyma_lahde = "arvio"
                for fmt in ("%d.%m.%Y klo %H.%M.%S", "%d.%m.%Y %H.%M.%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y klo %H.%M"):
                    try:
                        lahto_aika = datetime.strptime(aika, fmt)
                        arvioitu_saapuminen = (lahto_aika + timedelta(minutes=siirtyma)).strftime("%H:%M")
                        break
                    except Exception:
                        pass
            else:
                status = "matkalla"
                sijainti = lahto_rasti

        result.append({
            "nimi": v["nimi"],
            "status": status,
            "sijainti": sijainti,
            "aika": aika,
            "arvioitu_saapuminen": arvioitu_saapuminen,
            "siirtyma_lahde": siirtyma_lahde if status == "tulossa" else None,
            "kaynut_talla_rastilla": v["nimi"] in kaynneet_set,
        })

    return result