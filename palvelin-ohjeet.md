# Palvelimen käyttöohjeet (Hetzner, Linux)

Yhteenveto palvelimen käytöstä, tiedostojen siirrosta sekä Kipan ja pt-kisaseurannan asennuksesta.

Korvaa komennoissa:
- `kayttaja` = palvelimen käyttäjänimi (Hetznerillä yleensä `root`)
- `palvelimen_ip` = palvelimen IP-osoite

> **Muistisääntö:** `ssh`- ja `scp`-komennot ajetaan **omalla koneella (PowerShell)**. Muut Linux-komennot ajetaan **palvelimella** SSH-yhteyden kautta.
> Näet missä olet komentorivin alusta: `PS C:\...>` = oma kone, `root@palvelin:~#` = palvelin.

---

## 1. Yhteys palvelimeen

```powershell
ssh kayttaja@palvelimen_ip
```

Uloskirjautuminen:
```bash
exit
```

## 2. Kansioissa liikkuminen (palvelimella)

| Komento | Mitä tekee |
|---|---|
| `pwd` | Näyttää nykyisen kansion polun |
| `ls` | Listaa kansion sisällön |
| `ls -la` | Tarkka listaus, myös piilotiedostot |
| `ls -d */` | Näyttää vain kansiot |
| `cd kansio` | Siirry kansioon |
| `cd ..` | Palaa ylöspäin |
| `cd ~` | Palaa kotihakemistoon |
| `mkdir kansio` | Luo uuden kansion |
| `cat tiedosto` | Näyttää tiedoston sisällön |
| `rm tiedosto` | Poistaa tiedoston |

Kohdekansion polun selvittäminen siirtoa varten: mene kansioon `cd`-komennolla ja aja `pwd`.

## 3. Tiedostojen siirto omalta koneelta (PowerShell + scp)

Avaa PowerShell tiedoston kansiossa: Resurssienhallinnassa oikea klikkaus kansion tyhjään kohtaan → **Avaa päätteessä**. Tai:

```powershell
cd "C:\Users\Nimesi\Desktop"
dir
```

Yksittäinen tiedosto palvelimen kotihakemistoon:
```powershell
scp .\tiedosto.txt kayttaja@palvelimen_ip:~/
```

Koko kansio:
```powershell
scp -r .\kansionnimi kayttaja@palvelimen_ip:~/kohdekansio/
```

Palvelimelta omalle koneelle:
```powershell
scp kayttaja@palvelimen_ip:~/tiedosto.txt .\
```

Hyödyllisiä valitsimia: `-r` kansiot, `-v` vianetsintä, `-p` säilyttää aikaleimat ja oikeudet.

**Virhe `Could not resolve hostname c`:** `scp` luki `C:`-alun palvelimen nimeksi. Siirry ensin tiedoston kansioon ja käytä muotoa `.\tiedosto`, tai tarkista ettet aja komentoa palvelimella.

## 4. Ohjelmien käynnistäminen (palvelimella)

| Tiedosto | Komento |
|---|---|
| `.sh` | `chmod +x skripti.sh` ja `./skripti.sh` |
| `.py` | `python3 ohjelma.py` |
| `.js` | `node ohjelma.js` |
| `.jar` | `java -jar ohjelma.jar` |
| `.exe` | Windows-ohjelma, ei toimi suoraan Linuxissa. Etsi Linux- tai Docker-versio. |

Tiedostotyypin tarkistus:
```bash
file tiedosto
```

Käyttöjärjestelmän ja prosessorin tarkistus:
```bash
cat /etc/os-release
uname -m      # x86_64 = tavallinen, aarch64 = ARM
```

### Ohjelma käyntiin taustalle (screen)

```bash
apt install screen
screen -S nimi        # avaa uuden istunnon
# käynnistä ohjelma
# irrottaudu: Ctrl+A, sitten D
screen -r nimi        # palaa istuntoon
screen -ls            # listaa istunnot
```

---

## 5. Kipa (Docker)

Kipa on selainpohjainen Python-ohjelma. Linux-palvelimella se ajetaan Dockerilla, `.exe`-versiota ja Wineä ei tarvita.

Lähde: https://github.com/partio-scout/kipa (asennusohje: `docs/installation.md`)

### Asennus

```bash
apt update
apt install docker.io
```

### Käynnistys

Kontti avaa portit 80 ja 3000. Testaa kumpi toimii:

```bash
docker rm -f kipa
docker run -p 8000:80 -p 8001:3000 --name kipa -d --restart unless-stopped --volume kipa-volume:/db ghcr.io/partio-scout/kipa:latest

curl -I http://localhost:8000/kipa/
curl -I http://localhost:8001/kipa/
```

