"""LLM tool wrappers for the universal data analysis pipeline (Phase 1)."""
import json
import re

from backend.core.extraction_pipeline import (
    web_search_and_fetch as _search_and_fetch,
    extract_data_from_sources as _extract,
    batch_add_data_points as _batch_add,
)


def web_search_and_fetch(query: str, max_sources: int = 10, source_type: str = "web") -> str:
    """Search the web (Exa) and fetch page content — returns source list for extraction."""
    if not query or not query.strip():
        return "Missing required parameter: query."
    results = _search_and_fetch(query, int(max_sources), source_type)
    if not results:
        return "No sources found."
    if len(results) == 1 and "error" in results[0]:
        return f"Error: {results[0]['error']}"
    lines = [f"Found {len(results)} sources for '{query}':"]
    for i, r in enumerate(results, 1):
        lines.append(f"  {i}. **{r.get('title', 'Untitled')}** — {r.get('url', '')}")
        snippet = (r.get("content", "") or "")[:200].replace("\n", " ")
        if snippet:
            lines.append(f"     {snippet}…")
    # Append a machine-readable block so the result can be fed directly into
    # extract_data_from_sources without the LLM having to reconstruct dicts.
    lines.append("\n---\nSOURCES_JSON:")
    lines.append("```json")
    lines.append(json.dumps(results, ensure_ascii=False))
    lines.append("```")
    return "\n".join(lines)


def _coerce_sources(sources) -> list | str:
    """Normalize whatever the LLM passed into a list of source dicts.

    Accepts: a list of dicts, a JSON string of dicts, the markdown output of
    web_search_and_fetch (with an embedded SOURCES_JSON block), or a single dict.
    Returns the coerced list, or an error string if it cannot be parsed.
    """
    if not sources:
        return "Missing required parameter: sources (list of {url, title, content})."
    if isinstance(sources, dict):
        return [sources]
    if isinstance(sources, str):
        text = sources.strip()
        # Prefer an embedded SOURCES_JSON fenced block from web_search_and_fetch.
        m = re.search(r"SOURCES_JSON:\s*```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)
        else:
            # Strip any surrounding markdown fences if present.
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return ("Error: 'sources' must be a JSON list of {url, title, content} objects. "
                    "Pass the raw result of web_search_and_fetch (it includes a SOURCES_JSON block), "
                    "or a JSON list of source dicts.")
        return parsed
    return sources


def extract_data_from_sources(sources: list, schema: dict | None = None, context: str = "") -> str:
    """Extract structured rows (JSON) from fetched web sources via the LLM."""
    coerced = _coerce_sources(sources)
    if isinstance(coerced, str):
        return coerced
    sources = coerced
    if not isinstance(sources, list) or not sources:
        return "Error: 'sources' must be a non-empty list of {url, title, content} objects."
    rows = _extract(sources, schema, context or "")
    if not rows:
        return "Extraction produced no rows — the sources may not contain tabular data."
    if len(rows) == 1 and "error" in rows[0]:
        return f"Error: {rows[0]['error']}"
    summary = f"Extracted **{len(rows)}** rows. First rows:\n"
    for r in rows[:5]:
        summary += "  - " + ", ".join(f"{k}: {v}" for k, v in r.items()) + "\n"
    return summary.strip()


def search_academic(query: str, max_sources: int = 20, difficulty: int = 5) -> str:
    """Academic search: arXiv → DOI → OpenAlex 3-corpus fan with citation rerank. Use for academic/technical literature, papers, citations."""
    if not query or not query.strip():
        return "Missing required parameter: query."
    try:
        from backend.core.academic_search import academic_search as _academic
    except Exception as e:
        return f"Error: academic search unavailable: {e}"
    results = _academic(query, max_sources=int(max_sources), difficulty=int(difficulty))
    if not results:
        return "No academic sources found."
    if len(results) == 1 and "error" in results[0]:
        return f"Error: {results[0]['error']}"
    lines = [f"Found {len(results)} academic sources for '{query}':"]
    for i, r in enumerate(results, 1):
        doi_str = f" DOI:{r.get('doi')}" if r.get("doi") else ""
        cite_str = f" cites:{r.get('citationCount')}" if r.get("citationCount") is not None else ""
        lines.append(f"  {i}. **{r.get('title', 'Untitled')}** — {r.get('url', '')}{doi_str}{cite_str} [{r.get('corpus','')}]")
        snippet = (r.get("content", "") or "")[:200].replace("\n", " ")
        if snippet:
            lines.append(f"     {snippet}…")
    lines.append("\n---\nSOURCES_JSON:")
    lines.append("```json")
    lines.append(json.dumps(results, ensure_ascii=False))
    lines.append("```")
    return "\n".join(lines)


def batch_add_data_points(topic: str, data_points: list, store_type: str = "research") -> str:
    """Bulk-store extracted rows as data points in a research topic or project (auto-creates research)."""
    if not topic or not topic.strip():
        return "Missing required parameter: topic."
    if isinstance(data_points, str):
        try:
            data_points = json.loads(data_points)
        except json.JSONDecodeError:
            return "Error: 'data_points' must be a JSON list of row objects."
    result = _batch_add(topic.strip(), data_points, store_type)
    if "error" in result:
        return f"Error: {result['error']}"
    return json.dumps({
        "message": (
            f"Stored **{result['stored_count']}** data points in {result['store_type']} "
            f"**'{result['topic']}'**. Suggested chart type: {result.get('suggested_chart', 'bar')}. "
            f"Next: call generate_chart(topic=\"{result['topic']}\", chart_type=\"auto\")."
        ),
        "data": {
            "store_type": result["store_type"],
            "topic": result["topic"],
            "stored_count": result["stored_count"],
            "suggested_chart": result.get("suggested_chart", "bar"),
        },
    })