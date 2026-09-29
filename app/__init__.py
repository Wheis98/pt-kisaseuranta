from pathlib import Path
from pydantic import BaseModel
import os
import sqlite3
import threading

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

class _Tietokanta:
    """Antaa jokaiselle säikeelle oman SQLite-yhteyden, jolloin yhden pyynnön commit ei vahvista toisen
    pyynnön keskeneräisiä kirjoituksia. Muu koodi käyttää tätä kuten tavallista yhteyttä (db.execute, db.commit)."""
    def __init__(self, polku):
        self._polku = str(polku)
        self._local = threading.local()
        # Muistitietokanta on olemassa vain yhdessä yhteydessä, joten sille käytetään jaettua yhteyttä
        self._jaettu = self._yhteys(check_same_thread=False) if self._polku == ":memory:" else None

    def _yhteys(self, check_same_thread=True):
        c = sqlite3.connect(self._polku, timeout=10, check_same_thread=check_same_thread)  # timeout: odottaa toisen kirjoituksen valmistumista
        c.row_factory = sqlite3.Row  # palauttaa rivit dict-tyylisesti nimen perusteella
        return c

    def __getattr__(self, nimi):
        c = self._jaettu or getattr(self._local, "c", None)
        if c is None:
            c = self._local.c = self._yhteys()
        return getattr(c, nimi)

# Yhdistetään SQLite-tietokantaan.
# KIPA_DB-ympäristömuuttujalla voi käyttää toista tietokantaa (esim. testaukseen).
# Oletuksena kanta on projektin data-kansiossa (data/kipa.db).
_DB_POLKU = os.environ.get("KIPA_DB") or BASE_DIR.parent / "data" / "kipa.db"
if str(_DB_POLKU) != ":memory:":
    Path(_DB_POLKU).parent.mkdir(parents=True, exist_ok=True)
db = _Tietokanta(_DB_POLKU)

