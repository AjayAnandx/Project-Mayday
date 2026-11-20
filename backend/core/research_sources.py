"""Source adapters for research runs: search + full-text fetch behind one interface.

Every adapter returns the same shape so the flow engine, verification and citations work
the same for all of them:

    {"url", "title", "content", "published_date", "doi", "citationCount", "score",
     "corpus", "type", "tier"}

Adapters live in ``CATALOG`` with a description the planner sees and an ``available()``
check, so the planner only offers sources that can actually run. Three families:

- built-in HTTP adapters (Exa web/news, academic fan-out, Wikipedia, Crossref, PubMed, Firecrawl)
- MCP-backed adapters declared in config ``research.mcp_adapters`` (any MCP server/tool that
  returns search results, e.g. GitHub repository search for technical research)

Adding a source = one function + one ``Adapter`` entry (or one config block for MCP).
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

import httpx

from backend.core.config import load_config

logger = logging.getLogger(__name__)

EXA_API_BASE = "https://api.exa.ai"
FIRECRAWL_API_BASE = "https://api.firecrawl.dev/v1"
_UA = "Mozilla/5.0 (compatible; MaydayResearch/1.0)"
def _api_ua() -> str:
    """API etiquette (Wikimedia, Crossref, NCBI) wants a contact URL in the User-Agent. Uses
    config research.contact_url; never includes personal details unless the user sets them."""
    contact = (load_config().get("research", {}) or {}).get("contact_url") or "https://github.com/"
    return f"MaydayResearch/1.0 ({contact}; personal research assistant)"
_TIMEOUT = httpx.Timeout(connect=10, read=40, write=20, pool=10)


# ── source tiers ────────────────────────────────────────────────────────────

_PRIMARY_HOSTS = ("sec.gov", "europa.eu", "who.int", "worldbank.org", "imf.org", "oecd.org", "un.org",
                  "nih.gov", "iea.org", "irena.org", "bis.org", "ecb.europa.eu", "rbi.org.in", "data.gov")
_TERTIARY_HOSTS = ("wikipedia.org", "britannica.com", "investopedia.com")


def _host(url: str) -> str:
    host = urlsplit(url if "://" in url else "https://" + url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def classify_tier(src: dict) -> str:
    """primary = official/regulatory data, filings, research papers; secondary = news and
    analysis; tertiary = encyclopedias and explainers; unknown = everything else."""
    if src.get("tier") in ("primary", "secondary", "tertiary"):
        return src["tier"]
    host = _host(src.get("url", ""))
    if (src.get("publication_type") or "").lower() == "review":
        return "secondary"  # review articles summarise other studies: secondary literature
    if src.get("type") in ("paper", "filing", "government") or src.get("doi"):
        return "primary"
    if re.search(r"(^|\.)(gov|mil|int)(\.[a-z]{2})?$", host) or any(host == h or host.endswith("." + h) for h in _PRIMARY_HOSTS):
        return "primary"
    if any(host == h or host.endswith("." + h) for h in _TERTIARY_HOSTS):
        return "tertiary"
    if src.get("type") == "news":
        return "secondary"
    return "unknown"


SCHOLARLY_FIELDS = ("arxiv_id", "openalex_id", "pmid", "authors", "venue", "volume", "issue", "pages", "year",
                    "publication_type", "evidence_status", "is_retracted", "is_oa", "oa_pdf_url",
                    "referenced_works", "cited_by_count", "updates")


def _finish(rows: list[dict], kind: str, typ: str) -> list[dict]:
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or r.get("error") or not (r.get("url") or r.get("doi")):
            continue
        row = {
            "url": r.get("url") or (f"https://doi.org/{r['doi']}" if r.get("doi") else ""),
            "title": str(r.get("title") or "")[:300],
            "content": r.get("content") or r.get("abstract") or "",
            "published_date": str(r.get("published_date") or "")[:10],
            "doi": r.get("doi"),
            "citationCount": r.get("citationCount"),
            "score": r.get("score"),
            "corpus": r.get("corpus") or kind,
            "type": r.get("type") or typ,
            "publisher": r.get("publisher", ""),
        }
        # Scholarly metadata (backend/core/scholarly.py) travels with the source so the flow can
        # check retractions, prefer open-access PDFs, snowball citations and format references.
        for k in SCHOLARLY_FIELDS:
            if r.get(k) not in (None, "", []):
                row[k] = r[k]
        row["tier"] = classify_tier(row)
        out.append(row)
    return out


# ── built-in adapters ───────────────────────────────────────────────────────

def _exa_key() -> str:
    from backend.core.extraction_pipeline import _exa_key as k
    return k()


def _firecrawl_key() -> str:
    key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        key = (((load_config().get("mcp", {}) or {}).get("servers", {}) or {})
               .get("firecrawl", {}).get("env", {}) or {}).get("FIRECRAWL_API_KEY", "")
    return key or ""


def search_web(query: str, n: int) -> list[dict]:
    from backend.core.extraction_pipeline import web_search_and_fetch
    return _finish(web_search_and_fetch(query, max_sources=n, source_type="web"), "web", "web")


def search_news(query: str, n: int) -> list[dict]:
    from backend.core.extraction_pipeline import web_search_and_fetch
    return _finish(web_search_and_fetch(query, max_sources=n, source_type="news"), "news", "news")


def search_academic(query: str, n: int) -> list[dict]:
    from backend.core.academic_search import academic_search
    difficulty = int(((load_config().get("research", {}) or {}).get("academic", {}) or {}).get("difficulty", 3))
    return _finish(academic_search(query, max_sources=n, difficulty=difficulty), "academic", "paper")


def search_wikipedia(query: str, n: int) -> list[dict]:
    resp = httpx.get("https://en.wikipedia.org/w/api.php", headers={"User-Agent": _api_ua()}, timeout=_TIMEOUT,
                     params={"action": "query", "list": "search", "srsearch": query, "srlimit": n,
                             "format": "json", "utf8": 1})
    resp.raise_for_status()
    rows = []
    for r in resp.json().get("query", {}).get("search", []):
        title = r.get("title", "")
        rows.append({"url": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"), "title": title,
                     "content": re.sub(r"<[^>]+>", "", html.unescape(r.get("snippet", ""))),
                     "published_date": (r.get("timestamp") or "")[:10], "publisher": "Wikipedia"})
    return _finish(rows, "wikipedia", "web")


def _jats_to_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()


def search_crossref(query: str, n: int) -> list[dict]:
    resp = httpx.get("https://api.crossref.org/works", headers={"User-Agent": _api_ua()}, timeout=_TIMEOUT,
                     params={"query": query, "rows": n,
                             "select": "DOI,title,URL,published,container-title,is-referenced-by-count,abstract,publisher"})
    resp.raise_for_status()
    rows = []
    for it in resp.json().get("message", {}).get("items", []):
        parts = (it.get("published") or {}).get("date-parts") or [[]]
        date = "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts[0])) if parts[0] else ""
        rows.append({"url": it.get("URL") or f"https://doi.org/{it.get('DOI')}", "doi": it.get("DOI"),
                     "title": (it.get("title") or [""])[0], "content": _jats_to_text(it.get("abstract", "")),
                     "published_date": date, "citationCount": it.get("is-referenced-by-count"),
                     "publisher": (it.get("container-title") or [it.get("publisher", "")])[0]})
    return _finish(rows, "crossref", "paper")


def search_pubmed(query: str, n: int) -> list[dict]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    ids = httpx.get(f"{base}/esearch.fcgi", headers={"User-Agent": _api_ua()}, timeout=_TIMEOUT,
                    params={"db": "pubmed", "term": query, "retmax": n, "retmode": "json", "sort": "relevance"}
                    ).json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    xml = httpx.get(f"{base}/efetch.fcgi", headers={"User-Agent": _api_ua()}, timeout=_TIMEOUT,
                    params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}).text
    rows = []
    for art in ET.fromstring(xml).iter("PubmedArticle"):
        pmid = art.findtext(".//PMID") or ""
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        abstract = " ".join("".join(a.itertext()) for a in art.iter("AbstractText"))
        year = art.findtext(".//PubDate/Year") or art.findtext(".//ArticleDate/Year") or ""
        doi = next((e.text for e in art.iter("ArticleId") if e.get("IdType") == "doi"), None)
        rows.append({"url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "title": title, "content": abstract,
                     "published_date": year, "doi": doi,
                     "publisher": art.findtext(".//Journal/Title") or "PubMed"})
    return _finish(rows, "pubmed", "paper")


def search_firecrawl(query: str, n: int) -> list[dict]:
    resp = httpx.post(f"{FIRECRAWL_API_BASE}/search", json={"query": query, "limit": n}, timeout=_TIMEOUT,
                      headers={"Authorization": f"Bearer {_firecrawl_key()}"})
    resp.raise_for_status()
    rows = [{"url": r.get("url", ""), "title": r.get("title", ""), "content": r.get("description", "")}
            for r in resp.json().get("data", [])]
    return _finish(rows, "firecrawl", "web")


# ── MCP-backed adapters ─────────────────────────────────────────────────────

class _McpBridge:
    """Owns one asyncio loop in a daemon thread so synchronous research workers can call MCP
    tools. Servers are started on first use and kept for later runs."""

    def __init__(self):
        self._loop = None
        self._lock = threading.Lock()
        self._manager = None
        self._started: set[str] = set()

    def _ensure_loop(self):
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, name="research-mcp", daemon=True).start()

    async def _call(self, server: str, tool: str, args: dict) -> str:
        from backend.assistant.mcp_manager import MCPManager
        if self._manager is None:
            self._manager = MCPManager()
        if server not in self._started:
            cfg = ((load_config().get("mcp", {}) or {}).get("servers", {}) or {}).get(server)
            if not cfg:
                raise RuntimeError(f"MCP server '{server}' is not configured")
            await self._manager.add_server_stdio(server, command=cfg["command"], args=cfg.get("args", []),
                                                 env=cfg.get("env"))
            await self._manager.discover_tools()
            self._started.add(server)
        return await self._manager.call_tool(tool, args)

    def call(self, server: str, tool: str, args: dict, timeout: float = 90) -> str:
        self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(self._call(server, tool, args), self._loop)
        return fut.result(timeout=timeout)


_bridge = _McpBridge()


def _first_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "results", "data", "repositories", "papers", "documents", "hits"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def parse_mcp_results(text: str) -> list[dict]:
    """Map a JSON search result from any MCP tool onto the adapter shape (best effort)."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    rows = []
    for it in _first_list(data):
        if not isinstance(it, dict):
            continue
        url = it.get("html_url") or it.get("url") or it.get("link") or it.get("href") or ""
        if not url.startswith("http"):
            continue
        rows.append({"url": url,
                     "title": it.get("full_name") or it.get("title") or it.get("name") or "",
                     "content": it.get("description") or it.get("summary") or it.get("snippet") or it.get("text") or "",
                     "published_date": str(it.get("updated_at") or it.get("published_date") or it.get("date") or "")[:10]})
    return rows


