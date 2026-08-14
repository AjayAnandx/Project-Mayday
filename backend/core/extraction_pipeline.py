"""Universal data analysis pipeline core: web search + fetch, LLM extraction, batch store."""
import json
import logging
import re
from datetime import datetime, timezone

import httpx

from backend.core.config import load_config
from backend.core.report_generator import suggest_chart_type  # noqa: F401 (re-export)

logger = logging.getLogger(__name__)

EXA_API_BASE = "https://api.exa.ai"
EXA_TIMEOUT = httpx.Timeout(connect=10, read=60, write=30, pool=10)

_YEAR_RE = re.compile(r"^\d{4}$")
_TIME_VAL_RE = re.compile(r"^(Q[1-4]\s?\d{4}|\d{4}|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s/-]\d{4}|\d{4}[-/]\d{1,2})$", re.I)


def _exa_key() -> str:
    cfg = load_config()
    key = cfg.get("mcp", {}).get("servers", {}).get("exa", {}).get("env", {}).get("EXA_API_KEY", "")
    return key or __import__("os").environ.get("EXA_API_KEY", "")


def _extract_numeric(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
    if not text:
        return None
    multipliers = {"B": 1e9, "M": 1e6, "K": 1e3, "%": 1}
    suffix = text[-1].upper()
    if suffix in multipliers and len(text) > 1:
        try:
            return float(text[:-1].strip()) * multipliers[suffix]
        except ValueError:
            pass
    try:
        return float(text)
    except ValueError:
        return None


def _is_time_value(value) -> bool:
    text = _fmt_scalar(value).strip()
    return bool(_YEAR_RE.match(text) or _TIME_VAL_RE.match(text))


def _fmt_scalar(value) -> str:
    """Render a scalar cleanly for labels: 2020.0 -> '2020', keep others as-is."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ── Phase 1: Search + fetch ───────────────────────────────────────

def web_search_and_fetch(query: str, max_sources: int = 10, source_type: str = "web") -> list[dict]:
    """Exa search → fetch page text. Returns [{url, title, content, score}]."""
    if not query:
        return []
    if not _exa_key():
        return [{"error": "EXA_API_KEY not configured. Add it to config.yaml or .env."}]

    body: dict = {
        "query": query,
        "numResults": int(max_sources),
        "type": "auto",
        "contents": {"text": {"maxCharacters": 3000}},
    }
    category = {"news": "news", "academic": "paper"}.get(source_type or "web")
    if category:
        body["category"] = category

    try:
        resp = httpx.post(f"{EXA_API_BASE}/search", json=body,
                          headers={"x-api-key": _exa_key(), "Content-Type": "application/json"},
                          timeout=EXA_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("results", []):
            url = r.get("url", "")
            if not url:
                continue
            results.append({
                "url": url,
                "title": r.get("title", ""),
                "content": (r.get("text", "") or "")[:3000],
                "score": r.get("score", 0.5),
                "published_date": (r.get("publishedDate") or "")[:10],
            })
        return results
    except httpx.HTTPStatusError as e:
        logger.warning("Exa search HTTP %s: %s", e.response.status_code, e.response.text[:200])
        return [{"error": f"Exa search failed (HTTP {e.response.status_code})"}]
    except Exception as e:
        logger.exception("Exa search error")
        return [{"error": f"Exa search error: {e}"}]


# ── Phase 1: LLM extraction ───────────────────────────────────────

def _normalize_columns(cols) -> list[str]:
    """Coerce schema column entries (strings or {'name': ...} objects) to strings.

    LLMs frequently emit columns as objects like [{"name": "year"}] instead of
    plain strings; hashing/looking up such entries in the types dict raises
    'unhashable type: dict'. Normalize to plain names first.
    """
    names: list[str] = []
    for c in cols or []:
        if isinstance(c, str):
            names.append(c)
        elif isinstance(c, dict):
            name = None
            for key in ("name", "column", "title", "label"):
                v = c.get(key)
                if isinstance(v, str) and v.strip():
                    name = v.strip()
                    break
            names.append(name if name is not None else str(c))
        else:
            names.append(str(c))
    return names


def _column_type_hint(types: dict, col: str) -> str:
    """Return a scalar string type hint for a column, never a dict (LLM quirk)."""
    t = types.get(col, "string")
    if isinstance(t, dict):
        t = t.get("type") or t.get("name") or "string"
    if not isinstance(t, str):
        t = "string"
    return t


def extract_data_from_sources(sources: list[dict], schema: dict | None = None,
                              context: str = "") -> list[dict]:
    """Use the local LLM to extract structured rows from fetched web content.

    schema = {"columns": [..], "types": {col: "int|float|str"}} — optional; the
    LLM infers columns when omitted. Returns a list of row dicts.
    """
    from backend.assistant.llm_client import LLMClient

    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except (json.JSONDecodeError, TypeError):
            schema = None
    if not isinstance(schema, dict):
        schema = None

    cols = _normalize_columns((schema or {}).get("columns") or [])
    raw_types = (schema or {}).get("types") or {}
    types = raw_types if isinstance(raw_types, dict) else {}
    type_hint = ", ".join(f"{c} ({_column_type_hint(types, c)})" for c in cols) if cols else "infer sensible columns from the data"

    sources_text = []
    for i, s in enumerate(sources[:8], 1):
        if not isinstance(s, dict):
            # Skip malformed entries instead of crashing on s.get(...)
            continue
        title = s.get("title", "")
        url = s.get("url", "")
        content = (s.get("content", "") or "")[:2500]
        sources_text.append(f"[Source {i}] {title} ({url})\n{content}")
    joined = "\n\n".join(sources_text) if sources_text else "(no source content)"

    prompt = (
        "You extract structured tabular data from web research sources. "
        "Extract every relevant numeric data point you find; do not invent values. "
        f"Columns must be: {type_hint}.\n"
        f"Context: {context or '(general)'}\n\n"
        f"SOURCES:\n{joined}\n\n"
        "Respond with ONLY a JSON array of row objects conforming to those columns, "
        "e.g. [{\"year\": 2020, \"role\": \"ML Engineer\", \"postings\": 12500}]. "
        "Use numbers without thousands separators. If nothing extractable, respond with []."
    )
    messages = [
        {"role": "system", "content": "You are a precise data extraction engine. Output raw JSON only."},
        {"role": "user", "content": prompt},
    ]

    try:
        llm = LLMClient()
        resp = llm.chat(messages, stream=False, tools=[])
        resp.raise_for_status()
        content, _ = llm.extract_response(resp)
        return _parse_json_rows(content or "")
    except Exception as e:
        logger.exception("Extraction LLM call failed")
        return [{"error": f"Extraction failed: {e}"}]


def _parse_json_rows(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


# ── Phase 1: Batch store as data points ───────────────────────────

def _rows_to_data_points(rows: list[dict]) -> list[dict]:
    """Expand extracted rows into {label, value, unit, confidence} data points.

    Labels carry a 'series | point' marker when a time column exists so the
    chart builder can render multi-series line charts.
    """
    dps: list[dict] = []
    for idx, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        numeric_cols = {}
        time_cols = {}
        other_cols = {}
        for k, v in row.items():
            if v is None:
                continue
            if _extract_numeric(v) is not None and not _is_time_value(v):
                numeric_cols[str(k)] = v
            elif _is_time_value(v):
                time_cols[str(k)] = v
            else:
                other_cols[str(k)] = v

        if not numeric_cols:
            continue

        series_label = " / ".join(_fmt_scalar(v) for v in other_cols.values()) if other_cols else f"row {idx}"
        time_val = next(iter(time_cols.values()), None)

        for col, val in numeric_cols.items():
            time_str = _fmt_scalar(time_val) if time_val is not None else None
            if time_str is not None and len(numeric_cols) > 1:
                label = f"{series_label} {col} | {time_str}"
            elif time_str is not None:
                label = f"{series_label} | {time_str}"
            elif len(numeric_cols) > 1:
                label = f"{series_label} {col}"
            else:
                label = series_label
            dps.append({
                "label": str(label),
                "value": str(val),
                "unit": str(col) if len(numeric_cols) > 1 else "",
                "confidence": "medium",
                "sources": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
    return dps


def batch_add_data_points(topic: str, data_points: list[dict], store_type: str = "research") -> dict:
    """Store extracted rows (dicts) as data points in a research topic or project."""
    rows = data_points if isinstance(data_points, list) else []
    if not rows:
        return {"error": "No data points to store — extraction returned no rows."}
    if any("error" in r for r in rows if isinstance(r, dict)):
        errors = [r["error"] for r in rows if isinstance(r, dict) and "error" in r]
        return {"error": f"Source/extraction error: {errors[0]}"}

    converted = []
    for r in rows:
        if isinstance(r, dict) and "label" in r and "value" in r:
            converted.append({
                "label": _fmt_scalar(r["label"]),
                "value": _fmt_scalar(r["value"]),
                "unit": str(r.get("unit", "") or ""),
                "confidence": str(r.get("confidence", "medium") or "medium"),
                "sources": r.get("sources") or [],
            })
        else:
            converted.extend(_rows_to_data_points([r]))
    if not converted:
        return {"error": "No numeric data found in the extracted rows."}

    if store_type == "project":
        from backend.core.project_store import get_project_store
        store = get_project_store()
        project = store.find_project_by_name(topic)
        if not project:
            return {"error": f"Project '{topic}' not found — create it first with create_project."}
        project_id = project["id"]
        stored = []
        for dp in converted:
            stored.append(store.add_data_point(
                project_id, dp["label"], dp["value"],
                dp.get("unit", ""), dp.get("confidence", "medium"), dp.get("sources") or [],
            ))
        return {
            "store_type": "project",
            "topic": topic,
            "project_id": project_id,
            "stored_count": len(stored),
            "data_points": stored,
            "suggested_chart": suggest_chart_type(stored, topic),
        }

    from backend.core.research_store import get_research_store
    store = get_research_store()
    project = store._get_by_topic(topic)
    if not project:
        created = store.create_research(topic, "market", 2)
        if "error" in created:
            return {"error": f"Could not create research '{topic}': {created['error']}"}
    stored = []
    for dp in converted:
        stored.append(store.add_data_point(
            topic, dp["label"], dp["value"],
            dp.get("unit", ""), dp.get("confidence", "medium"), dp.get("sources") or [],
        ))
    return {
        "store_type": "research",
        "topic": topic,
        "stored_count": len(stored),
        "data_points": stored,
        "suggested_chart": suggest_chart_type(stored, topic),
    }