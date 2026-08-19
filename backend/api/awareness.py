from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.core.user_awareness import get_awareness_store, SLOTS


router = APIRouter(prefix="/api/awareness", tags=["awareness"])


class BeliefIn(BaseModel):
    slot: str
    value: str
    provenance: str = "inference"
    confidence: float | None = None
    consent_tier: str | None = None
    source_refs: list[str] | None = None


class BeliefUpdate(BaseModel):
    value: str | None = None
    confidence: float | None = None
    consent_tier: str | None = None


class QuestionIn(BaseModel):
    slot: str
    question: str


class AnswerIn(BaseModel):
    question_id: str
    answer: str
    slot: str | None = None


@router.get("")
def get_awareness(slot: str = Query(""), min_confidence: float = 0.0):
    store = get_awareness_store()
    beliefs = store.list_beliefs(slot=slot or None, min_confidence=min_confidence or None)
    return {
        "beliefs": beliefs,
        "consented_tiers": sorted(store._consented_tiers),
        "tombstones": store._tombstones,
    }


@router.put("")
def add_belief(body: BeliefIn):
    store = get_awareness_store()
    res = store.add_belief(
        body.slot, body.value, provenance=body.provenance,
        confidence=body.confidence, consent_tier=body.consent_tier,
        source_refs=body.source_refs,
    )
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.patch("/{belief_id}")
def update_belief(belief_id: str, body: BeliefUpdate):
    store = get_awareness_store()
    res = store.update_belief(
        belief_id, value=body.value, confidence=body.confidence,
        consent_tier=body.consent_tier,
    )
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.delete("/{belief_id}")
def delete_belief(belief_id: str):
    store = get_awareness_store()
    if not store.delete_belief(belief_id):
        raise HTTPException(status_code=404, detail="Belief not found")
    return {"deleted": True}


@router.get("/snapshot")
def get_snapshot(context: str = Query(""), top_k: int = 8):
    store = get_awareness_store()
    return {"snapshot": store.snapshot(context=context or None, top_k=top_k)}


@router.get("/slots")
def list_slots():
    return {"slots": list(SLOTS)}


@router.post("/ask")
def queue_question(body: QuestionIn):
    store = get_awareness_store()
    if body.slot.strip().lower() not in SLOTS:
        raise HTTPException(status_code=400, detail=f"Unknown slot '{body.slot}'")
    res = store.queue_question(body.slot, body.question)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.get("/questions")
def get_questions(limit: int = 0):
    store = get_awareness_store()
    return {"questions": store.pending_questions(limit=limit or None)}


@router.post("/answer")
def answer_question(body: AnswerIn):
    store = get_awareness_store()
    res = store.record_answer(body.question_id, body.answer, slot=body.slot)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.post("/reflect")
def reflect():
    store = get_awareness_store()
    return store.run_reflection()


@router.post("/import")
def import_beliefs(beliefs: list[BeliefIn]):
    store = get_awareness_store()
    added = []
    for b in beliefs:
        res = store.add_belief(
            b.slot, b.value, provenance=b.provenance, confidence=b.confidence,
            consent_tier=b.consent_tier, source_refs=b.source_refs,
        )
        if "error" not in res:
            added.append(res)
    return {"imported": len(added), "beliefs": added}


@router.post("/consent")
def grant_consent(tier: str):
    store = get_awareness_store()
    ok = store.grant_consent(tier)
    return {"granted": ok, "consented_tiers": sorted(store._consented_tiers)}


@router.get("/followups")
def get_followups(due_only: bool = False):
    store = get_awareness_store()
    fus = store.due_followups() if due_only else list(store._followups)
    return {"followups": fus, "due_count": len(store.due_followups())}


@router.delete("/followups/{person}")
def delete_followup(person: str):
    store = get_awareness_store()
    ok = store.remove_followup(person)
    if not ok:
        raise HTTPException(status_code=404, detail="No follow-up for that person")
    return {"deleted": True}


@router.get("/people")
def get_people():
    from backend.core.person_brief import list_people
    return {"people": list_people()}
