import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from backend.core.research_store import get_research_store

_CHART_SERIES_SEP = " | "

logger = logging.getLogger(__name__)

CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"
MAX_CHART_JSON_SIZE = 500 * 1024


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _fmt_date(iso_str: str) -> str:
    if not iso_str:
        return ""
    return iso_str[:10]


def _normalize_source_for_display(s):
    if isinstance(s, dict):
        url = s.get("url", "") or s.get("doi", "") or ""
        # prefer doi link if url missing
        if not url and s.get("doi"):
            url = f"https://doi.org/{s['doi']}"
        return url or s.get("title", "") or str(s)
    return str(s)

def _is_trusted_source(s) -> bool:
    if isinstance(s, dict):
        # dict source trusted if score>0.7 or citationCount>10 or explicit trusted tag
        if float(s.get("score", 0) or 0) > 0.7:
            return True
        try:
            if s.get("citationCount") is not None and int(s.get("citationCount") or 0) > 10:
                return True
        except Exception:
            pass
        url = (s.get("url", "") or "").lower()
        if "trusted" in url or "trusted" in (s.get("title", "") or "").lower():
            return True
        return False
    return "trusted" in str(s).lower()

def _source_badge(sources: list) -> str:
    if not sources:
        return "*No source cited*"
    trusted = any(_is_trusted_source(s) for s in sources)
    badge = "✓ Verified Source" if trusted else "Source"
    display = [_normalize_source_for_display(s) for s in sources[:3]]
    urls = ", ".join(display)
    if len(sources) > 3:
        urls += f" (+{len(sources)-3} more)"
    # pick first url for link target
    first_url = display[0] if display and display[0].startswith("http") else urls.split(",")[0].strip()
    if first_url.startswith("http"):
        return f"[{badge}]({first_url}) {urls}"
    return f"[{badge}]({urls})"


def _confidence_label(confidence: str | None) -> str:
    if not confidence:
        return "Medium"
    c = confidence.lower()
    if c == "high":
        return "High — well-sourced"
    if c == "medium":
        return "Medium — moderately supported"
    if c == "low":
        return "Low — limited evidence"
    return confidence.title()


def _build_section_md(project: dict, index: int) -> list[str]:
    lines = []
    lines.append(f"## {index}. {project['topic']}")
    lines.append("")
    lines.append(f"**Type:** {project['type']} | **Status:** {project['status']} | **Last updated:** {_fmt_date(project.get('updated_at', ''))}")
    lines.append("")

    if project.get("summary"):
        lines.append("### Executive Summary")
        lines.append("")
        lines.append(project["summary"])
        lines.append("")

    if project.get("research_questions"):
        lines.append("### Research Questions")
        lines.append("")
        for q in project["research_questions"]:
            lines.append(f"- {q}")
        lines.append("")

    dps = project.get("data_points", [])
    if dps:
        lines.append("### Key Data Points")
        lines.append("")
        lines.append("| # | Label | Value | Unit | Confidence | Source |")
        lines.append("|---|-------|-------|------|------------|--------|")
        for i, dp in enumerate(dps, 1):
            unit_str = dp.get("unit", "") or ""
            conf = _confidence_label(dp.get("confidence", "medium"))
            src = _source_badge(dp.get("sources", []))
            lines.append(f"| {i} | {dp['label']} | {dp['value']} | {unit_str} | {conf} | {src} |")
        lines.append("")

    entities = project.get("entities", [])
    if entities:
        lines.append("### Key Entities")
        lines.append("")
        for ent in entities:
            rel_str = f" (relevance: {ent.get('relevance', 0.5):.2f})" if ent.get('relevance') else ""
            src = _source_badge(ent.get("sources", []))
            lines.append(f"- **{ent['name']}** — *{ent.get('type', 'unknown')}*{rel_str}")
            if ent.get("description"):
                lines.append(f"  > {ent['description']}")
            lines.append(f"  {src}")
        lines.append("")

    findings = project.get("findings", [])
    if findings:
        lines.append("### Key Findings")
        lines.append("")
        for i, fin in enumerate(findings, 1):
            conf = _confidence_label(fin.get("confidence", "medium"))
            src = _source_badge(fin.get("sources", []))
            lines.append(f"{i}. **{fin['content']}** — {conf}")
            lines.append(f"   {src}")
        lines.append("")

    lines.append("---")
    lines.append("")
    return lines


