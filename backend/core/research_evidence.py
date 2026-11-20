"""Evidence model for research records: source registry, claims with evidence quotes, runs.

Pure functions over a research record (dict). ``ResearchStore`` wraps them with its
lock and persistence. Nothing here does network I/O or calls an LLM.

Record keys added (all lists, created on demand):
- ``sources``: deduplicated source registry. Items reference sources by ``source_ids``.
- ``claims``:  statements backed by evidence quotes, each quote checked against a stored
  snapshot of the source text.
- ``runs``:    one execution of the research flow (brief, budget, stage log, usage).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SOURCE_TYPES = ("web", "paper", "news", "filing", "dataset", "government", "user_doc", "imported_file", "other")
SOURCE_TIERS = ("primary", "secondary", "tertiary", "unknown")
CLAIM_KINDS = ("fact", "number", "opinion", "forecast", "definition")
CLAIM_STATUSES = ("unverified", "supported", "contested", "unsupported")
STANCES = ("supports", "contradicts")
RUN_STAGES = ("scope", "plan", "gather", "extract", "verify", "synthesize", "review", "deliver")
RUN_STATUSES = ("running", "completed", "stopped", "failed")

IMPORTED_PREFIX = "imported_from_file_row_"
_TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|ref|ref_src)$", re.I)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ── sources ─────────────────────────────────────────────────────────────────

def canonical_url(url: str) -> str:
    """Stable form of a URL for dedup: lowercase host, no www/scheme/fragment/tracking params."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)))
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("", host, path, query, "")).lstrip("/")


# Scholarly fields kept on sources (filled by backend/core/scholarly.py; never required).
SCHOLARLY_FIELDS = ("arxiv_id", "openalex_id", "pmid", "authors", "venue", "volume", "issue", "pages", "year",
                    "publication_type", "evidence_status", "is_retracted", "is_oa", "oa_pdf_url",
                    "referenced_works", "cited_by_count", "updates")


def source_key(src: dict) -> str:
    """Canonical identity: arXiv id ⇄ 10.48550/arxiv DOI, then DOI, OpenAlex id, PMID, URL, title."""
    from backend.core.scholarly import identity_key
    key = identity_key(src)
    if key:
        return key
    doi = (src.get("doi") or "").strip().lower()
    if doi:
        return "doi:" + doi.removeprefix("https://doi.org/")
    cu = canonical_url(src.get("url", ""))
    if cu:
        return "url:" + cu
    title = re.sub(r"\s+", " ", (src.get("title") or "").strip().lower())
    return "title:" + title if title else ""


def _guess_type(src: dict) -> str:
    corpus = str(src.get("corpus") or "").lower()
    url = str(src.get("url") or "").lower()
    if src.get("type") in SOURCE_TYPES:
        return src["type"]
    if corpus == "imported_file":
        return "imported_file"
    if src.get("doi") or any(k in corpus for k in ("arxiv", "openalex", "paper", "academic")):
        return "paper"
    if "news" in corpus:
        return "news"
    if any(h in url for h in ("sec.gov", "edgar")):
        return "filing"
    if re.search(r"\.(gov|gov\.[a-z]{2}|nic\.in)(/|$)", urlsplit(url if "://" in url else "https://" + url).netloc + "/"):
        return "government"
    return "web" if url else "other"


def normalize_source(raw) -> dict:
    """Any source input (url string, legacy dict, adapter dict) → canonical source fields."""
    if isinstance(raw, str):
        raw = {"url": raw}
    if not isinstance(raw, dict):
        raw = {"url": str(raw)}
    url = str(raw.get("url") or "")
    if url.startswith(IMPORTED_PREFIX):
        return {"url": "", "title": raw.get("title") or "Imported file", "doi": None, "type": "imported_file",
                "tier": "unknown", "corpus": "imported_file", "publisher": "", "published_date": "",
                "score": None, "citationCount": None}
    doi = raw.get("doi") or None
    if not url and doi:
        url = f"https://doi.org/{doi}"
    score = raw.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    out = {
        "url": url,
        "title": str(raw.get("title") or ""),
        "doi": doi,
        "publisher": str(raw.get("publisher") or ""),
        "published_date": str(raw.get("published_date") or raw.get("publishedDate") or "")[:10],
        "score": score,
        "citationCount": raw.get("citationCount", raw.get("cited_by_count")),
        "corpus": str(raw.get("corpus") or "web"),
        "tier": raw.get("tier") if raw.get("tier") in SOURCE_TIERS else "unknown",
    }
    out["type"] = _guess_type({**raw, **out})
    for k in SCHOLARLY_FIELDS:
        if raw.get(k) not in (None, "", []):
            out[k] = raw[k]
    if out["type"] == "paper" or any(k in out for k in ("arxiv_id", "openalex_id", "publication_type")):
        from backend.core.scholarly import evidence_status
        out["evidence_status"] = evidence_status(out)
    return out


