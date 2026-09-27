"""
Turvallinen lausekearvioija tehtävien kaavapohjaiselle pisteytykselle.

Kaava kirjoitetaan nimetyillä syötteillä (esim. "a", "b") ja funktioilla, esim.:
    interpoloi(aikavali(a,b), min(kaikki(aikavali(a,b))), 10, max(kaikki(aikavali(a,b))))

Myös vanhan Kipan syntaksi toimii: ".a" (tai "..a") on kaikkien saman sarjan vartioiden a-arvojen joukko,
jolle laskutoimitukset ja funktiot tehdään vartiokohtaisesti, ja "..mukana" on 1 jokaiselle vartiolle. Esim.:
    max(interpoloi(min([aikavali(a,b), 1.5*med(aikavali(.a,.b)*..mukana)]), min(aikavali(.a,.b)), 10, 1.5*med(aikavali(.a,.b))))
Luvun perästä puuttuva kertomerkki lisätään (1.5med(...) -> 1.5*med(...)).

Arvioidaan Pythonin ast-moduulilla whitelist-periaatteella (ei eval()/exec()) —
vain alla listatut solmutyypit ja funktiot sallitaan, kaikki muu hylätään KaavaVirhe-poikkeuksella.
"""
import ast
import math
import operator
import re
import statistics


class KaavaVirhe(Exception):
    pass


class _Joukko(dict):
    # Vanhan Kipan ".a"-muuttujan arvo: {vartion indeksi kaikki_suoritukset-listassa: arvo}
    pass


_JOUKKO_ETULIITE = "__joukko__"


def _vartioittain(funktio):
    # Tekee funktiosta joukko-yhteensopivan: jos jokin argumentti on joukko, lasketaan jokaiselle vartiolle
    # erikseen niille vartioille, joilla on arvo kaikissa joukko-argumenteissa (kuten vanhassa Kipassa).
    def f(*args):
        joukot = [a for a in args if isinstance(a, _Joukko)]
        if not joukot:
            return funktio(*args)
        avaimet = set(joukot[0]).intersection(*joukot[1:])
        return _Joukko({k: funktio(*(a[k] if isinstance(a, _Joukko) else a for a in args)) for k in avaimet})
    return f


def _minmax(funktio):
    def f(*args):
        arvot = _flat(args)
        if not arvot:
            raise KaavaVirhe("Ei arvoja laskettavaksi")
        return funktio(arvot)
    return f


def _tilasto(funktio):
    def f(*args):
        arvot = _flat(args)
        if not arvot:
            raise KaavaVirhe("Ei arvoja laskettavaksi")
        return funktio(arvot)
    return f


def _flat(args):
    tulos = []
    for a in args:
        if isinstance(a, _Joukko):
            tulos.extend(_flat(list(a.values())))
        elif isinstance(a, list):
            tulos.extend(_flat(a))
        else:
            tulos.append(a)
    return tulos


def _interpoloi(oma, paras, jaettavat, nolla=0):
    if paras == nolla:
        return jaettavat if oma >= paras else 0
    osuus = (oma - nolla) / (paras - nolla)
    osuus = max(0.0, min(1.0, osuus))
    return jaettavat * osuus


def _aikavali(alku, loppu):
    v = loppu - alku
    if v < 0:
        v += 86400
    return v


def _jos(ehto, a, b):
    return a if ehto else b


FUNKTIOT = {
    "min": _minmax(min),
    "max": _minmax(max),
    "med": _tilasto(statistics.median),
    "mean": _tilasto(statistics.mean),
    "sum": lambda *a: sum(_flat(a)),
    "interpoloi": _vartioittain(_interpoloi),
    "aikavali": _vartioittain(_aikavali),
    "jos": _vartioittain(_jos),
    "floor": _vartioittain(math.floor),
    "ceil": _vartioittain(math.ceil),
    "abs": _vartioittain(abs),
    "sqrt": _vartioittain(math.sqrt),
    "pyorista": _vartioittain(lambda x, n=0: round(x, int(n))),
}
# Vanhan Kipan suomenkieliset nimet
FUNKTIOT["pienin"] = FUNKTIOT["min"]
FUNKTIOT["suurin"] = FUNKTIOT["max"]
FUNKTIOT["kesk"] = FUNKTIOT["mean"]

_BINOP = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.Gt: operator.gt,
    ast.LtE: operator.le,
    ast.GtE: operator.ge,
}


