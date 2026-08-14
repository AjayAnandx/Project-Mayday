import json
import logging
import os

import httpx

from backend.core.config import load_config

logger = logging.getLogger(__name__)

EXA_API_BASE = "https://api.exa.ai"
EXA_TIMEOUT = httpx.Timeout(connect=10, read=60, write=30, pool=10)


def _api_key() -> str:
    cfg = load_config()
    key = cfg.get("mcp", {}).get("servers", {}).get("exa", {}).get("env", {}).get("EXA_API_KEY", "")
    return key or os.environ.get("EXA_API_KEY", "")


def _headers() -> dict:
    return {"x-api-key": _api_key(), "Content-Type": "application/json"}


def _fmt_search_results(data: dict, limit: int) -> str:
    results = data.get("results", [])
    if not results:
        return "No results found."
    lines = []
    for r in results[:limit]:
        lines.append(f"Title: {r.get('title', 'N/A')}")
        lines.append(f"URL: {r.get('url', '')}")
        lines.append(f"Published: {r.get('publishedDate') or r.get('published', '') or 'N/A'}")
        lines.append(f"Author: {r.get('author', 'N/A')}")
        highlights = r.get("highlights", []) or []
        if highlights:
            lines.append("Highlights:")
            for h in highlights[:4]:
                lines.append(f"  {h}")
        text = r.get("text", "")
        if text and not highlights:
            lines.append("Text:")
            lines.append(f"  {text[:1500]}")
        lines.append("")
    return "\n".join(lines).strip()


def web_search_exa(query: str = "", numResults: int = 10, type: str = "auto",
                   category: str = "", includeDomains: list | None = None,
                   excludeDomains: list | None = None, startPublishedDate: str = "",
                   endPublishedDate: str = "", includeText: list | None = None,
                   enableSummary: bool = False, enableHighlights: bool = False,
                   highlightsQuery: str = "", livecrawl: str = "fallback") -> str:
    if not query:
        return "Missing required parameter: query. Call web_search_exa with a non-empty 'query' string (e.g. {\"query\": \"your search terms\"})."
    if not _api_key():
        return "EXA_API_KEY not configured. Add it to config.yaml or .env."
    body = {
        "query": query,
        "numResults": int(numResults),
        "type": type,
        "livecrawl": livecrawl,
    }
    if category:
        body["category"] = category
    if includeDomains:
        body["includeDomains"] = includeDomains
    if excludeDomains:
        body["excludeDomains"] = excludeDomains
    if startPublishedDate:
        body["startPublishedDate"] = startPublishedDate
    if endPublishedDate:
        body["endPublishedDate"] = endPublishedDate
    if includeText:
        body["includeText"] = includeText
    contents: dict = {}
    if enableHighlights:
        contents["highlights"] = {"query": highlightsQuery or query, "numSentences": 3}
    if enableSummary:
        contents["summary"] = {"query": query}
    if not contents:
        contents["text"] = {"maxCharacters": 1800}
    body["contents"] = contents
    try:
        resp = httpx.post(f"{EXA_API_BASE}/search", json=body, headers=_headers(), timeout=EXA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("results") is None:
            return f"Exa search returned no results. Response: {json.dumps(data)[:400]}"
        return _fmt_search_results(data, int(numResults))
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:300]
        logger.warning("Exa search HTTP %s: %s", e.response.status_code, detail)
        return f"Exa search failed (HTTP {e.response.status_code}): {detail}"
    except Exception as e:
        logger.exception("Exa search error")
        return f"Exa search error: {e}"


def web_search_advanced_exa(query: str = "", numResults: int = 10, type: str = "auto",
                            category: str = "", includeDomains: list | None = None,
                            excludeDomains: list | None = None, startPublishedDate: str = "",
                            endPublishedDate: str = "", includeText: list | None = None,
                            enableSummary: bool = False, enableHighlights: bool = False,
                            highlightsQuery: str = "", livecrawl: str = "fallback") -> str:
    return web_search_exa(
        query=query,
        numResults=numResults,
        type=type,
        category=category,
        includeDomains=includeDomains,
        excludeDomains=excludeDomains,
        startPublishedDate=startPublishedDate,
        endPublishedDate=endPublishedDate,
        includeText=includeText,
        enableSummary=enableSummary,
        enableHighlights=enableHighlights,
        highlightsQuery=highlightsQuery,
        livecrawl=livecrawl,
    )


def web_fetch_exa(urls: list | str = None, textMaxCharacters: int = 5000,
                  livecrawl: str = "fallback") -> str:
    if not _api_key():
        return "EXA_API_KEY not configured. Add it to config.yaml or .env."
    if isinstance(urls, str):
        urls = [urls]
    urls = [u for u in (urls or []) if u]
    if not urls:
        return "No URLs provided to fetch."
    body = {
        "ids": urls,
        "text": {"maxCharacters": int(textMaxCharacters)},
        "livecrawl": livecrawl,
    }
    try:
        resp = httpx.post(f"{EXA_API_BASE}/contents", json=body, headers=_headers(), timeout=EXA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return f"Exa fetch returned no content for: {', '.join(urls)}"
        parts = []
        for r in results:
            parts.append(f"# {r.get('title', 'N/A')}")
            parts.append(f"URL: {r.get('url', '')}")
            text = r.get("text", "")
            parts.append(text if text else "(No extractable text — the page may be a paywalled or image-based PDF)")
        return "\n\n".join(parts)
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:300]
        logger.warning("Exa fetch HTTP %s: %s", e.response.status_code, detail)
        return f"Exa fetch failed (HTTP {e.response.status_code}): {detail}"
    except Exception as e:
        logger.exception("Exa fetch error")
        return f"Exa fetch error: {e}"
