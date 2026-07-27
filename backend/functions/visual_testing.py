import os
import json
import hashlib
import base64
from pathlib import Path
from datetime import datetime, timezone


_BASELINE_DIR = Path(__file__).resolve().parent.parent.parent / "baselines"
_BASELINE_INDEX = _BASELINE_DIR / "index.json"


def _ensure_dir():
    os.makedirs(_BASELINE_DIR, exist_ok=True)
    if not _BASELINE_INDEX.exists():
        _BASELINE_INDEX.write_text(json.dumps({"baselines": []}), encoding="utf-8")


def _load_index() -> dict:
    _ensure_dir()
    return json.loads(_BASELINE_INDEX.read_text(encoding="utf-8"))


def _save_index(index: dict):
    _BASELINE_INDEX.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def _image_hash(image_data: bytes) -> str:
    return hashlib.sha256(image_data).hexdigest()[:16]


def visual_diff(name: str, image_data_b64: str) -> str:
    image_data = base64.b64decode(image_data_b64)
    index = _load_index()
    baselines = index.get("baselines", [])
    existing = [b for b in baselines if b["name"] == name]

    new_hash = _image_hash(image_data)

    if existing:
        baseline = existing[0]
        if baseline["hash"] == new_hash:
            baseline["last_matched"] = datetime.now(timezone.utc).isoformat()
            _save_index(index)
            return f"visual_diff '{name}': PASS — no visual changes detected."
        else:
            baseline["last_failed"] = datetime.now(timezone.utc).isoformat()
            baseline["last_hash"] = new_hash
            _save_index(index)
            diff_path = _BASELINE_DIR / f"{name}_diff_{new_hash}.png"
            diff_path.write_bytes(image_data)
            return (
                f"visual_diff '{name}': FAIL — visual changes detected.\n"
                f"  Expected hash: {baseline['hash']}\n"
                f"  Actual hash:   {new_hash}\n"
                f"  New screenshot saved to: {diff_path}\n"
                f"  Use update_baseline('{name}') to accept the new version."
            )
    else:
        baseline_path = _BASELINE_DIR / f"{name}_baseline_{new_hash}.png"
        baseline_path.write_bytes(image_data)
        baselines.append({
            "name": name,
            "hash": new_hash,
            "path": str(baseline_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_matched": datetime.now(timezone.utc).isoformat(),
        })
        _save_index(index)
        return f"visual_diff '{name}': BASELINE SET — saved as baseline for future comparisons."


def check_element(url: str, selector: str = "", text: str = "") -> str:
    return (
        f"check_element called for {url}\n"
        f"  Selector: {selector or '(none)'}\n"
        f"  Text: {text or '(none)'}\n"
        f"Note: Browser navigation and element checking will be handled by the Selenium MCP server."
    )


def update_baseline(name: str) -> str:
    index = _load_index()
    baselines = index.get("baselines", [])
    for b in baselines:
        if b["name"] == name:
            if "last_hash" in b:
                b["hash"] = b["last_hash"]
                del b["last_hash"]
                _save_index(index)
                return f"Baseline '{name}' updated to last captured version."
            return f"Baseline '{name}' has no pending update."
    return f"Baseline '{name}' not found."
