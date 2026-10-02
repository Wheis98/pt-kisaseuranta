from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import FileResponse
import sqlite3
import uuid
from app import db, AdminIn, AdminSalasanaIn, admin_sessions, sessions, STATIC_DIR
from app.utils import hash_salasana, vaadi_admin

router = APIRouter()

@router.get("/admin.html")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")

@router.post("/api/admin/setup")
def admin_setup(a: AdminIn):
    # Luo ensimmäisen adminin — toimii vain jos admintaulu on tyhjä
    maara = db.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    if maara > 0:
        raise HTTPException(status_code=403, detail="Admin on jo luotu")
    if not a.kayttajanimi.strip() or not a.salasana:
        raise HTTPException(status_code=400, detail="Käyttäjänimi ja salasana vaaditaan")
    db.execute("INSERT INTO admins (kayttajanimi, salasana_hash) VALUES (?,?)",
               (a.kayttajanimi.strip(), hash_salasana(a.salasana)))
    db.commit()
    return {"ok": True}

@router.get("/api/admin/setup_tarvitaan")
def admin_setup_tarvitaan():
    # Palauttaa tarvitaan:true jos yhtään adminia ei ole luotu — käytetään setup-sivun näyttämiseen
    maara = db.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
    return {"tarvitaan": maara == 0}

@router.post("/api/admin/login")
def admin_login(a: AdminIn):
    # Kirjaa adminin sisään ja palauttaa session-tokenin muistiin tallennettavaksi
    row = db.execute(
        "SELECT salasana_hash FROM admins WHERE kayttajanimi=?", (a.kayttajanimi.strip(),)
    ).fetchone()
    if not row or row["salasana_hash"] != hash_salasana(a.salasana):
        raise HTTPException(status_code=401, detail="Väärä käyttäjänimi tai salasana")
    token = str(uuid.uuid4())
    admin_sessions[token] = a.kayttajanimi.strip()
    return {"admin_token": token}

@router.post("/api/admin/salasana")
def vaihda_admin_salasana(a: AdminSalasanaIn, x_admin_token: str = Header(None)):
    # Vaihtaa kirjautuneen adminin oman salasanan — nykyinen salasana vaaditaan, jotta auki jäänyt istunto ei riitä
    vaadi_admin(x_admin_token)
    kayttajanimi = admin_sessions[x_admin_token]
    row = db.execute("SELECT salasana_hash FROM admins WHERE kayttajanimi=?", (kayttajanimi,)).fetchone()
    if not row or row["salasana_hash"] != hash_salasana(a.nykyinen):
        raise HTTPException(status_code=401, detail="Nykyinen salasana on väärä")
    if not a.uusi:
        raise HTTPException(status_code=400, detail="Uusi salasana vaaditaan")
    db.execute("UPDATE admins SET salasana_hash=? WHERE kayttajanimi=?", (hash_salasana(a.uusi), kayttajanimi))
    db.commit()
    # Saman adminin muut istunnot (muut laitteet) kirjataan ulos; tämä istunto pysyy voimassa
    for token in [t for t, k in admin_sessions.items() if k == kayttajanimi and t != x_admin_token]:
        del admin_sessions[token]
    return {"ok": True, "kayttajanimi": kayttajanimi}

@router.post("/api/admin/luo")
def luo_admin(a: AdminIn, x_admin_token: str = Header(None)):
    # Luo uuden adminin — vaatii olemassa olevan admin-session
    vaadi_admin(x_admin_token)
    if not a.kayttajanimi.strip() or not a.salasana:
        raise HTTPException(status_code=400, detail="Käyttäjänimi ja salasana vaaditaan")
    try:
        db.execute("INSERT INTO admins (kayttajanimi, salasana_hash) VALUES (?,?)",
                   (a.kayttajanimi.strip(), hash_salasana(a.salasana)))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Käyttäjänimi on jo käytössä")
    return {"ok": True}

