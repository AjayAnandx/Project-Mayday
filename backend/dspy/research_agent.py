"""Module B — RL Multi-Hop Research Agent (Mode A: self-contained LLM tool).

A single tool the chat engine calls once. The agent runs its own bounded hop
loop internally (the chat engine's 20-iteration loop, duplicate guard, and
tools=[] rule stay untouched). Each hop dispatches an EXISTING research tool
through ``dispatch_call`` — reusing the same arg-repair safety net and operation-log
recording. A deterministic gap score (metrics.gap_score) drives termination; the
RL reward signal (metrics.per_hop_reward) is accumulated per hop.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

try:
    import dspy  # type: ignore

    _DSPY = dspy
except Exception:  # pragma: no cover
    dspy = None  # type: ignore
    _DSPY = None


if _DSPY is not None:

    class ResearchHop(_DSPY.Signature):
        """Decide the next research action given current state. Actions are typed."""

        topic: str = _DSPY.InputField()
        research_type: str = _DSPY.InputField()
        research_questions: list[str] = _DSPY.InputField()
        task_title: str = _DSPY.InputField(desc="current task from store")
        collected: list[dict] = _DSPY.InputField(desc="data_points+entities+findings so far")
        last_observation: str = _DSPY.InputField(desc="result of the previous action or ''")
        score: float = _DSPY.InputField(desc="current deterministic gap score 0..1")
        feedback: str = _DSPY.InputField(desc="gap feedback from checker")
        next_action: str = _DSPY.OutputField(
            desc="one of: web_search_and_fetch | extract_data_from_sources | "
            "batch_add_data_points | add_finding | finish"
        )
        args: dict = _DSPY.OutputField(desc="valid args for next_action; finish => {}")

    class GapChecker(_DSPY.Signature):
        """Score research progress and produce actionable gap feedback (GEPA pattern)."""

        research_questions: list[str] = _DSPY.InputField()
        task_title: str = _DSPY.InputField()
        collected: list[dict] = _DSPY.InputField()
        score: float = _DSPY.OutputField(desc="0..1, deterministic metric verdict")
        feedback: str = _DSPY.OutputField(desc="unanswered questions, low-confidence findings, missing sources")

else:  # pragma: no cover
    ResearchHop = None
    GapChecker = None


_COMPILED_HOP = None


def _get_hop_predictor():
    global _COMPILED_HOP
    if _COMPILED_HOP is not None:
        return _COMPILED_HOP
    predictor = None
    try:
        from backend.dspy.bridge import get_bridge

        art = get_bridge().artifacts_dir / "ResearchHop.json"
        if art.exists():
            predictor = ResearchHop()
            predictor.load(str(art))
    except Exception:
        predictor = None
    if predictor is None:
        predictor = _DSPY.Predict(ResearchHop)
    _COMPILED_HOP = predictor
    return predictor


ALLOWED_ACTIONS = {
    "web_search_and_fetch",
    "extract_data_from_sources",
    "batch_add_data_points",
    "add_finding",
    "finish",
}

_HOP_FIELDS = {
    "web_search_and_fetch": ["query"],
    "extract_data_from_sources": ["sources"],
    "batch_add_data_points": ["topic", "data_points"],
    "add_finding": ["topic", "content"],
}


def _current_task(project: dict) -> Optional[str]:
    for t in project.get("tasks", []) or []:
        if t.get("status") == "in_progress":
            return t.get("title") or t.get("task_id")
    return None


def _collect(project: dict) -> list[dict]:
    out: list[dict] = []
    for dp in project.get("data_points", []) or []:
        out.append({"kind": "data_point", "label": dp.get("label"), "value": dp.get("value")})
    for e in project.get("entities", []) or []:
        out.append({"kind": "entity", "name": e.get("name"), "type": e.get("type")})
    for f in project.get("findings", []) or []:
        out.append({"kind": "finding", "content": f.get("content")})
    return out


def predict_hop(
    project: dict,
    questions: list[str],
    task_title: Optional[str],
    collected: list[dict],
    last_observation: str,
    score: float,
    feedback: str,
) -> tuple[str, dict]:
    """Return (next_action, args). Falls back to 'finish' on any error."""
    if _DSPY is None or ResearchHop is None:
        return "finish", {}
    from backend.dspy.bridge import get_bridge

    try:
        pred = _get_hop_predictor()

        def _call():
            return pred(
                topic=project.get("topic", ""),
                research_type=project.get("type", "market"),
                research_questions=questions,
                task_title=task_title or "",
                collected=collected,
                last_observation=last_observation or "",
                score=score,
                feedback=feedback,
            )

        out = get_bridge().call_with_fallback(_call)
        action = (out.next_action or "finish").strip().lower()
        if action not in ALLOWED_ACTIONS:
            action = "finish"
        args = out.args if isinstance(out.args, dict) else {}
        return action, args
    except Exception:
        return "finish", {}


def _normalize_args(action: str, args: dict, topic: str) -> dict:
    """Ensure the action has the minimal args it needs (topic is implicit)."""
    a = dict(args or {})
    if action in ("batch_add_data_points", "add_finding") and "topic" not in a:
        a["topic"] = topic
    if action == "web_search_and_fetch" and "query" not in a and "topic" not in a:
        a["query"] = topic
    return a


async def run_research_agent(
    topic: str,
    max_hops: int | None = None,
    auto_report: bool = True,
    dispatch: Optional[Callable[[str, dict], Awaitable[str]]] = None,
    hop_predictor=None,
) -> str:
    """Bounded multi-hop research loop. Returns a human-readable progress summary.

    ``dispatch`` must be an async callable (name, args) -> str (typically
    function_registry.dispatch_call). ``hop_predictor`` overrides predict_hop for tests.
    """
    from backend.core.research_store import get_research_store
    from backend.dspy import get_bridge
    from backend.dspy.metrics import gap_score, gap_feedback, per_hop_reward

    store = get_research_store()
    project = store._get_by_topic(topic)
    if not project:
        return f"Research '{topic}' not found — cannot run research agent."

    bridge = get_bridge()
    budget = max_hops or bridge.max_hops or 12

    # Import the real dispatcher lazily to avoid a hard import cycle at module load.
    if dispatch is None:
        from backend.assistant.function_registry import dispatch_call as _dc

        async def _wrap(name: str, args: dict):
            return await _dc(name, args)

        dispatch = _wrap

    questions = project.get("research_questions", []) or []
    task_title = _current_task(project)

    log: list[str] = [f"Research agent started for '{topic}' (budget={budget})."]
    last_actions: list[str] = []
    rollout_reward = 0.0
    last_obs = ""

    for hop in range(budget):
        collected = _collect(project)
        # Re-read project so newly stored data points are visible.
        project = store._get_by_topic(topic) or project
        score = gap_score(project, questions, collected)
        feedback = gap_feedback(project, questions, collected)

        if score >= 0.9 and questions:
            log.append(f"  hop {hop}: gap score {score:.2f} >= 0.9 → finish.")
            break
        if not questions and collected:
            log.append(f"  hop {hop}: no questions and data collected → finish.")
            break

        if hop_predictor is not None:
            action, args = hop_predictor(project, questions, task_title, collected, last_obs, score, feedback)
        else:
            action, args = predict_hop(project, questions, task_title, collected, last_obs, score, feedback)

        if action not in ALLOWED_ACTIONS:
            action = "finish"
        if action == "finish":
            log.append(f"  hop {hop}: agent chose finish (score {score:.2f}).")
            break

        args = _normalize_args(action, args, topic)
        # Dedup guard (mirrors chat engine 3x duplicate guard).
        sig = f"{action}:{sorted((k, str(v)) for k, v in args.items())}"
        if last_actions.count(sig) >= 2:
            log.append(f"  hop {hop}: repeated identical hop → penalty, forcing finish.")
            rollout_reward += per_hop_reward(action, valid=True, repeated=True)
            break
        last_actions.append(sig)

        try:
            result = await dispatch(action, args)
        except Exception as exc:
            log.append(f"  hop {hop}: {action} errored: {exc}")
            break

        # Reward: valid action + new data points / coverage gained.
        before = project
        project = store._get_by_topic(topic) or project
        new_dps = len(project.get("data_points", [])) - len(before.get("data_points", []))
        newly_covered = 0
        if questions:
            s0 = gap_score(before, questions)
            s1 = gap_score(project, questions)
            newly_covered = max(0, int(round((s1 - s0) * len(questions))))
        reward = per_hop_reward(
            action, valid=True, new_data_points=max(0, new_dps), newly_covered=newly_covered
        )
        rollout_reward += reward
        last_obs = (result or "")[:300]
        log.append(f"  hop {hop}: {action} → +{reward:.1f} (score {score:.2f}); obs={last_obs[:80]!r}")

    final_project = store._get_by_topic(topic) or project
    final_score = gap_score(final_project, questions, _collect(final_project))
    log.append(f"Research agent done. Final gap score {final_score:.2f}, rollout reward {rollout_reward:.1f}.")
    if final_score < 0.5 and questions:
        log.append("Weak coverage — logging gap review note.")
        try:
            from backend.functions.research_functions import add_research_note

            add_research_note(
                topic=topic,
                filename="gap_review.md",
                content="\n".join(log),
                force=True,
            )
        except Exception:
            pass

    if auto_report:
        try:
            from backend.functions.research_functions import generate_report

            rep = generate_report(topic, format="md", synthesis=None)
            log.append(rep.splitlines()[0] if rep else "Report generated.")
        except Exception as exc:
            log.append(f"(report step skipped: {exc})")

    return "\n".join(log)
