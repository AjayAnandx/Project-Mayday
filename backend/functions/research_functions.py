import json

from backend.core.research_store import get_research_store
from backend.core.report_generator import (
    generate_report as _generate_report,
    generate_chart as _generate_chart,
    generate_combined_report as _generate_combined_report,
)


def add_research_note(topic: str, content: str, filename: str = "", file_name: str = "", force: bool = False) -> str:
    if not filename and file_name:
        filename = file_name
    if not filename:
        filename = "notes.md"
    store = get_research_store()
    result = store.add_research_note(topic, filename, content, force=force)
    if "error" in result:
        return f"Error: {result['error']}"
    return (
        f"Research note saved to **{result['filename']}** for '{topic}' "
        f"({result['size']} chars). Path: `{result['path']}`"
    )


def list_research_notes(topic: str) -> str:
    store = get_research_store()
    notes = store.list_research_notes(topic)
    if not notes:
        return f"No research notes found for '{topic}'."
    lines = [f"Research notes for '{topic}' ({len(notes)}):"]
    for n in notes:
        lines.append(f"  - **{n['filename']}** ({n['size']} chars, updated {n['updated_at'][:16]})")
    return "\n".join(lines)


def promote_research_to_project(topic: str, name: str | None = None) -> str:
    store = get_research_store()
    result = store.promote_to_project(topic, name)
    if "error" in result:
        return f"Error: {result['error']}"
    copied = result.get("copied", {})
    return (
        f"Promoted research **'{topic}'** to project **'{result['project']}'** "
        f"(id: {result['project_id']}). "
        f"Copied {len(copied.get('notes', []))} notes and {len(copied.get('outputs', []))} outputs "
        f"to `{result['folder']}`. Research record archived as completed with a `promoted_to` "
        f"link in the knowledge graph. Use `resume_project(name=\"{result['project']}\")` to work on it."
    )


def search_research(query: str) -> str:
    from backend.core.research_index import get_research_index
    results = get_research_index().search(query, limit=10)
    if not results:
        return f"No research found for: {query}"
    lines = [f"Research matches for '{query}' ({len(results)}):"]
    for r in results:
        kind = r["kind"]
        label = r["topic"] if kind == "topic" else f"{r['topic']} / {r.get('filename', '')}"
        lines.append(f"  - [{kind}] {label}")
        if r.get("snippet"):
            lines.append(f"    {r['snippet'][:150]}")
    return "\n".join(lines)


def create_research(topic: str, type: str = "market", depth: int = 2, questions: list[str] | None = None) -> str:
    store = get_research_store()
    result = store.create_research(topic, type, depth, questions)
    if "error" in result:
        return f"Error: {result['error']}"
    tasks_summary = ", ".join(f"'{t['title']}'" for t in result.get("tasks", []))
    return (
        f"Created research project **'{result['topic']}'** (type: {result['type']}, depth: {result['depth']}). "
        f"Auto-created {result.get('task_count', 0)} tasks: {tasks_summary}. "
        f"Resume with `resume_research(topic=\"{result['topic']}\")`."
    )


def resume_research(topic: str) -> str:
    store = get_research_store()
    project = store.resume_research(topic)
    if not project:
        existing = store.list_projects()
        topics = [p["topic"] for p in existing]
        if topics:
            return f"Research '{topic}' not found. Available projects: {', '.join(topics)}"
        return f"Research '{topic}' not found. No research projects exist yet."
    dp_count = len(project.get("data_points", []))
    ent_count = len(project.get("entities", []))
    fin_count = len(project.get("findings", []))
    tasks = project.get("tasks", [])
    task_summary = ", ".join(f"{t['title']} ({t['status']})" for t in tasks)
    summary = project.get("summary", "")
    lines = [
        f"**Research: {project['topic']}** ({project['type']}, status: {project['status']})",
        f"Data points: {dp_count}, Entities: {ent_count}, Findings: {fin_count}",
        f"Tasks: {task_summary}",
    ]
    if summary:
        lines.append(f"Summary: {summary[:300]}")
    if project.get("research_questions"):
        lines.append("Questions: " + "; ".join(project["research_questions"]))
    if dp_count > 0:
        lines.append("Data Points:")
        for dp in project["data_points"]:
            unit_str = f" {dp.get('unit', '')}" if dp.get('unit') else ""
            sources_str = f" [src: {', '.join(dp['sources'][:2])}]" if dp.get('sources') else ""
            lines.append(f"  - {dp['label']}: {dp['value']}{unit_str} ({dp.get('confidence', 'medium')}){sources_str}")
    if ent_count > 0:
        lines.append("Entities:")
        for ent in project["entities"]:
            lines.append(f"  - {ent['name']} ({ent.get('type', 'unknown')}, relevance: {ent.get('relevance', 0.5):.2f})")
    if fin_count > 0:
        lines.append("Findings:")
        for fin in project["findings"]:
            lines.append(f"  - {fin['content'][:200]}")
    return "\n".join(lines)


