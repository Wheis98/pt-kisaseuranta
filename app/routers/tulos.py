from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, admin_sessions, sessions, SuoritusKommenttiIn, TulosIn, STATIC_DIR
from app.utils import vaadi_admin
from app.kaava import evaluoi, KaavaVirhe
import json

router = APIRouter()

@router.get("/pisteet.html")
def pisteet_page():
    return FileResponse(STATIC_DIR / "pisteet.html")

@router.get("/tulokset.html")
def tulokset_page():
    return FileResponse(STATIC_DIR / "tulokset.html")

def merkitse_pisteytetyksi(vartio: str, rasti_id: int):
    # Tallentaa mihin käyntiin (viimeisin leimaus rastilla) pisteet kuuluvat, jotta uudelleen tuotu vartio
    # nousee taas "Merkitse pisteet" -listalle seuraavan ulosleimauksen jälkeen.
    db.execute("""
        INSERT INTO pisteytetyt_kaynnit (vartio, rasti_id, leimaus_id)
        VALUES (?, ?, COALESCE((SELECT MAX(l.id) FROM leimaukset l JOIN rastit r ON r.numero = l.numero
                                WHERE r.id = ? AND l.vartio = ?), 0))
        ON CONFLICT(vartio, rasti_id) DO UPDATE SET leimaus_id = excluded.leimaus_id
    """, (vartio, rasti_id, rasti_id, vartio))

