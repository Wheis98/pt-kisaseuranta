# pt-kisaseuranta Docker-kontissa (Traefikin takana, ks. palvelin-ohjeet.md)
FROM python:3.12-slim

# Ajastin ja lähtöjen käynnistys ottavat ajan palvelimen kellosta, joten kontin pitää olla Suomen ajassa
ENV TZ=Europe/Helsinki \
    PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Tietokanta on kontin ulkopuolella liitetyssä /data-kansiossa, jottei se häviä kontin uudelleenrakennuksessa
ENV KIPA_DB=/data/kipa.db
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