Vastaus `200` tai `302` = toimiva portti. Käynnistä sen jälkeen pelkällä toimivalla portilla, esim. jos 3000 toimi:

```bash
docker rm -f kipa
docker run -p 8000:3000 --name kipa -d --restart unless-stopped --volume kipa-volume:/db ghcr.io/partio-scout/kipa:latest
```

Tietokanta säilyy `kipa-volume`-volumessa, vaikka kontti poistetaan.

Selaimessa: `http://palvelimen_ip:8000/kipa/`

### Hallinta

```bash
docker ps -a          # kontin tila
docker logs kipa      # lokit
docker stop kipa      # sammuta
docker start kipa     # käynnistä
docker inspect kipa --format '{{.Config.ExposedPorts}}'   # kontin portit
```

### Vianetsintä

| Oire | Syy |
|---|---|
| `Connection refused` | Kontti ei ole käynnissä → `docker ps -a`, `docker logs kipa` |
| `Connection reset by peer` | Kontti käynnissä, mutta väärä sisäinen portti → kokeile porttia 3000 |
| `curl` toimii palvelimella, selain ei | Palomuuri estää portin (kohta 7) |
| `exec format error` lokeissa | ARM-palvelin, kontti ei tue sitä |

---

## 6. pt-kisaseuranta (Python)

Lähde: https://github.com/Wheis98/pt-kisaseuranta

### Lataus palvelimelle

```bash
apt install git
cd ~
git clone https://github.com/Wheis98/pt-kisaseuranta.git
cd ~/pt-kisaseuranta
ls -la
cat README.md
```

### Python-ympäristö

```bash
apt install python3 python3-venv python3-pip
cd ~/pt-kisaseuranta
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Tietokanta

Sovellus käyttää SQLite-tiedostoa. Oletuspolku on projektin juuressa `kipa.db` (`BASE_DIR.parent / "kipa.db"`, ks. `app/__init__.py`), mutta polun voi ohittaa ympäristömuuttujalla:

```bash
export KIPA_DB=/polku/omaan/kipa.db
```

Siirrä olemassa oleva kanta palvelimelle `scp`:llä (kohta 3) tai anna sovelluksen luoda uusi tyhjä kanta ensimmäisellä käynnistyksellä. **Älä ylikirjoita tuotantokantaa vahingossa** — testaa ensin `kipa-testi.db`:llä tai vastaavalla kopiolla.

### Käynnistys

Sovellus on FastAPI (`app/main.py`), riippuvuudet `fastapi` ja `uvicorn` (`requirements.txt`). Käynnistetään uvicornilla, ei suoraan `python3`-komennolla:

```bash
cd ~/pt-kisaseuranta
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8002
```

Taustalle:
```bash
screen -S kisaseuranta
cd ~/pt-kisaseuranta
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8002
# Ctrl+A, D
```

Huomioita:
- `--host 0.0.0.0` on pakollinen, jotta palvelu näkyy palvelimen ulkopuolelle (ei `127.0.0.1`).
- Käytä eri porttia kuin Kipa (esim. `8002`) ja avaa se palomuurissa (kohta 7).
- `Procfile`-tiedostossa on valmis komento (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`) alustoja varten, jotka asettavat `$PORT`-ympäristömuuttujan automaattisesti — Hetznerillä portti annetaan komennossa suoraan kuten yllä.

---

## 7. Portin avaaminen

### Hetzner Cloud -palomuuri

1. Kirjaudu: https://console.hetzner.cloud
2. Valitse projekti → **Firewalls**
3. Avaa palvelimeen liitetty palomuuri (jos palomuureja ei ole, Hetzner ei estä mitään)
4. **Inbound** → **Add rule**: Protocol `TCP`, Port esim. `8000`
5. Sources: `Any IPv4` + `Any IPv6`, tai turvallisemmin oma IP muodossa `123.45.67.89/32`
6. **Save rules** ja tarkista **Resources**-välilehdeltä, että palomuuri on liitetty palvelimeen

### Palvelimen oma palomuuri (ufw)

```bash
ufw status
ufw allow 8000/tcp     # vain jos status on active
```

### Käytössä olevat portit

| Portti | Ohjelma |
|---|---|
| 8000 | Kipa |
| 8002 | pt-kisaseuranta (ehdotus) |

---

## 8. Tietoturva

- Julkisesti avattua Kipaa voi kuka tahansa osoitteen tietävä muokata. Rajaa pääsy palomuurissa kisatoimiston IP-osoitteeseen tai lisää salasanasuojaus.
- Avaa palomuurista vain tarvittavat portit.
- Älä aja tuntemattomia `.exe`-tiedostoja. UPX-pakatut tiedostot kannattaa tarkistaa esim. VirusTotalissa.
