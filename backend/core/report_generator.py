import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from backend.core.research_store import get_research_store

logger = logging.getLogger(__name__)

CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"
MAX_CHART_JSON_SIZE = 500 * 1024


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _fmt_date(iso_str: str) -> str:
    if not iso_str:
        return ""
    return iso_str[:10]


def _source_badge(sources: list[str]) -> str:
    if not sources:
        return "*No source cited*"
    trusted = any("trusted" in s.lower() for s in sources)
    badge = "✓ Verified Source" if trusted else "Source"
    urls = ", ".join(sources[:3])
    if len(sources) > 3:
        urls += f" (+{len(sources)-3} more)"
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
                if s not in seen:
                    seen.add(s)
                    sources.append(s)
        for ent in p.get("entities", []):
            for s in ent.get("sources", []):
                if s not in seen:
                    seen.add(s)
                    sources.append(s)
        for fin in p.get("findings", []):
            for s in fin.get("sources", []):
                if s not in seen:
                    seen.add(s)
                    sources.append(s)
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

    slug = "combined-research-report"
    outputs_dir = store._outputs_dir / slug / "outputs"
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

def _data_points_to_chart_data(data_points: list[dict]) -> dict:
    labels = []
    values = []
    for dp in data_points:
        raw = dp.get("value", "0")
        numeric = _extract_numeric(raw)
        if numeric is not None:
            labels.append(dp.get("label", ""))
            values.append(numeric)
    return {"labels": labels, "values": values}


def _extract_numeric(value: str) -> float | None:
    cleaned = value.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
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


def generate_chart(topic: str, chart_type: str = "bar", metric: str | None = None) -> dict:
    valid_types = ("bar", "pie", "line")
    if chart_type not in valid_types:
        return {"error": f"Invalid chart_type '{chart_type}'. Must be one of: {', '.join(valid_types)}"}

    store = get_research_store()
    project = store._get_by_topic(topic)
    if not project:
        return {"error": f"Research '{topic}' not found"}

    data_points = project.get("data_points", [])
    if not data_points:
        return {"error": "No data points collected yet — collect data first with add_data_point"}

    chart_data = _data_points_to_chart_data(data_points)
    if not chart_data["values"]:
        return {"error": "No numeric data points available for charting"}

    if chart_type == "pie" and len(chart_data["values"]) > 20:
        chart_type = "bar"

    colors = _chart_colors(len(chart_data["labels"]))

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
            }],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "title": {
                    "display": True,
                    "text": f"{project['topic']} — {chart_type.title()} Chart",
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
        },
    }

    outputs_dir = store.get_outputs_dir(project)
    outputs_dir.mkdir(parents=True, exist_ok=True)

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

    relative_path = str(Path(".") / project["slug"] / "outputs" / chart_dir.name / "index.html").replace("\\", "/")

    return {
        "chart_type": chart_type,
        "data_points": len(chart_data["labels"]),
        "json_path": str(json_path),
        "html_path": str(html_path),
        "chart_dir": str(chart_dir),
        "relative_url": f"/research/{relative_path}",
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
