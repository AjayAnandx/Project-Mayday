# run-voice.ps1 — start Mayday backend + a Cloudflare quick tunnel for Voice.
#
# What it does:
#   1. Ensures the Mayday backend is reachable on $Port (defaults to 8772,
#      the dev port; the stale NSSM service on 8771 predates the voice API).
#   2. Opens a cloudflared quick tunnel to that port.
#   3. Rewrites workers/voice-agent/wrangler.toml with the live tunnel URLs
#      and redeploys the Worker, so voice works end-to-end in one command.
#
# Usage:
#   .\run-voice.ps1                 # tunnel only (assumes backend already up)
#   .\run-voice.ps1 -StartBackend   # also start the FastAPI backend
#
# Requires: cloudflared (winget install cloudflare.cloudflared)

param(
  [int]$Port = 8772,
  [switch]$StartBackend
)

$ErrorActionPreference = "Stop"
$backendProc = $null

# Resolve cloudflared: prefer PATH, else known install locations.
$cloudflared = $null
if (Get-Command cloudflared -ErrorAction SilentlyContinue) {
  $cloudflared = "cloudflared"
} else {
  $candidates = @(
    "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    "C:\Program Files\cloudflared\cloudflared.exe",
    "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe",
    "$env:USERPROFILE\scoop\shims\cloudflared.exe"
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { $cloudflared = $c; break }
  }
}
if (-not $cloudflared) {
  Write-Host "ERROR: cloudflared not found." -ForegroundColor Red
  Write-Host "Install: winget install cloudflare.cloudflared" -ForegroundColor Yellow
  Write-Host "Or download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" -ForegroundColor Yellow
  Write-Host "Or add its install folder to PATH (e.g. C:\Program Files (x86)\cloudflared)." -ForegroundColor Yellow
  exit 1
}

$portInUse = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $portInUse) {
  if (-not $StartBackend) {
    Write-Host ("Backend not listening on :" + $Port + " and -StartBackend not set.") -ForegroundColor Red
    Write-Host "Start it yourself, or re-run: .\run-voice.ps1 -StartBackend" -ForegroundColor Yellow
    exit 1
  }
  $venv = if (Test-Path (Join-Path $PSScriptRoot "venv\Scripts\python.exe")) { (Join-Path $PSScriptRoot "venv\Scripts\python.exe") } else { "python" }
  $backendLog = Join-Path $PSScriptRoot "backend_voice.log"
  $backendErr = Join-Path $PSScriptRoot "backend_voice.err"
  Write-Host ("Starting backend on :" + $Port + " ...") -ForegroundColor Green
  $backendProc = Start-Process -FilePath $venv -ArgumentList "-m","uvicorn","backend.main:app","--host","127.0.0.1","--port",$Port -WorkingDirectory $PSScriptRoot -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr -WindowStyle Hidden -PassThru
  $portInUse = $false
  ForEach ($i in 1..20) {
    Start-Sleep -Seconds 2
    $portInUse = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($portInUse) { break }
  }
  if (-not $portInUse) {
    Write-Host ("Backend failed to come up on :" + $Port + ".") -ForegroundColor Red
    Write-Host ("Try starting it manually: .\venv\Scripts\python.exe -m uvicorn backend.main:app --port " + $Port) -ForegroundColor Yellow
    if ($backendProc) { Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue }
    exit 1
  }
}

Write-Host ("Opening Cloudflare tunnel to http://localhost:" + $Port + " ...") -ForegroundColor Green
$tunnelErr = Join-Path $PSScriptRoot "tunnel.err"
$tunnelOut = Join-Path $PSScriptRoot "tunnel.log"
Remove-Item -Force $tunnelErr, $tunnelOut -ErrorAction SilentlyContinue
$tunnelProc = Start-Process -FilePath $cloudflared -ArgumentList "tunnel","--url",("http://localhost:" + $Port) -RedirectStandardOutput $tunnelOut -RedirectStandardError $tunnelErr -WindowStyle Hidden -PassThru

$tunnelHost = $null
ForEach ($i in 1..35) {
  Start-Sleep -Seconds 1
  if (Test-Path $tunnelErr) {
    $l = Get-Content $tunnelErr -Raw -ErrorAction SilentlyContinue
    if ($l -match 'https://([a-z0-9\-]+\.trycloudflare\.com)') { $tunnelHost = $Matches[1]; break }
  }
}
if (-not $tunnelHost) {
  Write-Host "Could not detect tunnel URL. Is cloudflared installed and network ok?" -ForegroundColor Red
  if ($tunnelProc) { Stop-Process -Id $tunnelProc.Id -Force -ErrorAction SilentlyContinue }
  if ($backendProc) { Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue }
  exit 1
}

$turn = ("https://" + $tunnelHost + "/api/voice/turn")
$sync = ("https://" + $tunnelHost + "/api/voice/sync")

$tomlPath = Join-Path $PSScriptRoot "workers/voice-agent/wrangler.toml"
if (Test-Path $tomlPath) {
  $c = Get-Content $tomlPath -Raw
  $turnLine = 'MAYDAY_TURN_URL = "' + $turn + '"'
  $syncLine = 'MAYDAY_SYNC_URL  = "' + $sync + '"'
  $c = $c -replace 'MAYDAY_TURN_URL = "[^"]*"', $turnLine
  $c = $c -replace 'MAYDAY_SYNC_URL\s*=\s*"[^"]*"', $syncLine
  Set-Content $tomlPath $c
  Write-Host ("Updated " + $tomlPath) -ForegroundColor Green
  Write-Host "Redeploying Worker with live tunnel URLs..." -ForegroundColor Green
  Push-Location (Join-Path $PSScriptRoot "workers/voice-agent")
  wrangler deploy 2>&1 | ForEach-Object { Write-Host $_ }
  Pop-Location
} else {
  Write-Host ("Could not find " + $tomlPath + ". Set URLs manually, then wrangler deploy.") -ForegroundColor Yellow
  Write-Host ("MAYDAY_TURN_URL = " + $turn) -ForegroundColor White
  Write-Host ("MAYDAY_SYNC_URL  = " + $sync) -ForegroundColor White
}

Write-Host ""
Write-Host "=== Cloudflare Voice is LIVE ===" -ForegroundColor Cyan
Write-Host ("Brain endpoint : " + $turn) -ForegroundColor White
Write-Host "Open the Voice tab in the app or the Worker URL and speak." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the tunnel (and backend, if started here)." -ForegroundColor DarkGray

try {
  while ($true) { Start-Sleep -Seconds 1 }
} finally {
  Write-Host "`nStopping tunnel..." -ForegroundColor DarkGray
  if ($tunnelProc) { Stop-Process -Id $tunnelProc.Id -Force -ErrorAction SilentlyContinue }
  if ($backendProc) { Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue }
}
