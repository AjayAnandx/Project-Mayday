"""Quality metrics for one research run. Pure functions over the stored record + run."""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from backend.core.research_report import _render_answer, _source_numbering


def _minutes(run: dict) -> float:
    try:
        a = datetime.fromisoformat(run["started_at"])
        b = datetime.fromisoformat(run["finished_at"])
        return round((b - a).total_seconds() / 60, 2)
    except (KeyError, TypeError, ValueError):
        return 0.0


def score_run(record: dict, run: dict, expect: list[str] | None = None) -> dict:
    """Metrics (0-1 unless noted) and a composite quality score (0-100).

    expect: regex patterns of stable facts the answers should contain (case-insensitive)."""
    answers = run.get("answers") or []
    questions = (run.get("brief") or {}).get("questions") or [a["question"] for a in answers]
    claims = {c["id"]: c for c in record.get("claims", [])}
    run_claims = [c for c in record.get("claims", []) if c.get("run_id") == run["id"]]
    claim_refs, cited_sources = _source_numbering(record, answers)

    answered = [a for a in answers if a.get("answer")]
    from backend.core.research_flow import split_sentences
    kept = sum(len(split_sentences(a["answer"])) for a in answered)
    dropped = sum(a.get("dropped_sentences", 0) for a in answers)
    cited_ids = [cid for a in answers for cid in a.get("claim_ids", [])]
    leaked = [cid for cid in cited_ids if claims.get(cid, {}).get("status") not in ("supported", "contested")]
    verified = [c for c in run_claims if c["status"] in ("supported", "contested")]
    domains = {urlsplit(s.get("url", "")).netloc.lower().removeprefix("www.") for s in cited_sources if s.get("url")}
    primary = [s for s in cited_sources if s.get("tier") == "primary"]
    confs = [claims[c]["confidence"] for c in cited_ids if c in claims]

    text = " ".join(_render_answer(a, claim_refs) for a in answers)
    hits = [p for p in (expect or []) if re.search(p, text, re.I)]

    m = {
        "questions": len(questions),
        "answered_rate": round(len(answered) / len(questions), 3) if questions else 0.0,
        "citation_coverage": round(kept / (kept + dropped), 3) if kept + dropped else 0.0,
        "verification_rate": round(len(verified) / len(run_claims), 3) if run_claims else 0.0,
        "claims_extracted": len(run_claims),
        "cited_sources": len(cited_sources),
        "primary_share": round(len(primary) / len(cited_sources), 3) if cited_sources else 0.0,
        "cited_domains": len(domains),
        "avg_cited_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
        "unsupported_leaks": len(leaked),
        "expected_facts": len(expect or []),
        "expected_fact_recall": round(len(hits) / len(expect), 3) if expect else None,
        "missing_facts": [p for p in (expect or []) if p not in hits],
        "cost_usd": round((run.get("usage") or {}).get("cost_usd", 0.0), 4),
        "llm_calls": (run.get("usage") or {}).get("llm_calls", 0),
        "minutes": _minutes(run),
        "status": run.get("status"),
        "gates_failed": [s["stage"] for s in run.get("stages", []) if not s["passed"]],
    }
    # Scholarly metrics (academic pack). Computed over this run's included sources / cited claims.
    srcs_read = [s for s in record.get("sources", []) if s.get("snapshot")]
    papers = [s for s in srcs_read if s.get("type") == "paper" or s.get("evidence_status")]
    cited_claims = [claims[c] for c in cited_ids if c in claims]
    m["paper_sources"] = len(papers)
    m["doi_coverage"] = round(sum(1 for s in papers if s.get("doi") or s.get("arxiv_id")) / len(papers), 3) \
        if papers else None
    m["full_text_rate"] = round(sum(1 for s in papers if s.get("access") == "ok") / len(papers), 3) if papers else None
    m["preprint_share"] = round(sum(1 for s in cited_sources if s.get("evidence_status") == "preprint")
                                / len(cited_sources), 3) if cited_sources else 0.0
    m["study_design_coverage"] = round(sum(1 for c in cited_claims if (c.get("study") or {}).get("design"))
                                       / len(cited_claims), 3) if cited_claims else None
    m["retracted_in_answers"] = sum(1 for s in cited_sources if s.get("is_retracted"))
    m["excluded_retracted"] = int((run.get("selection") or {}).get("excluded_retracted", 0))
    recall = m["expected_fact_recall"] if m["expected_fact_recall"] is not None else m["answered_rate"]
    m["quality"] = round(100 * (
        0.25 * m["answered_rate"]
        + 0.20 * m["citation_coverage"]
        + 0.15 * m["verification_rate"]
        + 0.15 * recall
        + 0.10 * min(1.0, m["primary_share"] / 0.5)
        + 0.10 * min(1.0, m["cited_domains"] / 5)
        + 0.05 * (1.0 if not leaked and not m["retracted_in_answers"] else 0.0)
    ), 1)
    return m


SUMMARY_KEYS = ("quality", "answered_rate", "citation_coverage", "verification_rate", "expected_fact_recall",
                "primary_share", "cited_domains", "unsupported_leaks", "cost_usd", "minutes",
                "doi_coverage", "full_text_rate", "preprint_share", "study_design_coverage", "retracted_in_answers")


def summarize(results: list[dict]) -> dict:
    """Mean of each summary metric over cases (ignores None), plus totals for cost."""
    out = {}
    for k in SUMMARY_KEYS:
        vals = [r["metrics"][k] for r in results if r.get("metrics") and r["metrics"].get(k) is not None]
        out[k] = round(sum(vals) / len(vals), 3) if vals else None
    out["total_cost_usd"] = round(sum(r["metrics"]["cost_usd"] for r in results if r.get("metrics")), 4)
    out["cases"] = len(results)
    out["failed_cases"] = sum(1 for r in results if not r.get("metrics") or r["metrics"]["status"] == "failed")
    return out
