# Varmuuskopioi käytössä olevan kannan sovelluksen pyöriessä. Ajetaan palvelimella cronista 5 minuutin välein:
#   docker compose exec -T sovellus python /data/varmuuskopioi.py
# Kopiot menevät kannan viereen kansioon varmuuskopiot/:
#   <kanta>-5min-1.db … -3.db   kolme viimeisintä, vanhin kirjoitetaan yli
#   <kanta>-tunti-VVVVKKPP-HH00.db   jokaisen tunnin alussa, säilytetään kaikki
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

kanta = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KIPA_DB") or "/data/kipa.db")
if not kanta.is_file():
    sys.exit(f"VIRHE: kantaa {kanta} ei löydy")
kansio = kanta.parent / "varmuuskopiot"
kansio.mkdir(exist_ok=True)
nyt = datetime.now()

# Kopio tehdään ensin väliaikaistiedostoon: kesken jäänyt kopiointi ei riko aiempaa kopiota
kohde = kansio / f"{kanta.stem}-5min-{nyt.minute // 5 % 3 + 1}.db"
tmp = kohde.with_suffix(".tmp")
tmp.unlink(missing_ok=True)
lahde = sqlite3.connect(kanta, timeout=30)
kopio = sqlite3.connect(tmp)
lahde.backup(kopio)
lahde.close()
eheys = kopio.execute("PRAGMA quick_check").fetchone()[0]
leimauksia = kopio.execute("SELECT COUNT(*) FROM leimaukset").fetchone()[0]
kopio.close()
if eheys != "ok":
    tmp.unlink()
    sys.exit(f"VIRHE: kopio ei ole eheä ({eheys}), aiempi kopio {kohde.name} jätettiin ennalleen")
os.replace(tmp, kohde)
viesti = f"{nyt:%d.%m.%Y %H:%M:%S} {kanta.name} -> {kohde.name} ({kohde.stat().st_size // 1024} kt, {leimauksia} leimausta)"

if nyt.minute < 5:
    tunti = kansio / f"{kanta.stem}-tunti-{nyt:%Y%m%d-%H}00.db"
    shutil.copy2(kohde, tunti)
    viesti += f" + {tunti.name}"
print(viesti)