# Luodaan taulut jos niitä ei vielä ole
db.executescript("""
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL UNIQUE,
  token TEXT UNIQUE NOT NULL,
  salasana_hash TEXT
);
CREATE TABLE IF NOT EXISTS rastit (
  id INTEGER PRIMARY KEY,
  numero TEXT NOT NULL UNIQUE,
  jarjestys INTEGER NOT NULL DEFAULT 0,
  kesto_min INTEGER NOT NULL DEFAULT 10,
  siirtyma_min INTEGER NOT NULL DEFAULT 5
);
CREATE TABLE IF NOT EXISTS leimaukset (
  id INTEGER PRIMARY KEY,
  kayttaja TEXT NOT NULL,
  numero TEXT NOT NULL,
  vartio TEXT NOT NULL,
  aika TEXT NOT NULL,
  tyyppi TEXT NOT NULL DEFAULT 'sisaan'
);
CREATE TABLE IF NOT EXISTS vartiot (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL,
  token TEXT UNIQUE NOT NULL,
  numero TEXT NOT NULL DEFAULT '',
  sarja TEXT NOT NULL DEFAULT '',
  lippukunta TEXT NOT NULL DEFAULT '',
  piiri TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS admins (
  id INTEGER PRIMARY KEY,
  kayttajanimi TEXT NOT NULL UNIQUE,
  salasana_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asetukset (
  avain TEXT PRIMARY KEY,
  arvo TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tehtavat (
  id INTEGER PRIMARY KEY,
  rasti_id INTEGER NOT NULL,
  nimi TEXT NOT NULL,
  tyyppi TEXT NOT NULL CHECK(tyyppi IN ('pisteet','oikein_vaarin','ajanotto','kaava')),
  max_pisteet REAL,
  jarjestys INTEGER NOT NULL DEFAULT 0,
  kaava TEXT
);
CREATE TABLE IF NOT EXISTS osatehtavat (
  id INTEGER PRIMARY KEY,
  tehtava_id INTEGER NOT NULL,
  nimi TEXT NOT NULL,
  tyyppi TEXT NOT NULL CHECK(tyyppi IN ('pisteet','oikein_vaarin','ajanotto','kaava')),
  max_pisteet REAL,
  jarjestys INTEGER NOT NULL DEFAULT 0,
  kaava TEXT
);
CREATE TABLE IF NOT EXISTS suoritukset (
  id INTEGER PRIMARY KEY,
  vartio TEXT NOT NULL,
  rasti_id INTEGER NOT NULL,
  kommentti TEXT,
  luotu TEXT NOT NULL,
  UNIQUE(vartio, rasti_id)
);
CREATE TABLE IF NOT EXISTS tehtava_tulokset (
  id INTEGER PRIMARY KEY,
  suoritus_id INTEGER NOT NULL,
  tehtava_id INTEGER NOT NULL,
  pisteet REAL,
  oikein INTEGER,
  aika_sekuntia REAL,
  paivitetty TEXT NOT NULL,
  UNIQUE(suoritus_id, tehtava_id)
);
CREATE TABLE IF NOT EXISTS osatehtava_tulokset (
  id INTEGER PRIMARY KEY,
  suoritus_id INTEGER NOT NULL,
  osatehtava_id INTEGER NOT NULL,
  pisteet REAL,
  oikein INTEGER,
  aika_sekuntia REAL,
  paivitetty TEXT NOT NULL,
  UNIQUE(suoritus_id, osatehtava_id)
);
CREATE TABLE IF NOT EXISTS pisteytetyt_kaynnit (
  vartio TEXT NOT NULL,
  rasti_id INTEGER NOT NULL,
  leimaus_id INTEGER NOT NULL,
  PRIMARY KEY (vartio, rasti_id)
);
CREATE TABLE IF NOT EXISTS jono (
  id INTEGER PRIMARY KEY,
  numero TEXT NOT NULL,
  vartio TEXT NOT NULL,
  aika TEXT NOT NULL,
  UNIQUE(numero, vartio)
);
CREATE TABLE IF NOT EXISTS jono_loki (
  id INTEGER PRIMARY KEY,
  numero TEXT NOT NULL,
  vartio TEXT NOT NULL,
  tapahtuma TEXT NOT NULL,  -- jonoon | rastille | poistettu
  aika TEXT NOT NULL,
  kayttaja TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS kayttaja_pyynnot (
  id INTEGER PRIMARY KEY,
  etunimi TEXT NOT NULL,
  sukunimi TEXT NOT NULL,
  rasti_id INTEGER,
  aika TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rasti_oikeudet (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  rasti_id INTEGER NOT NULL,
  UNIQUE(user_id, rasti_id)
);
CREATE TABLE IF NOT EXISTS oikeus_pyynnot (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  rasti_id INTEGER NOT NULL,
  aika TEXT NOT NULL,
  UNIQUE(user_id, rasti_id)
);
CREATE TABLE IF NOT EXISTS syotemaaritteet (
  id INTEGER PRIMARY KEY,
  taso TEXT NOT NULL CHECK(taso IN ('tehtava','osatehtava')),
  kohde_id INTEGER NOT NULL,
  nimi TEXT NOT NULL,
  kuvaus TEXT NOT NULL DEFAULT '',
  tyyppi TEXT NOT NULL CHECK(tyyppi IN ('aika','piste')),
  jarjestys INTEGER NOT NULL DEFAULT 0,
  UNIQUE(taso, kohde_id, nimi)
);
CREATE TABLE IF NOT EXISTS syote_arvot (
  id INTEGER PRIMARY KEY,
  suoritus_id INTEGER NOT NULL,
  syotemaarite_id INTEGER NOT NULL,
  arvo REAL NOT NULL,
  paivitetty TEXT NOT NULL,
  UNIQUE(suoritus_id, syotemaarite_id)
);
CREATE TABLE IF NOT EXISTS ajastimet (
  id INTEGER PRIMARY KEY,
  numero TEXT NOT NULL,
  vartio TEXT NOT NULL,
  alku TEXT NOT NULL,   -- palvelimen kellonaika ISO-muodossa (YYYY-MM-DDTHH:MM:SS)
  loppu TEXT,           -- NULL = ajastin käynnissä
  kayttaja TEXT NOT NULL DEFAULT '',
  UNIQUE(numero, vartio)
);
CREATE TABLE IF NOT EXISTS lahdot (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL,
  rasti_id INTEGER,        -- lähtörasti: käynnistys leimaa vartiot sisään ja käynnistää tämän rastin ajastimet
  jarjestys INTEGER NOT NULL DEFAULT 0,
  kaynnistetty TEXT        -- viimeisimmän käynnistyksen hetki (ISO), NULL = ei käynnistetty
);
CREATE TABLE IF NOT EXISTS lahto_sarjat (
  lahto_id INTEGER NOT NULL,
  sarja_id INTEGER NOT NULL UNIQUE,  -- sarja lähtee vain yhdessä lähdössä
  PRIMARY KEY (lahto_id, sarja_id)
);
CREATE TABLE IF NOT EXISTS sarjat (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS sarja_rastit (
  id INTEGER PRIMARY KEY,
  sarja_id INTEGER NOT NULL,
  rasti_id INTEGER NOT NULL,
  jarjestys INTEGER NOT NULL DEFAULT 0,
  UNIQUE(sarja_id, rasti_id)
);
""")

