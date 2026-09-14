from fastapi import APIRouter
from fastapi.responses import FileResponse
from app import db
from app.utils import laske_siirtyma_mediaanit

router = APIRouter()

@router.get("/tilanne.html")
def tilanne_page():
    return FileResponse("static/tilanne.html")

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

    vartiot_rows = db.execute("SELECT nimi, jasenet FROM vartiot ORDER BY nimi").fetchall()

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
            "jasenet": v["jasenet"],
            "status": status,
            "sijainti": sijainti,
            "aika": aika,
            "arvioitu_saapuminen": arvioitu_saapuminen,
            "siirtyma_lahde": siirtyma_lahde if status == "tulossa" else None,
            "kaynut_talla_rastilla": v["nimi"] in kaynneet_set,
        })

    return result