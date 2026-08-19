"""Module A — DSPy Report Synthesis signatures + predictors.

All signature classes are defined only when dspy is importable, so this module
never raises on import in a dspy-less environment. The predictor helpers are
no-ops (return None) unless the bridge is enabled AND an LM is configured.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    import dspy

    _DSPY = dspy
except Exception:  # pragma: no cover - depends on environment
    dspy = None  # type: ignore
    _DSPY = None


if _DSPY is not None:

    class ExecutiveSummary(_DSPY.Signature):
        """Synthesize an executive summary from structured research data."""

        research_questions: list[str] = _DSPY.InputField()
        data_points: list[dict] = _DSPY.InputField(desc="list of {label,value,unit,confidence,sources}")
        entities: list[dict] = _DSPY.InputField()
        findings: list[dict] = _DSPY.InputField()
        executive_summary: str = _DSPY.OutputField(
            desc="3-5 sentences; every number cited must come from the inputs"
        )

    class AnswerResearchQuestions(_DSPY.Signature):
        """Answer each research question using only the provided data; mark gaps."""

        research_questions: list[str] = _DSPY.InputField()
        data_points: list[dict] = _DSPY.InputField()
        findings: list[dict] = _DSPY.InputField()
        answers: list[dict] = _DSPY.OutputField(
            desc="list of {'question':str,'answer':str,'confidence':str,'answered':bool}"
        )

    class SynthesisNarrative(_DSPY.Signature):
        """Narrative synthesis per section (key entities / data points / findings)."""

        topic: str = _DSPY.InputField()
        section: str = _DSPY.InputField(desc="one of 'entities' | 'data_points' | 'findings'")
        inputs: list[dict] = _DSPY.InputField(desc="the items for this section")
        narrative: str = _DSPY.OutputField(desc="2-4 paragraphs, grounded strictly in inputs")

else:  # pragma: no cover - depends on environment
    ExecutiveSummary = None
    AnswerResearchQuestions = None
    SynthesisNarrative = None


# Lazily-loaded compiled predictors (Module A). At runtime, if a compiled artifact
# exists under the bridge's artifacts_dir, it is loaded once; otherwise the plain
# Predict is used. No LM call happens at import or startup.
_COMPILED: dict[str, Any] = {}


def _get_predictor(name: str, sig_cls) -> Any:
    if name in _COMPILED:
        return _COMPILED[name]
    predictor = None
    try:
        from backend.dspy.bridge import get_bridge

        art = get_bridge().artifacts_dir / f"{name}.json"
        if art.exists():
            predictor = sig_cls()
            predictor.load(str(art))
    except Exception:
        predictor = None
    if predictor is None:
        predictor = _DSPY.Predict(sig_cls)
    _COMPILED[name] = predictor
    return predictor


def _project_payload(project: dict) -> dict:
    return {
        "research_questions": project.get("research_questions", []) or [],
        "data_points": project.get("data_points", []) or [],
        "entities": project.get("entities", []) or [],
        "findings": project.get("findings", []) or [],
    }


def synthesize_summary(project: dict) -> Optional[str]:
    if _DSPY is None or ExecutiveSummary is None:
        return None
    from backend.dspy.bridge import get_bridge

    try:
        pred = _get_predictor("ExecutiveSummary", ExecutiveSummary)

        def _call():
            return pred(**_project_payload(project))

        out = get_bridge().call_with_fallback(_call)
        return (out.executive_summary or "").strip() or None
    except Exception:
        return None


def synthesize_answers(project: dict) -> Optional[list[dict]]:
    if _DSPY is None or AnswerResearchQuestions is None:
        return None
    from backend.dspy.bridge import get_bridge

    try:
        pred = _get_predictor("AnswerResearchQuestions", AnswerResearchQuestions)

        def _call():
            return pred(**_project_payload(project))

        out = get_bridge().call_with_fallback(_call)
        ans = out.answers
        if isinstance(ans, list):
            return [a for a in ans if isinstance(a, dict)]
        return None
    except Exception:
        return None


def synthesize_narrative(project: dict, section: str, items: list[dict]) -> Optional[str]:
    if _DSPY is None or SynthesisNarrative is None:
        return None
    from backend.dspy.bridge import get_bridge

    try:
        pred = _get_predictor("SynthesisNarrative", SynthesisNarrative)

        def _call():
            return pred(topic=project.get("topic", ""), section=section, inputs=items)

        out = get_bridge().call_with_fallback(_call)
        return (out.narrative or "").strip() or None
    except Exception:
        return None