@router.get("/api/suoritus")
def get_or_create_suoritus(vartio: str, rasti_id: int, token: str = "", x_admin_token: str = Header(None)):
    # Hakee tai luo suorituksen vartio+rasti-parille, palauttaa myös tallennetut tulokset
    if token:
        session = sessions.get(token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    vrow = db.execute("SELECT sarja FROM vartiot WHERE nimi=?", (vartio,)).fetchone()
    if not vrow:
        raise HTTPException(status_code=404, detail=f"Vartiota '{vartio}' ei löydy")
    row = db.execute("SELECT id, kommentti FROM suoritukset WHERE vartio=? AND rasti_id=?", (vartio, rasti_id)).fetchone()
    if not row:
        from datetime import datetime
        nyt = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        db.execute("INSERT OR IGNORE INTO suoritukset (vartio, rasti_id, kommentti, luotu) VALUES (?,?,NULL,?)", (vartio, rasti_id, nyt))
        db.commit()
        row = db.execute("SELECT id, kommentti FROM suoritukset WHERE vartio=? AND rasti_id=?", (vartio, rasti_id)).fetchone()
    sid = row["id"]
    tt = db.execute("SELECT tehtava_id, pisteet, oikein, aika_sekuntia FROM tehtava_tulokset WHERE suoritus_id=?", (sid,)).fetchall()
    ot = db.execute("SELECT osatehtava_id, pisteet, oikein, aika_sekuntia FROM osatehtava_tulokset WHERE suoritus_id=?", (sid,)).fetchall()
    syote_rows = db.execute("""
        SELECT sm.taso, sm.kohde_id, sm.nimi, sa.arvo FROM syote_arvot sa
        JOIN syotemaaritteet sm ON sm.id = sa.syotemaarite_id
        WHERE sa.suoritus_id=?
    """, (sid,)).fetchall()
    syotteet: dict = {}
    for r in syote_rows:
        avain = f"{r['taso']}:{r['kohde_id']}"
        syotteet.setdefault(avain, {})[r["nimi"]] = r["arvo"]
    return {
        "id": sid,
        "kommentti": row["kommentti"],
        "tehtava_tulokset": [dict(r) for r in tt],
        "osatehtava_tulokset": [dict(r) for r in ot],
        "syotteet": syotteet,
        "sarja_id": _sarja_id(vrow["sarja"] or ""),  # pistesivu piilottaa kohdat, jotka eivät koske tätä sarjaa
    }

@router.put("/api/suoritus/{suoritus_id}")
def update_suoritus(suoritus_id: int, s: SuoritusKommenttiIn, x_admin_token: str = Header(None)):
    # Päivittää suorituksen kommentin
    if s.token:
        session = sessions.get(s.token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    db.execute("UPDATE suoritukset SET kommentti=? WHERE id=?", (s.kommentti, suoritus_id))
    rivi = db.execute("SELECT vartio, rasti_id FROM suoritukset WHERE id=?", (suoritus_id,)).fetchone()
    if rivi:
        merkitse_pisteytetyksi(rivi["vartio"], rivi["rasti_id"])
    db.commit()
    return {"ok": True}

@router.post("/api/tulos")
def save_tulos(t: TulosIn, x_admin_token: str = Header(None)):
    # Tallentaa tai päivittää yksittäisen tehtävän tai osatehtävän tuloksen
    if t.token:
        session = sessions.get(t.token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
    elif x_admin_token and x_admin_token in admin_sessions:
        pass
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    suoritus = db.execute("SELECT id, vartio, rasti_id FROM suoritukset WHERE id=?", (t.suoritus_id,)).fetchone()
    if not suoritus:
        raise HTTPException(status_code=404, detail="Suoritusta ei löydy")

    if t.tehtava_id is not None:
        taso, kohde_id = "tehtava", t.tehtava_id
        kohde = db.execute("SELECT tyyppi, kaava, max_pisteet, keskiyo FROM tehtavat WHERE id=?", (kohde_id,)).fetchone()
    elif t.osatehtava_id is not None:
        taso, kohde_id = "osatehtava", t.osatehtava_id
        kohde = db.execute("SELECT tyyppi, kaava, max_pisteet, keskiyo FROM osatehtavat WHERE id=?", (kohde_id,)).fetchone()
    else:
        raise HTTPException(status_code=400, detail="tehtava_id tai osatehtava_id vaaditaan")

    pisteet = t.pisteet
    if kohde and kohde["tyyppi"] == "kaava" and t.syotteet is not None:
        # Kaava-tyypin pisteet lasketaan syötteistä, ei anneta suoraan — tallennetaan raaka-arvot
        # ja lasketaan heti alustava pisteet (lopullinen arvo lasketaan aina tuoreena tulosten haussa,
        # koska muiden vartioiden arvot voivat vielä muuttua).
        from datetime import datetime
        nyt = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        _tarkista_aikajarjestys(taso, kohde_id, t.syotteet, bool(kohde["keskiyo"]))
        for nimi, arvo in t.syotteet.items():
            sm = db.execute("SELECT id FROM syotemaaritteet WHERE taso=? AND kohde_id=? AND nimi=?", (taso, kohde_id, nimi)).fetchone()
            if not sm:
                raise HTTPException(status_code=400, detail=f"Tuntematon syöte: {nimi}")
            db.execute("""
                INSERT INTO syote_arvot (suoritus_id, syotemaarite_id, arvo, paivitetty) VALUES (?,?,?,?)
                ON CONFLICT(suoritus_id, syotemaarite_id) DO UPDATE SET arvo=excluded.arvo, paivitetty=excluded.paivitetty
            """, (t.suoritus_id, sm["id"], arvo, nyt))
        db.commit()
        if kohde["kaava"]:
            vartion_sarja = db.execute("SELECT sarja FROM vartiot WHERE nimi=?", (suoritus["vartio"],)).fetchone()
            sarja = (vartion_sarja["sarja"] if vartion_sarja else "") or ""
            muuttujat = _kaavan_omat_arvot(t.suoritus_id, taso, kohde_id, sarja)
            try:
                pisteet = round(float(evaluoi(kohde["kaava"], muuttujat, _kaavan_kaikki_muuttujat(sarja, taso, kohde_id))), 2)
            except KaavaVirhe:
                pisteet = None
    elif pisteet is not None:
        # Pisteet eivät saa olla negatiivisia eikä ylittää tehtävän maksimia (ei koske kaava-laskettuja pisteitä)
        max_p = kohde["max_pisteet"] if kohde else None
        if pisteet < 0:
            raise HTTPException(status_code=400, detail="Pisteet eivät voi olla negatiivisia")
        if max_p is not None and pisteet > max_p:
            raise HTTPException(status_code=400, detail=f"Pisteet {pisteet:g} ylittävät maksimin {max_p:g}")

    if t.tehtava_id is not None:
        db.execute("""
            INSERT INTO tehtava_tulokset (suoritus_id, tehtava_id, pisteet, oikein, aika_sekuntia, paivitetty)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(suoritus_id, tehtava_id) DO UPDATE SET
              pisteet=excluded.pisteet, oikein=excluded.oikein,
              aika_sekuntia=excluded.aika_sekuntia, paivitetty=excluded.paivitetty
        """, (t.suoritus_id, t.tehtava_id, pisteet, t.oikein, t.aika_sekuntia, t.aika))
    else:
        db.execute("""
            INSERT INTO osatehtava_tulokset (suoritus_id, osatehtava_id, pisteet, oikein, aika_sekuntia, paivitetty)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(suoritus_id, osatehtava_id) DO UPDATE SET
              pisteet=excluded.pisteet, oikein=excluded.oikein,
              aika_sekuntia=excluded.aika_sekuntia, paivitetty=excluded.paivitetty
        """, (t.suoritus_id, t.osatehtava_id, pisteet, t.oikein, t.aika_sekuntia, t.aika))
    merkitse_pisteytetyksi(suoritus["vartio"], suoritus["rasti_id"])
    db.commit()
    return {"ok": True}

def _kello(sek: float) -> str:
    k = int(sek) % 86400
    return f"{k // 3600:02d}:{k // 60 % 60:02d}:{k % 60:02d}"

def _tarkista_aikajarjestys(taso: str, kohde_id: int, syotteet: dict, keskiyo: bool) -> None:
    # Ensimmäinen aika-syöte on alkuaika ja viimeinen loppuaika. Loppuaika ennen alkuaikaa hyväksytään
    # vain, jos tehtävälle on sallittu keskiyön ylitys (muuten aikavali() tulkitsisi suorituksen ~24 h mittaiseksi).
    if keskiyo:
        return
    ajat = [r["nimi"] for r in db.execute(
        "SELECT nimi FROM syotemaaritteet WHERE taso=? AND kohde_id=? AND tyyppi='aika' ORDER BY jarjestys, id",
        (taso, kohde_id)).fetchall()]
    if len(ajat) < 2 or ajat[0] not in syotteet or ajat[-1] not in syotteet:
        return
    alku, loppu = syotteet[ajat[0]], syotteet[ajat[-1]]
    if loppu < alku:
        raise HTTPException(status_code=400, detail=f"Loppuaika {_kello(loppu)} on ennen alkuaikaa {_kello(alku)} — tarkista ajat")

@router.get("/api/tulokset")
def get_tulokset(x_admin_token: str = Header(None)):
    # Palauttaa kaikkien vartioiden tulokset — käytetään tuloslistauksessa
    vaadi_admin(x_admin_token)
    vartiot_rows = db.execute("SELECT DISTINCT vartio FROM suoritukset ORDER BY vartio").fetchall()
    rajat = _ajanoton_rajat()
    kaikki_cache: dict = {}
    return [_vartio_tulokset(v["vartio"], rajat, kaikki_cache) for v in vartiot_rows]

@router.get("/api/tulokset/{vartio}")
def get_tulokset_vartio(vartio: str, x_admin_token: str = Header(None)):
    # Palauttaa yhden vartion tulokset kaikilla rasteilla
    vaadi_admin(x_admin_token)
    return _vartio_tulokset(vartio, _ajanoton_rajat(), {})

def _ajanoton_rajat() -> dict:
    # Nopein ja hitain aika jokaiselle ajanotto-tehtävälle sarjoittain: (tyyppi, id, sarja) -> (min, max)
    rajat: dict = {}
    for tyyppi, taulu, tulostaulu, sarake in (("t", "tehtavat", "tehtava_tulokset", "tehtava_id"),
                                              ("o", "osatehtavat", "osatehtava_tulokset", "osatehtava_id")):
        rows = db.execute(f"""
            SELECT x.id, v.sarja, tu.aika_sekuntia AS aika
            FROM {tulostaulu} tu
            JOIN {taulu} x ON x.id = tu.{sarake}
            JOIN suoritukset s ON s.id = tu.suoritus_id
            JOIN vartiot v ON v.nimi = s.vartio
            WHERE x.tyyppi = 'ajanotto' AND tu.aika_sekuntia IS NOT NULL
        """).fetchall()
        for r in rows:
            avain = (tyyppi, r["id"], r["sarja"] or "")
            lo, hi = rajat.get(avain, (r["aika"], r["aika"]))
            rajat[avain] = (min(lo, r["aika"]), max(hi, r["aika"]))
    return rajat

def _interpoloi_pisteet(rivi: dict, tyyppi: str, sarja: str, rajat: dict) -> None:
    # Ajanotto-tehtävän pisteet suoraviivaisesti sarjan nopeimman (max pistettä) ja hitaimman (0 p) ajan välillä.
    # Jos vain yksi aika tai kaikki samat, saa maksimin. Ilman max-pisteitä tai aikaa jää syötetty arvo.
    if rivi["tyyppi"] != "ajanotto" or rivi["aika_sekuntia"] is None or rivi["max_pisteet"] is None:
        return
    lo, hi = rajat[(tyyppi, rivi["id"], sarja)]
    osuus = 0 if hi == lo else (rivi["aika_sekuntia"] - lo) / (hi - lo)
    rivi["pisteet"] = round(rivi["max_pisteet"] * (1 - osuus), 2)

def _sarja_id(sarja: str):
    rivi = db.execute("SELECT id FROM sarjat WHERE nimi=?", (sarja,)).fetchone()
    return rivi["id"] if rivi else None

def _piilossa(sarjat_json, sarja: str) -> bool:
    # Onko kohta (osatehtävä tai syöte) rajattu pois tämän sarjan vartioilta. Rajaamaton kohta tai
    # vartio, jonka sarjaa ei ole sarjat-taulussa, näkee kaiken.
    if not sarjat_json:
        return False
    sarja_id = _sarja_id(sarja)
    return sarja_id is not None and sarja_id not in json.loads(sarjat_json)

def _syoterajaus(taso: str, kohde_id: int, sarja: str, cache: dict | None = None) -> tuple:
    # Kohteen syötteet, jotka on piilotettu tältä sarjalta, ja onko piilotettu kaikki (pistesivu ei silloin
    # näytä kohdetta lainkaan). Sama kaikille sarjan vartioille, joten tuloshaussa lasketaan kerran.
    key = ("rajaus", taso, kohde_id, sarja)
    if cache is not None and key in cache:
        return cache[key]
    rows = db.execute("SELECT nimi, sarjat FROM syotemaaritteet WHERE taso=? AND kohde_id=?", (taso, kohde_id)).fetchall()
    piilotetut = [r["nimi"] for r in rows if _piilossa(r["sarjat"], sarja)]
    tulos = (piilotetut, bool(rows) and len(piilotetut) == len(rows))
    if cache is not None:
        cache[key] = tulos
    return tulos

def _taydenna_piilotetut(arvot: dict, piilotetut: list) -> dict:
    # Sarjalta piilotettu syöte on kaavassa 0 — vain jos vartiolla on muita syötteitä, jotta tyhjä
    # suoritus ei tule mukaan sarjan vertailujoukkoihin (.a, kaikki())
    if arvot:
        for nimi in piilotetut:
            arvot.setdefault(nimi, 0)
    return arvot

def _kaavan_omat_arvot(suoritus_id: int, taso: str, kohde_id: int, sarja: str, cache: dict | None = None) -> dict:
    # Tämän suorituksen omat syöte-arvot nimen mukaan: {nimi: arvo}
    rows = db.execute("""
        SELECT sm.nimi, sa.arvo FROM syote_arvot sa
        JOIN syotemaaritteet sm ON sm.id = sa.syotemaarite_id
        WHERE sa.suoritus_id=? AND sm.taso=? AND sm.kohde_id=?
    """, (suoritus_id, taso, kohde_id)).fetchall()
    return _taydenna_piilotetut({r["nimi"]: r["arvo"] for r in rows}, _syoterajaus(taso, kohde_id, sarja, cache)[0])

def _kaavan_kaikki_muuttujat(sarja: str, taso: str, kohde_id: int) -> list:
    # Kaikkien saman sarjan vartioiden syöte-dictit tälle kohteelle — kaikki()-funktiota varten kaavassa
    rows = db.execute("""
        SELECT s.id AS suoritus_id, sm.nimi, sa.arvo
        FROM syote_arvot sa
        JOIN syotemaaritteet sm ON sm.id = sa.syotemaarite_id
        JOIN suoritukset s ON s.id = sa.suoritus_id
        JOIN vartiot v ON v.nimi = s.vartio
        WHERE sm.taso=? AND sm.kohde_id=? AND COALESCE(v.sarja,'')=?
    """, (taso, kohde_id, sarja)).fetchall()
    per_suoritus: dict = {}
    for r in rows:
        per_suoritus.setdefault(r["suoritus_id"], {})[r["nimi"]] = r["arvo"]
    piilotetut = _syoterajaus(taso, kohde_id, sarja)[0]
    return [_taydenna_piilotetut(m, piilotetut) for m in per_suoritus.values()]

def _laske_kaava_pisteet(rivi: dict, taso: str, kohde_id: int, suoritus_id: int, sarja: str, kaikki_cache: dict) -> None:
    # Kaava-tyypin pisteet lasketaan aina tuoreena syöte-arvoista, koska muiden vartioiden arvot
    # (kaikki()-funktio) voivat muuttua sitä mukaa kun uusia tuloksia syötetään.
    if rivi["tyyppi"] != "kaava" or not rivi.get("kaava"):
        rivi.pop("kaava", None)
        return
    kaava = rivi.pop("kaava")
    muuttujat = _kaavan_omat_arvot(suoritus_id, taso, kohde_id, sarja, kaikki_cache)
    if not muuttujat:
        rivi["pisteet"] = None
        return
    key = (taso, kohde_id, sarja)
    if key not in kaikki_cache:
        kaikki_cache[key] = _kaavan_kaikki_muuttujat(sarja, taso, kohde_id)
    try:
        tarkka = float(evaluoi(kaava, muuttujat, kaikki_cache[key]))
    except KaavaVirhe:
        rivi["pisteet"] = None
        return
    rivi["pisteet"] = round(tarkka, 2)
    rivi["_tarkka"] = tarkka  # tehtävän kaavaan pyöristämättömänä kuten vanhassa Kipassa, ei näytetä

def _hae_osat(suoritus_id: int, tehtava_id: int, sarja: str, rajat: dict, kaikki_cache: dict) -> list:
    # Tehtävän osatehtävät tämän suorituksen tuloksineen, ajanotto-interpolointi ja kaavat laskettuina
    rows = db.execute("""
        SELECT o.id, o.nimi, o.tyyppi, o.max_pisteet, o.kaava, o.muuttuja, o.sarjat,
               ot.pisteet, ot.oikein, ot.aika_sekuntia
        FROM osatehtavat o
        LEFT JOIN osatehtava_tulokset ot ON ot.osatehtava_id=o.id AND ot.suoritus_id=?
        WHERE o.tehtava_id=? ORDER BY o.jarjestys, o.id
    """, (suoritus_id, tehtava_id)).fetchall()
    osat = [dict(o) for o in rows]
    for o in osat:
        # Piilotettu osatehtävä tai kaava-osatehtävä, jonka kaikki syötteet on piilotettu, on tälle sarjalle 0 p
        o["_piilossa"] = _piilossa(o.pop("sarjat"), sarja) or (
            o["tyyppi"] == "kaava" and _syoterajaus("osatehtava", o["id"], sarja, kaikki_cache)[1])
        _interpoloi_pisteet(o, "o", sarja, rajat)
        _laske_kaava_pisteet(o, "osatehtava", o["id"], suoritus_id, sarja, kaikki_cache)
    return osat

def _osan_pisteet(o: dict):
    if o["tyyppi"] == "oikein_vaarin" and o["oikein"] is not None:
        return (o["max_pisteet"] if o["max_pisteet"] is not None else 1) if o["oikein"] else 0
    return o.get("_tarkka", o["pisteet"])

def _osien_muuttujat(osat: list, suoritus_id: int) -> dict:
    # Tehtävän kaavan muuttujat osatehtävistä: osatehtävän oma kirjain (a, b, c...) = pisteet ja a_aika = ajanoton
    # aika sekunteina. Rinnakkaisnimet järjestyksen mukaan: o1, o2, ... ja o1_aika, ...
    # Tuloksen puuttuessa muuttujaa ei ole (kaava jää laskematta).
    m: dict = {}
    piilotetut = []
    for i, o in enumerate(osat, 1):
        nimet = [f"o{i}"] + ([o["muuttuja"]] if o.get("muuttuja") else [])
        if o.get("_piilossa"):
            piilotetut += nimet
            continue
        p = _osan_pisteet(o)
        for n in nimet:
            if p is not None:
                m[n] = p
            if o["aika_sekuntia"] is not None:
                m[f"{n}_aika"] = o["aika_sekuntia"]
    return _taydenna_piilotetut(m, piilotetut)  # sarjalta piilotettu osatehtävä = 0 p

def _osakaavan_kaikki(rasti_id: int, tehtava_id: int, sarja: str, rajat: dict, kaikki_cache: dict) -> list:
    # Saman sarjan kaikkien vartioiden osatehtävämuuttujat tälle tehtävälle — kaikki()/.o1 -joukkoja varten
    key = ("osat", tehtava_id, sarja)
    if key not in kaikki_cache:
        rows = db.execute("""
            SELECT s.id FROM suoritukset s JOIN vartiot v ON v.nimi = s.vartio
            WHERE s.rasti_id=? AND COALESCE(v.sarja,'')=?
        """, (rasti_id, sarja)).fetchall()
        kaikki = [_osien_muuttujat(_hae_osat(r["id"], tehtava_id, sarja, rajat, kaikki_cache), r["id"]) for r in rows]
        kaikki_cache[key] = [m for m in kaikki if m]
    return kaikki_cache[key]

def _laske_osakaava(td: dict, rasti_id: int, suoritus_id: int, sarja: str, rajat: dict, kaikki_cache: dict) -> None:
    # Kaava-tyyppisen tehtävän, jolla on osatehtäviä, pisteet lasketaan tehtävän kaavasta osatehtävien tuloksilla
    kaava = td.pop("kaava", None)
    td["osakaava"] = True
    td["pisteet"] = None
    if not kaava:
        return
    muuttujat = _osien_muuttujat(td["osatehtavat"], suoritus_id)
    if not muuttujat:
        return
    try:
        td["pisteet"] = round(float(evaluoi(kaava, muuttujat, _osakaavan_kaikki(rasti_id, td["id"], sarja, rajat, kaikki_cache))), 2)
    except KaavaVirhe:
        pass

def _vartio_tulokset(vartio: str, rajat: dict, kaikki_cache: dict) -> dict:
    vrow = db.execute("SELECT sarja, numero FROM vartiot WHERE nimi=?", (vartio,)).fetchone()
    sarja = (vrow["sarja"] if vrow else "") or ""
    suoritukset = db.execute(
        "SELECT s.id, s.rasti_id, r.numero, s.kommentti FROM suoritukset s JOIN rastit r ON r.id=s.rasti_id WHERE s.vartio=? ORDER BY r.jarjestys, r.id",
        (vartio,)
    ).fetchall()
    rasti_data = []
    for s in suoritukset:
        tt = db.execute("""
            SELECT t.id, t.nimi, t.tyyppi, t.max_pisteet, t.kaava,
                   tt.pisteet, tt.oikein, tt.aika_sekuntia
            FROM tehtavat t
            LEFT JOIN tehtava_tulokset tt ON tt.tehtava_id=t.id AND tt.suoritus_id=?
            WHERE t.rasti_id=? ORDER BY t.jarjestys, t.id
        """, (s["id"], s["rasti_id"])).fetchall()
        tehtavat_data = []
        for t in tt:
            td = dict(t)
            td["osatehtavat"] = _hae_osat(s["id"], t["id"], sarja, rajat, kaikki_cache)
            if td["osatehtavat"] and td["tyyppi"] == "kaava":
                _laske_osakaava(td, s["rasti_id"], s["id"], sarja, rajat, kaikki_cache)
            else:
                _interpoloi_pisteet(td, "t", sarja, rajat)
                _laske_kaava_pisteet(td, "tehtava", t["id"], s["id"], sarja, kaikki_cache)
            # Pyöristämätön apuarvo ja sarjalta piilotetut osatehtävät eivät kuulu vastaukseen
            td.pop("_tarkka", None)
            td["osatehtavat"] = [o for o in td["osatehtavat"] if not o.pop("_piilossa")]
            for o in td["osatehtavat"]:
                o.pop("_tarkka", None)
            tehtavat_data.append(td)
        rasti_data.append({
            "suoritus_id": s["id"],
            "rasti_id": s["rasti_id"],
            "rasti_numero": s["numero"],
            "kommentti": s["kommentti"],
            "tehtavat": tehtavat_data,
        })
    return {
        "vartio": vartio,
        "sarja": vrow["sarja"] if vrow else "",
        "numero": vrow["numero"] if vrow else "",
        "rastit": rasti_data,
    }