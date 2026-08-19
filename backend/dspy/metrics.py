"""Deterministic, LM-free metrics for DSPy research modules.

These functions are the shared evaluation/guard surface for Module A (report
synthesis) and Module B (RL research agent). They never call an LLM. The
fabrication guard is ALWAYS on, even when DSPy is disabled — it protects the
template report path from being replaced by hallucinated synthesis.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
_NUM_RE = re.compile(r"\d[\d,]*\.?\d*\s?%?|[$€£]\s?\d[\d,]*\.?\d*|\d[\d,]*\s?(?:GB|MB|KB|B|TB|kg|km|mi|hrs?|mins?)")


def extract_numbers(text: str) -> list[str]:
    """Return every number-like token in ``text`` (normalized: commas stripped, lowercased)."""
    if not text:
        return []
    out: list[str] = []
    for m in _NUM_RE.findall(text):
        out.append(_norm_number(m))
    return out


def _norm_number(token: str) -> str:
    t = token.strip().lower()
    t = t.replace(",", "")
    t = re.sub(r"\s+", "", t)
    return t


def extract_urls(text: str) -> list[str]:
    """Return markdown/url links found in ``text``."""
    if not text:
        return []
    return re.findall(r"\]\(([^)]+)\)", text) + re.findall(r"https?://\S+", text)


def _store_numbers(project: dict) -> set[str]:
    nums: set[str] = set()
    for dp in project.get("data_points", []) or []:
        v = str(dp.get("value", ""))
        for n in extract_numbers(v):
            nums.add(n)
        for n in extract_numbers(str(dp.get("label", ""))):
            nums.add(n)
    for ent in project.get("entities", []) or []:
        for n in extract_numbers(str(ent.get("relevance", ""))):
            nums.add(n)
        for n in extract_numbers(str(ent.get("description", ""))):
            nums.add(n)
    for fin in project.get("findings", []) or []:
        for n in extract_numbers(str(fin.get("content", ""))):
            nums.add(n)
    return nums


def _store_sources(project: dict) -> set[str]:
    src: set[str] = set()
    for dp in project.get("data_points", []) or []:
        src.update(dp.get("sources", []) or [])
    for ent in project.get("entities", []) or []:
        src.update(ent.get("sources", []) or [])
    for fin in project.get("findings", []) or []:
        src.update(fin.get("sources", []) or [])
    return src


def _store_entities(project: dict) -> set[str]:
    return {str(e.get("name", "")).strip().lower() for e in project.get("entities", []) or [] if e.get("name")}


def _number_supported(num: str, store_nums: set[str]) -> bool:
    """A synthesized number is supported if it (or a store number) contains the other."""
    for s in store_nums:
        if num and (num in s or s in num):
            return True
    return False


# --------------------------------------------------------------------------
# Module A metrics
# --------------------------------------------------------------------------
def fabrication_score(text: str, project: dict) -> float:
    """0..1 fraction of numbers/sources in ``text`` that are backed by the store.

    Numbers that cannot be traced to a store data point/entity/finding value count
    as fabrication. Uncited source URLs also count as fabrication.
    """
    store_nums = _store_numbers(project)
    store_src = _store_sources(project)
    checks = 0
    fails = 0

    numbers = extract_numbers(text)
    for n in numbers:
        checks += 1
        if not _number_supported(n, store_nums):
            fails += 1

    urls = extract_urls(text)
    for u in urls:
        u = u.rstrip(").,")
        checks += 1
        if u not in store_src:
            fails += 1

    if checks == 0:
        return 1.0
    return max(0.0, 1.0 - fails / checks)


def coverage_score(answers: Iterable[dict], questions: list[str] | None = None) -> float:
    """Fraction of research questions with answered=true and >=1 supporting data point."""
    ans = list(answers or [])
    total = len(ans) if ans else (len(questions or []) or 0)
    if total == 0:
        return 0.0
    covered = 0
    for a in ans:
        if a.get("answered") and (a.get("confidence") or a.get("data_points")):
            covered += 1
    return covered / total


def summary_faithfulness(summary: str, project: dict, min_len: int = 40, max_len: int = 1200) -> float:
    """Length bounds + required-entity coverage (store entities that appear in summary)."""
    if not summary:
        return 0.0
    length_ok = min_len <= len(summary) <= max_len
    ents = _store_entities(project)
    if not ents:
        # No entities to cover; length alone decides.
        return 1.0 if length_ok else 0.5
    present = sum(1 for e in ents if e and e in summary.lower())
    coverage = present / len(ents)
    return round((0.5 if length_ok else 0.0) + 0.5 * coverage, 4)


def section_faithful(text: str, project: dict) -> tuple[bool, str]:
    """Integrity guard for one synthesized section.

    Hard failures (→ drop section, template fallback):
      - a numeric token not traceable to store values
      - a cited source URL not present in store sources
    """
    store_nums = _store_numbers(project)
    store_src = _store_sources(project)
    for n in extract_numbers(text):
        if not _number_supported(n, store_nums):
            return False, f"fabricated number '{n}' not in store"
    for u in extract_urls(text):
        u = u.rstrip(").,")
        if u not in store_src:
            return False, f"uncited source '{u}'"
    return True, ""


# --------------------------------------------------------------------------
# Module B metrics (deterministic reward / gap)
# --------------------------------------------------------------------------
def gap_score(project: dict, questions: list[str] | None = None, collected: list[dict] | None = None) -> float:
    """Deterministic 0..1 research-completeness score.

    Combines: fraction of questions covered by a data point/finding whose label or
    content shares a term with the question, plus data-point volume normalized.
    """
    qs = [q for q in (questions or []) if q]
    if not qs:
        return 1.0 if (project.get("data_points") or project.get("findings")) else 0.0

    dps = project.get("data_points", []) or []
    fins = project.get("findings", []) or []
    covered = 0
    for q in qs:
        qterms = set(_terms(q))
        hit = False
        for dp in dps:
            if qterms & set(_terms(str(dp.get("label", "")) + " " + str(dp.get("value", "")))):
                hit = True
                break
        if not hit:
            for fin in fins:
                if qterms & set(_terms(str(fin.get("content", "")))):
                    hit = True
                    break
        if hit:
            covered += 1
    base = covered / len(qs)
    volume = min(1.0, (len(dps) + len(fins)) / 10.0)
    return round(0.7 * base + 0.3 * volume, 4)


def gap_feedback(project: dict, questions: list[str] | None = None, collected: list[dict] | None = None) -> str:
    qs = [q for q in (questions or []) if q]
    if not qs:
        return "No research questions defined; collect general data points."
    dps = project.get("data_points", []) or []
    fins = project.get("findings", []) or []
    gaps = []
    for q in qs:
        qterms = set(_terms(q))
        hit = any(qterms & set(_terms(str(dp.get("label", "")) + " " + str(dp.get("value", "")))) for dp in dps)
        if not hit:
            hit = any(qterms & set(_terms(str(fin.get("content", "")))) for fin in fins)
        if not hit:
            gaps.append(q)
    if not gaps:
        return "All research questions covered by collected data."
    return "Unanswered questions: " + "; ".join(gaps)


def per_hop_reward(
    action: str,
    valid: bool,
    new_data_points: int = 0,
    high_conf_sourced: int = 0,
    newly_covered: int = 0,
    repeated: bool = False,
) -> float:
    """Deterministic per-hop reward (Module B RL signal)."""
    if repeated:
        return -1.0
    if not valid:
        return 0.0
    r = 1.0
    r += min(new_data_points, 5) * 1.0
    r += min(high_conf_sourced, 5) * 0.5
    r += min(newly_covered, 5) * 1.0
    return r


def _terms(text: str) -> list[str]:
    if not text:
        return []
    toks = re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{2,}", text.lower())
    stop = {
        "the", "and", "for", "are", "with", "that", "this", "from", "has", "have",
        "was", "were", "what", "how", "why", "who", "when", "which", "their", "its",
    }
    return [t for t in toks if t not in stop]