# Migraatio: poistetaan virheellisesti lisätty rastinumero users-taulusta
try:
    db.execute("ALTER TABLE users DROP COLUMN rastinumero")
    db.commit()
except Exception:
    pass

# Migraatio: lisätään salasana_hash users-tauluun jos puuttuu
try:
    db.execute("ALTER TABLE users ADD COLUMN salasana_hash TEXT")
    db.commit()
except Exception:
    pass

# Migraatio: lisätään puuttuvat sarakkeet vanhoihin tietokantoihin (ALTER TABLE epäonnistuu hiljaa jos sarake on jo olemassa)
# Migraatio: lisätään pisteytys_kaytos rastit-tauluun
try:
    db.execute("ALTER TABLE rastit ADD COLUMN pisteytys_kaytos INTEGER NOT NULL DEFAULT 1")
    db.commit()
except Exception:
    pass

# Oletusasetus pisteytystilalle jos ei vielä asetettu
db.execute("INSERT OR IGNORE INTO asetukset VALUES ('pisteytys_tila','kaikki_pois')")
db.commit()

for col, definition in [
    ("tyyppi", "TEXT NOT NULL DEFAULT 'sisaan'"),
    ("jarjestys", "INTEGER NOT NULL DEFAULT 0"),
    ("kesto_min", "INTEGER NOT NULL DEFAULT 10"),
    ("siirtyma_min", "INTEGER NOT NULL DEFAULT 5"),
]:
    try:
        db.execute(f"ALTER TABLE leimaukset ADD COLUMN {col} {definition}")
        db.commit()
    except Exception:
        pass
    try:
        db.execute(f"ALTER TABLE rastit ADD COLUMN {col} {definition}")
        db.commit()
    except Exception:
        pass

# Migraatio: lisätään vartion numero, sarja, lippukunta ja piiri vanhoihin tietokantoihin
for col in ("numero", "sarja", "lippukunta", "piiri"):
    try:
        db.execute(f"ALTER TABLE vartiot ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        db.commit()
    except Exception:
        pass

# Migraatio: poistetaan vartion koko (jäsenmäärä) käytöstä
try:
    db.execute("ALTER TABLE vartiot DROP COLUMN jasenet")
    db.commit()
except Exception:
    pass
try:
    db.execute("ALTER TABLE leimaukset DROP COLUMN jasenet")
    db.commit()
except Exception:
    pass

# Migraatio: lisätään kaava-sarake tehtavat/osatehtavat-tauluihin (kaavapohyainen pisteytys)
for taulu in ("tehtavat", "osatehtavat"):
    try:
        db.execute(f"ALTER TABLE {taulu} ADD COLUMN kaava TEXT")
        db.commit()
    except Exception:
        pass

# Migraatio: sallitaan tyyppi='kaava' tehtavat/osatehtavat-tauluissa.
# CHECK(tyyppi IN (...)) on leivottu tauluun sen luontihetkellä, joten CREATE TABLE IF NOT EXISTS
# ei päivitä sitä vanhoihin kantoihin — taulu pitää rakentaa uudelleen kertaalleen.
def _salli_kaava_tyyppi(taulu):
    rivi = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (taulu,)).fetchone()
    if not rivi or not rivi["sql"] or "'kaava'" in rivi["sql"]:
        return  # taulua ei vielä ole (executescript hoitaa oikean CHECK:n) tai jo migroitu
    sarakkeet = [r["name"] for r in db.execute(f"PRAGMA table_info({taulu})").fetchall()]
    kentat = ", ".join(sarakkeet)
    db.execute(f"ALTER TABLE {taulu} RENAME TO {taulu}_vanha")
    if taulu == "tehtavat":
        db.execute("""
            CREATE TABLE tehtavat (
              id INTEGER PRIMARY KEY,
              rasti_id INTEGER NOT NULL,
              nimi TEXT NOT NULL,
              tyyppi TEXT NOT NULL CHECK(tyyppi IN ('pisteet','oikein_vaarin','ajanotto','kaava')),
              max_pisteet REAL,
              jarjestys INTEGER NOT NULL DEFAULT 0,
              kaava TEXT
            )
        """)
    else:
        db.execute("""
            CREATE TABLE osatehtavat (
              id INTEGER PRIMARY KEY,
              tehtava_id INTEGER NOT NULL,
              nimi TEXT NOT NULL,
              tyyppi TEXT NOT NULL CHECK(tyyppi IN ('pisteet','oikein_vaarin','ajanotto','kaava')),
              max_pisteet REAL,
              jarjestys INTEGER NOT NULL DEFAULT 0,
              kaava TEXT
            )
        """)
    db.execute(f"INSERT INTO {taulu} ({kentat}) SELECT {kentat} FROM {taulu}_vanha")
    db.execute(f"DROP TABLE {taulu}_vanha")
    db.commit()