def _collect_all_sources(projects: list[dict]) -> list[str]:
    seen = set()
    sources = []
    for p in projects:
        for dp in p.get("data_points", []):
            for s in dp.get("sources", []):
                key = s.get("url", str(s)) if isinstance(s, dict) else str(s)
                if key not in seen:
                    seen.add(key)
                    sources.append(_normalize_source_for_display(s) if isinstance(s, dict) else str(s))
        for ent in p.get("entities", []):
            for s in ent.get("sources", []):
                key = s.get("url", str(s)) if isinstance(s, dict) else str(s)
                if key not in seen:
                    seen.add(key)
                    sources.append(_normalize_source_for_display(s) if isinstance(s, dict) else str(s))
        for fin in p.get("findings", []):
            for s in fin.get("sources", []):
                key = s.get("url", str(s)) if isinstance(s, dict) else str(s)
                if key not in seen:
                    seen.add(key)
                    sources.append(_normalize_source_for_display(s) if isinstance(s, dict) else str(s))
    return sources


def build_combined_md(projects: list[dict], title: str = "Combined Research Report") -> str:
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Generated:** {_utcnow()}")
    lines.append(f"**Topics covered:** {len(projects)}")
    lines.append("")

    if projects:
        lines.append("## Table of Contents")
        lines.append("")
        for i, p in enumerate(projects, 1):
            toc_num = str(i)
            toc_link = p['topic'].lower().replace(' ', '-').replace('.', '').replace(',', '')
            lines.append(f"- [{i}. {p['topic']}](#{toc_num}-{toc_link})")
        lines.append("")

    for i, p in enumerate(projects, 1):
        lines.extend(_build_section_md(p, i))

    all_sources = _collect_all_sources(projects)
    if all_sources:
        lines.append("## Appendix: All Sources")
        lines.append("")
        for i, s in enumerate(all_sources, 1):
            lines.append(f"{i}. {s}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Report generated by Mayday Research — {sum(len(p.get('data_points', [])) for p in projects)} data points, "
                 f"{sum(len(p.get('entities', [])) for p in projects)} entities, "
                 f"{sum(len(p.get('findings', [])) for p in projects)} findings*")
    return "\n".join(lines)


def generate_combined_report(topics: list[str] | None = None, title: str = "Combined Research Report", fmt: str = "md") -> dict:
    store = get_research_store()
    if topics:
        projects = []
        for t in topics:
            p = store._get_by_topic(t)
            if p:
                projects.append(p)
            else:
                return {"error": f"Research '{t}' not found"}
        if not projects:
            return {"error": "No valid research topics found"}
    else:
        all_projects = store.list_projects()
        projects = [store._get_by_topic(p["topic"]) for p in all_projects if p["status"] in ("active", "completed")]
        projects = [p for p in projects if p is not None]
        if not projects:
            return {"error": "No research projects found"}

    slug = f"combined-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    outputs_dir = store._outputs_dir / slug / "artifacts" / "reports"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    md_content = build_combined_md(projects, title)

    md_path = outputs_dir / "report.md"
    md_path.write_text(md_content, encoding="utf-8")

    result = {
        "format": "md",
        "path": str(md_path),
        "content_length": len(md_content),
        "topic_count": len(projects),
        "data_point_count": sum(len(p.get("data_points", [])) for p in projects),
        "entity_count": sum(len(p.get("entities", [])) for p in projects),
        "finding_count": sum(len(p.get("findings", [])) for p in projects),
    }

    if fmt == "pdf":
        pdf_result = _generate_pdf(projects, title, outputs_dir)
        result.update(pdf_result)

    return result


