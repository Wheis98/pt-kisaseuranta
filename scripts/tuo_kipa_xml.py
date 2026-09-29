"""Tuo sarjat, rastit ja tehtävät vanhan Kipan kisatiedostosta (Kipa: /kipa/<kisa>/tallenna/ -> tietokanta.xml).

Käyttö:  python scripts/tuo_kipa_xml.py tietokanta.xml data/kipa.db [--korvaa "Energy Vaasa"] [--kuivaharjoitus]

Vanhassa Kipassa tehtävät kuuluvat sarjoille, tässä järjestelmässä rasteille. Jokaisesta eri nimisestä
tehtävästä tehdään oma rasti (tunnuksena tehtävän nimi), jolla on yksi kaava-tehtävä. Sarjan reitiksi
tulevat sen tehtävien rastit Kipan järjestysnumeron mukaan. Jos saman niminen tehtävä on eri sarjoissa
eri tavalla määritelty, käytetään yleisintä versiota; syöte, joka puuttuu joidenkin sarjojen versiosta,
on vapaaehtoinen (tyhjä = 0).

Kipan osatehtävän parametrit (suor, muk, tapa, parhaan_haku...) sijoitetaan valmiiksi kaavaan samalla
tavalla kuin Kipan TulosLaskin tekee, joten tuloksena on app/kaava.py:n ymmärtämä Kipa-syntaksin kaava.

Olemassa olevia rasteja ei muuteta (ne ohitetaan). --korvaa "Rastin nimi" (voi toistaa) vaihtaa olemassa
olevan rastin tehtävät tiedoston mukaisiksi; rasti asetuksineen ja rastioikeuksineen säilyy. Korvaus
keskeytetään, jos rastilla on jo tuloksia. Sarjojen reitit kirjoitetaan aina uudelleen tiedoston mukaisiksi.
Vartioita ei tuoda.
"""
import collections
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PROJEKTI = Path(__file__).resolve().parent.parent

if len(sys.argv) < 3:
    sys.exit(__doc__)
xml_polku, kanta = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
kuiva = "--kuivaharjoitus" in sys.argv[3:]
korvattavat = {sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == "--korvaa"}
if not xml_polku.exists():
    sys.exit(f"Tiedostoa ei löydy: {xml_polku}")
if not kanta.exists():
    sys.exit(f"Tietokantaa ei löydy: {kanta}")
os.environ["KIPA_DB"] = str(kanta)
sys.path.insert(0, str(PROJEKTI))  # app-paketti löytyy, vaikka skripti on scripts-kansiossa

from app import db  # noqa: E402  (KIPA_DB pitää olla asetettu ennen importtia)
from app.kaava import evaluoi, KaavaVirhe  # noqa: E402


# --- XML:n luku ---------------------------------------------------------------------------------------------

O = collections.defaultdict(dict)
for obj in ET.parse(xml_polku).getroot():
    O[obj.get("model").split(".")[1]][obj.get("pk")] = {f.get("name"): f.text or "" for f in obj}

def lapset(malli, kentta, pk):
    return [(k, v) for k, v in sorted(O[malli].items(), key=lambda x: int(x[0])) if v[kentta] == pk]


# --- Kipan kaavan muodostus (vrt. tupa/TulosLaskin.py: luoOsatehtavanKaava, suoritusJoukko, luoTehtavanKaava) --

def suoritus_joukko(s):
    # Vartion suoritus a -> .a eli kaikkien saman sarjan vartioiden vastaava arvo
    s = re.sub(r"(([.][^-,+*/ ]+)+)(\.[^-,+*/)(]*)(?![^-,+*/() ])", r"\g<1>", s)
    return re.sub(r"(?<![a-zA-Z.])([a-zA-Z]\w*)(?!\w*[(.])", r".\g<1>", s)

def osatehtavan_kaava(kaava, parametrit, syotteet):
    if kaava == "ss":  # suora summa syötteistä
        kaava = "+".join(syotteet)
    for _ in range(50):
        vanha = kaava
        for nimi, arvo in parametrit.items():
            kaava = re.sub(nimi + r"(?!\w+)", lambda _m, a=arvo: a, kaava)
        kaava = re.sub(r"muk(?!\w+)", "..mukana", kaava)
        if "vartion_kaava" in parametrit:
            vk = parametrit["vartion_kaava"]
            for nimi, arvo in parametrit.items():
                vk = re.sub(nimi + r"(?!\w+)", lambda _m, a=arvo: a, vk)
            kaava = re.sub(r"suor(?!\w+)", lambda _m: suoritus_joukko(vk), kaava)
        if kaava == vanha:
            return kaava
    raise ValueError(f"Kaavan parametrit eivät asetu: {kaava}")