def register_source(record: dict, raw) -> str:
    """Add a source to the record's registry (or merge into the existing one). Returns its id."""
    reg = record.setdefault("sources", [])
    src = normalize_source(raw)
    key = source_key(src)
    if src["type"] == "imported_file" and not key:
        key = "imported:" + (src["title"] or "file")
    for existing in reg:
        if existing.get("key") == key and key:
            for k, v in src.items():  # fill gaps, never overwrite known values
                if v not in (None, "", "unknown", "web", []) and existing.get(k) in (None, "", "unknown", []):
                    existing[k] = v
            if src.get("is_retracted") and not existing.get("is_retracted"):
                existing["is_retracted"] = True  # a retraction found by any lookup sticks
            if existing.get("is_retracted"):
                existing["evidence_status"] = "retracted"
            elif src.get("evidence_status") == "peer_reviewed" and existing.get("evidence_status") in (None, "unknown", "preprint"):
                existing["evidence_status"] = "peer_reviewed"  # the published version supersedes the preprint
            return existing["id"]
    entry = {"id": _new_id("src"), "key": key, **src, "added_at": utcnow(),
             "fetched_at": None, "content_hash": None, "snapshot": None, "access": None}
    reg.append(entry)
    return entry["id"]


def get_source(record: dict, source_id: str) -> dict | None:
    return next((s for s in record.get("sources", []) if s["id"] == source_id), None)


def resolve_source_ref(record: dict, ref) -> str:
    """A source id, url, or dict → registry id (registering when new)."""
    if isinstance(ref, str) and ref.startswith("src_") and get_source(record, ref):
        return ref
    return register_source(record, ref)


def snapshot_dir(topic_dir: Path) -> Path:
    return topic_dir / "sources"


def save_snapshot(record: dict, topic_dir: Path, source_id: str, text: str, access: str = "ok") -> dict:
    """Store the fetched text of a source so evidence quotes can be checked later."""
    src = get_source(record, source_id)
    if src is None:
        raise KeyError(source_id)
    d = snapshot_dir(topic_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{source_id}.txt"
    path.write_text(text or "", encoding="utf-8")
    src["snapshot"] = f"sources/{source_id}.txt"
    src["content_hash"] = "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    src["fetched_at"] = utcnow()
    src["access"] = access
    return src


def read_snapshot(record: dict, topic_dir: Path, source_id: str) -> str | None:
    src = get_source(record, source_id)
    if not src or not src.get("snapshot"):
        return None
    p = topic_dir / src["snapshot"]
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


# ── quote verification ──────────────────────────────────────────────────────

# All quotation marks are dropped and dashes unified: models often swap ' and " or wrap a quote.
_PUNCT_MAP = str.maketrans({"‘": None, "’": None, "“": None, "”": None,
                            "'": None, '"': None, "`": None,
                            "–": "-", "—": "-", " ": " "})
_CITATION_MARK = re.compile(r"\[\d+(?:\s*[,\-]\s*\d+)*\]")   # [13], [13, 14], [13-15]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"</?(sup|sub|i|b|em|strong|span|a)(\s[^>]*)?>", "", text)  # inline markup, e.g. i<sup>2</sup>
    text = text.replace("…", "...").translate(_PUNCT_MAP)
    text = _CITATION_MARK.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r" ([,.;:!?)\]])", r"\1", text).strip()   # "metals , x" == "metals, x"


def quote_in_text(quote: str, text: str) -> bool:
    """True when the quote appears verbatim in the text.

    Insensitive only to case, whitespace, quotation marks, citation markers like [13], and the
    punctuation that ends the quote (a model often ends a quote with "." where the source goes
    on with ","). No fuzzy matching: a changed word or number fails.
    An ellipsis (... or …) splits the quote into parts that must appear in order.
    """
    q, t = _norm(quote), _norm(text)
    if not q or not t:
        return False
    parts = [p.strip().strip(".,;:!? ") for p in re.split(r"\.\.\.", q)]
    parts = [p for p in parts if p]
    if not parts:
        return False
    pos = 0
    for part in parts:
        idx = t.find(part, pos)
        if idx < 0:
            return False
        pos = idx + len(part)
    return True