def generate_report(topic: str, fmt: str = "md") -> dict:
    store = get_research_store()
    project = store._get_by_topic(topic)
    if not project:
        return {"error": f"Research '{topic}' not found"}

    # Prefer new artifacts layout, fallback to legacy handled by store
    try:
        outputs_dir = store.get_reports_dir(project)
    except Exception:
        outputs_dir = store.get_outputs_dir(project)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    md_content = build_combined_md([project], f"Research Report: {project['topic']}")

    md_path = outputs_dir / "report.md"
    md_path.write_text(md_content, encoding="utf-8")

    store.add_generated_output(project, str(md_path), "md")

    result = {
        "format": "md",
        "path": str(md_path),
        "content_length": len(md_content),
        "topic_count": 1,
        "data_point_count": len(project.get("data_points", [])),
        "entity_count": len(project.get("entities", [])),
        "finding_count": len(project.get("findings", [])),
    }

    if fmt == "pdf":
        pdf_result = _generate_pdf([project], f"Research Report: {project['topic']}", outputs_dir)
        result.update(pdf_result)

    return result


def _generate_pdf(projects: list[dict], title: str, outputs_dir: Path) -> dict:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    _pdf_cover(pdf, projects, title)
    _pdf_toc(pdf, projects)

    for i, p in enumerate(projects, 1):
        _pdf_section(pdf, p, i)

    _pdf_sources(pdf, projects)

    pdf_path = outputs_dir / "report.pdf"
    pdf.output(str(pdf_path))
    logger.info("PDF generated: %s", pdf_path)

    result = {}
    if pdf_path.exists():
        result["pdf_path"] = str(pdf_path)
        result["pdf_size"] = pdf_path.stat().st_size
        if len(projects) == 1:
            store = get_research_store()
            project = projects[0]
            store.add_generated_output(project, str(pdf_path), "pdf")
    return result


