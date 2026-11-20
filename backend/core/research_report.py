"""Evidence-backed Markdown report for one research run.

Answers cite claims as [C#] internally; the report turns those into numbered source
references [1][2] that resolve to the bibliography, and lists the exact quote behind each
claim so a reader can check every statement.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from backend.core import research_evidence as ev

_CITE = re.compile(r"(?:\[C\d+\])+")


def _source_numbering(record: dict, answers: list[dict]) -> tuple[dict, list[dict]]:
    """Number sources in order of first citation. Returns ({claim_id: [n,..]}, ordered sources)."""
    claims = {c["id"]: c for c in record.get("claims", [])}
    order: list[str] = []
    claim_refs: dict[str, list[int]] = {}
    for a in answers:
        for cid in a.get("claim_ids", []):
            c = claims.get(cid)
            if not c:
                continue
            nums = []
            for e in c["evidence"]:
                if e.get("verified") and e["stance"] == "supports":
                    if e["source_id"] not in order:
                        order.append(e["source_id"])
                    nums.append(order.index(e["source_id"]) + 1)
            claim_refs[cid] = sorted(set(nums))
    sources = [ev.get_source(record, sid) for sid in order]
    return claim_refs, [s for s in sources if s]


def _render_answer(answer: dict, claim_refs: dict) -> str:
    cite_map = answer.get("cite_map", {})

    def repl(m):
        nums = set()
        for tag in re.findall(r"C\d+", m.group(0)):
            nums.update(claim_refs.get(cite_map.get(tag, ""), []))
        return "".join(f"[{n}]" for n in sorted(nums))

    return _CITE.sub(repl, answer.get("answer", ""))


def _fmt_conf(c: float) -> str:
    return "high" if c >= 0.75 else "medium" if c >= 0.5 else "low"


def build_run_report(record: dict, run: dict, stopped_early: str = "", limitations=None, skills=None) -> str:
    answers = run.get("answers") or []
    claim_refs, sources = _source_numbering(record, answers)
    claims = {c["id"]: c for c in record.get("claims", [])}
    usage, budget = run.get("usage", {}), run.get("budget", {})
    lines = [f"# {record['topic']}", "",
             f"*Research run `{run['id']}` · {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
             f"{usage.get('sources', 0)} new sources · {usage.get('llm_calls', 0)} model calls · "
             f"${usage.get('cost_usd', 0):.3f}*", ""]
    if stopped_early:
        lines += [f"> **Stopped early:** {stopped_early}. Results below use the evidence gathered so far.", ""]
    if run.get("brief", {}).get("scope"):
        lines += [f"**Scope:** {run['brief']['scope']}", ""]

    lines += ["## Answers", ""]
    for i, a in enumerate(answers, 1):
        lines.append(f"### {i}. {a['question']}")
        lines.append("")
        if a.get("answer"):
            confs = [claims[c]["confidence"] for c in a.get("claim_ids", []) if c in claims]
            lines.append(_render_answer(a, claim_refs))
            if confs:
                lines += ["", f"*Evidence strength: {_fmt_conf(sum(confs) / len(confs))} "
                              f"({len(confs)} verified claim{'s' if len(confs) != 1 else ''})*"]
        else:
            lines.append("_Not enough verified evidence to answer this question._")
        lines.append("")

    hyps = [h for h in (run.get("hypotheses") or []) if h.get("statement")]
    if hyps:
        lines += ["## Hypotheses", "", "| Hypothesis | Verdict | For | Against | Claims |", "|---|---|---|---|---|"]
        for h in hyps:
            lines.append(f"| {h.get('label', '')}: {h['statement']} | {h.get('verdict') or 'untested'} | "
                         f"{h.get('support', 0)} | {h.get('refute', 0)} | {len(h.get('claims') or [])} |")
        lines += ["", "Verdicts weigh only verified claims by evidence level (strong 3, moderate 2, limited 1, "
                      "weak 0.5); supported/refuted needs at least twice the weight of the other side.", ""]

    gaps = run.get("gaps") or []
    issues = run.get("review") or []
    if gaps or issues or limitations:
        lines += ["## Gaps and limitations", ""]
        lines += [f"- No verified evidence for: {g}" for g in gaps]
        lines += [f"- {x}" for x in (limitations or [])]
        lines += [f"- Reviewer: {x}" for x in issues]
        lines.append("")

    cited = [claims[cid] for a in answers for cid in a.get("claim_ids", []) if cid in claims]
    if cited:
        lines += ["## Evidence", "", "| # | Claim | Status | Confidence | Source | Quote |", "|---|---|---|---|---|---|"]
        seen = set()
        for c in cited:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            e = next((x for x in c["evidence"] if x.get("verified")), c["evidence"][0] if c["evidence"] else {})
            refs = "".join(f"[{n}]" for n in claim_refs.get(c["id"], []))
            quote = (e.get("quote") or "").replace("|", "\\|").replace("\n", " ")[:160]
            stmt = c["statement"].replace("|", "\\|")
            lines.append(f"| {len(seen)} | {stmt} | {c['status']} | {c['confidence']:.2f} | {refs} | \u201c{quote}\u201d |")
        lines.append("")

    if sources:
        from backend.core.research_cite import apa
        lines += ["## Sources", ""]
        for n, s in enumerate(sources, 1):
            access = "full text" if s.get("access") == "ok" else ("abstract/snippet only" if s.get("access") == "snippet" else "")
            status = {"peer_reviewed": "peer reviewed", "preprint": "preprint (not peer reviewed)",
                      "retracted": "RETRACTED"}.get(s.get("evidence_status") or "", "")
            if s.get("authors") or s.get("venue"):  # scholarly source: proper reference
                meta = [status, access]
                lines.append(f"{n}. {apa(s)}" + (f" — {', '.join(m for m in meta if m)}" if any(meta) else ""))
                continue
            title = s.get("title") or s.get("url") or "Untitled"
            link = f"[{title}]({s['url']})" if s.get("url") else title
            meta = [s.get("type", ""), s.get("tier", "") if s.get("tier") != "unknown" else "",
                    s.get("published_date", ""), status, access,
                    f"retrieved {s['fetched_at'][:10]}" if s.get("fetched_at") else ""]
            lines.append(f"{n}. {link} — {', '.join(m for m in meta if m)}")
        lines.append("")

    sel = run.get("selection") or {}
    if sel:
        order = [("identified", "records found by the searches"), ("duplicates_or_known", "duplicates or already saved"),
                 ("snowball_added", "added by following citations"), ("excluded_retracted", "excluded: retracted"),
                 ("screened", "screened"), ("over_budget", "not fetched: over the source budget"),
                 ("fetch_failed", "not retrievable"), ("abstract_or_snippet_only", "abstract/snippet only"),
                 ("full_text", "full text read"), ("included", "included as sources"),
                 ("no_relevant_claims", "read but no relevant evidence")]
        lines += ["## Search and selection", "", "| Step | Records |", "|---|---|"]
        lines += [f"| {label} | {sel[k]} |" for k, label in order if sel.get(k)]
        if sel.get("retracted_titles"):
            lines += ["", "Excluded as retracted: " + "; ".join(sel["retracted_titles"][:10])]
        crit = (run.get("brief") or {}).get("criteria") or {}
        if crit.get("include") or crit.get("exclude"):
            lines += ["", f"Inclusion: {'; '.join(crit.get('include') or []) or '-'}. "
                          f"Exclusion: {'; '.join(crit.get('exclude') or []) or '-'}."]
        log = run.get("search_log") or []
        if log:
            lines += ["", "Searches: " + "; ".join(f"{q['kind']}: “{q['query']}” ({q['results']})" for q in log[:30])]
        lines.append("")

    lines += ["## Methodology", "",
              f"Budget: {budget.get('max_minutes')} min, {budget.get('max_sources')} sources, "
              f"${budget.get('max_cost_usd')}. Models: "
              + ", ".join(f"{k}={v}" for k, v in (run.get("models") or {}).items()) + ".",
              "Claims count as verified only when their quote was found in the stored copy of the source. "
              "Sentences without a verified citation were removed from the answers.", ""]
    if skills:
        lines += [f"Playbooks used: {', '.join(skills)}.", ""]
    lines += ["| Stage | Gate | Notes |", "|---|---|---|"]
    for st in run.get("stages", []):
        lines.append(f"| {st['stage']} | {'passed' if st['passed'] else 'not met'} | {st['notes']} |")
    lines.append("")
    return "\n".join(lines)


def write_run_report(store, record: dict, run: dict, stopped_early: str = "", limitations=None, skills=None) -> str:
    text = build_run_report(record, run, stopped_early, limitations, skills)
    reports = store.get_reports_dir(record)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"run-{run['id']}.md"
    path.write_text(text, encoding="utf-8")
    (reports / "report.md").write_text(text, encoding="utf-8")  # latest run is the topic's report
    try:
        store.add_generated_output(record, str(path), "md")
    except Exception:
        pass
    return str(path)


# ── spoken summaries (voice / Telegram) ─────────────────────────────────────

_STRENGTH = {"strong": "strong", "moderate": "moderate", "limited": "limited", "weak": "weak"}


def _first_sentences(text: str, n: int = 1) -> str:
    import re as _re
    clean = _re.sub(r"(?:\[\w+\])+", "", text or "")
    clean = _re.sub(r"\s{2,}", " ", clean).strip()
    parts = _re.split(r"(?<=[.!?])\s+", clean)
    return " ".join(parts[:n]).strip()


def voice_summary(record: dict, run: dict, max_chars: int = 900) -> str:
    """Spoken-length summary of one run: headline answer per question (no citation markers),
    evidence strength, caveats, and where the full report is. Deterministic, no LLM."""
    claims = {c["id"]: c for c in record.get("claims", [])}
    answers = [a for a in run.get("answers") or [] if a.get("answer")]
    if run.get("status") == "failed" or not answers:
        why = run.get("error") or "no verified evidence was found"
        return f"The research on {record['topic']} finished without a verified answer: {why}."
    lines = [f"Here is what I found on {record['topic']}."]
    for a in answers[:3]:
        head = _first_sentences(a["answer"], 1)
        levels = [claims[c].get("evidence_level") or "" for c in a.get("claim_ids", []) if c in claims]
        confs = [claims[c]["confidence"] for c in a.get("claim_ids", []) if c in claims]
        if any(levels):
            best = max((lv for lv in levels if lv in _STRENGTH), key=list(_STRENGTH).index, default="")
            tail = f" The evidence is {best}." if best else ""
        elif confs:
            avg = sum(confs) / len(confs)
            tail = " The evidence is strong." if avg >= 0.75 else " The evidence is moderate." if avg >= 0.5 else " The evidence is thin."
        else:
            tail = ""
        lines.append(head + tail)
    verdicts = [h for h in run.get("hypotheses") or [] if h.get("verdict") in ("supported", "refuted")]
    for h in verdicts[:2]:
        lines.append(f"The hypothesis that {h['statement'].rstrip('.').lower()} is {h['verdict']}.")
    sel = run.get("selection") or {}
    if sel.get("excluded_retracted"):
        lines.append(f"I left out {sel['excluded_retracted']} retracted paper{'s' if sel['excluded_retracted'] > 1 else ''}.")
    gaps = run.get("gaps") or []
    if gaps:
        lines.append(f"{len(gaps)} question{'s' if len(gaps) > 1 else ''} had no verified evidence.")
    if run.get("status") == "stopped":
        lines.append("It stopped early at the budget limit, so treat this as partial.")
    lines.append("The full report with sources is ready.")
    out = " ".join(lines)
    return out if len(out) <= max_chars else out[: max_chars].rsplit(". ", 1)[0] + "."


def group_voice_summary(parts: list[tuple[str, dict, dict]], request: str = "", max_chars: int = 1400) -> str:
    """parts = [(label, record, run)] for a multi-category research group."""
    intro = f"Your research is done, in {len(parts)} parts." if len(parts) > 1 else ""
    pieces = []
    budget = max(300, max_chars // max(1, len(parts)))
    for label, record, run in parts:
        s = voice_summary(record, run, max_chars=budget)
        s = s.replace(f"Here is what I found on {record['topic']}.", f"On the {label} side:").replace(
            " The full report with sources is ready.", "")
        pieces.append(s)
    return " ".join([intro, *pieces, "Full reports with sources are ready."]).strip()
