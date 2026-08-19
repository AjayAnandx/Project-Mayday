"""Module A adapter — composes the DSPy-enhanced Markdown report.

This file is deliberately kept OUT of report_generator.py. It reuses
``build_combined_md`` / ``_build_section_md`` verbatim for the template tables
and appendix, and layers synthesized summary / answered-questions / narratives on
top. Every synthesized component passes through the deterministic integrity guard
(metrics.section_faithful); on any failure that component reverts to the template
equivalent. When DSPy is disabled (or the LM fails) the output is byte-for-byte the
existing template report.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.core.report_generator import (
    _build_section_md,
    _collect_all_sources,
    _utcnow,
)
from backend.dspy import get_bridge
from backend.dspy import research_synthesis as syn
from backend.dspy.metrics import section_faithful

logger = logging.getLogger(__name__)


def _synthesize_project(project: dict) -> Optional[dict]:
    """Run the three Module A predictors. Returns None entirely if synthesis is unavailable."""
    summary = syn.synthesize_summary(project)
    answers = syn.synthesize_answers(project)
    narratives: dict[str, str] = {}
    for sec, key in (("entities", "entities"), ("data_points", "data_points"), ("findings", "findings")):
        items = project.get(key) or []
        if items:
            text = syn.synthesize_narrative(project, sec, items)
            if text:
                narratives[sec] = text
    if not (summary or answers or narratives):
        return None
    return {"summary": summary, "answers": answers, "narratives": narratives}


def _format_answers(answers: list[dict], project: dict) -> tuple[list[str], bool]:
    """Format answered questions; returns (lines, ok). ok=False if any answer fails the guard."""
    lines: list[str] = []
    for a in answers:
        text = str(a.get("answer", ""))
        ok, reason = section_faithful(text, project)
        if not ok:
            logger.info("DSPy answers dropped (guard): %s", reason)
            return [], False
        q = a.get("question", "")
        answered = a.get("answered", True)
        conf = a.get("confidence", "")
        mark = "answered" if answered else "gap"
        lines.append(f"- **Q:** {q}")
        lines.append(f"  - **A:** {text}  _(confidence: {conf}, {mark})_")
    return lines, True


def _build_dspy_section(project: dict, idx: int, synthesized: Optional[dict]) -> list[str]:
    """Build one topic section. ``synthesized=None`` → plain template section."""
    if synthesized is None:
        return _build_section_md(project, idx)

    # Template tables portion (summary + questions stripped to avoid duplication).
    stripped = {**project, "summary": "", "research_questions": []}
    template = _build_section_md(stripped, idx)
    header = template[:4]
    body = template[4:]
    # body ends with ["---", ""]; we insert narratives before it.
    if body and body[-1] == "" and body[-2:][0] == "---":
        tail = body[-2:]
        body = body[:-2]
    else:
        tail = ["---", ""]

    top: list[str] = []

    if synthesized.get("summary"):
        ok, reason = section_faithful(synthesized["summary"], project)
        if ok:
            top += ["### Executive Summary", "", synthesized["summary"], ""]
        elif project.get("summary"):
            top += ["### Executive Summary", "", project["summary"], ""]
            logger.info("DSPy summary dropped (guard): %s", reason)
        else:
            logger.info("DSPy summary dropped (guard): %s", reason)

    if synthesized.get("answers"):
        ans_lines, ok = _format_answers(synthesized["answers"], project)
        if ok:
            top += ["### Answered Research Questions", ""] + ans_lines + [""]
        else:
            qlines = ["- " + q for q in (project.get("research_questions") or [])]
            if qlines:
                top += ["### Research Questions", ""] + qlines + [""]

    nar = synthesized.get("narratives") or {}
    for sec in ("entities", "data_points", "findings"):
        text = nar.get(sec)
        if not text:
            continue
        ok, reason = section_faithful(text, project)
        if ok:
            body += [f"### Synthesis: {sec.replace('_', ' ').title()}", "", text, ""]
        else:
            logger.info("DSPy narrative(%s) dropped (guard): %s", sec, reason)

    return header + top + body + tail


def build_dspy_md(
    projects: list[dict],
    title: str = "Combined Research Report",
    synthesized: Any = None,
) -> str:
    """Compose the full DSPy report. ``synthesized`` may be a dict (applied to all
    projects) or None (decided per-project from the bridge's module flag)."""
    bridge = get_bridge()
    use_synth = synthesized is not None or bridge.module_enabled("research_synthesis")

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"**Generated:** {_utcnow()}")
    lines.append(f"**Topics covered:** {len(projects)}")
    lines.append("")

    if projects:
        lines.append("## Table of Contents")
        lines.append("")
        for i, p in enumerate(projects, 1):
            toc_link = p["topic"].lower().replace(" ", "-").replace(".", "").replace(",", "")
            lines.append(f"- [{i}. {p['topic']}](#{i}-{toc_link})")
        lines.append("")

    for i, p in enumerate(projects, 1):
        syn_dict: Optional[dict] = None
        if use_synth:
            syn_dict = synthesized if synthesized is not None else _synthesize_project(p)
        lines.extend(_build_dspy_section(p, i, syn_dict))

    all_sources = _collect_all_sources(projects)
    if all_sources:
        lines.append("## Appendix: All Sources")
        lines.append("")
        for i, s in enumerate(all_sources, 1):
            lines.append(f"{i}. {s}")
        lines.append("")

    lines.append("---")
    lines.append(
        f"*Report generated by Mayday Research (DSPy synthesis) — "
        f"{sum(len(p.get('data_points', [])) for p in projects)} data points, "
        f"{sum(len(p.get('entities', [])) for p in projects)} entities, "
        f"{sum(len(p.get('findings', [])) for p in projects)} findings*"
    )
    return "\n".join(lines)