def _mcp_adapter_fn(name: str, spec: dict) -> Callable[[str, int], list[dict]]:
    def run(query: str, n: int) -> list[dict]:
        args = dict(spec.get("args") or {})
        args[spec.get("query_arg", "query")] = query
        if spec.get("limit_arg"):
            args[spec["limit_arg"]] = n
        text = _bridge.call(spec["server"], spec["tool"], args)
        return _finish(parse_mcp_results(text)[:n], f"mcp:{name}", spec.get("type", "web"))
    return run


# ── catalog ─────────────────────────────────────────────────────────────────

@dataclass
class Adapter:
    name: str
    search: Callable[[str, int], list[dict]]
    description: str
    available: Callable[[], bool] = lambda: True


def _builtin() -> list[Adapter]:
    return [
        Adapter("web", search_web, "General web search (Exa): company sites, reports, analysis.", lambda: bool(_exa_key())),
        Adapter("news", search_news, "Recent news coverage (Exa news). Use for events of the last 1-2 years.",
                lambda: bool(_exa_key())),
        Adapter("academic", search_academic, "Research papers: arXiv + OpenAlex + Exa papers, ranked by citations."),
        Adapter("crossref", search_crossref, "Scholarly works with DOIs and abstracts across all disciplines (Crossref)."),
        Adapter("pubmed", search_pubmed, "Biomedical and health literature with abstracts (PubMed)."),
        Adapter("wikipedia", search_wikipedia, "Background and definitions (Wikipedia). Tertiary: use to orient, not as main evidence."),
        Adapter("firecrawl", search_firecrawl, "Web search with full-page extraction (Firecrawl).", lambda: bool(_firecrawl_key())),
    ]


