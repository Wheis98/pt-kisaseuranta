import sys
from pathlib import Path

if __name__ == "__main__":
    # Sallii tiedoston suoran ajamisen (esim. IDE:n Run-napista) lisäämällä
    # projektin juurikansion polkuun, jotta "app"-paketti löytyy.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from app import STATIC_DIR
from app.routers import asetus, leimaus, login, rasti, sarja, tehtava, tilanne, tulos, user, vartio
from app.internal import admin

app = FastAPI()

@app.middleware("http")
async def ei_valimuistia_sivuille(request, call_next):
    # Selain tarkistaa HTML-sivut ja tyylit palvelimelta joka kerta (ETag), jotta päivitetty sivu
    # ei jää laitteille vanhana versiona välimuistiin
    response = await call_next(request)
    tyyppi = response.headers.get("content-type", "")
    if tyyppi.startswith("text/html") or tyyppi.startswith("text/css"):
        response.headers["Cache-Control"] = "no-cache"
    return response

app.include_router(asetus.router)
app.include_router(leimaus.router)
app.include_router(login.router)
app.include_router(rasti.router)
app.include_router(sarja.router)
app.include_router(tehtava.router)
app.include_router(tilanne.router)
app.include_router(tulos.router)
app.include_router(user.router)
app.include_router(vartio.router)

app.include_router(admin.router)

@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/ohje.html")
def ohje():
    # Rastihenkilön käyttöohje
    return FileResponse(STATIC_DIR / "ohje.html")

@app.get("/style.css")
def style():
    return FileResponse(STATIC_DIR / "style.css")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
