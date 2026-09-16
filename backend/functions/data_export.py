"""LLM tool: export a research/project dataset to CSV or bare-table PDF.

CSV goes to the configured ``uploads/`` directory (served at /uploads/<file_id>).
PDF uses FPDF with the same dark/green style as report_generator._pdf_section.
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


def _get_data_points(topic: str, store_type: str = "research") -> tuple[list[dict] | None, str | None]:
    """Return (data_points, error). Looks in research store or project store."""
    if store_type == "project":
        from backend.core.project_store import get_project_store
        ps = get_project_store()
        proj = ps.find_project_by_name(topic) or ps.get_project(topic)
        if not proj:
            return None, f"Project '{topic}' not found"
        dps = proj.get("data_points", [])
        return dps, None
    store = get_research_store()
    project = store._get_by_topic(topic)
    if not project:
        return None, f"Research '{topic}' not found"
    return project.get("data_points", []), None


def export_dataset_pdf(topic: str, store_type: str = "research", filename: str | None = None) -> str:
    """Bare-table dataset PDF for a research topic or project.

    Columns: # / Label / Value / Unit / Confidence / Source  (same style as
    report_generator._pdf_section table). Supports both stores via store_type.
    Returns JSON with ``pdf_path`` / ``artifact`` so Telegram sender can send it.
    """
    dps, err = _get_data_points(topic, store_type=store_type)
    if err:
        return json.dumps({"error": err})
    if not dps:
        return json.dumps({"error": "No data points to export — collect data first with batch_add_data_points."})

    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_fill_color(13, 13, 13)
    pdf.rect(0, 0, 210, 297, "F")

    pdf.set_text_color(34, 197, 94)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, f"Dataset: {topic}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_text_color(163, 163, 163)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Rows: {len(dps)}   Store: {store_type}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # header
    col_w = [8, 55, 25, 20, 40, 35]
    headers = ["#", "Label", "Value", "Unit", "Confidence", "Source"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(30, 30, 30)
    pdf.set_text_color(204, 204, 204)
    for j, h in enumerate(headers):
        pdf.cell(col_w[j], 7, h, border=0, fill=True, align="C" if j == 0 else "L")
    pdf.ln()

    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(229, 229, 229)
    for i_dp, dp in enumerate(dps, 1):
        if pdf.get_y() > 270:
            pdf.add_page()
            pdf.set_fill_color(13, 13, 13)
            pdf.rect(0, 0, 210, 297, "F")
            pdf.set_text_color(229, 229, 229)
            pdf.set_font("Helvetica", "", 7)
        src_text = ", ".join(dp.get("sources", [])[:1]) if dp.get("sources") else "-"
        if len(src_text) > 32:
            src_text = src_text[:30] + ".."
        unit_str = dp.get("unit", "") or "-"
        conf = (dp.get("confidence") or "medium").title()
        vals = [str(i_dp), str(dp.get("label", "")), str(dp.get("value", "")), unit_str, conf, src_text]
        for j, v in enumerate(vals):
            # sanitize for latin-1 Helvetica
            try:
                v.encode("latin-1")
            except UnicodeEncodeError:
                v = v.encode("latin-1", errors="replace").decode("latin-1")
            pdf.cell(col_w[j], 6, v, border=0, align="C" if j == 0 else "L")
        pdf.ln()

    udir = _uploads_dir()
    base = filename or f"{_slugify(topic)}_dataset"
    base = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    file_id = f"{uuid.uuid4().hex[:12]}_{base}"
    path = udir / file_id
    pdf.output(str(path))
    url = f"/uploads/{file_id}"
    return json.dumps({
        "message": f"Exported **{len(dps)}** rows from '{topic}' ({store_type}) to PDF (`{file_id}`).",
        "pdf_path": str(path),
        "artifact": {"url": url, "title": base},
        "files": [{"format": "pdf", "file_id": file_id, "name": base, "url": url, "path": str(path)}],
    })


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