# ── claims ──────────────────────────────────────────────────────────────────

# ── scientific study fields ─────────────────────────────────────────────────

STUDY_DESIGNS = ("meta_analysis", "systematic_review", "rct", "quasi_experiment", "observational", "benchmark",
                 "simulation", "survey", "qualitative", "case_study", "theory", "other")
# Generic evidence ladder (not GRADE): how much a single study of this design can establish.
DESIGN_STRENGTH = {"meta_analysis": 2, "systematic_review": 2, "rct": 1, "quasi_experiment": 1, "benchmark": 1,
                   "observational": 0, "survey": 0, "simulation": 0, "qualitative": 0, "case_study": 0,
                   "theory": 0, "other": 0}
EVIDENCE_LEVELS = ("weak", "limited", "moderate", "strong")
_NUM = re.compile(r"(?<![\w.])[-−–]?\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """Canonical numbers in a text: '1,024' → '1024', '0.50' → '0.5', unicode minus → '-'."""
    out = set()
    for m in _NUM.findall(text or ""):
        s = m.replace("−", "-").replace("–", "-").replace(",", "")
        try:
            f = float(s)
            out.add(repr(int(f)) if f.is_integer() else repr(f))
        except ValueError:
            continue
    return out


def numbers_supported(value, quotes: list[str]) -> bool:
    """True when every number in ``value`` appears in at least one quote (or value has no numbers)."""
    nums = _numbers(str(value))
    if not nums:
        return True
    found = set().union(*(_numbers(q) for q in quotes)) if quotes else set()
    return nums <= found


def clean_study(study: dict | None, quotes: list[str]) -> dict | None:
    """Validate model-extracted study fields. Numeric fields survive only when their numbers occur
    in the claim's verbatim quote(s); dropped fields are listed so nothing is silently invented."""
    if not isinstance(study, dict) or not study:
        return None
    out, dropped = {}, []
    design = str(study.get("design") or study.get("study_design") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if design in STUDY_DESIGNS:
        out["design"] = design
    for k in ("population", "intervention", "comparator", "dataset", "outcome", "limitations"):
        v = study.get(k)
        if v not in (None, "", []):
            out[k] = str(v)[:300]
    for k in ("sample_n", "p_value"):
        v = study.get(k)
        if v in (None, ""):
            continue
        if numbers_supported(v, quotes):
            out[k] = str(v)[:60]
        else:
            dropped.append(k)
    eff = study.get("effect")
    if isinstance(eff, dict) and any(eff.get(x) not in (None, "") for x in ("value", "ci")):
        clean_eff = {"metric": str(eff.get("metric") or "")[:80]}
        for x in ("value", "ci"):
            if eff.get(x) in (None, ""):
                continue
            if numbers_supported(eff[x], quotes):
                clean_eff[x] = str(eff[x])[:60]
            else:
                dropped.append(f"effect.{x}")
        if len(clean_eff) > 1:
            out["effect"] = clean_eff
    if dropped:
        out["dropped_unquoted"] = dropped
    return out or None


def evidence_level(record: dict, claim: dict, supporting_source_ids: set[str], contested: bool) -> str | None:
    """Ladder from study design, independent replication, peer review and contradiction.
    Only for claims that come from scholarly papers; returns None otherwise."""
    srcs = [get_source(record, sid) or {} for sid in supporting_source_ids]
    if not srcs or not any(s.get("type") == "paper" or s.get("evidence_status") for s in srcs):
        return None
    design = ((claim.get("study") or {}).get("design")) or "other"
    level = DESIGN_STRENGTH.get(design, 0) + 1          # 1..3
    if len(srcs) >= 2:
        level += 1                                       # independently replicated
    if {s.get("evidence_status") for s in srcs} == {"preprint"}:
        level -= 1                                       # not yet peer reviewed
    if contested:
        level -= 1
    return EVIDENCE_LEVELS[max(0, min(3, level))]


def add_claim(record: dict, statement: str, evidence: list[dict] | None = None, *, kind: str = "fact",
              value=None, unit: str = "", as_of: str = "", entity: str = "", question: str = "",
              run_id: str | None = None, study: dict | None = None, hypothesis_id: str | None = None,
              hypothesis_stance: str | None = None) -> dict:
    statement = (statement or "").strip()
    if not statement:
        raise ValueError("Claim statement cannot be empty")
    ev_items = []
    for ev in evidence or []:
        if not isinstance(ev, dict):
            ev = {"source": ev}
        ref = ev.get("source_id") or ev.get("source") or ev.get("url")
        if not ref:
            continue
        stance = ev.get("stance") if ev.get("stance") in STANCES else "supports"
        ev_items.append({
            "source_id": resolve_source_ref(record, ref),
            "quote": str(ev.get("quote") or "").strip(),
            "location": str(ev.get("location") or ""),
            "stance": stance,
            "verified": None,
            "verified_at": None,
        })
    claim = {
        "id": _new_id("clm"),
        "statement": statement,
        "kind": kind if kind in CLAIM_KINDS else "fact",
        "value": None if value in (None, "") else str(value),
        "unit": unit or "",
        "as_of": as_of or "",
        "entity": entity or "",
        "question": question or "",
        "status": "unverified",
        "confidence": 0.0,
        "confidence_reasons": [],
        "evidence": ev_items,
        "run_id": run_id,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    quotes = [e["quote"] for e in ev_items if e["quote"]]
    if claim["value"] is not None and not numbers_supported(claim["value"], quotes):
        claim["value"] = None  # a number the quote does not contain is not evidence
    cleaned = clean_study(study, quotes)
    if cleaned:
        claim["study"] = cleaned
    if hypothesis_id and hypothesis_stance in ("supports", "refutes", "neutral"):
        claim["hypothesis_id"] = hypothesis_id
        claim["hypothesis_stance"] = hypothesis_stance
    record.setdefault("claims", []).append(claim)
    return claim


def score_claim(record: dict, claim: dict) -> None:
    """Set status + confidence from the evidence alone (never from model self-report)."""
    ev = claim.get("evidence", [])

    def retracted(e):
        return bool((get_source(record, e["source_id"]) or {}).get("is_retracted"))

    sup_all = [e for e in ev if e["stance"] == "supports" and e.get("verified")]
    sup = [e for e in sup_all if not retracted(e)]  # a retracted paper supports nothing
    con = [e for e in ev if e["stance"] == "contradicts" and e.get("verified") and not retracted(e)]
    pending = [e for e in ev if e.get("verified") is None]
    reasons = []
    if not ev:
        status, conf = "unsupported", 0.0
        reasons.append("no evidence attached")
    elif sup_all and not sup and not con:
        status = "unsupported"
        reasons.append("only retracted sources support this")
    elif sup and con:
        status = "contested"
    elif sup:
        status = "supported"
    elif pending:
        status = "unverified"
    else:
        status = "unsupported"
        reasons.append("no quote was found in its source")

    conf = 0.0
    claim["evidence_level"] = "retracted" if (sup_all and not sup) else None
    if sup:
        distinct = {e["source_id"] for e in sup}
        conf = {1: 0.5, 2: 0.7}.get(len(distinct), 0.85)
        reasons.append(f"{len(distinct)} independent source(s) with verified quotes")
        tiers = {(get_source(record, sid) or {}).get("tier") for sid in distinct}
        level = evidence_level(record, claim, distinct, bool(con))
        claim["evidence_level"] = level
        if level:
            # Scholarly claims: the evidence ladder replaces the blanket primary-source bonus.
            conf += {"strong": 0.1, "moderate": 0.05, "limited": 0.0, "weak": -0.1}[level]
            design = (claim.get("study") or {}).get("design")
            reasons.append(f"evidence level {level}" + (f" ({design.replace('_', ' ')})" if design else ""))
        elif "primary" in tiers:
            conf += 0.1
            reasons.append("includes a primary source")
        if con:
            conf -= 0.2 * len({e['source_id'] for e in con})
            reasons.append(f"{len(con)} verified contradicting quote(s)")
        statuses = {(get_source(record, sid) or {}).get("evidence_status") for sid in distinct}
        if statuses == {"preprint"}:
            conf = min(conf, 0.6)
            reasons.append("supported by preprints only (not peer reviewed)")
        if len(sup) < len(sup_all):
            reasons.append("retracted sources ignored")
    claim["status"] = status
    claim["confidence"] = round(max(0.0, min(1.0, conf)), 2)
    claim["confidence_reasons"] = reasons
    claim["updated_at"] = utcnow()


def verify_claim(record: dict, topic_dir: Path, claim: dict) -> None:
    """Check each evidence quote against the stored snapshot of its source, then rescore."""
    for e in claim.get("evidence", []):
        if not e.get("quote"):
            e["verified"] = False
            e["verified_at"] = utcnow()
            continue
        text = read_snapshot(record, topic_dir, e["source_id"])
        if text is None:
            e["verified"] = None  # no snapshot yet: can't check, stays pending
            continue
        e["verified"] = quote_in_text(e["quote"], text)
        e["verified_at"] = utcnow()
    score_claim(record, claim)


def verify_all(record: dict, topic_dir: Path) -> dict:
    counts = {s: 0 for s in CLAIM_STATUSES}
    for c in record.get("claims", []):
        verify_claim(record, topic_dir, c)
        counts[c["status"]] += 1
    return counts


# ── runs ────────────────────────────────────────────────────────────────────

def start_run(record: dict, brief: dict, budget: dict, models: dict | None = None) -> dict:
    run = {
        "id": _new_id("run"),
        "status": "running",
        "stage": "scope",
        "brief": brief,
        "budget": budget,
        "usage": {"sources": 0, "llm_calls": 0, "cost_usd": 0.0},
        "models": models or {},
        "stages": [],
        "outputs": [],
        "error": None,
        "started_at": utcnow(),
        "finished_at": None,
    }
    record.setdefault("runs", []).append(run)
    return run


def get_run(record: dict, run_id: str) -> dict | None:
    return next((r for r in record.get("runs", []) if r["id"] == run_id), None)


def record_stage(run: dict, stage: str, passed: bool, notes: str = "") -> dict:
    if stage not in RUN_STAGES:
        raise ValueError(f"Unknown stage '{stage}'. Stages: {', '.join(RUN_STAGES)}")
    entry = {"stage": stage, "passed": bool(passed), "notes": notes, "at": utcnow()}
    run["stages"].append(entry)
    run["stage"] = stage
    return entry


def finish_run(run: dict, status: str = "completed", error: str | None = None) -> dict:
    if status not in RUN_STATUSES:
        raise ValueError(f"Invalid run status '{status}'")
    run["status"] = status
    run["error"] = error
    run["finished_at"] = utcnow()
    return run


# ── migration of legacy records ─────────────────────────────────────────────

def migrate_record(record: dict) -> bool:
    """Idempotently build the source registry from legacy item sources. Returns True if changed."""
    changed = False
    for key in ("sources", "claims", "runs"):
        if key not in record:
            record[key] = []
            changed = True
    # Re-key sources with the canonical scholarly identity (arXiv id ⇄ 10.48550 DOI ...).
    # A collision keeps both entries untouched rather than silently merging stored evidence.
    taken = {s.get("key") for s in record["sources"]}
    for s in record["sources"]:
        if s.get("type") == "imported_file":
            continue
        new = source_key(s)
        if new and new != s.get("key") and new not in taken:
            taken.discard(s.get("key"))
            s["key"] = new
            taken.add(new)
            changed = True
    for coll in ("data_points", "entities", "findings"):
        for item in record.get(coll, []):
            if "source_ids" in item:
                continue
            ids, display = [], []
            for s in item.get("sources") or []:
                sid = register_source(record, s)
                if sid not in ids:
                    ids.append(sid)
                    display.append(source_display(get_source(record, sid)))
            item["source_ids"] = ids
            item["sources"] = display
            changed = True
    return changed


def source_display(src: dict | None) -> dict:
    """Legacy-shaped source dict kept on items so reports/exports keep working."""
    if not src:
        return {}
    return {"url": src.get("url", ""), "title": src.get("title", ""), "doi": src.get("doi"),
            "score": src.get("score") if src.get("score") is not None else 0.5,
            "published_date": src.get("published_date", ""), "citationCount": src.get("citationCount"),
            "corpus": src.get("corpus", "web"), "source_id": src["id"], "tier": src.get("tier", "unknown")}


def link_item_sources(record: dict, item: dict, sources) -> None:
    """Register an item's sources and store both ids and display copies on it."""
    ids, display = [], []
    for s in sources or []:
        sid = resolve_source_ref(record, s)
        if sid not in ids:
            ids.append(sid)
            display.append(source_display(get_source(record, sid)))
    item["source_ids"] = ids
    item["sources"] = display
