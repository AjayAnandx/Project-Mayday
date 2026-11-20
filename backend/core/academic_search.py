"""arXiv → DOI → OpenAlex academic search path.

Implements the 3-corpus fan (arXiv keyword, OpenAlex keyword, Exa category=paper)
with DOI-anchored dedup (id→DOI→normalized title), blended rerank
(citationCount + Exa score + recency), and difficulty-budget follow-ups
chasing referenced_works (OR orx-lit-review pattern: 1-3:0, 4-7:1, 8-10:2).

No new deps — httpx + xml.etree + regex. All endpoints public (no keys)
except Exa which reuses existing _exa_key().
"""
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from backend.core import scholarly
from backend.core.config import load_config

logger = logging.getLogger(__name__)
# suppress httpx access logs that would leak api_key query param
for _n in ("httpx", "httpcore"):
    try:
        logging.getLogger(_n).setLevel(logging.WARNING)
    except Exception:
        pass

ARXIV_API = "https://export.arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"
EXA_API_BASE = "https://api.exa.ai"

TIMEOUT = httpx.Timeout(connect=10, read=30, write=10, pool=10)

ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _exa_key() -> str:
    cfg = load_config()
    key = cfg.get("mcp", {}).get("servers", {}).get("exa", {}).get("env", {}).get("EXA_API_KEY", "")
    return key or __import__("os").environ.get("EXA_API_KEY", "")


def _openalex_key() -> str:
    cfg = load_config()
    key = cfg.get("openalex", {}).get("api_key", "") or cfg.get("academic", {}).get("openalex_api_key", "")
    return key or __import__("os").environ.get("OPENALEX_API_KEY", "")


def _normalize_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _parse_arxiv_feed(text: str) -> list[dict]:
    root = ET.fromstring(text)
    results = []
    for entry in root.findall("atom:entry", ARXIV_NS):
        def _t(tag):
            el = entry.find(tag, ARXIV_NS)
            return el.text.strip().replace("\n", " ") if el is not None and el.text else ""
        arxiv_url = _t("atom:id")
        arxiv_id = scholarly.normalize_arxiv_id(arxiv_url)
        # Only the arXiv-declared journal DOI counts; DOIs inside the abstract usually belong
        # to *cited* papers, so they are never taken as this paper's DOI.
        doi = scholarly.normalize_doi(_t("arxiv:doi")) or None
        authors = [a.findtext("atom:name", "", ARXIV_NS).strip() for a in entry.findall("atom:author", ARXIV_NS)]
        journal_ref = _t("arxiv:journal_ref")
        results.append({
            "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else arxiv_url,
            "title": _t("atom:title"),
            "content": _t("atom:summary")[:3000],
            "doi": doi,
            "published_date": _t("atom:published")[:10],
            "arxiv_id": arxiv_id or None,
            "authors": [a for a in authors if a][:50],
            "venue": journal_ref,
            "oa_pdf_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None,
            "is_oa": True,
            "publication_type": "article" if (doi and journal_ref) else "",
            "score": 0.6,
            "citationCount": None,
            "corpus": "arxiv",
            "type": "paper",
        })
    return results


def search_arxiv(query: str, limit: int = 20, sort_by: str = "relevance") -> list[dict]:
    """Query arXiv Atom API (one retry on 503/429)."""
    if not query or not query.strip():
        return []
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max(1, min(int(limit), 50)),
        "sortBy": sort_by if sort_by in ("relevance", "lastUpdatedDate", "submittedDate") else "relevance",
        "sortOrder": "descending",
    }
    for attempt in range(2):
        try:
            resp = httpx.get(ARXIV_API, params=params, timeout=TIMEOUT)
            if resp.status_code in (429, 503) and attempt == 0:
                time.sleep(3.5)
                continue
            resp.raise_for_status()
            return _parse_arxiv_feed(resp.text)
        except Exception as e:
            if attempt == 1:
                logger.warning("arXiv search error: %s", e)
    return []


def search_openalex_keyword(query: str, limit: int = 20, from_date: str | None = None) -> list[dict]:
    """OpenAlex keyword search (shared parser in backend/core/scholarly.py)."""
    if not query or not query.strip():
        return []
    rows = scholarly.openalex_search(query, n=limit,
                                     filters={"from_publication_date": from_date} if from_date else None)
    for r in rows:
        r["score"] = 0.6
    return rows


def resolve_openalex_by_doi(doi: str) -> dict | None:
    rows = scholarly.openalex_by_dois([doi]) if doi else []
    return rows[0] if rows else None


def search_openalex_by_referenced(openalex_ids: list[str], limit: int = 5) -> list[dict]:
    rows = scholarly.openalex_get_many(list(openalex_ids)[:limit])
    for r in rows:
        r["score"] = 0.55
        r["corpus"] = "openalex_ref"
    return rows