def catalog() -> dict[str, Adapter]:
    adapters = {a.name: a for a in _builtin()}
    cfg = (load_config().get("research", {}) or {}).get("mcp_adapters", {}) or {}
    servers = ((load_config().get("mcp", {}) or {}).get("servers", {}) or {})
    for name, spec in cfg.items():
        if not isinstance(spec, dict) or not spec.get("server") or not spec.get("tool"):
            continue
        adapters[name] = Adapter(name, _mcp_adapter_fn(name, spec),
                                 spec.get("description", f"MCP {spec['server']}.{spec['tool']}"),
                                 (lambda s=spec: s["server"] in servers and s.get("enabled", True)))
    return adapters


def available_adapters() -> dict[str, Adapter]:
    out = {}
    for name, a in catalog().items():
        try:
            if a.available():
                out[name] = a
        except Exception:
            continue
    return out


def search(query: str, kind: str = "web", n: int = 8) -> list[dict]:
    adapters = available_adapters()
    adapter = adapters.get(kind) or adapters.get("web") or next(iter(adapters.values()), None)
    if adapter is None:
        logger.warning("no research search adapter available")
        return []
    try:
        return adapter.search(query, n)
    except Exception as e:  # one failing adapter must not stop the run
        logger.warning("research search adapter %s failed for %r: %s", adapter.name, query, e)
        return []


