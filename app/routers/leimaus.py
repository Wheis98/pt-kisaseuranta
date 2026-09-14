from fastapi.responses import FileResponse
from fastapi import APIRouter, HTTPException, Header
from app import db, sessions, admin_sessions, LeimausIn, STATIC_DIR
from app.utils import vaadi_admin

router = APIRouter()

@router.get("/leimaus.html")
def leimaus_page():
    return FileResponse(STATIC_DIR / "leimaus.html")

@router.get("/data.html")
def data_page():
    return FileResponse(STATIC_DIR / "data.html")

@router.post("/api/leimaus")
def leimaus(l: LeimausIn):
    # Tallentaa sisään- tai ulosleimauksen. Estää kaksoisleimauksen sisään ilman välistä ulosta.
    session = sessions.get(l.token)
    if not session:
        raise HTTPException(status_code=401, detail="Tuntematon istunto — kirjaudu uudelleen")
    if not l.vartio.strip():
        raise HTTPException(status_code=400, detail="Vartion nimi vaaditaan")
    vartio_row = db.execute("SELECT id FROM vartiot WHERE nimi=?", (l.vartio.strip(),)).fetchone()
    if not vartio_row:
        raise HTTPException(status_code=404, detail=f"Vartiota '{l.vartio.strip()}' ei löydy — pyydä adminia luomaan vartio ensin")
    if not l.rastinumero.strip():
        raise HTTPException(status_code=400, detail="Rastinumero vaaditaan")
    if l.tyyppi not in ("sisaan", "ulos"):
        raise HTTPException(status_code=400, detail="Virheellinen tyyppi")
    if l.tyyppi == "sisaan":
        viimeisin = db.execute(
            "SELECT numero, tyyppi FROM leimaukset WHERE vartio=? ORDER BY id DESC LIMIT 1",
            (l.vartio.strip(),)
        ).fetchone()
        if viimeisin and viimeisin["tyyppi"] == "sisaan":
            raise HTTPException(status_code=409, detail=f"{l.vartio.strip()} on jo rastilla {viimeisin['numero']} — leimaa ensin ulos")
        if not l.uudelleen:
            aiempi_ulos = db.execute(
                "SELECT id FROM leimaukset WHERE vartio=? AND numero=? AND tyyppi='ulos'",
                (l.vartio.strip(), l.rastinumero.strip())
            ).fetchone()
            if aiempi_ulos:
                raise HTTPException(status_code=409, detail=f"uudelleen_kaynti:{l.vartio.strip()}")
    db.execute(
        "INSERT INTO leimaukset (kayttaja, numero, vartio, jasenet, aika, tyyppi) VALUES (?,?,?,?,?,?)",
        (session["nimi"], l.rastinumero.strip(), l.vartio.strip(), l.jasenet, l.aika, l.tyyppi),
    )
    db.commit()
    return {"ok": True}

@router.get("/api/aktiiviset")
def aktiiviset(numero: str):
    # Palauttaa vartiot jotka ovat tällä hetkellä sisään leimattuina tietylle rastille.
    # Subquery varmistaa että otetaan vain viimeisin leimaus per vartio+rasti-pari.
    rows = db.execute("""
        SELECT vartio, jasenet, aika FROM leimaukset l1
        WHERE numero = ? AND tyyppi = 'sisaan'
        AND id = (
            SELECT MAX(id) FROM leimaukset l2
            WHERE l2.vartio = l1.vartio AND l2.numero = l1.numero
        )
        ORDER BY id DESC
    """, (numero,)).fetchall()
    return [dict(r) for r in rows]

@router.get("/api/data")
def get_data(token: str = "", numero: str = "", vartio: str = "", x_admin_token: str = Header(None)):
    if x_admin_token and x_admin_token in admin_sessions:
        query = "SELECT id, kayttaja, numero, vartio, jasenet, aika, tyyppi FROM leimaukset WHERE 1=1"
        params: list = []
        if numero:
            query += " AND numero=?"; params.append(numero)
        if vartio:
            query += " AND vartio=?"; params.append(vartio)
        query += " ORDER BY id DESC"
    elif token:
        session = sessions.get(token)
        if not session:
            raise HTTPException(status_code=401, detail="Tuntematon istunto")
        if not numero:
            raise HTTPException(status_code=400, detail="Rastinumero vaaditaan")
        query = "SELECT id, kayttaja, numero, vartio, jasenet, aika, tyyppi FROM leimaukset WHERE numero=? ORDER BY id DESC"
        params = [numero]
    else:
        raise HTTPException(status_code=401, detail="Kirjaudu uudelleen")
    rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]

@router.delete("/api/leimaus/{leimaus_id}")
def delete_leimaus(leimaus_id: int, x_admin_token: str = Header(None)):
    vaadi_admin(x_admin_token)
    db.execute("DELETE FROM leimaukset WHERE id=?", (leimaus_id,))
    db.commit()
    return {"ok": True}