def _esikasittele(kaava: str) -> str:
    # Muuntaa vanhan Kipan syntaksin Pythonin ast-moduulin ymmärtämään muotoon:
    # "1.5med(" -> "1.5*med(", "2a" -> "2*a", ")..mukana" -> ")*..mukana" ja ".a" / "..a" / "...a" -> "__joukko__a"
    kaava = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)(?=[A-Za-z_(])", r"\1*", kaava)
    kaava = re.sub(r"\)(?=\.{1,3}[A-Za-z_])", ")*", kaava)
    return re.sub(r"(?<![\w.)\]])\.{1,3}([A-Za-z_]\w*)(?![\w(])", _JOUKKO_ETULIITE + r"\1", kaava)


def evaluoi(kaava: str, muuttujat: dict, kaikki_suoritukset: list | None = None):
    """
    muuttujat: {nimi: arvo} tämän suorituksen syötteet.
    kaikki_suoritukset: lista muiden (saman sarjan) vartioiden syöte-dictejä, kaikki(...)-funktiota
    ja vanhan Kipan .a-joukkoja varten.
    """
    if kaikki_suoritukset is None:
        kaikki_suoritukset = []
    try:
        puu = ast.parse(_esikasittele(kaava), mode="eval")
    except SyntaxError as e:
        raise KaavaVirhe(f"Syntaksivirhe: {e}")
    tulos = _arvioi(puu.body, muuttujat, kaikki_suoritukset)
    if isinstance(tulos, (_Joukko, list)):
        raise KaavaVirhe("Kaavan tulos on joukko eikä yksittäinen luku — käytä esim. min(), max() tai med()")
    return tulos


def _arvioi(node, muuttujat, kaikki_suoritukset):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise KaavaVirhe("Vain numerot ovat sallittuja vakioita")

    if isinstance(node, ast.Name):
        if node.id.startswith(_JOUKKO_ETULIITE):
            nimi = node.id[len(_JOUKKO_ETULIITE):]
            if nimi == "mukana":
                return _Joukko({i: 1 for i in range(len(kaikki_suoritukset))})
            return _Joukko({i: m[nimi] for i, m in enumerate(kaikki_suoritukset) if nimi in m})
        if node.id == "mukana":
            return 1
        if node.id not in muuttujat:
            raise KaavaVirhe(f"Tuntematon muuttuja: {node.id}")
        return muuttujat[node.id]

    if isinstance(node, ast.List):
        return [_arvioi(e, muuttujat, kaikki_suoritukset) for e in node.elts]

    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOP:
            raise KaavaVirhe("Kielletty laskutoimitus")
        vasen = _arvioi(node.left, muuttujat, kaikki_suoritukset)
        oikea = _arvioi(node.right, muuttujat, kaikki_suoritukset)
        try:
            return _vartioittain(_BINOP[type(node.op)])(vasen, oikea)
        except ZeroDivisionError:
            raise KaavaVirhe("Nollalla jako")
        except TypeError:
            raise KaavaVirhe("Laskutoimitusta ei voi tehdä listalle — käytä esim. min(), max() tai med()")

    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY:
            raise KaavaVirhe("Kielletty etumerkki")
        try:
            return _vartioittain(_UNARY[type(node.op)])(_arvioi(node.operand, muuttujat, kaikki_suoritukset))
        except TypeError:
            raise KaavaVirhe("Etumerkkiä ei voi käyttää listalle")

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1 or type(node.ops[0]) not in _CMP:
            raise KaavaVirhe("Vain yksittäinen vertailu sallittu (==, !=, <, >, <=, >=)")
        vasen = _arvioi(node.left, muuttujat, kaikki_suoritukset)
        oikea = _arvioi(node.comparators[0], muuttujat, kaikki_suoritukset)
        try:
            return _vartioittain(_CMP[type(node.ops[0])])(vasen, oikea)
        except TypeError:
            raise KaavaVirhe("Vertailua ei voi tehdä listalle")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise KaavaVirhe("Vain suorat funktiokutsut sallittu")
        nimi = node.func.id

        if nimi == "kaikki":
            if len(node.args) != 1:
                raise KaavaVirhe("kaikki(...) vaatii tarkalleen yhden lausekkeen")
            tulokset = []
            for toisen_muuttujat in kaikki_suoritukset:
                try:
                    tulokset.append(_arvioi(node.args[0], toisen_muuttujat, kaikki_suoritukset))
                except KaavaVirhe:
                    pass  # kyseiseltä vartiolta puuttuu tarvittava syöte — ohitetaan
            return tulokset

        if nimi == "oletus":
            # oletus(x, arvo): x, tai arvo jos x:ää ei voi laskea (esim. syöte jätetty tyhjäksi)
            if len(node.args) != 2:
                raise KaavaVirhe("oletus(x, arvo) vaatii kaksi parametria")
            try:
                return _arvioi(node.args[0], muuttujat, kaikki_suoritukset)
            except KaavaVirhe:
                return _arvioi(node.args[1], muuttujat, kaikki_suoritukset)

        if nimi == "jos" and len(node.args) == 3:
            # Lasketaan vain valittu haara, jotta esim. hylätyltä puuttuvat mitat eivät kaada kaavaa.
            # Joukko-ehdolla (vanha .a-syntaksi) lasketaan vartiokohtaisesti molemmat haarat.
            ehto = _arvioi(node.args[0], muuttujat, kaikki_suoritukset)
            if not isinstance(ehto, _Joukko):
                return _arvioi(node.args[1] if ehto else node.args[2], muuttujat, kaikki_suoritukset)
            args = [ehto] + [_arvioi(a, muuttujat, kaikki_suoritukset) for a in node.args[1:]]
            return FUNKTIOT["jos"](*args)

        if nimi not in FUNKTIOT:
            raise KaavaVirhe(f"Tuntematon funktio: {nimi}")
        args = [_arvioi(a, muuttujat, kaikki_suoritukset) for a in node.args]
        try:
            return FUNKTIOT[nimi](*args)
        except KaavaVirhe:
            raise
        except ZeroDivisionError:
            raise KaavaVirhe(f"Nollalla jako funktiossa {nimi}")
        except (TypeError, ValueError, statistics.StatisticsError) as e:
            raise KaavaVirhe(f"Virhe funktiossa {nimi}: {e}")

    raise KaavaVirhe("Kielletty lauseke")
