from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.user_awareness import get_awareness_store, SLOTS


router = APIRouter(prefix="/api/awareness", tags=["awareness"])


class QuestionIn(BaseModel):
    slot: str
    question: str


class AnswerIn(BaseModel):
    question_id: str
    answer: str
    slot: str | None = None


@router.get("/slots")
def list_slots():
    return {"slots": list(SLOTS)}


@router.get("/user-name")
def get_user_name():
    return {"user_name": get_awareness_store().get_user_name() or ""}


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


@router.get("/phf")
def get_phf():
    from backend.core.phf import disposition_summary, field_signal
    return {"habitus": disposition_summary(), "field_signal": field_signal()}
