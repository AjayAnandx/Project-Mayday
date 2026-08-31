"""LLM-facing awareness functions.

Per the consolidation plan, only the retained awareness features are exposed:
onboarding questions, personal notes, and per-person briefs. Belief/confidence/
consent tooling was removed — personal facts now flow through `remember` into
the shared knowledge graph.
"""

from backend.core.user_awareness import get_awareness_store, SLOTS


def ask_user(question: str, slot: str = "context") -> str:
    store = get_awareness_store()
    slot = slot.strip().lower()
    if slot not in SLOTS:
        return f"Unknown slot '{slot}'. Valid: {', '.join(SLOTS)}"
    res = store.queue_question(slot, question)
    if "error" in res:
        return res["error"]
    return f"Queued onboarding question (id {res['id']}) for slot '{slot}': {question}"


def record_answer(question_id: str, answer: str, slot: str = "") -> str:
    store = get_awareness_store()
    res = store.record_answer(question_id, answer, slot=slot or None)
    if "error" in res:
        return res["error"]
    b = res["belief"]
    return f"Recorded answer to onboarding question {question_id}: learned [{b['slot']}] {b['value']}"


def person_brief(name: str) -> str:
    return get_awareness_store().person_brief(name)
