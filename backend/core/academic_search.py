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

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
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


def _extract_doi(text: str, arxiv_doi_elem: str | None = None) -> str | None:
    if arxiv_doi_elem and arxiv_doi_elem.strip():
        m = DOI_RE.search(arxiv_doi_elem)
        if m:
            return m.group(0)
        # arxiv:doi may be bare DOI without prefix handling
        cand = arxiv_doi_elem.strip()
        if cand.startswith("10."):
            return cand
    if text:
        m = DOI_RE.search(text)
        if m:
            return m.group(0).rstrip(".")
    return None


def search_arxiv(query: str, limit: int = 20, sort_by: str = "relevance") -> list[dict]:
    """Query arXiv Atom API. Returns [{url,title,content,doi,published_date,arxiv_id}]."""
    if not query or not query.strip():
        return []
    # arXiv expects search_query param; use all: prefix for broad match
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max(1, min(int(limit), 50)),
        "sortBy": sort_by if sort_by in ("relevance", "lastUpdatedDate", "submittedDate") else "relevance",
        "sortOrder": "descending",
    }
    try:
        resp = httpx.get(ARXIV_API, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        results = []
        for entry in root.findall("atom:entry", ARXIV_NS):
            title_el = entry.find("atom:title", ARXIV_NS)
            summary_el = entry.find("atom:summary", ARXIV_NS)
            id_el = entry.find("atom:id", ARXIV_NS)
            pub_el = entry.find("atom:published", ARXIV_NS)
            doi_el = entry.find("arxiv:doi", ARXIV_NS)
            title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""
            summary = summary_el.text.strip().replace("\n", " ") if summary_el is not None and summary_el.text else ""
            arxiv_url = id_el.text.strip() if id_el is not None and id_el.text else ""
            arxiv_id = arxiv_url.split("/abs/")[-1] if "/abs/" in arxiv_url else arxiv_url
            doi_text = doi_el.text.strip() if doi_el is not None and doi_el.text else None
            doi = _extract_doi(summary, doi_text)
            pub = pub_el.text.strip()[:10] if pub_el is not None and pub_el.text else ""
            results.append({
                "url": arxiv_url or f"https://arxiv.org/abs/{arxiv_id}",
                "title": title,
                "content": summary[:3000],
                "doi": doi,
                "published_date": pub,
                "arxiv_id": arxiv_id,
                "score": 0.6,  # base, reranked later
                "citationCount": None,
                "corpus": "arxiv",
            })
        return results
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 503:
            time.sleep(3.5)
            try:
                resp = httpx.get(ARXIV_API, params=params, timeout=TIMEOUT)
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
                # quick parse retry (single)
                results = []
                for entry in root.findall("atom:entry", ARXIV_NS):
                    title_el = entry.find("atom:title", ARXIV_NS)
                    summary_el = entry.find("atom:summary", ARXIV_NS)
                    id_el = entry.find("atom:id", ARXIV_NS)
                    pub_el = entry.find("atom:published", ARXIV_NS)
                    doi_el = entry.find("arxiv:doi", ARXIV_NS)
                    title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""
                    summary = summary_el.text.strip().replace("\n", " ") if summary_el is not None and summary_el.text else ""
                    arxiv_url = id_el.text.strip() if id_el is not None and id_el.text else ""
                    arxiv_id = arxiv_url.split("/abs/")[-1] if "/abs/" in arxiv_url else arxiv_url
                    doi_text = doi_el.text.strip() if doi_el is not None and doi_el.text else None
                    doi = _extract_doi(summary, doi_text)
                    pub = pub_el.text.strip()[:10] if pub_el is not None and pub_el.text else ""
                    results.append({
                        "url": arxiv_url or f"https://arxiv.org/abs/{arxiv_id}",
                        "title": title,
                        "content": summary[:3000],
                        "doi": doi,
                        "published_date": pub,
                        "arxiv_id": arxiv_id,
                        "score": 0.6,
                        "citationCount": None,
                        "corpus": "arxiv",
                    })
                return results
            except Exception:
                logger.warning("arXiv retry failed")
                return []
        logger.warning("arXiv HTTP %s", e.response.status_code)
        return []
    except Exception as e:
        logger.warning("arXiv search error: %s", e)
        return []


def search_openalex_keyword(query: str, limit: int = 20, from_date: str | None = None) -> list[dict]:
    """OpenAlex keyword search via title_and_abstract.search."""
    if not query or not query.strip():
        return []
    params = {
        "search": query,
        "per-page": max(1, min(int(limit), 50)),
        "sort": "relevance_score:desc",
    }
    if from_date:
        params["filter"] = f"from_publication_date:{from_date}"
    # attach API key if configured (raising rate limits) via header to avoid URL logging
    _oak = _openalex_key()
    _headers = {"api_key": _oak} if _oak else None
    try:
        resp = httpx.get(OPENALEX_API, params=params, headers=_headers, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for w in data.get("results", [])[:limit]:
            doi = w.get("doi", "")
            if doi and doi.startswith("https://doi.org/"):
                doi = doi.replace("https://doi.org/", "")
            title = w.get("title", "") or ""
            # abstract inverted index → reconstruct snippet
            ab = w.get("abstract_inverted_index")
            abstract = ""
            if isinstance(ab, dict) and ab:
                # rebuild approximate abstract by sorting by position
                try:
                    flat = {}
                    for word, pos_list in ab.items():
                        for pos in pos_list:
                            flat[pos] = word
                    abstract = " ".join(flat[i] for i in sorted(flat))[:3000]
                except Exception:
                    abstract = ""
            if not abstract:
                # fallback: use display_name + concepts
                abstract = title
            pub_date = w.get("publication_date", "") or ""
            cited = w.get("cited_by_count", 0) or 0
            landing = (w.get("primary_location") or {}).get("landing_page_url") or w.get("id", "")
            # OpenAlex id like https://openalex.org/W123 -> url
            openalex_id = w.get("id", "")
            url = doi and f"https://doi.org/{doi}" or landing or openalex_id
            results.append({
                "url": url,
                "title": title,
                "content": abstract[:3000],
                "doi": doi or None,
                "published_date": pub_date[:10],
                "score": 0.6,
                "citationCount": cited,
                "openalex_id": openalex_id,
                "referenced_works": w.get("referenced_works", [])[:20],
                "corpus": "openalex",
            })
        return results
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            retry_after = int(e.response.headers.get("Retry-After", "1") or "1")
            time.sleep(min(retry_after, 5))
            try:
                resp = httpx.get(OPENALEX_API, params=params, headers=_headers, timeout=TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                results = []
                for w in data.get("results", [])[:limit]:
                    doi = w.get("doi", "")
                    if doi and doi.startswith("https://doi.org/"):
                        doi = doi.replace("https://doi.org/", "")
                    title = w.get("title", "") or ""
                    ab = w.get("abstract_inverted_index")
                    abstract = ""
                    if isinstance(ab, dict) and ab:
                        try:
                            flat = {}
                            for word, pos_list in ab.items():
                                for pos in pos_list:
                                    flat[pos] = word
                            abstract = " ".join(flat[i] for i in sorted(flat))[:3000]
                        except Exception:
                            abstract = ""
                    if not abstract:
                        abstract = title
                    pub_date = w.get("publication_date", "") or ""
                    cited = w.get("cited_by_count", 0) or 0
                    landing = (w.get("primary_location") or {}).get("landing_page_url") or w.get("id", "")
                    openalex_id = w.get("id", "")
                    url = doi and f"https://doi.org/{doi}" or landing or openalex_id
                    results.append({
                        "url": url,
                        "title": title,
                        "content": abstract[:3000],
                        "doi": doi or None,
                        "published_date": pub_date[:10],
                        "score": 0.6,
                        "citationCount": cited,
                        "openalex_id": openalex_id,
                        "referenced_works": w.get("referenced_works", [])[:20],
                        "corpus": "openalex",
                    })
                return results
            except Exception:
                return []
        logger.warning("OpenAlex HTTP %s", e.response.status_code)
        return []
    except Exception as e:
        logger.warning("OpenAlex search error: %s", e)
        return []


def resolve_openalex_by_doi(doi: str) -> dict | None:
    if not doi:
        return None
    try:
        _oak = _openalex_key()
        _headers = {"api_key": _oak} if _oak else None
        url = f"{OPENALEX_API}/https://doi.org/{doi}"
        resp = httpx.get(url, headers=_headers, timeout=TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        w = resp.json()
        title = w.get("title", "") or ""
        doi_clean = w.get("doi", "").replace("https://doi.org/", "") if w.get("doi") else doi
        cited = w.get("cited_by_count", 0) or 0
        pub_date = w.get("publication_date", "") or ""
        return {
            "doi": doi_clean,
            "title": title,
            "citationCount": cited,
            "published_date": pub_date[:10],
            "referenced_works": w.get("referenced_works", [])[:20],
            "openalex_id": w.get("id", ""),
        }
    except Exception:
        return None


def search_openalex_by_referenced(openalex_ids: list[str], limit: int = 5) -> list[dict]:
    results = []
    _oak = _openalex_key()
    _headers = {"api_key": _oak} if _oak else None
    for oid in openalex_ids[:limit]:
        # OpenAlex id like https://openalex.org/W123
        try:
            target = oid if oid.startswith("http") else f"{OPENALEX_API}/{oid}"
            resp = httpx.get(target, headers=_headers, timeout=TIMEOUT)
            if resp.status_code != 200:
                continue
            w = resp.json()
            doi = w.get("doi", "")
            if doi and doi.startswith("https://doi.org/"):
                doi = doi.replace("https://doi.org/", "")
            title = w.get("title", "") or ""
            ab = w.get("abstract_inverted_index")
            abstract = ""
            if isinstance(ab, dict) and ab:
                try:
                    flat = {}
                    for word, pos_list in ab.items():
                        for pos in pos_list:
                            flat[pos] = word
                    abstract = " ".join(flat[i] for i in sorted(flat))[:3000]
                except Exception:
                    abstract = ""
            if not abstract:
                abstract = title
            pub_date = w.get("publication_date", "") or ""
            cited = w.get("cited_by_count", 0) or 0
            landing = (w.get("primary_location") or {}).get("landing_page_url") or w.get("id", "")
            url = doi and f"https://doi.org/{doi}" or landing or oid
            results.append({
                "url": url,
                "title": title,
                "content": abstract[:3000],
                "doi": doi or None,
                "published_date": pub_date[:10],
                "score": 0.55,
                "citationCount": cited,
                "openalex_id": w.get("id", oid),
                "corpus": "openalex_ref",
            })
        except Exception:
            continue
    return results


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
    seen: dict[str, dict] = {}
    for s in sources:
        doi = (s.get("doi") or "").strip().lower()
        arxiv_id = (s.get("arxiv_id") or "").strip().lower()
        norm_title = _normalize_title(s.get("title", "") or "")
        key = doi or arxiv_id or norm_title
        if not key:
            # fallback to url
            key = (s.get("url", "") or "").strip().lower()
        if key in seen:
            # merge citationCount/score if better
            existing = seen[key]
            # keep higher citationCount/score
            if (s.get("citationCount") or 0) > (existing.get("citationCount") or 0):
                existing["citationCount"] = s.get("citationCount")
            if float(s.get("score", 0) or 0) > float(existing.get("score", 0) or 0):
                existing["score"] = s.get("score")
            # merge content longer
            if len(s.get("content", "") or "") > len(existing.get("content", "") or ""):
                existing["content"] = s.get("content", "")
            # keep doi if missing
            if not existing.get("doi") and s.get("doi"):
                existing["doi"] = s.get("doi")
        else:
            seen[key] = s
    return list(seen.values())


def _rerank(sources: list[dict]) -> list[dict]:
    if not sources:
        return sources
    max_cite = max((s.get("citationCount") or 0) for s in sources) or 1
    # compute recency bonus: newer = higher (within 5 years)
    now_year = datetime.now(timezone.utc).year
    for idx, s in enumerate(sources):
        base = 0.0
        # reciprocal rank approximation via original order
        base += 0.4 * (1.0 / (idx + 1))
        cite = s.get("citationCount") or 0
        # log1p normalized
        import math
        cite_norm = math.log1p(cite) / math.log1p(max_cite) if max_cite else 0
        base += 0.3 * cite_norm
        exa_score = float(s.get("score", 0.5) or 0.5)
        base += 0.3 * exa_score
        # recency: within 2y bonus 0.05, 5y 0.02
        pub = s.get("published_date", "") or ""
        try:
            year = int(pub[:4]) if pub and pub[:4].isdigit() else None
            if year:
                age = now_year - year
                if age <= 2:
                    base += 0.05
                elif age <= 5:
                    base += 0.02
        except Exception:
            pass
        s["_rank_score"] = base
    sources.sort(key=lambda x: x.get("_rank_score", 0), reverse=True)
    for s in sources:
        s.pop("_rank_score", None)
    return sources


def academic_search(query: str, max_sources: int = 20, difficulty: int = 5, include_arxiv: bool = True, include_openalex: bool = True) -> list[dict]:
    """3-corpus academic search with DOI dedup + rerank + difficulty budget.

    difficulty 1-3:0 follow-ups, 4-7:1, 8-10:2 (OR pattern).
    """
    if not query or not query.strip():
        return []
    max_sources = max(1, min(int(max_sources), 50))
    difficulty = max(1, min(int(difficulty), 10))
    # follow-up budget
    if difficulty <= 3:
        follow_budget = 0
    elif difficulty <= 7:
        follow_budget = 1
    else:
        follow_budget = 2

    arxiv_results = search_arxiv(query, limit=max_sources // 2 + 5) if include_arxiv else []
    openalex_results = search_openalex_keyword(query, limit=max_sources // 2 + 5) if include_openalex else []
    exa_paper_results = search_exa_paper(query, limit=max_sources // 3 + 3)

    merged = _dedup_sources(arxiv_results + openalex_results + exa_paper_results)
    merged = _rerank(merged)

    # difficulty follow-ups: chase referenced_works of top OpenAlex hits
    if follow_budget > 0:
        top_openalex = [s for s in merged if s.get("corpus") == "openalex"][:3]
        referenced_ids = []
        for s in top_openalex:
            refs = s.get("referenced_works") or []
            referenced_ids.extend(refs[:3])
        # dedup referenced ids
        referenced_ids = list(dict.fromkeys(referenced_ids))[: follow_budget * 3]
        if referenced_ids:
            follow = search_openalex_by_referenced(referenced_ids, limit=follow_budget * 3)
            if follow:
                merged = _dedup_sources(merged + follow)
                merged = _rerank(merged)

    # optional DOI enrichment: for arXiv entries without citationCount, try OpenAlex DOI resolve
    # limit to top 5 to avoid hammering
    for s in merged[:5]:
        if s.get("doi") and s.get("citationCount") is None and s.get("corpus") == "arxiv":
            info = resolve_openalex_by_doi(s["doi"])
            if info:
                s["citationCount"] = info.get("citationCount")
                s["published_date"] = s.get("published_date") or info.get("published_date", "")
                s["referenced_works"] = info.get("referenced_works", [])

    merged = merged[:max_sources]
    # log metrics
    try:
        doi_cov = sum(1 for s in merged if s.get("doi")) / len(merged) if merged else 0
        logger.info("academic_search q=%r returned=%d doi_cov=%.2f difficulty=%d", query[:60], len(merged), doi_cov, difficulty)
    except Exception:
        pass
    return merged