# ── full-text fetch ─────────────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def _fetch_exa(url: str, max_chars: int) -> str:
    key = _exa_key()
    if not key:
        return ""
    resp = httpx.post(f"{EXA_API_BASE}/contents",
                      json={"urls": [url], "text": {"maxCharacters": max_chars}},
                      headers={"x-api-key": key, "Content-Type": "application/json"}, timeout=45)
    resp.raise_for_status()
    results = resp.json().get("results") or []
    return (results[0].get("text") or "") if results else ""


def _fetch_firecrawl(url: str, max_chars: int) -> str:
    key = _firecrawl_key()
    if not key:
        return ""
    resp = httpx.post(f"{FIRECRAWL_API_BASE}/scrape", json={"url": url, "formats": ["markdown"],
                                                             "onlyMainContent": True},
                      headers={"Authorization": f"Bearer {key}"}, timeout=60)
    resp.raise_for_status()
    return ((resp.json().get("data") or {}).get("markdown") or "")[:max_chars]


def _fetch_direct(url: str, max_chars: int) -> str:
    resp = httpx.get(url, headers={"User-Agent": _UA}, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        try:
            import fitz  # pymupdf
            from backend.core.paper_text import clean_pdf_text
            with fitz.open(stream=resp.content, filetype="pdf") as doc:
                # Keep paragraph breaks and section headings: extraction picks Methods/Results by them.
                return clean_pdf_text([page.get_text() for page in doc])[:max_chars]
        except Exception:
            return ""
    if "html" not in ctype and "text" not in ctype:
        return ""
    return _strip_html(resp.text)[:max_chars]


def fetch_text(url: str, fallback: str = "", max_chars: int = 20000) -> tuple[str, str]:
    """Best available full text for a URL. Returns (text, access) where access is
    'ok' (full text), 'snippet' (only the search snippet) or 'failed'.
    Order: Exa contents → Firecrawl (JS-heavy pages, if configured) → direct HTTP/PDF."""
    if url:
        for fetcher in (_fetch_exa, _fetch_firecrawl, _fetch_direct):
            try:
                text = fetcher(url, max_chars)
                if text and len(text) > max(400, len(fallback)):
                    return text, "ok"
            except Exception as e:
                logger.debug("fetch %s via %s failed: %s", url, fetcher.__name__, e)
    if fallback:
        return fallback, "snippet"
    return "", "failed"
