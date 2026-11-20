"""Mayday desktop sensor (Brain V3 P8). Runs in the USER session, not in the service.

    pythonw -m backend.brain.sensor_agent            # normally started at logon (scripts/install_brain_sensor.ps1)
    python  -m backend.brain.sensor_agent --once     # print one 15 s aggregate and exit (debug)

Why a separate process: the backend runs as a Windows service (session 0), which cannot see the
interactive desktop, so GetForegroundWindow there always returns nothing.

What it sends every 15 s to POST /api/brain/signals (header X-Brain-Token):
    {"kind": "desktop_window", "value": {"window_s": 15, "cat": {"code": 12, "browser": 3},
     "switches": 2, "idle_s": 0, "locked": false, "on_battery": false}}
Privacy: window titles and executable paths never leave this process. The title is read
only to tell a meeting in the browser (Meet/Zoom/Teams tab) from ordinary browsing, then
discarded. Only app CATEGORIES and counts are sent.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOKEN_FILE = REPO / "brain_sensor.token"

DEFAULT_CATEGORIES = {
    "code": ["code.exe", "code - insiders.exe", "cursor.exe", "pycharm64.exe", "idea64.exe", "devenv.exe",
             "sublime_text.exe", "notepad++.exe", "windsurf.exe", "zed.exe"],
    "terminal": ["windowsterminal.exe", "wt.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "mintty.exe",
                 "conhost.exe"],
    "docs": ["winword.exe", "powerpnt.exe", "onenote.exe", "acrobat.exe", "acrord32.exe", "obsidian.exe",
             "notion.exe", "notepad.exe", "sumatrapdf.exe"],
    "data": ["excel.exe", "tableau.exe", "jupyter-lab.exe"],
    "design": ["figma.exe", "photoshop.exe", "illustrator.exe", "blender.exe", "canva.exe"],
    "meeting": ["teams.exe", "ms-teams.exe", "zoom.exe", "webex.exe"],
    "chat": ["whatsapp.exe", "telegram.exe", "slack.exe", "discord.exe", "signal.exe"],
    "media": ["spotify.exe", "vlc.exe", "netflix.exe", "wmplayer.exe"],
    "browser": ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "arc.exe"],
    "system": ["explorer.exe", "lockapp.exe", "searchhost.exe", "shellexperiencehost.exe"],
}
# browser tab titles that mean "meeting" / "mayday" (title is inspected locally, never sent)
_BROWSER_MEETING = re.compile(r"\b(google meet|meet -|zoom meeting|microsoft teams|webex)\b", re.I)
_BROWSER_MAYDAY = re.compile(r"\bmayday\b", re.I)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                ("BatteryLifeTime", wt.DWORD), ("BatteryFullLifeTime", wt.DWORD)]


def idle_seconds() -> float:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return max(0.0, (kernel32.GetTickCount() - lii.dwTime) / 1000.0)


def on_battery() -> bool | None:
    s = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None
    return s.ACLineStatus == 0


def foreground() -> tuple[str, str]:
    """(exe name lower-case, title) of the foreground window; ('', '') when none (locked)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wt.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                exe = os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(h)
    n = user32.GetWindowTextLengthW(hwnd)
    tbuf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, tbuf, n + 1)
    return exe, tbuf.value


def categorize(exe: str, title: str, mapping: dict[str, list[str]]) -> str:
    if not exe:
        return "none"
    for cat, exes in mapping.items():
        if exe in exes:
            if cat == "browser":
                if _BROWSER_MEETING.search(title or ""):
                    return "meeting"
                if _BROWSER_MAYDAY.search(title or ""):
                    return "mayday"
            return cat
    return "other"


def is_locked(exe: str) -> bool:
    return exe in ("", "lockapp.exe", "logonui.exe")


def load_settings() -> dict:
    url = os.environ.get("MAYDAY_URL")
    mapping = {k: list(v) for k, v in DEFAULT_CATEGORIES.items()}
    try:
        import yaml
        cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8")) or {}
        s = ((cfg.get("brain") or {}).get("sensors") or {})
        url = url or s.get("backend_url")
        for cat, exes in (s.get("categories") or {}).items():
            mapping.setdefault(cat, [])
            mapping[cat] = list({*mapping[cat], *[e.lower() for e in exes]})
        if not url:
            port = ((cfg.get("server") or {}).get("port")) or 8771
            url = f"http://127.0.0.1:{port}"
    except Exception:
        url = url or "http://127.0.0.1:8771"
    return {"url": url.rstrip("/"), "mapping": mapping}


def read_token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def aggregate(window_s: int, mapping: dict, sample=None, sleep=time.sleep) -> dict:
    """Sample once per second for window_s seconds; return the privacy-safe aggregate."""
    sample = sample or (lambda: (*foreground(), idle_seconds()))
    cats: dict[str, int] = {}
    switches, idle_s, locked_s = 0, 0, 0
    last_cat = None
    for _ in range(window_s):
        exe, title, idle = sample()
        cat = categorize(exe, title, mapping)
        title = None                                       # never kept
        if is_locked(exe):
            locked_s += 1
            idle_s += 1
        elif idle >= 60:
            idle_s += 1
        else:
            cats[cat] = cats.get(cat, 0) + 1
            if last_cat is not None and cat != last_cat:
                switches += 1
            last_cat = cat
        sleep(1)
    return {"window_s": window_s, "cat": cats, "switches": switches, "idle_s": idle_s,
            "locked": locked_s >= window_s * 0.9, "on_battery": on_battery()}


def post(url: str, token: str, value: dict, ts: str | None = None, timeout: float = 5.0) -> bool:
    body = json.dumps({"kind": "desktop_window", "source": "desktop", "value": value, "ts": ts}).encode()
    req = urllib.request.Request(f"{url}/api/brain/signals", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Brain-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--window", type=int, default=15)
    a = ap.parse_args(argv)
    settings = load_settings()
    if a.once:
        print(json.dumps(aggregate(a.window, settings["mapping"]), indent=2))
        return 0
    backlog: list[dict] = []
    while True:
        value = aggregate(a.window, settings["mapping"])
        from datetime import datetime, timezone
        backlog.append((datetime.now(timezone.utc).isoformat(), value))
        token = read_token()
        while backlog and post(settings["url"], token, backlog[0][1], ts=backlog[0][0]):
            backlog.pop(0)
        del backlog[:-20]                                  # keep at most 5 min while the backend is down


if __name__ == "__main__":
    sys.exit(main())
