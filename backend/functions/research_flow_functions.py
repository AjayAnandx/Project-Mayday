"""LLM tools for the evidence-based research flow (start a run, check it, inspect evidence)."""
from __future__ import annotations

import contextvars
import json
import re

from backend.core.research_store import RESEARCH_TYPES, get_research_store

# The user's own message for the current chat turn (set by chat._run_engine). Budget and
# question choices are decided from it, because models paraphrase requests and invent numbers.
CURRENT_USER_TEXT: contextvars.ContextVar[str] = contextvars.ContextVar("research_user_text", default="")


_HANDOFF = re.compile(r'^\[Voice realtime handoff\].*?What was heard: "(.*?)"\. ', re.S)


def user_words(text: str) -> str:
    """The user's own words: a realtime voice handoff wraps the transcript in a worker prompt
    (with a "- <fact>" template line) that must not count as the user's request."""
    m = _HANDOFF.match(text or "")
    if m:
        return m.group(1)
    if (text or "").startswith("[Voice realtime handoff]"):
        return ""
    return text or ""


def set_user_text(text: str) -> None:
    CURRENT_USER_TEXT.set(user_words(text))


_BUDGET_WORDS = re.compile(r"\d+\s*(min|minute|minutes|sources?|\$|usd|dollars?)|\$\s*\d", re.I)
_LISTED_QUESTIONS = re.compile(r"(\?.*\?)|(^\s*(\d+[.)]|[-*•])\s+\S)", re.S | re.M)

# Budget presets picked from the user's own words.
BUDGET_PRESETS = {
    "quick": {"max_minutes": 3, "max_sources": 15, "max_cost_usd": 0.1},
    "deep": {"max_minutes": 30, "max_sources": 120, "max_cost_usd": 2.0},
}
_QUICK = re.compile(r"\b(quick|quickly|brief|short|fast)\b", re.I)
_DEEP = re.compile(r"\b(deep|deeply|thorough|thoroughly|comprehensive|exhaustive|in[- ]depth)\b", re.I)


def _preset_for(text: str) -> dict:
    if _DEEP.search(text or ""):
        return BUDGET_PRESETS["deep"]
    if _QUICK.search(text or ""):
        return BUDGET_PRESETS["quick"]
    return {}


def resolve_start_args(user_text: str, request: str, questions, max_minutes, max_sources, max_cost_usd):
    """Decide budget and questions from what the user actually wrote.

    - A preset word ("quick", "deep", ...) in the user's message sets the budget.
    - Numeric budget arguments are honoured only when the user mentioned minutes/sources/money;
      otherwise they are model guesses and the configured default applies.
    - Model-supplied questions are kept only when the user listed questions themselves; otherwise
      the scope stage writes them (with its playbook).
    Without a user message (REST/tests), the tool arguments are trusted as given."""
    explicit = {"max_minutes": max_minutes, "max_sources": max_sources, "max_cost_usd": max_cost_usd}
    explicit = {k: v for k, v in explicit.items() if v is not None}
    if not user_text:
        budget = dict(_preset_for(request))
        budget.update(explicit)
        return budget, questions or None
    budget = dict(_preset_for(user_text))
    if _BUDGET_WORDS.search(user_text):
        budget.update(explicit)
    keep_questions = bool(_LISTED_QUESTIONS.search(user_text))
    return budget, (questions or None) if keep_questions else None


def resolve_academic_options(user_text: str, field: str = "", hypotheses=None, snowball=None,
                             sources=None) -> dict:
    """Academic options, trusting the model only where the user's own words back it up."""
    from backend.core.research_playbooks import FIELDS
    opts: dict = {}
    if field in FIELDS:
        opts["field"] = field
    if snowball is not None:
        opts["snowball"] = bool(snowball)
    text = (user_text or "").lower()
    if isinstance(hypotheses, list) and hypotheses:
        if not user_text or "hypothes" in text:  # model-invented hypotheses are ignored
            opts["hypotheses"] = [str(h).strip() for h in hypotheses if str(h).strip()][:5]
    elif hypotheses is True or hypotheses is False:
        opts["hypotheses"] = hypotheses
    if isinstance(sources, list) and sources:
        named = [s for s in sources if not user_text or str(s).lower() in text]
        if named:
            opts["sources"] = named
    return opts


