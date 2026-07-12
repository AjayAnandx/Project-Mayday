# Mayday — Deployment Guide

## Overview

Run Mayday 24/7 on a Windows laptop and access it from a phone browser anywhere via Tailscale.

**Architecture:** Single self-contained FastAPI server (port 8771) serving both the API and the built frontend. Registered as a Windows service via NSSM that starts on boot and auto-restarts on crash. Ollama runs as its own Windows service for the LLM backend.

---

## Prerequisites

| Item | Purpose |
|------|---------|
| Python 3.11+ | FastAPI backend |
| Node.js 18+ | Frontend build |
| Google Chrome | Selenium screenshots |
| NSSM | Windows service manager (`winget install nssm`) |
| Tailscale | Secure remote access (phone + laptop) |
| Ollama | Local LLM server (download — auto-registers service) |

---

## Step 1 — Install dependencies

```powershell
pip install -r requirements.txt
cd frontend
npm install
```

---

## Step 2 — Set up environment variables

Copy the template and fill in your API keys:

```powershell
copy .env.example .env
```

Edit `.env` with your keys:

| Variable | Required? | Get it at |
|----------|-----------|-----------|
| `DEEPGRAM_API_KEY` | Yes (voice) | https://console.deepgram.com/ |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | Yes (GH tools) | https://github.com/settings/tokens |
| `EXA_API_KEY` | Yes (web search) | https://dashboard.exa.ai/api-keys |

`.env` is already in `.gitignore` — your keys stay local.

---

## Step 3 — Build the frontend

```powershell
cd frontend
npm run build
```

Output goes to `frontend/dist/`. Only needs repeating when frontend code changes.

---

## Step 4 — Install Ollama and pull the model

Download from https://ollama.com/download/windows — the installer auto-registers a Windows service so it starts on boot.

```powershell
ollama pull gemma4:31b-cloud
```

Verify it works:

```powershell
curl http://localhost:11434/api/tags
→ {"models":[{"name":"gemma4:31b-cloud", ...}]}
```

---

## Step 5 — Install NSSM

```powershell
winget install nssm
```

Or download from https://nssm.cc and place `nssm.exe` in `C:\Windows\System32\`.

---

## Step 6 — Create the log directory

```powershell
mkdir logs
```

Service stdout/stderr will be written here.

---

## Step 7 — Register the FastAPI Windows service

```powershell
nssm install MaydayBackend
```

In the NSSM GUI that opens, set:

| Field | Value |
|-------|-------|
| **Path** | `C:\Users\hp\AppData\Local\Programs\Python\Python311\python.exe` |
| **Arguments** | `-m uvicorn backend.main:app --host 0.0.0.0 --port 8771` |
| **Startup directory** | `C:\Users\hp\Projects\Mayday` |

In the **Details** tab:
- **Display name**: `Mayday Backend`
- **Startup type**: `Automatic (Delayed Start)`

In the **Shutdown** tab:
- **Exit method**: `Terminate`
- **Stop priority**: `90, 60, 30`

In the **Exit actions** tab:
- On **Application crash**: `Restart` with a `10000` ms (10s) delay
- On **Application exit** (exit code `0`): `Restart` with a `0` ms delay

In the **I/O** tab:
- **Output (stdout)**: `C:\Users\hp\Projects\Mayday\logs\stdout.log`
- **Error (stderr)**: `C:\Users\hp\Projects\Mayday\logs\stderr.log`

### Start the service

```powershell
nssm start MaydayBackend
```

Verify it's running:

```powershell
curl http://localhost:8771/api/health
→ {"status":"ok"}
```

### Service management commands

| Action | Command |
|--------|---------|
| Start | `nssm start MaydayBackend` |
| Stop | `nssm stop MaydayBackend` |
| Restart | `nssm restart MaydayBackend` |
| Status | `nssm status MaydayBackend` |
| Remove | `nssm remove MaydayBackend confirm` |
| Edit GUI | `nssm edit MaydayBackend` |

---

## Step 8 — Install Tailscale

