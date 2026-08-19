"""Offline A/B eval harness (Plan R1 / eval gate).

Runs the dev set twice: baseline (today's template report) vs DSPy (build_dspy_md).
Prints an A/B table with deterministic metrics only. SemanticF1 is informational and
excluded from the flip decision. When DSPy synthesis is disabled (no LM), the harness
reports the baseline column only and notes that DSPy needs the bridge enabled.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _score_report(md: str, project: dict, questions: list[str]) -> dict:
    from backend.dspy.metrics import fabrication_score, coverage_score, summary_faithfulness

    summary = ""
    for line in md.splitlines():
        if line.strip().startswith("### Executive Summary"):
            summary = md.split("### Executive Summary", 1)[-1].split("###")[0].strip()
            break
    return {
        "fabrication": round(fabrication_score(md, project), 4),
        "summary_faithfulness": round(summary_faithfulness(summary, project), 4),
        "coverage": round(coverage_score([], questions), 4),
        "chars": len(md),
    }


def run_evaluation(max_topics: int = 10) -> list[dict]:
    from backend.dspy.devset import build_dev_set
    from backend.dspy import get_bridge
    from backend.core.report_generator import build_combined_md

    devset = build_dev_set(limit=max_topics)
    if not devset:
        return []

    enabled = get_bridge().module_enabled("research_synthesis")
    rows: list[dict] = []
    for rec in devset:
        project = {
            "topic": rec["topic"],
            "research_questions": rec["research_questions"],
            "data_points": rec["data_points"],
            "entities": rec["entities"],
            "findings": rec["findings"],
        }
        baseline_md = build_combined_md([project], f"Research Report: {rec['topic']}")
        base = _score_report(baseline_md, project, rec["research_questions"])
        row = {
            "topic": rec["topic"],
            "baseline_fabrication": base["fabrication"],
            "baseline_faithfulness": base["summary_faithfulness"],
            "baseline_chars": base["chars"],
        }
        if enabled:
            from backend.dspy.report_builder import build_dspy_md

            dspy_md = build_dspy_md([project], f"Research Report: {rec['topic']}")
            d = _score_report(dspy_md, project, rec["research_questions"])
            row.update(
                {
                    "dspy_fabrication": d["fabrication"],
                    "dspy_faithfulness": d["summary_faithfulness"],
                    "dspy_chars": d["chars"],
                }
            )
        else:
            row["note"] = "DSPy disabled — set dspy.enabled + research_synthesis flags to compare"
        rows.append(row)
    return rows


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No dev topics available to evaluate.")
        return
    hdr = ["topic", "base_fab", "base_faith", "dspy_fab", "dspy_faith"]
    print(f"{'topic':32} {'base_fab':>9} {'base_fa':>9} {'dspy_fab':>9} {'dspy_fa':>9}")
    for r in rows:
        print(
            f"{r['topic'][:32]:32} "
            f"{r.get('baseline_fabrication',''):>9} "
            f"{r.get('baseline_faithfulness',''):>9} "
            f"{str(r.get('dspy_fabrication','-')):>9} "
            f"{str(r.get('dspy_faithfulness','-')):>9}"
        )


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    from backend.dspy.bridge import configure_dspy

    configure_dspy()
    rows = run_evaluation()
    print_table(rows)


if __name__ == "__main__":
    main()