# ── Käyttäjäpyynnöt ───────────────────────────────────────────────────────────

@router.post("/api/kayttaja/pyynto")
def tee_kayttaja_pyynto(data: dict):
    etunimi = (data.get("etunimi") or "").strip()
    sukunimi = (data.get("sukunimi") or "").strip()
    rasti_id = data.get("rasti_id")
    if not etunimi or not sukunimi:
        raise HTTPException(status_code=400, detail="Etu- ja sukunimi vaaditaan")
    if len(etunimi) > 60 or len(sukunimi) > 60:
        raise HTTPException(status_code=400, detail="Nimi on liian pitkä")
    from datetime import datetime
    aika = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    # Sama henkilö voi lähettää pyynnön useasti: käsittelemätön pyyntö päivitetään eikä uutta luoda
    aiemmat = _samannimiset_pyynnot(etunimi, sukunimi)
    if aiemmat:
        db.execute("UPDATE kayttaja_pyynnot SET aika=?, rasti_id=COALESCE(?, rasti_id) WHERE id=?", (aika, rasti_id, aiemmat[0]))
    else:
        db.execute("INSERT INTO kayttaja_pyynnot (etunimi, sukunimi, rasti_id, aika) VALUES (?,?,?,?)",
                   (etunimi, sukunimi, rasti_id, aika))
    db.commit()
    return {"ok": True}

def _sama_nimi(a: str, b: str) -> bool:
    # Kirjainkoosta riippumaton vertailu Pythonissa: SQLiten lower() ei käsittele ä-, ö- ja å-kirjaimia
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()

def _samannimiset_pyynnot(etunimi: str, sukunimi: str) -> list:
    return [r["id"] for r in db.execute("SELECT id, etunimi, sukunimi FROM kayttaja_pyynnot ORDER BY id").fetchall()
            if _sama_nimi(r["etunimi"], etunimi) and _sama_nimi(r["sukunimi"], sukunimi)]

def _poista_samannimiset_pyynnot(etunimi: str, sukunimi: str) -> None:
    for pyynto_id in _samannimiset_pyynnot(etunimi, sukunimi):
        db.execute("DELETE FROM kayttaja_pyynnot WHERE id=?", (pyynto_id,))
    db.commit()