def build_dspy_report(topic: str, fmt: str = "md") -> dict:
    """Integration hook for ``research_functions.generate_report``.

    Returns the same dict shape as report_generator.generate_report so the caller
    can format its LLM-facing string unchanged. Writes report.md + (optionally)
    updates the stored summary via update_summary.
    """
    from backend.core.research_store import get_research_store

    store = get_research_store()
    project = store._get_by_topic(topic)
    if not project:
        return {"error": f"Research '{topic}' not found"}

    outputs_dir = store.get_outputs_dir(project)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    syn_dict: Optional[dict] = None
    if get_bridge().module_enabled("research_synthesis"):
        syn_dict = _synthesize_project(project)

    md = build_dspy_md([project], f"Research Report: {project['topic']}", synthesized=syn_dict)
    md_path = outputs_dir / "report.md"
    md_path.write_text(md, encoding="utf-8")
    store.add_generated_output(project, str(md_path), "md")

    summary = (syn_dict or {}).get("summary") if syn_dict else None
    if summary:
        try:
            store.update_summary(topic, summary)
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not write synthesized summary back: %s", exc)

    return {
        "format": fmt,
        "path": str(md_path),
        "content_length": len(md),
        "topic_count": 1,
        "data_point_count": len(project.get("data_points", [])),
        "entity_count": len(project.get("entities", [])),
        "finding_count": len(project.get("findings", [])),
        "synthesis": bool(syn_dict),
    }


def build_dspy_combined_report(
    topics: list[str] | None = None,
    title: str = "Combined Research Report",
    fmt: str = "md",
) -> dict:
    """Combined-report equivalent of build_dspy_report (reuses build_dspy_md)."""
    from backend.core.research_store import get_research_store

    store = get_research_store()
    if topics:
        projects: list[dict] = []
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

    md = build_dspy_md(projects, title)
    md_path = outputs_dir / "report.md"
    md_path.write_text(md, encoding="utf-8")
    store.add_generated_output(projects[0], str(md_path), "md")

    return {
        "format": fmt,
        "path": str(md_path),
        "content_length": len(md),
        "topic_count": len(projects),
        "data_point_count": sum(len(p.get("data_points", [])) for p in projects),
        "entity_count": sum(len(p.get("entities", [])) for p in projects),
        "finding_count": sum(len(p.get("findings", [])) for p in projects),
        "synthesis": get_bridge().module_enabled("research_synthesis"),
    }
