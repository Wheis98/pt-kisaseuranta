# Kipa — Kisaseuranta

Reaaliaikainen rastihenkilöiden leimaussovellus partiotapahtumiin.

---

## Kansiot

| Kansio | Sisältö |
|---|---|
| `app/` | Sovelluksen koodi (FastAPI) ja sivut (`app/static/`) |
| `data/` | Tietokannat `kipa.db` ja `kipa-testi.db` — eivät ole gitissä |
| `data/varmuuskopiot/` | Tietokantojen varmuuskopiot |
| `docs/` | Palvelimen käyttöohjeet (`palvelin-ohjeet.md`) ja muistiinpanot |
| `scripts/` | Testitilan käynnistys (`testi.ps1`) ja testidatan luonti (`seed_testi.py`) |
| `tupa/` | Vanhan Kipan koodi vertailua varten — ei ole gitissä |

Palvelimella sovellus ajetaan Docker-kontissa Traefikin takana, ks. [docs/palvelin-ohjeet.md](docs/palvelin-ohjeet.md) ja `Dockerfile`.

## Käynnistysohjeet

9. Varmista että Python on asennettuna (`python --version`)
10. Asenna riippuvuudet:
    ```
    pip install fastapi uvicorn
    ```
11. Siirry sovelluksen kansioon:
    ```
    cd pt-kisaseuranta
    ```
12. Käynnistä palvelin:
    ```
    uvicorn app.main:app --host 0.0.0.0 --port 8000
    ```
13. Avaa selaimessa: `http://localhost:8000`
14. Mene admin-hallintaan: `http://localhost:8000/admin.html`
15. Jos adminia ei ole vielä luotu, luo ensimmäinen admin-tunnus avautuvalla lomakkeella.
16. Luo käyttäjät (rastihenkilöt) admin-hallinnasta → **Käyttäjät**-osiosta.
17. Luo vartiot admin-hallinnasta → **Hallitse vartioita** ja tulosta QR-koodit.
18. Luo rastit ja aseta järjestys admin-hallinnasta → **Hallitse rasteja**.
19. Rastihenkilöt kirjautuvat etusivulta omalla nimellään ja salasanallaan.
20. Valittuaan rastin he voivat leimat vartioita sisään ja ulos.

## Testaus erillisellä tietokannalla

Testivartioita ja -leimauksia varten on oma tietokanta `data/kipa-testi.db`, jotta oikea `data/kipa.db` ei muutu:

```
.\scripts\testi.ps1            # käynnistää portissa 8001
.\scripts\testi.ps1 -Nollaa    # poistaa testidatan ja aloittaa puhtaalta pöydältä
python scripts\seed_testi.py    # täyttää testikannan esimerkkirasteilla ja -vartioilla
```

Testitila luo admin-tunnukset ja vartiot alusta. Sama toimii käsin: aseta ympäristömuuttuja `KIPA_DB` tietokantatiedoston polkuun ennen uvicornin käynnistystä.

## Julkaisu verkkoon (ngrok)

Käynnistä palvelin (kohta 12), ja sen jälkeen toisessa terminaalissa:

```
ngrok http 8000
```

Käytä näkyvää `https://`-osoitetta puhelimella tai muilla laitteilla.

## Tietoturvahuomio

Sovellus käyttää SHA-256-hashia salasanoille. Tuotantokäyttöön suositellaan bcrypt-kirjastoa.