def tehtavan_kaava(kaava, osat):
    # osat: [(osatehtävän nimi, lauseke)]. Kipa laskee jokaisen osatehtävän vähintään nollaksi.
    if kaava.lower() == "ss":
        return "+".join(f"max(0, {x})" for _, x in osat)
    kaava = kaava.lower()
    for nimi, x in osat:
        kaava = re.sub(r"(?<!\w|[.])" + nimi + r"(?<![.])(?!\w+)(?![.])", lambda _m, x=x: f"max(0, {x})", kaava)
    return kaava


# --- Tehtävien määritelmät ---------------------------------------------------------------------------------

def nimi_luettavaksi(nimi):
    return nimi.replace("_", " ").title() if nimi.isupper() else nimi.strip()

def maaritelma(tid):
    t = O["tehtava"][tid]
    osat = []
    for oid, ot in sorted(lapset("osatehtava", "tehtava", tid), key=lambda x: x[1]["nimi"]):
        syotteet = [{"nimi": s["nimi"], "kuvaus": s["kali_vihje"].strip(), "tyyppi": s["tyyppi"]}
                    for _, s in sorted(lapset("syotemaarite", "osa_tehtava", oid), key=lambda x: x[1]["nimi"])]
        parametrit = {p["nimi"]: p["arvo"] for _, p in lapset("parametri", "osa_tehtava", oid)}
        if "parhaan_haku" in parametrit and not parametrit["parhaan_haku"]:
            # Tyhjällä haulla Kipa laskee interpoloi():n listan [vartion suoritus, nollasuoritus] jokaiselle
            # alkiolle ja ottaa suurimman; kaava.py ei laske listalla, joten valitaan suurempi suoritus ensin
            parametrit["parhaan_haku"] = "max"
        osat.append({
            "nimi": ot["nimi"],
            "kaava": osatehtavan_kaava(ot["kaava"], parametrit, [s["nimi"] for s in syotteet]),
            "syotteet": syotteet,
        })
    return {
        "kaava": t["kaava"],
        "max": float(t["maksimipisteet"].replace(",", ".")) if t["maksimipisteet"].strip() else None,
        "ohje": t["rastikasky"].strip() or None,
        "osat": osat,
    }

sarjat = {pk: s["nimi"].strip() for pk, s in sorted(O["sarja"].items(), key=lambda x: int(x[0]))}
# tehtävän nimi -> [(sarja-pk, järjestysnro, kipa-pk, määritelmä)]
tehtavat = collections.defaultdict(list)
for tid, t in O["tehtava"].items():
    tehtavat[t["nimi"].strip()].append((t["sarja"], int(t["jarjestysnro"] or 0), int(tid), maaritelma(tid)))

def avain(m):
    # Vertailuavain versioille: osatehtävien ja syötteiden järjestys voi vaihdella sarjojen välillä
    return repr({**m, "osat": sorted(({**o, "syotteet": sorted(o["syotteet"], key=repr)} for o in m["osat"]), key=repr)})

valitut = {}
for nimi, versiot in tehtavat.items():
    laskuri = collections.Counter(avain(v[3]) for v in versiot)
    yleisin, kpl = laskuri.most_common(1)[0]
    valitut[nimi] = next(v[3] for v in versiot if avain(v[3]) == yleisin)
    if len(laskuri) > 1:
        poikkeavat = sorted(sarjat[v[0]] for v in versiot if avain(v[3]) != yleisin)
        print(f"HUOM: {nimi_luettavaksi(nimi)} on määritelty eri tavalla sarjoissa {', '.join(poikkeavat)} "
              f"— käytetään muiden sarjojen versiota ({kpl}/{len(versiot)})")
        # Syöte, joka puuttuu joidenkin sarjojen versiosta (esim. Energy Vaasan Potkuri), on vapaaehtoinen:
        # tyhjänä se lasketaan nollaksi, ja kuvaukseen merkitään sarjat, joita se koskee
        for osa in valitut[nimi]["osat"]:
            for s in osa["syotteet"]:
                mukana = sorted(sarjat[v[0]] for v in versiot
                                if any(o["nimi"] == osa["nimi"] and any(x["nimi"] == s["nimi"] for x in o["syotteet"])
                                       for o in v[3]["osat"]))
                if len(mukana) < len(versiot):
                    osa["kaava"] = re.sub(r"(?<![\w.])" + s["nimi"] + r"(?![\w(])", f"oletus({s['nimi']}, 0)", osa["kaava"])
                    s["kuvaus"] += f" – vain {', '.join(mukana)}"
                    print(f"      {osa['nimi']}/{s['nimi']} {s['kuvaus']}: vapaaehtoinen, tyhjä = 0")

