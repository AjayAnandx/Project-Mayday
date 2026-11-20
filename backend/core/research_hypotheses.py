"""Hypothesis verdicts from verified evidence (the OpenResearch "freeze when answered" idea).

A claim can be tagged with a hypothesis and a stance (supports / refutes). Only claims whose quotes
verified (status supported or contested) count, weighted by their evidence level, so a single weak
preprint cannot settle a hypothesis and retracted papers (status unsupported) never count.
"""
from __future__ import annotations

LEVEL_WEIGHT = {"strong": 3.0, "moderate": 2.0, "limited": 1.0, "weak": 0.5, None: 1.0}
VERDICTS = ("supported", "refuted", "inconclusive", "untested")
STANCES = ("supports", "refutes", "neutral")


def judge(record: dict, hypothesis_id: str) -> dict:
    support = refute = 0.0
    used = []
    for c in record.get("claims", []):
        if c.get("hypothesis_id") != hypothesis_id or c.get("status") not in ("supported", "contested"):
            continue
        stance = c.get("hypothesis_stance")
        if stance not in ("supports", "refutes"):
            continue
        w = LEVEL_WEIGHT.get(c.get("evidence_level"), 1.0) * (0.5 if c.get("status") == "contested" else 1.0)
        if stance == "supports":
            support += w
        else:
            refute += w
        used.append({"claim_id": c["id"], "stance": stance, "weight": round(w, 2),
                     "level": c.get("evidence_level"), "statement": c.get("statement", "")})
    if support == 0 and refute == 0:
        verdict = "untested"
    elif support >= 1.0 and support >= 2 * refute:
        verdict = "supported"
    elif refute >= 1.0 and refute >= 2 * support:
        verdict = "refuted"
    else:
        verdict = "inconclusive"
    return {"verdict": verdict, "support": round(support, 2), "refute": round(refute, 2), "claims": used}


def summary_line(h: dict) -> str:
    v = h.get("verdict") or "untested"
    return (f"{h.get('label', '')}: {h.get('statement', '')} — {v} "
            f"(support {h.get('support', 0)}, against {h.get('refute', 0)}, {len(h.get('claims', []))} claims)")
