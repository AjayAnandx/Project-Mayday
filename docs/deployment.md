# Mayday — Deployment Guide

## Overview

Run Mayday 24/7 on a Windows laptop and access it from a phone anywhere via Tailscale.

**Architecture:** Single self-contained FastAPI server (port 8770) serving both the API and the built frontend as static files. Registered as a Windows service that starts on boot and auto-restarts on crash.

---

## Prerequisites

| Item | Purpose |
|------|---------|
| Python 3.11+ | FastAPI backend |
| Node.js 18+ | Frontend build |
| NSSM | Windows service manager (`winget install nssm`) |
| Tailscale | Secure remote access (phone + laptop) |

---

## Step 1 — Serve frontend from FastAPI

Modify `backend/main.py` to mount the built frontend as static files with an SPA catch-all:

1. Add `from fastapi.staticfiles import StaticFiles` and `from fastapi.responses import FileResponse` imports
2. Mount `frontend/dist/` at the root path
3. Add a catch-all route that serves `index.html` for any unmatched path (so page refreshes and direct navigation work)

### Code changes

```python
# At the top with other imports
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# After all API routers are mounted
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

# Only serve static files if the build exists
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("ws"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index_path)
```

## Step 2 — Build the frontend

```powershell
cd frontend
npm run build
```

Output goes to `frontend/dist/`. Only needs repeating when frontend code changes.

## Step 3 — Create the log directory

```powershell
mkdir logs
```

Service stdout/stderr will be written here.

## Step 4 — Install NSSM

```powershell
winget install nssm
```

Or download from [nssm.cc](https://nssm.cc) and place `nssm.exe` in `C:\Windows\System32\`.

## Step 5 — Register the Windows service

```powershell
nssm install MaydayBackend
```

In the NSSM GUI that opens, set:

| Field | Value |
|-------|-------|
| **Path** | `C:\Users\hp\AppData\Local\Programs\Python\Python311\python.exe` |
| **Arguments** | `-m uvicorn backend.main:app --host 0.0.0.0 --port 8770` |
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
curl http://localhost:8770/api/health
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

## Step 6 — Install Tailscale

1. Download from [tailscale.com/download/windows](https://tailscale.com/download/windows)
2. Install and sign in with a Google/Microsoft/GitHub account
3. Enable **Run as system service on Windows** during install (or in settings after) — this keeps the tailnet connection alive even when no user is logged in

### On your phone

1. Install Tailscale (iOS App Store / Google Play)
2. Sign in with the same account
3. Both devices are now on the same tailnet

### Find your laptop's Tailscale IP

```powershell
tailscale status
→ 100.x.x.x   my-laptop   ...
```

### Access Mayday from phone

Open `http://100.x.x.x:8770` in the phone browser — the full app loads.

For convenience, note the **MagicDNS name** (e.g. `my-laptop.tailXXXXX.ts.net`) shown in the Tailscale admin console:

```
http://my-laptop.tailXXXXX.ts.net:8770
```

---

## Daily reboots — what to expect

1. Laptop boots → Windows starts → NSSM launches `MaydayBackend` service (delayed start, ~30-60s after boot)
2. FastAPI starts → scheduler begins checking reminders/todos/events every 60s
3. Phone connects via Tailscale → `http://100.x.x.x:8770` → full Mayday is available
4. If the process crashes → NSSM auto-restarts after 10s

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

## Troubleshooting

### Service won't start

Check logs:

```powershell
type logs\stderr.log
```

Common issues:
- **Port 8770 already in use**: `netstat -ano | findstr :8770` then kill the process
- **Python module not found**: Verify the working directory is `C:\Users\hp\Projects\Mayday`
- **Missing dependencies**: `pip install -r requirements.txt`

### Cannot reach from phone

- Verify Tailscale is connected on both devices: `tailscale status`
- Verify the service is running: `nssm status MaydayBackend`
- Check Windows Firewall: ensure port 8770 is allowed for private networks
- Try from laptop: `curl http://localhost:8770/api/health`
- Try from laptop's Tailscale IP: `curl http://100.x.x.x:8770/api/health`

### Frontend is outdated

Rebuild and restart:

```powershell
cd frontend
npm run build
nssm restart MaydayBackend
```

---

## Files involved

| File | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app — serves API + frontend static files |
| `frontend/dist/` | Built frontend (generated by `npm run build`) |
| `config.yaml` | Server config (`host: 0.0.0.0`, port 8770) |
| `logs/stdout.log` | Service stdout |
| `logs/stderr.log` | Service stderr |
| `install-service.ps1` | (Optional) Helper script for service management |
