from backend.core.user_awareness import get_awareness_store, SLOTS
from backend.core.personal_notes import get_personal_notes_store


def _fmt_belief(b: dict) -> str:
    return (f"[{b['slot']}] {b['value']} (conf {b['confidence']:.2f}, "
            f"{b['provenance']}, {b['consent_tier']})")


def ask_user(question: str, slot: str = "context") -> str:
    store = get_awareness_store()
    slot = slot.strip().lower()
    if slot not in SLOTS:
        return f"Unknown slot '{slot}'. Valid: {', '.join(SLOTS)}"
    res = store.queue_question(slot, question)
    if "error" in res:
        return res["error"]
    return f"Queued onboarding question (id {res['id']}) for slot '{slot}': {question}"


def list_beliefs(slot: str = "", min_confidence: float = 0.0) -> str:
    store = get_awareness_store()
    beliefs = store.list_beliefs(slot=slot or None, min_confidence=min_confidence or None)
    if not beliefs:
        return "No beliefs stored yet." if not slot else f"No beliefs in slot '{slot}'."
    return "Known beliefs:\n" + "\n".join(_fmt_belief(b) for b in beliefs)


def update_belief(belief_id: str, value: str = "", confidence: float = 0.0,
                  consent_tier: str = "") -> str:
    store = get_awareness_store()
    fields = {}
    if value:
        fields["value"] = value
    if consent_tier:
        fields["consent_tier"] = consent_tier
    if confidence and confidence > 0:
        fields["confidence"] = confidence
    res = store.update_belief(belief_id, **fields)
    if "error" in res:
        return res["error"]
    return f"Updated belief {belief_id}: {_fmt_belief(res)}"


def confirm_belief(belief_id: str = "", value: str = "") -> str:
    store = get_awareness_store()
    res = store.confirm_belief(belief_id=belief_id, value=value)
    if "error" in res:
        return res["error"]
    return f"Confirmed belief: {_fmt_belief(res)}"


def create_personal_note(text: str, title: str = "", entities: list[str] | None = None,
                         tags: list[str] | None = None) -> str:
    store = get_personal_notes_store()
    res = store.create_note(text=text, title=title, entities=entities, tags=tags)
    if "error" in res:
        return res["error"]
    return f"Created personal note {res['id']}: {res['title']}"


def list_personal_notes() -> str:
    store = get_personal_notes_store()
    notes = store.list_notes()
    if not notes:
        return "No personal notes yet."
    return "Personal notes:\n" + "\n".join(
        f"- {n['id']}: {n['title']}" + (f" (entities: {', '.join(n['entities'])})" if n["entities"] else "")
        for n in notes
    )


def search_personal_notes(query: str) -> str:
    store = get_personal_notes_store()
    notes = store.search_notes(query)
    if not notes:
        return f"No personal notes match '{query}'."
    return f"Found {len(notes)} note(s) for '{query}':\n" + "\n".join(
        f"- {n['id']}: {n['title']}" for n in notes
    )


def run_reflection() -> str:
    store = get_awareness_store()
    res = store.run_reflection()
    return (f"Reflection complete: merged {res['merged']} duplicate(s), "
            f"resolved {res['contradictions_resolved']} contradiction(s), "
            f"{res['belief_count']} belief(s) total.")


def awareness_summary(context: str = "") -> str:
    store = get_awareness_store()
    snap = store.snapshot(context=context or None)
    counts = {}
    for slot in SLOTS:
        counts[slot] = len(store.list_beliefs(slot=slot))
    total = sum(counts.values())
    line = "\n".join(f"  {s}: {counts[s]}" for s in SLOTS if counts[s])
    return (
        f"World model: {total} belief(s) across {sum(1 for v in counts.values() if v)} slot(s).\n"
        f"{line}\n\nWorld snapshot (for context):\n{snap}"
    )


def learn_belief(slot: str, value: str, provenance: str = "inference",
                 consent_tier: str = "") -> str:
    store = get_awareness_store()
    if slot.strip().lower() not in SLOTS:
        return f"Unknown slot '{slot}'. Valid: {', '.join(SLOTS)}"
    res = store.add_belief(slot, value, provenance=provenance,
                           consent_tier=consent_tier or None)
    if "error" in res:
        return res["error"]
    return f"Learned belief: {_fmt_belief(res)}"


def record_answer(question_id: str, answer: str, slot: str = "") -> str:
    store = get_awareness_store()
    res = store.record_answer(question_id, answer, slot=slot or None)
    if "error" in res:
        return res["error"]
    b = res["belief"]
    return f"Recorded answer to onboarding question {question_id}: learned {_fmt_belief(b)}"


def user_profile() -> str:
    """Return Mayday's synthesized understanding of the user (the companion view)."""
    store = get_awareness_store()
    return store.profile()