def search_exa_paper(query: str, limit: int = 10) -> list[dict]:
    """Exa category=paper fallback (uses existing _exa_key)."""
    key = _exa_key()
    if not key:
        return []
    body = {
        "query": query,
        "numResults": max(1, min(int(limit), 20)),
        "type": "auto",
        "category": "paper",
        "contents": {"text": {"maxCharacters": 3000}},
    }
    try:
        resp = httpx.post(f"{EXA_API_BASE}/search", json=body, headers={"x-api-key": key, "Content-Type": "application/json"}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        out = []
        for r in data.get("results", [])[:limit]:
            url = r.get("url", "")
            if not url:
                continue
            out.append({
                "url": url,
                "title": r.get("title", ""),
                "content": (r.get("text", "") or "")[:3000],
                "doi": None,
                "published_date": (r.get("publishedDate") or "")[:10],
                "score": float(r.get("score", 0.5) or 0.5),
                "citationCount": None,
                "corpus": "exa_paper",
            })
        return out
    except Exception as e:
        logger.warning("Exa paper search error: %s", e)
        return []


def _dedup_sources(sources: list[dict]) -> list[dict]:
    """Merge the same paper across corpora (arXiv id ⇄ 10.48550/arxiv DOI ⇄ DOI ⇄ OpenAlex id).
    Fields are merged fill-gaps-only; the higher citation count and longer abstract win."""
    seen: dict[str, dict] = {}
    for s in sources:
        key = scholarly.identity_key(s) or ("title:" + _normalize_title(s.get("title", "") or "")) \
            or (s.get("url", "") or "").strip().lower()
        if key not in seen:
            seen[key] = s
            continue
        existing = seen[key]
        if (s.get("citationCount") or 0) > (existing.get("citationCount") or 0):
            existing["citationCount"] = s.get("citationCount")
        if float(s.get("score", 0) or 0) > float(existing.get("score", 0) or 0):
            existing["score"] = s.get("score")
        if len(s.get("content", "") or "") > len(existing.get("content", "") or ""):
            existing["content"] = s.get("content", "")
        for k, v in s.items():
            if v not in (None, "", [], False) and existing.get(k) in (None, "", [], False):
                existing[k] = v
        existing["is_retracted"] = bool(existing.get("is_retracted") or s.get("is_retracted"))
    return list(seen.values())


def _rerank(sources: list[dict]) -> list[dict]:
    """Rank = 0.4·within-corpus reciprocal rank + 0.3·log citations + 0.3·base score + recency.

    Rank is taken *within each corpus* (stored as ``_corpus_rank`` by academic_search), so the
    order in which corpora were concatenated no longer biases the result. Unknown citation
    counts get the median instead of 0, so brand-new papers are not buried."""
    import math
    if not sources:
        return sources
    counts = sorted(s["citationCount"] for s in sources if isinstance(s.get("citationCount"), (int, float)))
    median = counts[len(counts) // 2] if counts else 0
    max_cite = max(counts) if counts else 1
    now_year = datetime.now(timezone.utc).year
    for s in sources:
        rank = s.get("_corpus_rank", 0)
        cite = s.get("citationCount") if isinstance(s.get("citationCount"), (int, float)) else median
        score = 0.4 * (1.0 / (rank + 1))
        score += 0.3 * (math.log1p(cite) / math.log1p(max_cite) if max_cite else 0)
        score += 0.3 * float(s.get("score", 0.5) or 0.5)
        pub = s.get("published_date", "") or ""
        if pub[:4].isdigit():
            age = now_year - int(pub[:4])
            score += 0.05 if age <= 2 else 0.02 if age <= 5 else 0.0
        if s.get("is_retracted"):
            score -= 1.0  # never rank a retracted paper first
        s["_rank_score"] = score
    sources.sort(key=lambda x: x.get("_rank_score", 0), reverse=True)
    for s in sources:
        s.pop("_rank_score", None)
    return sources


def _with_corpus_rank(rows: list[dict]) -> list[dict]:
    for i, r in enumerate(rows):
        r["_corpus_rank"] = i
    return rows


def academic_search(query: str, max_sources: int = 20, difficulty: int = 5, include_arxiv: bool = True,
                    include_openalex: bool = True, enrich: bool = True) -> list[dict]:
    """arXiv + OpenAlex (+ Exa papers) with cross-corpus dedup, rerank and optional reference chasing.

    difficulty 1-3: no follow-ups, 4-7: chase references of the top 3 OpenAlex hits, 8-10: more.
    ``enrich`` fills retraction/preprint/OA/author metadata via scholarly.enrich (batched)."""
    if not query or not query.strip():
        return []
    max_sources = max(1, min(int(max_sources), 50))
    difficulty = max(1, min(int(difficulty), 10))
    follow_budget = 0 if difficulty <= 3 else 1 if difficulty <= 7 else 2

    arxiv_results = _with_corpus_rank(search_arxiv(query, limit=max_sources // 2 + 5)) if include_arxiv else []
    openalex_results = _with_corpus_rank(search_openalex_keyword(query, limit=max_sources // 2 + 5)) \
        if include_openalex else []
    exa_paper_results = _with_corpus_rank(search_exa_paper(query, limit=max_sources // 3 + 3))
    for r in exa_paper_results:
        # Exa's "paper" category also returns tutorials and blog posts; without a scholarly
        # identifier a result is treated as a web page, not as a research paper.
        if not scholarly.identity_key(r):
            r["type"] = "web"

    merged = _dedup_sources(arxiv_results + openalex_results + exa_paper_results)
    merged = _rerank(merged)

    if follow_budget > 0:
        referenced_ids = []
        for s in [s for s in merged if s.get("openalex_id")][:3]:
            referenced_ids.extend((s.get("referenced_works") or [])[:3 * follow_budget])
        referenced_ids = list(dict.fromkeys(referenced_ids))[: follow_budget * 9]
        if referenced_ids:
            follow = _with_corpus_rank(search_openalex_by_referenced(referenced_ids, limit=len(referenced_ids)))
            merged = _rerank(_dedup_sources(merged + follow))

    merged = merged[:max_sources]
    if enrich:
        try:
            scholarly.enrich(merged, crossref=False)  # Crossref per-DOI calls happen later, for kept sources
        except Exception as e:
            logger.warning("scholarly enrichment failed: %s", e)
    for s in merged:
        s.pop("_corpus_rank", None)
    try:
        doi_cov = sum(1 for s in merged if s.get("doi")) / len(merged) if merged else 0
        logger.info("academic_search q=%r returned=%d doi_cov=%.2f difficulty=%d", query[:60], len(merged), doi_cov, difficulty)
    except Exception:
        pass
    return merged
