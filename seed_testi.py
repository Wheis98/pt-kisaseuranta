"""Täyttää testitietokannan (kipa-testi.db) esimerkkirasteilla, -tehtävillä ja -vartioilla.

Käyttö:  python seed_testi.py
Ei koskaan kirjoita kipa.db:hen. Ajo on idempotentti: jos rasteja on jo, ei lisätä mitään.
"""
import os
import sys
import uuid
from pathlib import Path

testikanta = Path(__file__).resolve().parent / "kipa-testi.db"
os.environ["KIPA_DB"] = str(testikanta)

from app import db  # noqa: E402  (KIPA_DB pitää olla asetettu ennen importtia)

polku = Path(db.execute("PRAGMA database_list").fetchone()["file"]).resolve()
if polku != testikanta:
    sys.exit(f"Keskeytetty: käytössä on {polku}, ei kipa-testi.db")


# (rasti, [(tehtävä, tyyppi, max_pisteet, [(osatehtävä, tyyppi, max_pisteet), ...])])
# oikein_vaarin-tehtävän maksimi muodostuu osatehtävistä, joten sille max_pisteet on None.
RASTIT = {
    "1": [
        ("Solmukilpa", "ajanotto", 10, []),
        ("Solmujen tunnistus", "oikein_vaarin", None,
         [("Ankkurisolmu", "oikein_vaarin", 1), ("Vaadinsolmu", "oikein_vaarin", 1), ("Tukkimiehensolmu", "oikein_vaarin", 1)]),
        ("Köysisilta", "pisteet", 8, []),
        ("Solmun selitys", "pisteet", 5, []),
        ("Tiimityö", "pisteet", 5, []),
        ("Turvallisuus", "oikein_vaarin", None,
         [("Kypärä päässä", "oikein_vaarin", 2), ("Varmistus tehty", "oikein_vaarin", 2)]),
    ],
    "2": [
        ("Ensiapuviesti", "pisteet", 10, []),
        ("Sidontatehtävä", "ajanotto", 12, []),
        ("Tajuton potilas", "oikein_vaarin", None,
         [("Tarkistus", "oikein_vaarin", 1), ("Hätänumero", "oikein_vaarin", 1), ("Asento", "oikein_vaarin", 2)]),
        ("Ensiapupakkaus", "pisteet", 6, []),
        ("Kylmävamma", "oikein_vaarin", None,
         [("Oireet", "oikein_vaarin", 2), ("Hoito", "oikein_vaarin", 2)]),
        ("Ryhmän toiminta", "pisteet", 4, []),
    ],
    "3": [
        ("Kartanlukurata", "ajanotto", 15, []),
        ("Karttamerkit", "oikein_vaarin", None,
         [("Kallio", "oikein_vaarin", 1), ("Suo", "oikein_vaarin", 1), ("Polku", "oikein_vaarin", 1), ("Rakennus", "oikein_vaarin", 1)]),
        ("Atsimuutti", "pisteet", 8, []),
        ("Etäisyysarvio", "pisteet", 6, []),
        ("Kompassin käyttö", "pisteet", 6, []),
        ("Suunnistusrasti", "oikein_vaarin", None,
         [("Löytyi", "oikein_vaarin", 3)]),
    ],
    "4": [
        ("Tulen sytytys", "ajanotto", 10, []),
        ("Nuotion rakenne", "pisteet", 8, []),
        ("Palokunnossa", "oikein_vaarin", None,
         [("Vesiämpäri valmiina", "oikein_vaarin", 1), ("Tulipaikka raivattu", "oikein_vaarin", 1), ("Sammutus", "oikein_vaarin", 2)]),
        ("Ruoanlaitto", "pisteet", 10, []),
        ("Puukon käsittely", "oikein_vaarin", None,
         [("Turvallinen ote", "oikein_vaarin", 2), ("Turvaväli", "oikein_vaarin", 2)]),
        ("Siisteys", "pisteet", 4, []),
    ],
    "5": [
        ("Estejuoksu", "ajanotto", 12, []),
        ("Tietovisa", "pisteet", 10, []),
        ("Luonnontuntemus", "oikein_vaarin", None,
         [("Puulaji", "oikein_vaarin", 1), ("Lintu", "oikein_vaarin", 1), ("Kasvi", "oikein_vaarin", 1)]),
        ("Leiripaikan arviointi", "pisteet", 6, []),
        ("Jäljet", "oikein_vaarin", None,
         [("Jälki tunnistettu", "oikein_vaarin", 2), ("Eläin nimetty", "oikein_vaarin", 1)]),
        ("Lopputehtävä", "pisteet", 8, []),
    ],
}

