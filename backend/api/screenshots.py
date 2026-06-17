import json
import logging
import os
import shutil
import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "screenshots")
INDEX_PATH = os.path.join(SCREENSHOTS_DIR, "index.json")


class ScreenshotStore:
    def __init__(self):
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        self._lock = threading.Lock()
        self._load_index()

    def _load_index(self):
        if os.path.exists(INDEX_PATH):
            with open(INDEX_PATH, encoding="utf-8") as f:
                self._index = json.load(f)
        else:
            self._index = {"screenshots": []}
            self._save_index()

    def _save_index(self):
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2)

    def add_screenshot(self, src_path: str) -> str | None:
        if not os.path.exists(src_path):
            logger.warning("Screenshot file not found: %s", src_path)
            return None
        filename = os.path.basename(src_path)
        dest = os.path.join(SCREENSHOTS_DIR, filename)
        shutil.copy2(src_path, dest)
        os.remove(src_path)
        entry = {
            "filename": filename,
            "timestamp": datetime.now().isoformat(),
            "url": f"/screenshots/{filename}",
        }
        with self._lock:
            self._index["screenshots"].append(entry)
            self._save_index()
        logger.info("Screenshot saved: %s", filename)
        return filename

    def list_screenshots(self) -> list[dict]:
        with self._lock:
            return list(reversed(self._index["screenshots"]))

    def get_screenshot(self, filename: str) -> dict | None:
        with self._lock:
            for s in self._index["screenshots"]:
                if s["filename"] == filename:
                    return s
        return None

    def delete_screenshot(self, filename: str) -> bool:
        filepath = os.path.join(SCREENSHOTS_DIR, filename)
        with self._lock:
            self._index["screenshots"] = [s for s in self._index["screenshots"] if s["filename"] != filename]
            self._save_index()
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False


_store: ScreenshotStore | None = None


def get_screenshot_store() -> ScreenshotStore:
    global _store
    if _store is None:
        _store = ScreenshotStore()
    return _store


# --- LLM tool functions ---

def list_screenshots() -> str:
    store = get_screenshot_store()
    shots = store.list_screenshots()
    if not shots:
        return "No screenshots stored."
    lines = [f"Stored screenshots ({len(shots)}):"]
    for s in shots:
        lines.append(f"  - {s['filename']} ({s['timestamp']})")
    return "\n".join(lines)


def get_screenshot_info(filename: str) -> str:
    store = get_screenshot_store()
    entry = store.get_screenshot(filename)
    if not entry:
        return f"Screenshot not found: {filename}"
    return json.dumps(entry)


def delete_screenshot_file(filename: str) -> str:
    store = get_screenshot_store()
    if store.delete_screenshot(filename):
        return f"Deleted screenshot: {filename}"
    return f"Screenshot not found: {filename}"


# --- REST router ---

router = APIRouter()


@router.get("/api/screenshots")
def list_screenshots_api():
    store = get_screenshot_store()
    return JSONResponse(content=store.list_screenshots())


@router.delete("/api/screenshots/{filename:path}")
def delete_screenshot_api(filename: str):
    store = get_screenshot_store()
    if store.delete_screenshot(filename):
        return JSONResponse(content={"status": "deleted", "filename": filename})
    raise HTTPException(status_code=404, detail="Screenshot not found")
