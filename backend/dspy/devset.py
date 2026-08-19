"""Dev-set builder for DSPy compile/eval (Plan R1 / R4).

Source: completed/active research topics in the Mayday Research store, their linked
conversations, and operations/ log entries. Each topic yields trace-shaped examples:
research_questions -> [hop actions + args + results] -> data_points/entities/findings
-> report -> scores. Target: 30-80 gold topics (enough for BootstrapFewShot).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _example_to_project(record: dict) -> dict:
    return {
        "topic": record.get("topic", ""),
        "type": record.get("type", "market"),
        "research_questions": record.get("research_questions", []) or [],
        "data_points": record.get("data_points", []) or [],
        "entities": record.get("entities", []) or [],
        "findings": record.get("findings", []) or [],
        "summary": record.get("summary", ""),
        "tasks": record.get("tasks", []) or [],
    }


def build_dev_set(status_filter: tuple[str, ...] = ("active", "completed"), limit: int = 80) -> list[dict]:
    """Return gold topic records suitable as DSPy trainset examples.

    Each record carries the inputs a synthesis/agent program needs plus any gold
    outputs available (summary). Topics without enough data are skipped.
    """
    from backend.core.research_store import get_research_store

    store = get_research_store()
    out: list[dict] = []
    try:
        projects = store.list_projects()
    except Exception as exc:  # pragma: no cover
        logger.warning("build_dev_set: could not list projects: %s", exc)
        return out

    for p in projects:
        if p.get("status") not in status_filter:
            continue
        rec = store._get_by_topic(p["topic"])
        if not rec:
            continue
        rec = _example_to_project(rec)
        if len(rec["data_points"]) + len(rec["entities"]) + len(rec["findings"]) < 1:
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    logger.info("build_dev_set: collected %d gold topics", len(out))
    return out


def to_trainset_a(devset: list[dict]) -> dict[str, list]:
    """Split devset into per-signature trainsets (dspy.Example-ready dicts)."""
    import dspy  # type: ignore

    summary_ex, ans_ex, nar_ex = [], [], []
    for rec in devset:
        payload = {
            "research_questions": rec["research_questions"],
            "data_points": rec["data_points"],
            "entities": rec["entities"],
            "findings": rec["findings"],
        }
        if rec.get("summary"):
            summary_ex.append(
                dspy.Example(
                    **payload, executive_summary=rec["summary"]
                ).with_inputs(
                    "research_questions", "data_points", "entities", "findings"
                )
            )
        if rec["research_questions"]:
            gold = []
            for q in rec["research_questions"]:
                gold.append({"question": q, "answer": "", "confidence": "medium", "answered": bool(rec["data_points"] or rec["findings"])})
            ans_ex.append(
                dspy.Example(**payload, answers=gold).with_inputs(
                    "research_questions", "data_points", "findings"
                )
            )
        for sec, key in (("entities", "entities"), ("data_points", "data_points"), ("findings", "findings")):
            items = rec.get(key) or []
            if items:
                nar_ex.append(
                    dspy.Example(
                        topic=rec["topic"], section=sec, inputs=items, narrative=""
                    ).with_inputs("topic", "section", "inputs")
                )
    return {"ExecutiveSummary": summary_ex, "AnswerResearchQuestions": ans_ex, "SynthesisNarrative": nar_ex}
