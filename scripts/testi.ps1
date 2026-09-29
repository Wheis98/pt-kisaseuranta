# Käynnistää sovelluksen erillisellä testitietokannalla (data\kipa-testi.db) portissa 8001.
# Oikea data\kipa.db ei muutu. Nollaa testidata: .\scripts\testi.ps1 -Nollaa
param([switch]$Nollaa)

# Projektin juuri (tämän skriptin yläkansio), jotta uvicorn löytää app-paketin
$projekti = Split-Path -Parent $PSScriptRoot
Set-Location $projekti
$testikanta = Join-Path $projekti "data\kipa-testi.db"
if ($Nollaa -and (Test-Path $testikanta)) { Remove-Item $testikanta }

$env:KIPA_DB = $testikanta
Write-Host "TESTITILA: käytetään $env:KIPA_DB, osoite http://localhost:8001"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
