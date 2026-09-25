"""
Turvallinen lausekearvioija tehtävien kaavapohjaiselle pisteytykselle.

Kaava kirjoitetaan nimetyillä syötteillä (esim. "a", "b") ja funktioilla, esim.:
    interpoloi(aikavali(a,b), min(kaikki(aikavali(a,b))), 10, max(kaikki(aikavali(a,b))))

Arvioidaan Pythonin ast-moduulilla whitelist-periaatteella (ei eval()/exec()) —
vain alla listatut solmutyypit ja funktiot sallitaan, kaikki muu hylätään KaavaVirhe-poikkeuksella.
"""
import ast
import math
import operator
import statistics


class KaavaVirhe(Exception):
    pass


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
        if isinstance(a, list):
            tulos.extend(a)
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
    "interpoloi": _interpoloi,
    "aikavali": _aikavali,
    "jos": _jos,
    "floor": math.floor,
    "ceil": math.ceil,
    "abs": abs,
    "sqrt": math.sqrt,
    "pyorista": lambda x, n=0: round(x, int(n)),
}

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


def evaluoi(kaava: str, muuttujat: dict, kaikki_suoritukset: list | None = None):
    """
    muuttujat: {nimi: arvo} tämän suorituksen syötteet.
    kaikki_suoritukset: lista muiden (saman sarjan) vartioiden syöte-dictejä, kaikki(...)-funktiota varten.
    """
    if kaikki_suoritukset is None:
        kaikki_suoritukset = []
    try:
        puu = ast.parse(kaava, mode="eval")
    except SyntaxError as e:
        raise KaavaVirhe(f"Syntaksivirhe: {e}")
    return _arvioi(puu.body, muuttujat, kaikki_suoritukset)


def _arvioi(node, muuttujat, kaikki_suoritukset):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise KaavaVirhe("Vain numerot ovat sallittuja vakioita")

    if isinstance(node, ast.Name):
        if node.id not in muuttujat:
            raise KaavaVirhe(f"Tuntematon muuttuja: {node.id}")
        return muuttujat[node.id]

    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BINOP:
            raise KaavaVirhe("Kielletty laskutoimitus")
        vasen = _arvioi(node.left, muuttujat, kaikki_suoritukset)
        oikea = _arvioi(node.right, muuttujat, kaikki_suoritukset)
        try:
            return _BINOP[type(node.op)](vasen, oikea)
        except ZeroDivisionError:
            raise KaavaVirhe("Nollalla jako")

    if isinstance(node, ast.UnaryOp):
        if type(node.op) not in _UNARY:
            raise KaavaVirhe("Kielletty etumerkki")
        return _UNARY[type(node.op)](_arvioi(node.operand, muuttujat, kaikki_suoritukset))

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1 or type(node.ops[0]) not in _CMP:
            raise KaavaVirhe("Vain yksittäinen vertailu sallittu (==, !=, <, >, <=, >=)")
        vasen = _arvioi(node.left, muuttujat, kaikki_suoritukset)
        oikea = _arvioi(node.comparators[0], muuttujat, kaikki_suoritukset)
        return _CMP[type(node.ops[0])](vasen, oikea)

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

        if nimi not in FUNKTIOT:
            raise KaavaVirhe(f"Tuntematon funktio: {nimi}")
        args = [_arvioi(a, muuttujat, kaikki_suoritukset) for a in node.args]
        try:
            return FUNKTIOT[nimi](*args)
        except KaavaVirhe:
            raise
        except (TypeError, ValueError, statistics.StatisticsError) as e:
            raise KaavaVirhe(f"Virhe funktiossa {nimi}: {e}")

    raise KaavaVirhe("Kielletty lauseke")