async def research_start(topic: str, request: str = "", questions: list | None = None, type: str = "domain",
                         max_minutes: float | None = None, max_sources: int | None = None,
                         max_cost_usd: float | None = None, field: str = "", hypotheses=None,
                         snowball: bool | None = None, sources: list | None = None) -> str:
    # async on purpose: runs in the chat task, so CURRENT_USER_TEXT is visible
    # (sync tools run in an executor thread, which does not inherit context variables).
    from backend.core import research_autopilot
    user_text = CURRENT_USER_TEXT.get()
    if not (topic or "").strip() and not user_text:
        return "Missing required parameter: topic."
    budget, questions = resolve_start_args(user_text, request or topic, questions,
                                           max_minutes, max_sources, max_cost_usd)
    options = resolve_academic_options(user_text, field, hypotheses, snowball, sources)
    # The router (not the model) decides category, field and whether to split by category.
    res = research_autopilot.launch(user_text or request or topic, (topic or "").strip(),
                                    model_type=type if type in RESEARCH_TYPES else None,
                                    budget=budget, questions=questions, options=options)
    if not res["runs"]:
        return "Could not start research: " + "; ".join(res["errors"] or ["unknown error"])
    names = ", ".join(f"'{r['topic']}'" for r in res["runs"])
    out = (f"{res['explanation']} Started in the background: {names}. Tell the user this in one or two "
           "spoken sentences. They will be told the result (by voice if listening, otherwise Telegram and on "
           "screen) when it finishes; research_status() with no topic checks the latest research.")
    if res["errors"]:
        out += " Not started: " + "; ".join(res["errors"])
    return out


def _resolve_topic(topic: str) -> str:
    """Empty topic = the most recent research the user started."""
    if (topic or "").strip():
        return topic
    from backend.core.research_autopilot import latest_topic
    return latest_topic()


def research_status_voice(topic: str = "") -> str:
    """Spoken-length status of the latest research (or a topic), covering every part of a group."""
    from backend.core import research_autopilot as ap
    from backend.core.research_report import group_voice_summary, voice_summary
    from backend.core.research_router import LABELS
    store = get_research_store()
    last = ap.latest() if not topic else None
    topics = (last or {}).get("topics") or [_resolve_topic(topic)]
    if not topics or not topics[0]:
        return "There is no research yet."
    running, parts = [], []
    for t in topics:
        rec = store._get_by_topic(t)
        run = (rec or {}).get("runs", [None])[-1] if rec and rec.get("runs") else None
        if not run:
            continue
        if run["status"] == "running":
            running.append(f"{t} (stage {run['stage']})")
        else:
            parts.append((LABELS.get(rec.get("type"), rec.get("type", "")), rec, run))
    if running:
        return "Still working on " + "; ".join(running) + (". Finished parts are ready." if parts else ".")
    if len(parts) == 1:
        return voice_summary(parts[0][1], parts[0][2])
    return group_voice_summary(parts)


def research_status(topic: str = "", run_id: str = "") -> str:
    topic = _resolve_topic(topic)
    store = get_research_store()
    record = store._get_by_topic(topic)
    if not record:
        return f"No research topic '{topic}'."
    runs = record.get("runs", [])
    if not runs:
        return f"'{topic}' has no research runs yet. Start one with research_start."
    run = next((r for r in runs if r["id"] == run_id), None) if run_id else runs[-1]
    if not run:
        return f"No run '{run_id}' for '{topic}'."
    u = run.get("usage", {})
    lines = [f"Run {run['id']} — {run['status']} (stage: {run['stage']}); "
             f"{u.get('sources', 0)} sources, {u.get('llm_calls', 0)} model calls, ${u.get('cost_usd', 0):.3f}."]
    for st in run.get("stages", []):
        lines.append(f"  - {st['stage']}: {'passed' if st['passed'] else 'NOT MET'} — {st['notes']}")
    if run.get("error"):
        lines.append(f"Note: {run['error']}")
    for a in run.get("answers") or []:
        lines.append(f"Q: {a['question']}\n   A: {a['answer'] or 'Not enough verified evidence.'}")
    if run.get("outputs"):
        from pathlib import Path as _P
        # A served URL the model can link to (the stored output is a local file path).
        lines.append(f"Report: /research/{record['slug']}/artifacts/reports/{_P(run['outputs'][-1]).name}")
    text = "\n".join(lines)
    if run.get("answers") and run.get("status") != "running":
        from backend.core.openui_builder import research_run_ui
        return json.dumps({"message": text, "ui": research_run_ui(record, run)}, ensure_ascii=False)
    return text


