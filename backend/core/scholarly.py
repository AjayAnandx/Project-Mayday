"""Scholarly metadata: identifiers, OpenAlex works, Crossref records, retraction/preprint status.

One parser per upstream format, shared by academic search, research runs and citation export.
Verified live (Nov 2026): OpenAlex returns ``type`` ("preprint", "article", "review", ...),
``is_retracted``, ``best_oa_location.pdf_url``, ``referenced_works``, ``authorships``, and supports
``filter=cites:W…`` and ``filter=openalex:W1|W2``; arXiv preprints carry DOI ``10.48550/arxiv.<id>``;
Crossref work records list retractions/corrections in ``updated-by`` (Retraction Watch data).

Etiquette: no personal data is sent. ``research.contact_email`` (unset by default) adds OpenAlex's
``mailto`` / Crossref polite-pool parameter only if the user configures it; the OpenAlex key (if any)
is sent as the ``api_key`` query parameter.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

import httpx

from backend.core.config import load_config

logger = logging.getLogger(__name__)

OPENALEX = "https://api.openalex.org"
CROSSREF = "https://api.crossref.org"
TIMEOUT = httpx.Timeout(connect=10, read=30, write=10, pool=10)

_ARXIV_NEW = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(v\d+)?(?![\d])")
_ARXIV_OLD = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b", re.I)
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
_OPENALEX_ID = re.compile(r"\b(W\d{4,})\b")
_PMID = re.compile(r"^(?:pmid:?\s*)?(\d{5,9})$", re.I)
ARXIV_DOI_PREFIX = "10.48550/arxiv."

# OpenAlex/Crossref work types that go through editorial or peer review when published with a venue
# or a publisher DOI ("conference-paper" is OpenAlex's current label for proceedings papers).
PEER_REVIEWED_TYPES = ("article", "journal-article", "conference-paper", "proceedings-article", "review",
                       "book-chapter", "book")


# ── identifiers ─────────────────────────────────────────────────────────────

def normalize_arxiv_id(value: str) -> str:
    """'https://arxiv.org/abs/1706.03762v5' / 'arXiv:1706.03762' / DOI form → '1706.03762'."""
    v = (value or "").strip()
    v = re.sub(r"(?i)^https?://(www\.)?(export\.)?arxiv\.org/(abs|pdf)/", "", v)
    v = re.sub(r"(?i)^arxiv:", "", v)
    v = re.sub(r"(?i)^(https?://doi\.org/)?10\.48550/arxiv\.", "", v)
    v = re.sub(r"(?i)\.pdf$", "", v)
    m = _ARXIV_NEW.search(v) or _ARXIV_OLD.search(v)
    return m.group(1).lower() if m else ""


def normalize_doi(value: str) -> str:
    v = (value or "").strip()
    v = re.sub(r"(?i)^(https?://(dx\.)?doi\.org/|doi:\s*)", "", v)
    return v.rstrip(".,;)").lower()


def identify(ref: str) -> dict:
    """Detect what a reference is: arxiv | doi | openalex | pmid | url | unknown (like `orx paper`)."""
    r = (ref or "").strip()
    if not r:
        return {"kind": "unknown", "value": ""}
    low = r.lower()
    if "arxiv.org/" in low or low.startswith("arxiv:") or low.startswith(ARXIV_DOI_PREFIX) \
            or "doi.org/10.48550/arxiv." in low:
        aid = normalize_arxiv_id(r)
        if aid:
            return {"kind": "arxiv", "value": aid}
    if "openalex.org/" in low or re.fullmatch(r"W\d{4,}", r):
        m = _OPENALEX_ID.search(r)
        if m:
            return {"kind": "openalex", "value": m.group(1)}
    if "pubmed.ncbi.nlm.nih.gov/" in low:
        m = re.search(r"/(\d{5,9})", r)
        if m:
            return {"kind": "pmid", "value": m.group(1)}
    m = _PMID.match(r)
    if m:
        return {"kind": "pmid", "value": m.group(1)}
    if low.startswith("10.") or "doi.org/" in low or low.startswith("doi:"):
        d = normalize_doi(r)
        if d.startswith(ARXIV_DOI_PREFIX):
            return {"kind": "arxiv", "value": normalize_arxiv_id(d)}
        if _DOI.match(d):
            return {"kind": "doi", "value": d}
    if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", r):
        return {"kind": "arxiv", "value": normalize_arxiv_id(r)}
    if low.startswith("http"):
        return {"kind": "url", "value": r}
    return {"kind": "unknown", "value": r}


def identity_key(src: dict) -> str:
    """Canonical dedup key for a paper/source: arXiv id beats DOI beats OpenAlex id beats PMID."""
    aid = normalize_arxiv_id(src.get("arxiv_id") or "")
    doi = normalize_doi(src.get("doi") or "")
    if not aid and doi.startswith(ARXIV_DOI_PREFIX):
        aid = normalize_arxiv_id(doi)
    url = src.get("url") or ""
    if not aid and url:
        ident = identify(url)
        if ident["kind"] == "arxiv":
            aid = ident["value"]
        elif ident["kind"] == "doi" and not doi:
            doi = ident["value"]
    if aid:
        return "arxiv:" + aid
    if doi:
        return "doi:" + doi
    oid = (src.get("openalex_id") or "").rsplit("/", 1)[-1]
    if oid:
        return "openalex:" + oid.upper()
    if src.get("pmid"):
        return "pmid:" + str(src["pmid"])
    return ""


# ── status ──────────────────────────────────────────────────────────────────

def evidence_status(src: dict) -> str:
    """peer_reviewed | preprint | retracted | unknown (retraction wins)."""
    if src.get("is_retracted"):
        return "retracted"
    ptype = (src.get("publication_type") or "").lower()
    if ptype == "preprint":
        return "preprint"
    published_doi = normalize_doi(src.get("doi") or "")
    published_doi = bool(published_doi) and not published_doi.startswith(ARXIV_DOI_PREFIX)
    if ptype in PEER_REVIEWED_TYPES and "arxiv" not in (src.get("venue") or "").lower() \
            and (src.get("venue") or published_doi):
        return "peer_reviewed"
    if not ptype and src.get("arxiv_id"):
        return "preprint"  # arXiv-only record, no publication metadata
    return "unknown"


# ── HTTP helpers ────────────────────────────────────────────────────────────

def _cfg() -> dict:
    return (load_config().get("research", {}) or {})


def _openalex_params(extra: dict | None = None) -> dict:
    cfg = load_config()
    key = (cfg.get("openalex", {}) or {}).get("api_key") or (cfg.get("academic", {}) or {}).get("openalex_api_key") \
        or __import__("os").environ.get("OPENALEX_API_KEY", "")
    params = dict(extra or {})
    if key:
        params["api_key"] = key
    email = _cfg().get("contact_email")
    if email:
        params["mailto"] = email
    return params


def _ua() -> dict:
    contact = _cfg().get("contact_url") or "https://github.com/"
    return {"User-Agent": f"MaydayResearch/1.0 ({contact}; personal research assistant)"}


def _get(url: str, params: dict) -> dict | None:
    for attempt in range(2):
        try:
            r = httpx.get(url, params=params, headers=_ua(), timeout=TIMEOUT, follow_redirects=True)
            if r.status_code == 404:
                return None
            if r.status_code in (429, 503) and attempt == 0:
                import time
                time.sleep(2.0)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 1:
                logger.warning("scholarly GET %s failed: %s", url, e)
    return None


# ── OpenAlex ────────────────────────────────────────────────────────────────

_OA_SELECT = ("id,doi,title,display_name,type,publication_date,publication_year,is_retracted,cited_by_count,"
              "authorships,primary_location,best_oa_location,open_access,referenced_works,abstract_inverted_index,ids,"
              "biblio")


def _abstract(inv: dict | None) -> str:
    if not isinstance(inv, dict) or not inv:
        return ""
    flat = {}
    for word, positions in inv.items():
        for p in positions:
            flat[p] = word
    return " ".join(flat[i] for i in sorted(flat))


def openalex_work_to_source(w: dict) -> dict:
    """OpenAlex work JSON → Mayday source fields (single parser for every OpenAlex path)."""
    doi = normalize_doi(w.get("doi") or "")
    loc = w.get("primary_location") or {}
    venue_src = loc.get("source") or {}
    best = w.get("best_oa_location") or {}
    arxiv_id = normalize_arxiv_id(doi) if doi.startswith(ARXIV_DOI_PREFIX) else ""
    if not arxiv_id:
        for cand in (loc.get("landing_page_url"), best.get("landing_page_url"), best.get("pdf_url")):
            if cand and "arxiv.org" in cand:
                arxiv_id = normalize_arxiv_id(cand)
                break
    pmid = ((w.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1] or None
    title = w.get("title") or w.get("display_name") or ""
    abstract = _abstract(w.get("abstract_inverted_index"))
    authors = [((a.get("author") or {}).get("display_name") or "") for a in (w.get("authorships") or [])]
    biblio = w.get("biblio") or {}
    pages = "-".join(x for x in (biblio.get("first_page"), biblio.get("last_page")) if x)
    url = (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id
           else f"https://doi.org/{doi}" if doi else loc.get("landing_page_url") or w.get("id", ""))
    out = {
        "url": url,
        "title": title,
        "content": abstract[:3000] or "",
        "doi": doi or None,
        "arxiv_id": arxiv_id or None,
        "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1] or None,
        "pmid": pmid,
        "published_date": (w.get("publication_date") or "")[:10],
        "year": w.get("publication_year"),
        "authors": [a for a in authors if a][:50],
        "venue": venue_src.get("display_name") or "",
        "venue_is_journal": (venue_src.get("type") == "journal"),
        "volume": biblio.get("volume") or "",
        "issue": biblio.get("issue") or "",
        "pages": pages,
        "publication_type": (w.get("type") or "").lower(),
        "is_retracted": bool(w.get("is_retracted")),
        "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
        "oa_pdf_url": best.get("pdf_url") or (f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None),
        "referenced_works": [r.rsplit("/", 1)[-1] for r in (w.get("referenced_works") or [])][:200],
        "cited_by_count": w.get("cited_by_count"),
        "citationCount": w.get("cited_by_count"),
        "corpus": "openalex",
        "type": "paper",
    }
    out["evidence_status"] = evidence_status(out)
    return out


def openalex_search(query: str, n: int = 10, filters: dict | None = None,
                    sort: str = "relevance_score:desc") -> list[dict]:
    params = {"search": query, "per-page": max(1, min(int(n), 50)), "select": _OA_SELECT}
    if sort:
        params["sort"] = sort
    if filters:
        params["filter"] = ",".join(f"{k}:{v}" for k, v in filters.items() if v not in (None, ""))
    data = _get(f"{OPENALEX}/works", _openalex_params(params)) or {}
    return [openalex_work_to_source(w) for w in data.get("results", [])]


def openalex_get_many(ids: Iterable[str]) -> list[dict]:
    """Batch lookup by OpenAlex ids (W…), ≤50 per request."""
    ids = [i.rsplit("/", 1)[-1] for i in ids if i]
    out = []
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = _get(f"{OPENALEX}/works", _openalex_params(
            {"filter": "openalex:" + "|".join(chunk), "per-page": 50, "select": _OA_SELECT})) or {}
        out.extend(openalex_work_to_source(w) for w in data.get("results", []))
    return out


def openalex_by_dois(dois: Iterable[str]) -> list[dict]:
    """Batch lookup by DOI (≤50 per request). Unknown DOIs are simply absent."""
    dois = [normalize_doi(d) for d in dois if d]
    out = []
    for i in range(0, len(dois), 50):
        chunk = dois[i:i + 50]
        data = _get(f"{OPENALEX}/works", _openalex_params(
            {"filter": "doi:" + "|".join(chunk), "per-page": 50, "select": _OA_SELECT})) or {}
        out.extend(openalex_work_to_source(w) for w in data.get("results", []))
    return out


def openalex_citing(openalex_id: str, n: int = 10) -> list[dict]:
    """Forward citations: most-cited works that cite this one."""
    wid = (openalex_id or "").rsplit("/", 1)[-1]
    if not wid:
        return []
    data = _get(f"{OPENALEX}/works", _openalex_params(
        {"filter": f"cites:{wid}", "per-page": max(1, min(n, 50)), "sort": "cited_by_count:desc",
         "select": _OA_SELECT})) or {}
    return [openalex_work_to_source(w) for w in data.get("results", [])]


# ── Crossref ────────────────────────────────────────────────────────────────

def crossref_work(doi: str) -> dict | None:
    """Bibliographic metadata + retraction/correction notices for one DOI."""
    d = normalize_doi(doi)
    if not d or d.startswith(ARXIV_DOI_PREFIX):
        return None
    params = {}
    email = _cfg().get("contact_email")
    if email:
        params["mailto"] = email
    data = _get(f"{CROSSREF}/works/{d}", params)
    msg = (data or {}).get("message")
    if not msg:
        return None
    updates = msg.get("updated-by") or []
    retracted = any((u.get("type") or "").lower() in ("retraction", "removal", "withdrawal") for u in updates)
    authors = []
    for a in msg.get("author") or []:
        name = " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name") or ""
        if name:
            authors.append(name)
    parts = ((msg.get("issued") or {}).get("date-parts") or [[None]])[0]
    return {
        "doi": d,
        "title": (msg.get("title") or [""])[0],
        "authors": authors,
        "venue": (msg.get("container-title") or [""])[0],
        "volume": msg.get("volume") or "",
        "issue": msg.get("issue") or "",
        "pages": msg.get("page") or "",
        "year": parts[0] if parts else None,
        "publisher": msg.get("publisher") or "",
        "crossref_type": msg.get("type") or "",
        "is_retracted": retracted,
        "updates": [{"type": u.get("type"), "doi": u.get("DOI"), "label": u.get("label")} for u in updates][:10],
    }


# ── enrichment for research runs ────────────────────────────────────────────

def enrich(sources: list[dict], crossref: bool = True, max_crossref: int = 15) -> list[dict]:
    """Fill scholarly metadata on search results in place (batch OpenAlex, capped Crossref).

    Never overwrites values already present; adds is_retracted/evidence_status/oa_pdf_url etc."""
    need = [s for s in sources if (s.get("doi") or s.get("arxiv_id")) and not s.get("openalex_id")]
    by_doi = {}
    dois = []
    for s in need:
        d = normalize_doi(s.get("doi") or "") or (ARXIV_DOI_PREFIX + normalize_arxiv_id(s["arxiv_id"])
                                                  if s.get("arxiv_id") else "")
        if d:
            dois.append(d)
    for rec in openalex_by_dois(dois):
        if rec.get("doi"):
            by_doi[rec["doi"]] = rec
    for s in need:
        d = normalize_doi(s.get("doi") or "") or (ARXIV_DOI_PREFIX + normalize_arxiv_id(s.get("arxiv_id") or "")
                                                  if s.get("arxiv_id") else "")
        rec = by_doi.get(d)
        if rec:
            for k, v in rec.items():
                if k in ("url", "content", "corpus") or v in (None, "", [], False):
                    continue
                if s.get(k) in (None, "", [], 0):
                    s[k] = v
            s["is_retracted"] = bool(s.get("is_retracted") or rec.get("is_retracted"))
    if crossref:
        n = 0
        for s in sources:
            d = normalize_doi(s.get("doi") or "")
            if not d or d.startswith(ARXIV_DOI_PREFIX) or s.get("_crossref_checked"):
                continue
            if n >= max_crossref:
                break
            n += 1
            cr = crossref_work(d)
            s["_crossref_checked"] = True
            if not cr:
                continue
            for k in ("authors", "venue", "volume", "issue", "pages", "year", "publisher"):
                if cr.get(k) and not s.get(k):
                    s[k] = cr[k]
            if cr["is_retracted"]:
                s["is_retracted"] = True
            if cr.get("updates"):
                s["updates"] = cr["updates"]
    for s in sources:
        s.pop("_crossref_checked", None)
        if s.get("arxiv_id"):
            s["arxiv_id"] = normalize_arxiv_id(s["arxiv_id"])
            if not s.get("oa_pdf_url"):
                s["oa_pdf_url"] = f"https://arxiv.org/pdf/{s['arxiv_id']}"
        s["evidence_status"] = evidence_status(s)
    return sources
