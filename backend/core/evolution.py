import json
import logging
import re
from datetime import datetime, timezone

from backend.memory.knowledge_graph import get_graph
from backend.core.operation_log import get_operation_log

logger = logging.getLogger(__name__)


def run_post_mortem(
    project_name: str,
    user_text: str,
    iteration_count: int,
    errors: list[str] | None = None,
    opencode_used: bool = False,
    tool_calls_list: list[dict] | None = None,
):
    if not project_name:
        return
    kg = get_graph()
    ol = get_operation_log()

    ops = ol.query(query=project_name, action=None, entity_type=None, limit=50)

    def _detail_has_error(details) -> bool:
        if isinstance(details, str):
            return "error" in details.lower() or "fail" in details.lower()
        if isinstance(details, dict):
            return any("error" in str(v).lower() or "fail" in str(v).lower() for v in details.values())
        return False

    failed_ops = [o for o in ops if _detail_has_error(o.get("details", ""))]
    tool_call_count = len(tool_calls_list) if tool_calls_list else 0
    error_count = len(errors) if errors else len(failed_ops)
    build_score = max(0.0, 1.0 - (error_count / max(tool_call_count, 1)))

    what_worked: list[str] = []
    what_failed: list[str] = []
    user_corrections: list[str] = []

    _RE_RESOLVE_EVO = re.compile(r"Can't resolve|Cannot find module|TS2307|TS2305|Module not found|Failed to resolve import|Cannot find package|ERR_MODULE_NOT_FOUND", re.I)
    if tool_calls_list:
        for tc in tool_calls_list:
            fn_name = tc.get("function", {}).get("name", "")
            res_low = str(tc.get("result", ""))
            if "error" in res_low.lower() or "fail" in res_low.lower() or bool(_RE_RESOLVE_EVO.search(res_low)):
                what_failed.append(f"{fn_name}: {tc.get('result', '')[:100]}")
            elif "wrote" in str(tc.get("result", "")).lower() or "replaced" in str(tc.get("result", "")).lower():
                what_worked.append(f"{fn_name} succeeded")

    if errors:
        what_failed.extend(errors)

    project_type = _infer_project_type(project_name, user_text)

    lesson_id = kg.add_node("build_lesson", f"build:{project_name}/{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}", {
        "project_type": project_type,
        "project_name": project_name,
        "what_worked": json.dumps(what_worked),
        "what_failed": json.dumps(what_failed),
        "user_corrections": json.dumps(user_corrections),
        "build_score": str(build_score),
        "iterations_used": str(iteration_count),
        "tool_calls": str(tool_call_count),
        "errors_encountered": json.dumps(errors or []),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    logger.info("Post-mortem for '%s': score=%.2f, worked=%d, failed=%d, corrections=%d, node=%s",
        project_name, build_score, len(what_worked), len(what_failed), len(user_corrections), lesson_id)

    extract_preferences()


def extract_preferences():
    kg = get_graph()
    lessons = _get_build_lessons(kg)

    patterns: dict[str, dict] = {}
    for lesson in lessons:
        props = lesson.get("properties", {})
        ptype = props.get("project_type", "unknown")
        if ptype not in patterns:
            patterns[ptype] = {"preferred": {}, "avoided": {}, "corrections": {}}

        for item in json.loads(props.get("what_worked", "[]")):
            key = _normalize_pattern(item)
            patterns[ptype]["preferred"][key] = patterns[ptype]["preferred"].get(key, 0) + 1

        for item in json.loads(props.get("what_failed", "[]")):
            key = _normalize_pattern(item)
            patterns[ptype]["avoided"][key] = patterns[ptype]["avoided"].get(key, 0) + 1

        for item in json.loads(props.get("user_corrections", "[]")):
            key = _normalize_pattern(item)
            patterns[ptype]["corrections"][key] = patterns[ptype]["corrections"].get(key, 0) + 1

    total_builds = len(lessons)
    for ptype, data in patterns.items():
        for pattern, count in data["preferred"].items():
            confidence = count / max(total_builds, 1)
            _store_preference(kg, ptype, pattern, "preferred", confidence, count)

        for pattern, count in data["avoided"].items():
            if count >= 2:
                confidence = count / max(total_builds, 1)
                _store_preference(kg, ptype, pattern, "avoided", confidence, count)

        for pattern, count in data["corrections"].items():
            if count >= 1:
                confidence = count / max(total_builds, 1)
                _store_preference(kg, ptype, pattern, "correction", confidence, count)

    logger.info("Extracted preferences for %d project types", len(patterns))


def get_relevant_preferences(project_name: str = "", project_type: str = "") -> str:
    kg = get_graph()
    if not project_type and project_name:
        project_type = _infer_project_type(project_name, "")

    lines: list[str] = []
    seen: set[str] = set()

    for node in kg.get_nodes_by_type("preference"):
        props = node.get("properties", {})
        if props.get("project_type") != project_type and props.get("project_type") != "any":
            continue

        rule = props.get("rule", "")
        if rule in seen:
            continue
        seen.add(rule)

        confidence = float(props.get("confidence", 0))
        ptype = props.get("category", "preferred")
        icon = {"preferred": "+", "avoided": "-", "correction": "!"}.get(ptype, "?")

        lines.append(f"  {icon} [{ptype}] {rule} (confidence: {confidence:.0%})")

    if not lines:
        return ""

    total = len(kg.get_nodes_by_type("build_lesson"))
    return f"\n### Learned Preferences (from {total} past build(s)):\n" + "\n".join(lines) + "\n###"


def _infer_project_type(project_name: str, user_text: str) -> str:
    combined = f"{project_name} {user_text}".lower()
    if any(w in combined for w in ("portfolio", "showcase", "gallery")):
        return "portfolio"
    if any(w in combined for w in ("landing", "landing page", "marketing")):
        return "landing"
    if any(w in combined for w in ("dashboard", "admin", "analytics", "stats")):
        return "dashboard"
    if any(w in combined for w in ("blog", "article", "news", "magazine")):
        return "blog"
    if any(w in combined for w in ("shop", "store", "ecommerce", "commerce")):
        return "ecommerce"
    if any(w in combined for w in ("docs", "documentation", "wiki")):
        return "docs"
    if any(w in combined for w in ("app", "webapp", "application", "tool")):
        return "webapp"
    return "general"


def _normalize_pattern(text: str) -> str:
    text = text.lower().strip()
    for prefix in ("opencode_write succeeded", "opencode_edit succeeded"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text


def _store_preference(kg, project_type: str, rule: str, category: str, confidence: float, count: int):
    if not rule:
        return
    label = f"pref:{project_type}/{category}/{rule[:40]}"
    for node in kg.get_nodes_by_type("preference"):
        if node.get("properties", {}).get("rule") == rule:
            props = node["properties"]
            old_count = int(props.get("confirmation_count", 0))
            props["confirmation_count"] = str(old_count + count)
            props["confidence"] = str(min(1.0, confidence * 1.1))
            props["updated_at"] = datetime.now(timezone.utc).isoformat()
            kg._save()
            return

    kg.add_node("preference", label, {
        "project_type": project_type,
        "category": category,
        "rule": rule,
        "confidence": str(confidence),
        "confirmation_count": str(count),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def _get_build_lessons(kg):
    return kg.get_nodes_by_type("build_lesson")