def _pdf_cover(pdf: FPDF, projects: list[dict], title: str):
    pdf.add_page()
    pdf.set_fill_color(13, 13, 13)
    pdf.rect(0, 0, 210, 297, "F")

    pdf.set_text_color(34, 197, 94)
    pdf.set_font("Helvetica", "B", 28)
    pdf.ln(50)
    pdf.cell(0, 20, "Research Report", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_text_color(229, 229, 229)
    pdf.set_font("Helvetica", "", 14)
    pdf.ln(5)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(10)
    pdf.set_text_color(163, 163, 163)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 8, f"Generated: {_utcnow()[:10]}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 8, f"Topics: {len(projects)}", new_x="LMARGIN", new_y="NEXT", align="C")
    dp_total = sum(len(p.get("data_points", [])) for p in projects)
    ent_total = sum(len(p.get("entities", [])) for p in projects)
    fin_total = sum(len(p.get("findings", [])) for p in projects)
    pdf.cell(0, 8, f"Data points: {dp_total} | Entities: {ent_total} | Findings: {fin_total}", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.ln(15)
    pdf.set_text_color(115, 115, 115)
    pdf.set_font("Helvetica", "", 9)
    for p in projects:
        pdf.cell(0, 6, f"  - {p['topic']} ({p['type']})", new_x="LMARGIN", new_y="NEXT", align="C")


def _pdf_toc(pdf: FPDF, projects: list[dict]):
    pdf.add_page()
    pdf.set_fill_color(13, 13, 13)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_text_color(34, 197, 94)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 15, "Table of Contents", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_text_color(229, 229, 229)
    pdf.set_font("Helvetica", "", 11)
    for i, p in enumerate(projects, 1):
        pdf.cell(0, 8, f"{i}. {p['topic']} ({p['type']})", new_x="LMARGIN", new_y="NEXT")


def _pdf_section(pdf: FPDF, project: dict, index: int):
    pdf.add_page()
    pdf.set_fill_color(13, 13, 13)
    pdf.rect(0, 0, 210, 297, "F")

    pdf.set_text_color(34, 197, 94)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 15, f"{index}. {project['topic']}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_text_color(163, 163, 163)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Type: {project['type']} | Status: {project['status']} | Updated: {_fmt_date(project.get('updated_at', ''))}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_text_color(229, 229, 229)
    pdf.set_font("Helvetica", "", 10)

    if project.get("summary"):
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(34, 197, 94)
        pdf.cell(0, 8, "Executive Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(229, 229, 229)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, project["summary"])
        pdf.ln(3)

    if project.get("research_questions"):
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(34, 197, 94)
        pdf.cell(0, 8, "Research Questions", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(229, 229, 229)
        pdf.set_font("Helvetica", "", 10)
        for q in project["research_questions"]:
            pdf.cell(0, 6, f"  - {q}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    dps = project.get("data_points", [])
    if dps:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(34, 197, 94)
        pdf.cell(0, 8, "Key Data Points", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

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
            y_before = pdf.get_y()
            if y_before > 270:
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

            vals = [str(i_dp), dp["label"], dp["value"], unit_str, conf, src_text]
            for j, v in enumerate(vals):
                pdf.cell(col_w[j], 6, v, border=0, align="C" if j == 0 else "L")
            pdf.ln()
        pdf.ln(3)

    entities = project.get("entities", [])
    if entities:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(34, 197, 94)
        pdf.cell(0, 8, "Key Entities", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(229, 229, 229)
        pdf.set_font("Helvetica", "", 10)
        for ent in entities:
            rel_str = f" (relevance: {ent.get('relevance', 0.5):.2f})" if ent.get('relevance') else ""
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, f"{ent['name']} - {ent.get('type', 'unknown')}{rel_str}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            if ent.get("description"):
                pdf.multi_cell(0, 5, ent["description"])
            if ent.get("sources"):
                src_text = "; ".join(ent["sources"])
                pdf.set_text_color(115, 115, 115)
                pdf.cell(0, 5, f"Source: {src_text[:100]}", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(229, 229, 229)
            pdf.ln(2)

    findings = project.get("findings", [])
    if findings:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(34, 197, 94)
        pdf.cell(0, 8, "Key Findings", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(229, 229, 229)
        pdf.set_font("Helvetica", "", 10)
        for i_f, fin in enumerate(findings, 1):
            conf = (fin.get("confidence") or "medium").title()
            y_start = pdf.get_y()
            if y_start > 260:
                pdf.add_page()
                pdf.set_fill_color(13, 13, 13)
                pdf.rect(0, 0, 210, 297, "F")

            pdf.multi_cell(0, 6, f"{i_f}. {fin['content']} [{conf}]")
            if fin.get("sources"):
                pdf.set_text_color(115, 115, 115)
                src_text = "; ".join(fin["sources"][:2])
                if len(fin["sources"]) > 2:
                    src_text += f" (+{len(fin['sources'])-2} more)"
                pdf.set_font("Helvetica", "", 7)
                pdf.cell(0, 5, f"Source: {src_text}", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(229, 229, 229)
                pdf.set_font("Helvetica", "", 10)
            pdf.ln(2)
    pdf.ln(5)


def _pdf_sources(pdf: FPDF, projects: list[dict]):
    all_sources = _collect_all_sources(projects)
    if not all_sources:
        return
    pdf.add_page()
    pdf.set_fill_color(13, 13, 13)
    pdf.rect(0, 0, 210, 297, "F")
    pdf.set_text_color(34, 197, 94)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 15, "Appendix: All Sources", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(229, 229, 229)
    pdf.set_font("Helvetica", "", 9)
    for i, s in enumerate(all_sources, 1):
        y = pdf.get_y()
        if y > 270:
            pdf.add_page()
            pdf.set_fill_color(13, 13, 13)
            pdf.rect(0, 0, 210, 297, "F")
            pdf.set_text_color(229, 229, 229)
        pdf.cell(0, 5, f"{i}. {s}", new_x="LMARGIN", new_y="NEXT")


# ── Chart generation ──────────────────────────────────────────────

_YEAR_RE = re.compile(r"^\d{4}$")
_DATE_RE = re.compile(r"^(Q[1-4]\s?\d{4}|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s/-]\d{4}|\d{4}[-/]\d{1,2}|\d{1,2}[-/]\d{4})$", re.I)


def _split_series_label(label) -> tuple[str | None, str | None]:
    """Split a label like 'ML Engineer | 2020' into (series, point)."""
    if not isinstance(label, str):
        label = str(label)
    if _CHART_SERIES_SEP in label:
        series, point = label.split(_CHART_SERIES_SEP, 1)
        return series.strip(), point.strip()
    return None, None


def _is_time_label(label) -> bool:
    if not isinstance(label, str):
        label = str(label)
    if _YEAR_RE.match(label):
        return True
    if _DATE_RE.match(label):
        return True
    return False


def suggest_chart_type(data_points: list[dict], context: str = "") -> str:
    """Heuristic auto-chart-type selection (line / bar / pie).

    Rules:
      - Time series + multi-series  -> line (growth comparison)
      - Time series + single series -> line
      - Context keywords (growth/trend/over time) -> prefer line
      - Parts-of-a-whole (values sum to ~100 with '%' unit) -> pie
      - Otherwise categorical -> bar
    """
    if not data_points:
        return "bar"
    ctx = (context or "").lower()
    if any(k in ctx for k in ("growth", "trend", "over time", "timeline", "progress")):
        return "line"

    labels = [str(dp.get("label", "")).strip() or "" for dp in data_points if dp.get("label")]
    if not labels:
        return "bar"

    time_count = sum(1 for lb in labels if _is_time_label(lb) or _split_series_label(lb)[1] and _is_time_label(_split_series_label(lb)[1]))
    multi_series = any(_split_series_label(lb)[0] for lb in labels)

    if time_count >= max(1, len(labels) * 0.5):
        return "line"
    if multi_series:
        return "bar"

    units = {str(dp.get("unit", "")) for dp in data_points if dp.get("unit")}
    if units == {"%"} or units == {"percent", "percentage"}:
        numeric = [_extract_numeric(dp.get("value", "0")) for dp in data_points]
        numeric = [n for n in numeric if n is not None]
        if numeric and abs(sum(numeric) - 100) < 2:
            return "pie"

    return "bar"


def _data_points_to_chart_data(data_points: list[dict]) -> dict:
    labels = []
    values = []
    for dp in data_points:
        raw = dp.get("value", "0")
        numeric = _extract_numeric(raw)
        if numeric is not None:
            labels.append(str(dp.get("label", "")))
            values.append(numeric)
    return {"labels": labels, "values": values}


def _split_into_series(chart_data: dict) -> dict | None:
    """If labels carry 'series | point' markers, group into per-series datasets."""
    groups: dict[str, dict] = {}
    for label, value in zip(chart_data["labels"], chart_data["values"]):
        series, point = _split_series_label(label)
        if series is None or point is None:
            return None
        groups.setdefault(series, {"labels": [], "values": []})
        groups[series]["labels"].append(point)
        groups[series]["values"].append(value)
    if not groups:
        return None
    return groups


def _extract_numeric(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    try:
        cleaned = str(value).replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
    except Exception:
        return None
    if not cleaned:
        return None
    multipliers = {"B": 1e9, "M": 1e6, "K": 1e3, "%": 1}
    suffix = cleaned[-1].upper() if cleaned else ""
    if suffix in multipliers:
        try:
            base = float(cleaned[:-1].strip())
            return base * multipliers[suffix]
        except ValueError:
            pass
    try:
        return float(cleaned)
    except ValueError:
        return None


def _chart_colors(count: int) -> list[str]:
    palette = [
        "#22c55e", "#3b82f6", "#eab308", "#ef4444", "#a855f7",
        "#f97316", "#06b6d4", "#ec4899", "#84cc16", "#14b8a6",
    ]
    return [palette[i % len(palette)] for i in range(count)]


def _build_chart_json(chart_type: str, chart_data: dict, title: str, metric: str | None = None) -> dict:
    colors = _chart_colors(len(chart_data["labels"]))

    series = _split_into_series(chart_data)
    if series:
        datasets = []
        series_colors = _chart_colors(len(series))
        x_points: list[str] = []
        seen_points = set()
        for sdata in series.values():
            for lb in sdata["labels"]:
                if lb not in seen_points:
                    seen_points.add(lb)
                    x_points.append(lb)
        numeric_points = [_extract_numeric(p) for p in x_points]
        if all(n is not None for n in numeric_points):
            x_points = [p for _, p in sorted(zip(numeric_points, x_points))]  # type: ignore[arg-type]
        for i, (name, sdata) in enumerate(series.items()):
            by_point = dict(zip(sdata["labels"], sdata["values"]))
            aligned = [by_point.get(p) for p in x_points]
            datasets.append({
                "label": name,
                "data": aligned,
                "backgroundColor": series_colors[i],
                "borderColor": series_colors[i],
                "borderWidth": 1,
                "tension": 0.2,
            })
        chart_json = {
            "type": chart_type,
            "data": {
                "labels": x_points,
                "datasets": datasets,
            },
        }
    else:
        chart_json = {
            "type": chart_type,
            "data": {
                "labels": chart_data["labels"],
                "datasets": [{
                    "label": metric or "Value",
                    "data": chart_data["values"],
                    "backgroundColor": colors,
                    "borderColor": colors,
                    "borderWidth": 1,
                    "tension": 0.2,
                }],
            },
        }

    chart_json["options"] = {
        "responsive": True,
        "maintainAspectRatio": False,
        "plugins": {
            "title": {
                "display": True,
                "text": title,
                "color": "#e5e5e5",
                "font": {"size": 16},
            },
            "legend": {
                "labels": {"color": "#a3a3a3"},
            },
        },
        "scales": {} if chart_type == "pie" else {
            "x": {"ticks": {"color": "#a3a3a3"}, "grid": {"color": "#303030"}},
            "y": {"ticks": {"color": "#a3a3a3"}, "grid": {"color": "#303030"}},
        },
    }
    return chart_json


def generate_chart(topic: str, chart_type: str = "auto", metric: str | None = None,
                   title_override: str | None = None) -> dict:
    store = get_research_store()
    project = store._get_by_topic(topic)
    if not project:
        return {"error": f"Research '{topic}' not found"}

    data_points = project.get("data_points", [])
    if not data_points:
        return {"error": "No data points collected yet — collect data first with add_data_point or batch_add_data_points"}

    if chart_type == "auto" or chart_type not in ("bar", "pie", "line"):
        chart_type = suggest_chart_type(data_points, metric or "")
        if _split_into_series(_data_points_to_chart_data(data_points)):
            chart_type = "line"

    chart_data = _data_points_to_chart_data(data_points)
    if not chart_data["values"]:
        return {"error": "No numeric data points available for charting"}

    if chart_type == "pie" and len(chart_data["values"]) > 20:
        chart_type = "bar"

    try:
        outputs_dir = store.get_figures_dir(project)
    except Exception:
        outputs_dir = store.get_outputs_dir(project)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    title = title_override or f"{project['topic']} — {chart_type.title()} Chart"
    chart_json = _build_chart_json(chart_type, chart_data, title, metric)

    chart_json_bytes = json.dumps(chart_json, indent=2).encode("utf-8")
    if len(chart_json_bytes) > MAX_CHART_JSON_SIZE:
        return {"error": f"Chart data too large ({len(chart_json_bytes)} bytes). Max 500KB."}

    chart_dir = outputs_dir / f"chart_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    chart_dir.mkdir(parents=True, exist_ok=True)

    json_path = chart_dir / "chart.json"
    json_path.write_bytes(chart_json_bytes)

    html_path = chart_dir / "index.html"
    html_content = _build_chart_html(chart_type, chart_json)
    html_path.write_text(html_content, encoding="utf-8")

    store.add_generated_output(project, str(json_path), "chart_json", chart_type)

    # relative url under artifacts/figures if new layout
    if "artifacts" in str(outputs_dir).replace("\\", "/"):
        relative_path = str(Path(project["slug"]) / "artifacts" / "figures" / chart_dir.name / "index.html").replace("\\", "/")
    else:
        relative_path = str(Path(project["slug"]) / "outputs" / chart_dir.name / "index.html").replace("\\", "/")

    return {
        "chart_type": chart_type,
        "data_points": len(chart_data["labels"]),
        "json_path": str(json_path),
        "html_path": str(html_path),
        "chart_dir": str(chart_dir),
        "relative_url": f"/research/{relative_path}",
    }


def generate_project_chart(project_id: str, chart_type: str = "auto", metric: str | None = None) -> dict:
    """Generate a Chart.js chart from a project's data_points (outputs/ under project folder)."""
    from backend.core.project_store import get_project_store
    store = get_project_store()
    project = store.get_project(project_id)
    if not project:
        return {"error": f"Project '{project_id}' not found"}
    if project.get("status") == "scrapped":
        return {"error": f"Project '{project['name']}' is scrapped — cannot chart its data"}

    data_points = project.get("data_points", [])
    if not data_points:
        return {"error": "No data points collected yet for this project — collect data first with add_project_data_point or batch_add_data_points"}

    if chart_type == "auto" or chart_type not in ("bar", "pie", "line"):
        chart_type = suggest_chart_type(data_points, metric or "")
        if _split_into_series(_data_points_to_chart_data(data_points)):
            chart_type = "line"

    chart_data = _data_points_to_chart_data(data_points)
    if not chart_data["values"]:
        return {"error": "No numeric data points available for charting"}

    if chart_type == "pie" and len(chart_data["values"]) > 20:
        chart_type = "bar"

    outputs_dir = store.get_outputs_dir(project)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    chart_json = _build_chart_json(chart_type, chart_data, f"{project['name']} — {chart_type.title()} Chart", metric)

    chart_json_bytes = json.dumps(chart_json, indent=2).encode("utf-8")
    if len(chart_json_bytes) > MAX_CHART_JSON_SIZE:
        return {"error": f"Chart data too large ({len(chart_json_bytes)} bytes). Max 500KB."}

    chart_dir = outputs_dir / f"chart_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    chart_dir.mkdir(parents=True, exist_ok=True)

    json_path = chart_dir / "chart.json"
    json_path.write_bytes(chart_json_bytes)

    html_path = chart_dir / "index.html"
    html_path.write_text(_build_chart_html(chart_type, chart_json), encoding="utf-8")

    store.add_generated_output(project, str(json_path), "chart_json", chart_type)

    relative_path = str(Path(project["folder"]) / "outputs" / chart_dir.name / "index.html").replace("\\", "/")
    return {
        "chart_type": chart_type,
        "data_points": len(chart_data["labels"]),
        "json_path": str(json_path),
        "html_path": str(html_path),
        "chart_dir": str(chart_dir),
        "relative_url": f"/projects/{relative_path}",
    }


def _build_chart_html(chart_type: str, chart_data: dict) -> str:
    chart_json_str = json.dumps(chart_data)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chart — {chart_type.title()}</title>
<script src="{CHART_JS_CDN}"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0d0d0d;
    display: flex; align-items: center; justify-content: center;
    min-height: 100vh; font-family: system-ui, sans-serif;
  }}
  .chart-container {{
    width: 94%; max-width: 900px; height: 520px;
    background: #141414; border-radius: 16px; padding: 24px;
    border: 1px solid #262626;
  }}
  canvas {{ width: 100% !important; height: 100% !important; }}
  .empty {{ color: #737373; text-align: center; padding: 80px 20px; font-size: 18px; }}
</style>
</head>
<body>
<div class="chart-container">
  <canvas id="chart"></canvas>
</div>
<script>
  (function() {{
    var ctx = document.getElementById('chart').getContext('2d');
    var data = {chart_json_str};
    if (!data.data || !data.data.labels || data.data.labels.length === 0) {{
      document.querySelector('.chart-container').innerHTML = '<div class="empty">No data points collected yet</div>';
      return;
    }}
    new Chart(ctx, data);
  }})();
</script>
</body>
</html>"""
