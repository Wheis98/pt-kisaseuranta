# Käynnistää sovelluksen erillisellä testitietokannalla (kipa-testi.db) portissa 8001.
# Oikea kipa.db ei muutu. Nollaa testidata: .\testi.ps1 -Nollaa
param([switch]$Nollaa)

Set-Location $PSScriptRoot
if ($Nollaa -and (Test-Path kipa-testi.db)) { Remove-Item kipa-testi.db }

$env:KIPA_DB = Join-Path $PSScriptRoot "kipa-testi.db"
Write-Host "TESTITILA: käytetään $env:KIPA_DB, osoite http://localhost:8001"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