def research_claims(topic: str = "", status: str = "", limit: int = 20) -> str:
    topic = _resolve_topic(topic)
    store = get_research_store()
    if not store._get_by_topic(topic):
        return f"No research topic '{topic}'."
    claims = store.list_claims(topic, status or None)
    if not claims:
        return f"No {status + ' ' if status else ''}claims for '{topic}'."
    srcs = {s["id"]: s for s in store.list_sources(topic)}
    claims.sort(key=lambda c: -c["confidence"])
    lines = [f"{len(claims)} {status + ' ' if status else ''}claim(s) for '{topic}' (top {min(limit, len(claims))}):"]
    for c in claims[:limit]:
        e = next((x for x in c["evidence"] if x.get("verified")), c["evidence"][0] if c["evidence"] else None)
        src = srcs.get(e["source_id"], {}) if e else {}
        lines.append(f"- [{c['status']}, {c['confidence']:.2f}] {c['statement']}"
                     + (f"\n    quote: “{e['quote'][:200]}” — {src.get('title') or src.get('url', '')}" if e else ""))
    return "\n".join(lines)


def research_sources(topic: str = "", limit: int = 30) -> str:
    topic = _resolve_topic(topic)
    store = get_research_store()
    if not store._get_by_topic(topic):
        return f"No research topic '{topic}'."
    srcs = store.list_sources(topic)
    if not srcs:
        return f"No sources saved for '{topic}' yet."
    lines = [f"{len(srcs)} source(s) for '{topic}':"]
    for s in srcs[:limit]:
        access = {"ok": "full text", "snippet": "snippet only", "failed": "fetch failed"}.get(s.get("access"), "not fetched")
        lines.append(f"- {s.get('title') or s.get('url') or s['id']} ({s.get('type')}, {access}) {s.get('url', '')}")
    return "\n".join(lines)


def research_export(topic: str = "", format: str = "docx", run_id: str = "") -> str:
    topic = _resolve_topic(topic)
    from backend.core.research_export import export_run
    res = export_run(topic, run_id, format)
    if "error" in res:
        return f"Could not export: {res['error']}"
    from backend.core.openui_builder import download_ui
    title = f"{topic} ({res['format'].upper()})"
    # A download card, not an iframe artifact: browsers cannot display docx/xlsx in a frame.
    return json.dumps({"message": f"Exported run {res['run_id']} of '{topic}' as {res['format'].upper()}: {res['url']}",
                       "ui": download_ui(title, res["url"], res["format"]),
                       "file_path": res["path"]}, ensure_ascii=False)