# Rastien yleinen järjestys: sarja, jossa on eniten tehtäviä, ja sen järjestys; muut perään
def sarjan_tehtavat(spk):
    return [n for n, _, _ in sorted(((n, jn, pk) for n, vv in tehtavat.items() for s, jn, pk, _ in vv if s == spk),
                                    key=lambda x: (x[1], x[2]))]

laajin = max(sarjat, key=lambda s: len(sarjan_tehtavat(s)))
rastijarjestys = sarjan_tehtavat(laajin) + sorted(n for n in tehtavat if n not in sarjan_tehtavat(laajin))


# --- Kaavojen tarkistus esimerkkiarvoilla -----------------------------------------------------------------

def testiarvot(osa, i):
    # Aika-syötteet kellonaikoina sekunteina (alku ennen loppua), pisteet pieninä lukuina
    return {s["nimi"]: (36000 + 600 * j + 60 * i if s["tyyppi"] == "aika" else 1 + (i + j) % 3)
            for j, s in enumerate(osa["syotteet"])}

def tarkista(nimi, m):
    for osa in m["osat"]:
        kaikki = [testiarvot(osa, i) for i in range(4)]
        try:
            float(evaluoi(osa["kaava"], kaikki[0], kaikki))
        except KaavaVirhe as e:
            sys.exit(f"Kaava ei toimi: {nimi} / osatehtävä {osa['nimi']}: {e}\n  {osa['kaava']}")


# --- Tallennus ----------------------------------------------------------------------------------------------

def lisaa_syotteet(taso, kohde_id, syotteet):
    for j, s in enumerate(syotteet, 1):
        tyyppi = "aika" if s["tyyppi"] == "aika" or re.search(r"ylitetty aika", s["kuvaus"], re.I) else "piste"
        db.execute("INSERT INTO syotemaaritteet (taso, kohde_id, nimi, kuvaus, tyyppi, jarjestys) VALUES (?,?,?,?,?,?)",
                   (taso, kohde_id, s["nimi"], s["kuvaus"], tyyppi, j))

def poista_tehtavat(rasti_id):
    # Rastin tehtävät, osatehtävät ja syötemääritteet (tuloksia ei ole, se on tarkistettu ennen tätä)
    for t in db.execute("SELECT id FROM tehtavat WHERE rasti_id=?", (rasti_id,)).fetchall():
        for o in db.execute("SELECT id FROM osatehtavat WHERE tehtava_id=?", (t["id"],)).fetchall():
            db.execute("DELETE FROM syotemaaritteet WHERE taso='osatehtava' AND kohde_id=?", (o["id"],))
        db.execute("DELETE FROM osatehtavat WHERE tehtava_id=?", (t["id"],))
        db.execute("DELETE FROM syotemaaritteet WHERE taso='tehtava' AND kohde_id=?", (t["id"],))
    db.execute("DELETE FROM tehtavat WHERE rasti_id=?", (rasti_id,))

def rastilla_tuloksia(rasti_id):
    return db.execute("""
        SELECT 1 FROM suoritukset s WHERE s.rasti_id=? AND (
            EXISTS (SELECT 1 FROM tehtava_tulokset WHERE suoritus_id=s.id)
            OR EXISTS (SELECT 1 FROM osatehtava_tulokset WHERE suoritus_id=s.id)
            OR EXISTS (SELECT 1 FROM syote_arvot WHERE suoritus_id=s.id))
    """, (rasti_id,)).fetchone() is not None

