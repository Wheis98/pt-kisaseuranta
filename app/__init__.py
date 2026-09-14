from pathlib import Path
from pydantic import BaseModel
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Yhdistetään SQLite-tietokantaan. check_same_thread=False sallii saman yhteyden eri säikeistä.
db = sqlite3.connect(BASE_DIR.parent / "kipa.db", check_same_thread=False)
db.row_factory = sqlite3.Row  # palauttaa rivit dict-tyylisesti nimen perusteella

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
  jasenet INTEGER NOT NULL,
  aika TEXT NOT NULL,
  tyyppi TEXT NOT NULL DEFAULT 'sisaan'
);
CREATE TABLE IF NOT EXISTS vartiot (
  id INTEGER PRIMARY KEY,
  nimi TEXT NOT NULL,
  jasenet INTEGER NOT NULL,
  token TEXT UNIQUE NOT NULL
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
  tyyppi TEXT NOT NULL CHECK(tyyppi IN ('pisteet','oikein_vaarin','ajanotto')),
  max_pisteet REAL,
  jarjestys INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS osatehtavat (
  id INTEGER PRIMARY KEY,
  tehtava_id INTEGER NOT NULL,
  nimi TEXT NOT NULL,
  tyyppi TEXT NOT NULL CHECK(tyyppi IN ('pisteet','oikein_vaarin','ajanotto')),
  max_pisteet REAL,
  jarjestys INTEGER NOT NULL DEFAULT 0
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


class LeimausIn(BaseModel):
    token: str
    rastinumero: str
    vartio: str
    jasenet: int
    aika: str
    tyyppi: str = "sisaan"
    uudelleen: bool = False  # True = toinen käynti samalla rastilla hyväksytty


class TehtavaIn(BaseModel):
    rasti_id: int
    nimi: str
    tyyppi: str
    max_pisteet: float | None = None
    jarjestys: int = 0


class OsatehtavaIn(BaseModel):
    tehtava_id: int
    nimi: str
    tyyppi: str
    max_pisteet: float | None = None
    jarjestys: int = 0


class TulosIn(BaseModel):
    suoritus_id: int
    tehtava_id: int | None = None
    osatehtava_id: int | None = None
    pisteet: float | None = None
    oikein: int | None = None
    aika_sekuntia: float | None = None
    token: str | None = None
    aika: str


class SuoritusKommenttiIn(BaseModel):
    kommentti: str | None = None
    token: str | None = None


class AsetusIn(BaseModel):
    arvo: str


class VartioIn(BaseModel):
    nimi: str
    jasenet: int


class RastiIn(BaseModel):
    numero: str
    kesto_min: int = 10
    siirtyma_min: int = 5


class RastiJarjestysIn(BaseModel):
    jarjestys: list[int]  # lista rasti-id:istä halutussa järjestyksessä


class AdminIn(BaseModel):
    kayttajanimi: str
    salasana: str