# (nimi, numero, sarja, lippukunta, piiri) — samaa muotoa kuin oikeat vartiot
VARTIOT = [
    ("Testikarhut", "901", "Harmaa", "Testilaakson Karhut", "Hämeen Partiopiiri ry"),
    ("Yökotkat", "902", "Harmaa", "Kotkalan Erämiehet", "Lounais-Suomen Partiopiiri ry"),
    ("Sudenpennut", "903", "Keltainen", "Sudenkorven Vaeltajat", "Uudenmaan Partiopiiri ry"),
    ("Tulikärpäset", "904", "Keltainen", "Helsingin Metsänkävijät", "Pääkaupunkiseudun Partiolaiset ry"),
    ("Punaiset Ketut", "905", "Punainen", "Kajaanin Korvenpojat ry", "Järvi-Suomen Partiolaiset ry"),
    ("Ruskeat Ahmat", "906", "Ruskea", "Nokian Eräveikot", "Hämeen Partiopiiri ry"),
    ("Siniset Joet", "907", "Sininen", "Olarinmäen Samoojat", "Pääkaupunkiseudun Partiolaiset ry"),
]

if db.execute("SELECT COUNT(*) FROM rastit WHERE numero IN (%s)" % ",".join("?" * len(RASTIT)), tuple(RASTIT)).fetchone()[0]:
    sys.exit("Seed-rasteja (1-5) on jo testikannassa — aja .\\testi.ps1 -Nollaa jos haluat aloittaa alusta")

# Lisätään olemassa olevan datan jatkoksi, ei korvata sitä
alku_j = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM rastit").fetchone()[0]
for j, (numero, tehtavat) in enumerate(RASTIT.items(), start=alku_j + 1):
    rasti_id = db.execute("INSERT INTO rastit (numero, jarjestys) VALUES (?,?)", (numero, j)).lastrowid
    for tj, (nimi, tyyppi, max_p, osat) in enumerate(tehtavat, start=1):
        tid = db.execute(
            "INSERT INTO tehtavat (rasti_id, nimi, tyyppi, max_pisteet, jarjestys) VALUES (?,?,?,?,?)",
            (rasti_id, nimi, tyyppi, max_p, tj),
        ).lastrowid
        for oj, (onimi, otyyppi, omax) in enumerate(osat, start=1):
            db.execute(
                "INSERT INTO osatehtavat (tehtava_id, nimi, tyyppi, max_pisteet, jarjestys) VALUES (?,?,?,?,?)",
                (tid, onimi, otyyppi, omax, oj),
            )

for nimi, numero, sarja, lippukunta, piiri in VARTIOT:
    if db.execute("SELECT 1 FROM vartiot WHERE numero=?", (numero,)).fetchone():
        continue
    db.execute(
        "INSERT INTO vartiot (nimi, token, numero, sarja, lippukunta, piiri) VALUES (?,?,?,?,?,?)",
        (nimi, str(uuid.uuid4()), numero, sarja, lippukunta, piiri),
    )
db.commit()

print(f"Testikanta {polku}:")
print(" rastit:", db.execute("SELECT COUNT(*) FROM rastit").fetchone()[0],
      "| tehtävät:", db.execute("SELECT COUNT(*) FROM tehtavat").fetchone()[0],
      "| osatehtävät:", db.execute("SELECT COUNT(*) FROM osatehtavat").fetchone()[0],
      "| vartiot:", db.execute("SELECT COUNT(*) FROM vartiot").fetchone()[0])