for _taulu in ("tehtavat", "osatehtavat"):
    _salli_kaava_tyyppi(_taulu)


# Osatehtävän muuttujanimi tehtävän kaavaa varten: a, b, ..., z, aa, ab, ...
def muuttujan_nimi(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s

def muuttujan_indeksi(s: str) -> int:
    i = 0
    for c in s:
        i = i * 26 + (ord(c) - 96)
    return i - 1

def seuraava_muuttuja(tehtava_id: int) -> str:
    # Seuraava kirjain suurimman käytössä olevan jälkeen. Välistä poistetun osatehtävän kirjainta ei anneta
    # uudelleen (muiden kirjaimet eivät muutu); viimeisen poistaminen vapauttaa sen kirjaimen seuraavalle.
    kaytetyt = [r["muuttuja"] for r in db.execute("SELECT muuttuja FROM osatehtavat WHERE tehtava_id=? AND muuttuja IS NOT NULL", (tehtava_id,))]
    return muuttujan_nimi(max((muuttujan_indeksi(m) for m in kaytetyt), default=-1) + 1)

# Migraatio: osatehtävän muuttujanimi (a, b, c...) tehtävän kaavaa varten — annetaan vanhoille järjestyksessä
try:
    db.execute("ALTER TABLE osatehtavat ADD COLUMN muuttuja TEXT")
    db.commit()
except Exception:
    pass
for _r in db.execute("SELECT id, tehtava_id FROM osatehtavat WHERE muuttuja IS NULL ORDER BY tehtava_id, jarjestys, id").fetchall():
    db.execute("UPDATE osatehtavat SET muuttuja=? WHERE id=?", (seuraava_muuttuja(_r["tehtava_id"]), _r["id"]))
db.commit()

# Migraatio: arvostelukriteerit (ohje) ja valittavat vaihtoehdot (JSON-lista {pisteet, kuvaus}) tehtäville,
# osatehtäville ja kaavan syötteille. Vaihtoehdot näytetään pistesivulla valintoina numerokentän sijaan.
for _taulu, _sarake in (("tehtavat", "ohje"), ("tehtavat", "vaihtoehdot"), ("osatehtavat", "ohje"),
                        ("osatehtavat", "vaihtoehdot"), ("syotemaaritteet", "vaihtoehdot")):
    try:
        db.execute(f"ALTER TABLE {_taulu} ADD COLUMN {_sarake} TEXT")
        db.commit()
    except Exception:
        pass

# Migraatio: saako kaava-tehtävän loppuaika olla alkuaikaa aiemmin (suoritus yli keskiyön)
for _taulu in ("tehtavat", "osatehtavat"):
    try:
        db.execute(f"ALTER TABLE {_taulu} ADD COLUMN keskiyo INTEGER NOT NULL DEFAULT 0")
        db.commit()
    except Exception:
        pass

# Migraatio: sarjarajaus osatehtäville ja kaavan syötteille — JSON-lista sarja-id:istä, NULL = kaikki sarjat.
# Rajatun sarjan vartiolle kohta ei näy pistesivulla ja se lasketaan nollaksi.
for _taulu in ("osatehtavat", "syotemaaritteet"):
    try:
        db.execute(f"ALTER TABLE {_taulu} ADD COLUMN sarjat TEXT")
        db.commit()
    except Exception:
        pass

# Migraatio: sarjan tulokset voidaan laskea yhdessä toisen sarjan kanssa (esim. Harmaa A ja Harmaa B kiertävät
# eri reitit, mutta tulokset ja kaavojen vertailut ovat yhteiset Harmaan kanssa). NULL = oma tulosryhmä.
try:
    db.execute("ALTER TABLE sarjat ADD COLUMN tulossarja_id INTEGER")
    db.commit()
except Exception:
    pass

# Vartion token on painettu QR-koodiin, joten sitä ei saa koskaan muuttaa luonnin jälkeen
db.execute("""
CREATE TRIGGER IF NOT EXISTS vartiot_token_lukittu
BEFORE UPDATE OF token ON vartiot
WHEN NEW.token IS NOT OLD.token
BEGIN
  SELECT RAISE(ABORT, 'Vartion token on lukittu');
END
""")
db.commit()

# Ladataan käyttäjien tokenit muistiin käynnistyksen yhteydessä nopean autentikoinnin vuoksi
sessions: dict = {
    row["token"]: {"nimi": row["nimi"]}
    for row in db.execute("SELECT token, nimi FROM users").fetchall()
}

# Admin-sessiot pidetään pelkästään muistissa — palvelimen uudelleenkäynnistys kirjaa adminit ulos
admin_sessions: set = set()


# ── Pyyntömallit ──────────────────────────────────────────────────────────────

class UserIn(BaseModel):
    nimi: str


class LoginIn(BaseModel):
    nimi: str
    salasana: str


class AsetaSalasanaIn(BaseModel):
    nimi: str
    salasana: str


class JonoIn(BaseModel):
    token: str
    rastinumero: str
    vartio: str
    aika: str

class LeimausIn(BaseModel):
    token: str
    rastinumero: str
    vartio: str
    aika: str
    tyyppi: str = "sisaan"
    uudelleen: bool = False  # True = toinen käynti samalla rastilla hyväksytty


class LahtoIn(BaseModel):
    nimi: str
    rasti_id: int | None = None
    sarja_idt: list[int] = []


class AjastinIn(BaseModel):
    token: str
    rastinumero: str
    vartio: str


class Vaihtoehto(BaseModel):
    pisteet: float
    kuvaus: str = ""


class TehtavaIn(BaseModel):
    rasti_id: int
    nimi: str
    tyyppi: str
    max_pisteet: float | None = None
    jarjestys: int = 0
    kaava: str | None = None
    ohje: str | None = None                          # arvostelukriteerit, näkyy pistesivulla
    vaihtoehdot: list[Vaihtoehto] | None = None      # pisteet-tyypin valittavat vaihtoehdot
    keskiyo: bool = False                            # kaavan loppuaika saa olla ennen alkuaikaa


class OsatehtavaIn(BaseModel):
    tehtava_id: int
    nimi: str
    tyyppi: str
    max_pisteet: float | None = None
    jarjestys: int = 0
    kaava: str | None = None
    ohje: str | None = None
    vaihtoehdot: list[Vaihtoehto] | None = None
    keskiyo: bool = False
    sarjat: list[int] | None = None  # näytetään vain näille sarjoille; [] = kaikki, None = ei muuteta (PUT)


class SyoteMaariteIn(BaseModel):
    nimi: str
    kuvaus: str = ""
    tyyppi: str  # 'aika' | 'piste'
    vaihtoehdot: list[Vaihtoehto] | None = None  # piste-syötteen valittavat vaihtoehdot
    sarjat: list[int] | None = None  # näytetään vain näille sarjoille; [] = kaikki, None = ei muuteta (PUT)


class KaavaTestIn(BaseModel):
    kaava: str
    muuttujat: dict[str, float] = {}


class TulosIn(BaseModel):
    suoritus_id: int
    tehtava_id: int | None = None
    osatehtava_id: int | None = None
    pisteet: float | None = None
    oikein: int | None = None
    aika_sekuntia: float | None = None
    syotteet: dict[str, float] | None = None  # kaava-tyypin nimetyt raaka-arvot
    token: str | None = None
    aika: str


class SuoritusKommenttiIn(BaseModel):
    kommentti: str | None = None
    token: str | None = None


class AsetusIn(BaseModel):
    arvo: str


class VartioIn(BaseModel):
    nimi: str
    numero: str = ""
    sarja: str = ""
    lippukunta: str = ""
    piiri: str = ""


class RastiIn(BaseModel):
    numero: str
    kesto_min: int = 10
    siirtyma_min: int = 5


class RastiJarjestysIn(BaseModel):
    jarjestys: list[int]  # lista rasti-id:istä halutussa järjestyksessä


class SarjaIn(BaseModel):
    nimi: str


class SarjaTulossarjaIn(BaseModel):
    tulossarja_id: int | None = None  # sarja, jonka kanssa tulokset lasketaan yhdessä; None = oma tulosryhmä


class SarjaRastitIn(BaseModel):
    jarjestys: list[int]  # lista rasti-id:istä sarjan reitillä halutussa järjestyksessä — poisjätetyt rastit eivät kuulu sarjan reittiin


class AdminIn(BaseModel):
    kayttajanimi: str
    salasana: str
