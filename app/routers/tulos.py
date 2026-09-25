from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, admin_sessions, sessions, SuoritusKommenttiIn, TulosIn, STATIC_DIR
from app.utils import vaadi_admin
from app.kaava import evaluoi, KaavaVirhe

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
    if not db.execute("SELECT id FROM vartiot WHERE nimi=?", (vartio,)).fetchone():
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
        kohde = db.execute("SELECT tyyppi, kaava, max_pisteet FROM tehtavat WHERE id=?", (kohde_id,)).fetchone()
    elif t.osatehtava_id is not None:
        taso, kohde_id = "osatehtava", t.osatehtava_id
        kohde = db.execute("SELECT tyyppi, kaava, max_pisteet FROM osatehtavat WHERE id=?", (kohde_id,)).fetchone()
    else:
        raise HTTPException(status_code=400, detail="tehtava_id tai osatehtava_id vaaditaan")

    pisteet = t.pisteet
    if kohde and kohde["tyyppi"] == "kaava" and t.syotteet is not None:
        # Kaava-tyypin pisteet lasketaan syötteistä, ei anneta suoraan — tallennetaan raaka-arvot
        # ja lasketaan heti alustava pisteet (lopullinen arvo lasketaan aina tuoreena tulosten haussa,
        # koska muiden vartioiden arvot voivat vielä muuttua).
        from datetime import datetime
        nyt = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
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
            muuttujat = _kaavan_omat_arvot(t.suoritus_id, taso, kohde_id)
            try:
                pisteet = round(float(evaluoi(kohde["kaava"], muuttujat, _kaavan_kaikki_muuttujat(sarja, taso, kohde_id))), 1)
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
    rivi["pisteet"] = round(rivi["max_pisteet"] * (1 - osuus), 1)

def _kaavan_omat_arvot(suoritus_id: int, taso: str, kohde_id: int) -> dict:
    # Tämän suorituksen omat syöte-arvot nimen mukaan: {nimi: arvo}
    rows = db.execute("""
        SELECT sm.nimi, sa.arvo FROM syote_arvot sa
        JOIN syotemaaritteet sm ON sm.id = sa.syotemaarite_id
        WHERE sa.suoritus_id=? AND sm.taso=? AND sm.kohde_id=?
    """, (suoritus_id, taso, kohde_id)).fetchall()
    return {r["nimi"]: r["arvo"] for r in rows}

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
    return list(per_suoritus.values())

def _laske_kaava_pisteet(rivi: dict, taso: str, kohde_id: int, suoritus_id: int, sarja: str, kaikki_cache: dict) -> None:
    # Kaava-tyypin pisteet lasketaan aina tuoreena syöte-arvoista, koska muiden vartioiden arvot
    # (kaikki()-funktio) voivat muuttua sitä mukaa kun uusia tuloksia syötetään.
    if rivi["tyyppi"] != "kaava" or not rivi.get("kaava"):
        rivi.pop("kaava", None)
        return
    kaava = rivi.pop("kaava")
    muuttujat = _kaavan_omat_arvot(suoritus_id, taso, kohde_id)
    if not muuttujat:
        rivi["pisteet"] = None
        return
    key = (taso, kohde_id, sarja)
    if key not in kaikki_cache:
        kaikki_cache[key] = _kaavan_kaikki_muuttujat(sarja, taso, kohde_id)
    try:
        rivi["pisteet"] = round(float(evaluoi(kaava, muuttujat, kaikki_cache[key])), 1)
    except KaavaVirhe:
        rivi["pisteet"] = None

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
            osa_rows = db.execute("""
                SELECT o.id, o.nimi, o.tyyppi, o.max_pisteet, o.kaava,
                       ot.pisteet, ot.oikein, ot.aika_sekuntia
                FROM osatehtavat o
                LEFT JOIN osatehtava_tulokset ot ON ot.osatehtava_id=o.id AND ot.suoritus_id=?
                WHERE o.tehtava_id=? ORDER BY o.jarjestys, o.id
            """, (s["id"], t["id"])).fetchall()
            td = dict(t)
            _interpoloi_pisteet(td, "t", sarja, rajat)
            _laske_kaava_pisteet(td, "tehtava", t["id"], s["id"], sarja, kaikki_cache)
            td["osatehtavat"] = [dict(o) for o in osa_rows]
            for o in td["osatehtavat"]:
                _interpoloi_pisteet(o, "o", sarja, rajat)
                _laske_kaava_pisteet(o, "osatehtava", o["id"], s["id"], sarja, kaikki_cache)
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