def research_add_pdf(topic: str, pdf: str, title: str = "", doi: str = "") -> str:
    """Add one of the user's uploaded PDFs (Docs) to a research topic as a full-text source.
    The next research run on the topic extracts and verifies claims from it like any paper."""
    from pathlib import Path

    from backend.core import research_evidence as ev
    from backend.core.paper_text import clean_pdf_text
    from backend.core.pdf_store import get_pdf_store
    from backend.core.scholarly import enrich, normalize_doi

    store = get_research_store()
    if not store._get_by_topic(topic):
        created = store.create_research(topic, "academic", 2)
        if "error" in created:
            return f"Could not create topic: {created['error']}"
    ps = get_pdf_store()
    docs = ps.list_all()
    ref = (pdf or "").strip().lower()
    entry = next((d for d in docs if d["id"] == pdf), None) \
        or next((d for d in docs if ref and ref in (d.get("filename") or "").lower()), None) \
        or next(iter(ps.search(pdf, limit=1)), None)
    if not entry:
        return f"No uploaded PDF matches '{pdf}'. Upload it in Docs first, or use list_pdfs to find its id."
    meta_path = ps._meta_path(entry["id"])
    try:
        pages = json.loads(meta_path.read_text(encoding="utf-8")).get("pages", [])
    except (OSError, json.JSONDecodeError):
        pages = []
    text = clean_pdf_text([p.get("text", "") for p in pages])
    if len(text) < 200:
        return f"'{entry.get('filename')}' has no extractable text (scanned PDF?). Run OCR first."
    src = {"type": "user_doc", "title": title or entry.get("filename") or "Uploaded PDF",
           "url": f"/pdfs/{Path(ps._pdf_path(entry['id'])).name}", "corpus": "user_pdf"}
    if doi:
        src["doi"] = normalize_doi(doi)
        try:
            enrich([src], crossref=True, max_crossref=1)  # authors, venue, retraction status
        except Exception:
            pass
        src["type"] = "user_doc"
    saved = store.add_source(topic, src, snapshot_text=text, access="ok")
    status = saved.get("evidence_status")
    return (f"Added '{saved.get('title')}' ({len(text):,} characters of text) to research '{topic}' as source "
            f"{saved['id']}" + (f", status {status}" if status else "") +
            ". The next research run on this topic will extract and verify claims from it.")


def research_cite(topic: str, style: str = "apa", run_id: str = "") -> str:
    """Bibliography of a research topic's cited sources in BibTeX, APA, IEEE or CSL-JSON."""
    from backend.core.research_cite import bibliography, cite_keys, to_csl
    from backend.core.research_export import _cited_then_rest
    store = get_research_store()
    record = store._get_by_topic(topic)
    if not record:
        return f"No research topic '{topic}'."
    runs = [r for r in record.get("runs", []) if r.get("answers")]
    run = next((r for r in runs if r["id"] == run_id), None) if run_id else (runs[-1] if runs else None)
    sources = _cited_then_rest(record, run) if run else [s for s in record.get("sources", []) if s.get("snapshot")]
    if not sources:
        return f"'{topic}' has no sources to cite yet."
    style = (style or "apa").lower()
    if style in ("csl", "csl-json", "csl_json"):
        keys = cite_keys(sources)
        return json.dumps([to_csl(s, keys[s["id"]]) for s in sources], ensure_ascii=False, indent=1)
    if style not in ("apa", "ieee", "bibtex"):
        return "Style must be apa, ieee, bibtex or csl."
    return bibliography(sources, style)


def research_hypotheses(topic: str) -> str:
    """Hypotheses tested on a topic, with verdicts computed from verified evidence."""
    store = get_research_store()
    record = store._get_by_topic(topic)
    if not record:
        return f"No research topic '{topic}'."
    tasks = [t for t in record.get("tasks", []) if t.get("hypothesis")]
    if not tasks:
        return f"No hypotheses on '{topic}' yet. Start an academic research run (or state hypotheses) to test some."
    claims = {c["id"]: c for c in record.get("claims", [])}
    lines = [f"Hypotheses for '{topic}':"]
    for t in tasks:
        state = "answered (frozen)" if t.get("frozen") else t.get("status", "pending")
        lines.append(f"- {t['hypothesis']} — {t.get('verdict') or 'untested'} [{state}]")
        last = next((r for r in reversed(record.get("runs", []))
                     for h in r.get("hypotheses") or [] if h.get("id") == t["id"] and h.get("claims")), None)
        if last:
            h = next(h for h in last["hypotheses"] if h.get("id") == t["id"])
            for x in h["claims"][:4]:
                c = claims.get(x["claim_id"], {})
                lines.append(f"    {x['stance']}: {c.get('statement', x.get('statement', ''))} "
                             f"(evidence {x.get('level') or 'n/a'})")
    return "\n".join(lines)
