"""LLM tool: export a research topic's collected data points to a CSV dataset file.

The file is written into the configured `uploads/` directory so it appears in the
Data Import panel and is directly downloadable/served at /uploads/<file_id>.
"""
import csv
import json
import re
import uuid
from pathlib import Path

from backend.core.config import load_config
from backend.core.research_store import get_research_store

_SERIES_SEP = " | "

_CSV_COLUMNS = ["category", "period", "value", "unit"]


def _uploads_dir() -> Path:
    cfg = load_config()
    d = Path(cfg.get("data", {}).get("uploads_dir", "uploads"))
    if not d.is_absolute():
        d = Path(__file__).resolve().parent.parent.parent / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "dataset"


def export_research_dataset(topic: str, filename: str | None = None) -> str:
    """Write a research topic's data points to a CSV in the uploads directory.

    Reconstructs tidy long-format rows (category / period / value / unit) by
    reversing the 'series | time' label encoding used when data was stored.
    Returns a JSON string with an `artifact` entry so the chat UI shows a
    downloadable file (it will NOT auto-open — only charts auto-open).
    """
    store = get_research_store()
    project = store._get_by_topic(topic)
    if not project:
        return json.dumps({"error": f"Research '{topic}' not found"})

    dps = project.get("data_points", [])
    if not dps:
        return json.dumps({"error": "No data points to export — collect data first with batch_add_data_points."})

    rows = []
    for dp in dps:
        label = (dp.get("label") or "").strip()
        series = label
        period = ""
        if _SERIES_SEP in label:
            series, period = [p.strip() for p in label.split(_SERIES_SEP, 1)]
        rows.append({
            "category": series,
            "period": period,
            "value": dp.get("value", ""),
            "unit": dp.get("unit", "") or "",
        })

    udir = _uploads_dir()
    base = filename or f"{_slugify(topic)}_dataset"
    base = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    if not base.lower().endswith(".csv"):
        base += ".csv"
    file_id = f"{uuid.uuid4().hex[:12]}_{base}"
    path = udir / file_id

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    url = f"/uploads/{file_id}"
    return json.dumps({
        "message": (
            f"Exported **{len(rows)}** rows from '{topic}' to CSV (`{file_id}`). "
            f"The dataset is now available in the Data Import panel and downloadable at {url}."
        ),
        "artifact": {"url": url, "title": base},
        "files": [{
            "format": "csv",
            "file_id": file_id,
            "name": base,
            "url": url,
            "path": str(path),
        }],
    })