@router.get("/api/kayttaja/pyynnot")
def get_kayttaja_pyynnot(x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    rows = db.execute("""
        SELECT p.id, p.etunimi, p.sukunimi, p.rasti_id, r.numero, p.aika
        FROM kayttaja_pyynnot p
        LEFT JOIN rastit r ON r.id=p.rasti_id
        ORDER BY p.id DESC
    """).fetchall()
    return [dict(r) for r in rows]

@router.post("/api/kayttaja/pyynto/{pyynto_id}/hyvaksy")
def hyvaksy_kayttaja_pyynto(pyynto_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    pyynto = db.execute("SELECT * FROM kayttaja_pyynnot WHERE id=?", (pyynto_id,)).fetchone()
    if not pyynto:
        raise HTTPException(status_code=404, detail="Pyyntöä ei löydy")
    nimi = pyynto["etunimi"] + " " + pyynto["sukunimi"]
    if any(_sama_nimi(u["nimi"], nimi) for u in db.execute("SELECT nimi FROM users").fetchall()):
        # Tunnus on jo luotu (esim. aiemmasta pyynnöstä) — ylimääräiset pyynnöt ovat turhia
        _poista_samannimiset_pyynnot(pyynto["etunimi"], pyynto["sukunimi"])
        raise HTTPException(status_code=409, detail=f"Käyttäjä '{nimi}' on jo olemassa, joten hänen pyyntönsä poistettiin. "
                                                    "Jos salasana on unohtunut, nollaa se käyttäjälistasta.")
    token = str(uuid.uuid4())
    db.execute("INSERT INTO users (nimi, token) VALUES (?,?)", (nimi, token))
    db.commit()
    user = db.execute("SELECT id FROM users WHERE nimi=?", (nimi,)).fetchone()
    if pyynto["rasti_id"] and user:
        db.execute("INSERT OR IGNORE INTO rasti_oikeudet (user_id, rasti_id) VALUES (?,?)",
                   (user["id"], pyynto["rasti_id"]))
        db.commit()
    _poista_samannimiset_pyynnot(pyynto["etunimi"], pyynto["sukunimi"])
    return {"ok": True, "nimi": nimi}

@router.delete("/api/kayttaja/pyynto/{pyynto_id}")
def poista_kayttaja_pyynto(pyynto_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM kayttaja_pyynnot WHERE id=?", (pyynto_id,))
    db.commit()
    return {"ok": True}

# ── Käyttöoikeudet ────────────────────────────────────────────────────────────

@router.get("/api/oikeudet")
def get_oikeudet(token: str = ""):
    session = sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto")
    user = db.execute("SELECT id FROM users WHERE token=?", (token,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Tuntematon käyttäjä")
    rows = db.execute("SELECT rasti_id FROM rasti_oikeudet WHERE user_id=?", (user["id"],)).fetchall()
    if not rows:
        return {"kaikki": True, "oikeudet": []}
    return {"kaikki": False, "oikeudet": [r["rasti_id"] for r in rows]}

@router.get("/api/oikeudet/admin")
def get_oikeudet_admin(x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    users = db.execute("SELECT id, nimi FROM users ORDER BY nimi").fetchall()
    result = []
    for u in users:
        rows = db.execute("SELECT rasti_id FROM rasti_oikeudet WHERE user_id=?", (u["id"],)).fetchall()
        result.append({"id": u["id"], "nimi": u["nimi"], "oikeudet": [r["rasti_id"] for r in rows]})
    return result

@router.put("/api/oikeudet/{user_id}")
def set_oikeudet(user_id: int, data: dict, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    rasti_ids = data.get("rasti_ids", [])
    db.execute("DELETE FROM rasti_oikeudet WHERE user_id=?", (user_id,))
    for rid in rasti_ids:
        db.execute("INSERT OR IGNORE INTO rasti_oikeudet (user_id, rasti_id) VALUES (?,?)", (user_id, rid))
    db.commit()
    # Poista hyväksytyt pyynnöt
    if rasti_ids:
        db.execute("DELETE FROM oikeus_pyynnot WHERE user_id=? AND rasti_id IN ({})".format(",".join("?"*len(rasti_ids))), [user_id]+rasti_ids)
        db.commit()
    return {"ok": True}

@router.post("/api/oikeus/pyynto")
def tee_pyynto(data: dict, token: str = ""):
    session = sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto")
    user = db.execute("SELECT id FROM users WHERE token=?", (token,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Tuntematon käyttäjä")
    rasti_id = data.get("rasti_id")
    if not rasti_id:
        raise HTTPException(status_code=400, detail="rasti_id vaaditaan")
    from datetime import datetime
    aika = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    db.execute("INSERT OR IGNORE INTO oikeus_pyynnot (user_id, rasti_id, aika) VALUES (?,?,?)", (user["id"], rasti_id, aika))
    db.commit()
    return {"ok": True}

@router.get("/api/oikeus/pyynnot")
def get_pyynnot(x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    rows = db.execute("""
        SELECT p.id, p.user_id, u.nimi, p.rasti_id, r.numero, p.aika
        FROM oikeus_pyynnot p
        JOIN users u ON u.id=p.user_id
        JOIN rastit r ON r.id=p.rasti_id
        ORDER BY p.id DESC
    """).fetchall()
    return [dict(r) for r in rows]

@router.delete("/api/oikeus/pyynto/{pyynto_id}")
def poista_pyynto(pyynto_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM oikeus_pyynnot WHERE id=?", (pyynto_id,))
    db.commit()
    return {"ok": True}