def list_research(status: str | None = None) -> str:
    store = get_research_store()
    projects = store.list_projects(status)
    if not projects:
        if status:
            return f"No research projects with status '{status}'."
        return "No research projects yet."
    lines = [f"Research projects ({len(projects)} total):"]
    for p in projects:
        lines.append(
            f"  - **{p['topic']}** ({p['type']}, {p['status']}) "
            f"— {p['data_point_count']} dp, {p['entity_count']} ent, {p['finding_count']} fin, "
            f"{p['task_count']} tasks [updated {p['updated_at'][:10]}]"
        )
    return "\n".join(lines)


def update_research_status(topic: str, status: str) -> str:
    store = get_research_store()
    result = store.update_status(topic, status)
    if result is None:
        return f"Research '{topic}' not found."
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Research '{topic}' status updated to **{status}**."


def add_data_point(topic: str, label: str, value: str, unit: str | None = None,
                   confidence: str | None = None, sources: list[str] | None = None) -> str:
    store = get_research_store()
    result = store.add_data_point(topic, label, value, unit, confidence, sources)
    if "error" in result:
        return f"Error: {result['error']}"
    unit_str = f" {unit}" if unit else ""
    return (
        f"Data point added (**{result['id']}**): '{label}' = {value}{unit_str} "
        f"(confidence: {result.get('confidence', 'medium')})"
    )


def add_entity(topic: str, name: str, type: str = "company",
               description: str | None = None, relevance: float | None = None,
               sources: list[str] | None = None) -> str:
    store = get_research_store()
    result = store.add_entity(topic, name, type, description, relevance, sources)
    if "error" in result:
        return f"Error: {result['error']}"
    parts = [f"Entity added (**{result['id']}**): '{name}' ({type})"]
    if description:
        parts.append(f" — {description[:100]}")
    return "".join(parts)


def add_finding(topic: str, content: str, confidence: str | None = None,
                sources: list[str] | None = None) -> str:
    store = get_research_store()
    result = store.add_finding(topic, content, confidence, sources)
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Finding added (**{result['id']}**). Confidence: {result.get('confidence', 'medium')}"


def list_research_outputs(topic: str) -> str:
    store = get_research_store()
    outputs = store.list_outputs(topic)
    if isinstance(outputs, dict) and "error" in outputs:
        return f"Error: {outputs['error']}"
    if not outputs:
        return f"No charts generated yet for '{topic}'. Call generate_chart(topic) first."

    lines = [f"Charts for '{topic}' ({len(outputs)}):"]
    for o in outputs:
        lines.append(
            f"  - {o['chart_type']} chart ({o['data_points']} points) — {o['relative_url']} "
            f"[generated {o['created_at']}]"
        )

    newest = outputs[0]
    return json.dumps({
        "message": "\n".join(lines),
        "artifact": {
            "url": newest["relative_url"],
            "title": f"{topic} — {newest['chart_type']} chart",
        },
        "charts": outputs,
    })


def generate_report(topic: str, format: str = "md") -> str:
    result = _generate_report(topic, format)
    if "error" in result:
        return f"Error: {result['error']}"
    lines = [f"Report generated in **{result['format']}** format."]
    lines.append(f"Path: `{result['path']}`")
    if result.get("content_length"):
        lines.append(f"Content: ~{result['content_length']} characters")
    if result.get("pdf_path"):
        lines.append(f"PDF: `{result['pdf_path']}` ({result.get('pdf_size', 0)} bytes)")
    if result.get("pdf_warning"):
        lines.append(f"Note: {result['pdf_warning']}")
    lines.append(f"Data points: {result.get('data_point_count', 0)}, Entities: {result.get('entity_count', 0)}, Findings: {result.get('finding_count', 0)}")
    return "\n".join(lines)


def generate_combined_report(topics: list[str] | None = None, title: str = "Combined Research Report", format: str = "md") -> str:
    result = _generate_combined_report(topics, title, format)
    if "error" in result:
        return f"Error: {result['error']}"
    lines = [f"**Combined research report** generated — {result['topic_count']} topics."]
    lines.append(f"Format: {result['format']}")
    lines.append(f"Path: `{result['path']}`")
    if result.get("content_length"):
        lines.append(f"Content: ~{result['content_length']} characters")
    if result.get("pdf_path"):
        lines.append(f"PDF: `{result['pdf_path']}` ({result.get('pdf_size', 0)} bytes)")
    lines.append(f"Data points: {result.get('data_point_count', 0)}, Entities: {result.get('entity_count', 0)}, Findings: {result.get('finding_count', 0)}")
    return "\n".join(lines)


def generate_chart(topic: str, chart_type: str = "auto", metric: str | None = None) -> str:
    result = _generate_chart(topic, chart_type, metric)
    if "error" in result:
        return f"Error: {result['error']}"
    url = result.get("relative_url", "")
    return json.dumps({
        "message": f"**{result['chart_type'].title()} chart** generated from {result['data_points']} data points.",
        "artifact": {
            "url": url,
            "title": f"{topic} — {chart_type.title()} Chart",
        },
    })