def lisaa_tehtava(rasti_id, nimi, m):
    if len(m["osat"]) == 1:
        # Yksi osatehtävä: syötteet ja koko kaava suoraan tehtävälle
        osa = m["osat"][0]
        kaava = tehtavan_kaava(m["kaava"], [(osa["nimi"], osa["kaava"])])
        cur = db.execute("INSERT INTO tehtavat (rasti_id, nimi, tyyppi, max_pisteet, jarjestys, kaava, ohje) VALUES (?,?,?,?,?,?,?)",
                         (rasti_id, nimi_luettavaksi(nimi), "kaava", m["max"], 1, kaava, m["ohje"]))
        lisaa_syotteet("tehtava", cur.lastrowid, osa["syotteet"])
        return
    # Useampi osatehtävä: osatehtävän pisteet ovat tehtävän kaavassa sen kirjaimella (a, b, c...)
    kaava = tehtavan_kaava(m["kaava"], [(o["nimi"], o["nimi"]) for o in m["osat"]])
    cur = db.execute("INSERT INTO tehtavat (rasti_id, nimi, tyyppi, max_pisteet, jarjestys, kaava, ohje) VALUES (?,?,?,?,?,?,?)",
                     (rasti_id, nimi_luettavaksi(nimi), "kaava", m["max"], 1, kaava, m["ohje"]))
    tehtava_id = cur.lastrowid
    for j, osa in enumerate(m["osat"], 1):
        osan_nimi = osa["syotteet"][0]["kuvaus"] if len(osa["syotteet"]) == 1 else f"Osa {osa['nimi'].upper()}"
        cur = db.execute("INSERT INTO osatehtavat (tehtava_id, nimi, tyyppi, jarjestys, kaava, muuttuja) VALUES (?,?,?,?,?,?)",
                         (tehtava_id, osan_nimi, "kaava", j, osa["kaava"], osa["nimi"]))
        lisaa_syotteet("osatehtava", cur.lastrowid, osa["syotteet"])


for nimi in rastijarjestys:
    tarkista(nimi, valitut[nimi])

tuntemattomat = korvattavat - {nimi_luettavaksi(n) for n in rastijarjestys}
if tuntemattomat:
    sys.exit(f"--korvaa: tiedostossa ei ole tehtävää {', '.join(sorted(tuntemattomat))}")

olemassa = {r["numero"]: r["id"] for r in db.execute("SELECT id, numero FROM rastit").fetchall()}
alku = db.execute("SELECT COALESCE(MAX(jarjestys),0) FROM rastit").fetchone()[0]
for i, nimi in enumerate(rastijarjestys, 1):
    rasti = nimi_luettavaksi(nimi)
    if rasti in olemassa and rasti not in korvattavat:
        print(f"Ohitetaan rasti {rasti}: on jo olemassa")
        continue
    if rasti in olemassa:
        if rastilla_tuloksia(olemassa[rasti]):
            db.rollback()
            sys.exit(f"Keskeytetty: rastilla {rasti} on jo tuloksia, sen tehtäviä ei korvata. Mitään ei tallennettu.")
        poista_tehtavat(olemassa[rasti])
        rasti_id = olemassa[rasti]
        print(f"Korvataan rastin {rasti} tehtävät:", end=" ")
    else:
        rasti_id = db.execute("INSERT INTO rastit (numero, jarjestys) VALUES (?,?)", (rasti, alku + i)).lastrowid
        print(f"Rasti {rasti}:", end=" ")
    lisaa_tehtava(rasti_id, nimi, valitut[nimi])
    print(f"{len(valitut[nimi]['osat'])} osatehtävää")

rasti_idt = {r["numero"]: r["id"] for r in db.execute("SELECT id, numero FROM rastit").fetchall()}
for spk, snimi in sarjat.items():
    db.execute("INSERT OR IGNORE INTO sarjat (nimi) VALUES (?)", (snimi,))
    sarja_id = db.execute("SELECT id FROM sarjat WHERE nimi=?", (snimi,)).fetchone()["id"]
    reitti = [rasti_idt[nimi_luettavaksi(n)] for n in sarjan_tehtavat(spk)]
    db.execute("DELETE FROM sarja_rastit WHERE sarja_id=?", (sarja_id,))
    for j, rasti_id in enumerate(reitti):
        db.execute("INSERT INTO sarja_rastit (sarja_id, rasti_id, jarjestys) VALUES (?,?,?)", (sarja_id, rasti_id, j))
    print(f"Sarja {snimi}: {len(reitti)} rastia")

if kuiva:
    db.rollback()
    print("Kuivaharjoitus: mitään ei tallennettu")
else:
    db.commit()
    print(f"Tallennettu kantaan {kanta}")