1. Download from https://tailscale.com/download/windows
2. Install and sign in with a Google/Microsoft/GitHub account
3. Enable **Run as system service on Windows** during install — keeps the tailnet connection alive even when no user is logged in

### On your phone

1. Install Tailscale (Google Play / App Store)
2. Sign in with the **same account**
3. Both devices are now on the same tailnet

### Find your laptop's Tailscale IP

```powershell
tailscale status
→ 100.x.x.x   my-laptop   ...
```

### Access Mayday from phone

Open `http://100.x.x.x:8771` in the phone browser — the full app loads.

For convenience, note the **MagicDNS name** (e.g. `my-laptop.tailXXXXX.ts.net`) shown in the Tailscale admin console:

```
http://my-laptop.tailXXXXX.ts.net:8771
```

---

## Daily reboots — what to expect

1. Laptop boots → Windows starts
2. Ollama service starts (auto, ~10s)
3. Tailscale connects (system service, ~15s)
4. NSSM launches `MaydayBackend` (delayed start, ~30-60s after boot)
5. FastAPI starts → serves API + frontend
6. Phone connects via Tailscale → `http://100.x.x.x:8771` → full Mayday
7. If the process crashes → NSSM auto-restarts after 10s

**Total time from power button to usable:** ~60 seconds.

---

## Updating the app

### Backend changes only

1. Edit code
2. `nssm restart MaydayBackend` — no build needed

### Frontend changes

1. Edit code
2. `cd frontend && npm run build`
3. `nssm restart MaydayBackend` — serves the updated static files

### Both

Same as frontend changes — just rebuild and restart the service.

---

## What works on phone

| Feature | Works? |
|---------|--------|
| Chat (LLM) | ✅ Full markdown rendering |
| Todos CRUD | ✅ Full search/filter |
| Calendar | ✅ Month grid, events CRUD |
| Knowledge Graph | ✅ View + search |
| Unified Search | ✅ Ctrl+K (tap) overlay |
| Project tracking | ✅ Create projects, tasks, folders |
| Screenshots | ✅ View captured screenshots |
| Voice tab | ❌ Chrome/Edge only; not on iOS Safari |

Voice tab is limited to Chrome/Edge on desktop. On phone, use text chat instead.

---

## Troubleshooting

### Service won't start

Check logs:

```powershell
type logs\stderr.log
```

Common issues:
- **Port 8771 already in use**: `netstat -ano | findstr :8771` then kill the process
- **Python module not found**: Verify the working directory is `C:\Users\hp\Projects\Mayday`
- **Missing dependencies**: `pip install -r requirements.txt`
- **Ollama not running**: `curl http://localhost:11434/api/tags`

### Cannot reach from phone

- Verify Tailscale is connected on both devices: `tailscale status`
- Verify the service is running: `nssm status MaydayBackend`
- Check Windows Firewall: ensure port 8771 is allowed for private networks
- Try from laptop: `curl http://localhost:8771/api/health`
- Try from laptop's Tailscale IP: `curl http://100.x.x.x:8771/api/health`

### Frontend is outdated

Rebuild and restart:

```powershell
cd frontend
npm run build
nssm restart MaydayBackend
```

### Ollama issues

```powershell
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama service
nssm restart Ollama  # or use Windows Services GUI (services.msc)
```

---

## Files involved

| File | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app — serves API + frontend static files |
| `frontend/dist/` | Built frontend (generated by `npm run build`) |
| `config.yaml` | Server config (port 8771, model, MCP servers) |
| `.env` | API keys (not in git) |
| `logs/stdout.log` | Service stdout |
| `logs/stderr.log` | Service stderr |
| `data.json` | Todos and events data |
| `conversations/` | Per-day conversation files |
| `projects.json` | Project tracking store |

## Known limitations

- **Voice tab** — Browser SpeechRecognition API is Chrome/Edge only. iOS Safari and Firefox do not support it. Use text chat on phone.
- **Selenium screenshots** — Requires Google Chrome installed on the server. ChromeDriver is managed automatically by `mcp-server-selenium`.
- **Ollama model** — `gemma4:31b-cloud` routes through a cloud proxy via local Ollama. Expect higher latency than fully local models.
