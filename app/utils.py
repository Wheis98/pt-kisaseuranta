from fastapi import HTTPException, Header
import hashlib
from app import admin_sessions, db

def hash_salasana(salasana: str) -> str:
    # Hashataan salasana SHA-256:lla ennen tallennusta
    return hashlib.sha256(salasana.encode()).hexdigest()


def vaadi_admin(x_admin_token: str = Header(None)):
    # Tarkistaa että pyynnössä on voimassa oleva admin-token, muuten 403
    if not x_admin_token or x_admin_token not in admin_sessions:
        raise HTTPException(status_code=403, detail="Vaatii admin-oikeudet")

_mediaani_cache = {"aika": 0.0, "arvo": {}}
_MEDIAANI_TTL_S = 30

def laske_siirtyma_mediaanit():
    # Välimuisti: mediaanit muuttuvat harvoin, mutta niitä haetaan jokaisen käyttäjän tilannepäivityksessä
    import time
    if time.monotonic() - _mediaani_cache["aika"] > _MEDIAANI_TTL_S:
        _mediaani_cache["arvo"] = _laske_siirtyma_mediaanit()
        _mediaani_cache["aika"] = time.monotonic()
    return _mediaani_cache["arvo"]

def _laske_siirtyma_mediaanit():
    # Laskee mediaanisiirtymäajan jokaiselle rasti→rasti-parille toteutuneiden leimausten perusteella.
    # Palauttaa dict: "A→B" -> {mediaani: float, n: int}. Alle 2 havaintoa ei riitä ennusteeseen.
    from datetime import datetime
    FORMATS = ["%d.%m.%Y klo %H.%M.%S", "%d.%m.%Y %H.%M.%S", "%d.%m.%Y %H:%M:%S"]
    def parse_aika(s):
        for fmt in FORMATS:
            try: return datetime.strptime(s, fmt)
            except: pass
        return None

    kaikki = db.execute("SELECT vartio, numero, tyyppi, aika FROM leimaukset ORDER BY id").fetchall()
    per_vartio: dict = {}
    for l in kaikki:
        per_vartio.setdefault(l["vartio"], []).append(l)
    siirtymat: dict = {}
    for leimaukset in per_vartio.values():
        for i in range(len(leimaukset) - 1):
            curr, nxt = leimaukset[i], leimaukset[i + 1]
            if curr["tyyppi"] == "ulos" and nxt["tyyppi"] == "sisaan":
                t1, t2 = parse_aika(curr["aika"]), parse_aika(nxt["aika"])
                if t1 and t2:
                    diff = (t2 - t1).total_seconds() / 60
                    if 0 < diff < 300:  # hylätään yli 5 tunnin poikkeamat virheellisinä
                        key = curr["numero"] + "→" + nxt["numero"]
                        siirtymat.setdefault(key, []).append(diff)

    mediaanit = {}
    for key, times in siirtymat.items():
        times.sort()
        n = len(times)
        med = times[n // 2] if n % 2 == 1 else (times[n // 2 - 1] + times[n // 2]) / 2
        mediaanit[key] = {"mediaani": round(med, 1), "n": n}
    return mediaanit