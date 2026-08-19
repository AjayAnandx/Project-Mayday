from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.core.personal_notes import get_personal_notes_store


router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteIn(BaseModel):
    text: str
    title: str = ""
    entities: list[str] | None = None
    tags: list[str] | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    text: str | None = None
    entities: list[str] | None = None
    tags: list[str] | None = None


@router.get("")
def list_notes():
    return {"notes": get_personal_notes_store().list_notes()}


@router.post("")
def create_note(body: NoteIn):
    store = get_personal_notes_store()
    res = store.create_note(text=body.text, title=body.title,
                            entities=body.entities, tags=body.tags)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.get("/search")
def search_notes(q: str = Query("")):
    store = get_personal_notes_store()
    return {"notes": store.search_notes(q)}


@router.get("/{note_id}")
def get_note(note_id: str):
    note = get_personal_notes_store().get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}")
def update_note(note_id: str, body: NoteUpdate):
    store = get_personal_notes_store()
    res = store.update_note(
        note_id, title=body.title, text=body.text,
        entities=body.entities, tags=body.tags,
    )
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.delete("/{note_id}")
def delete_note(note_id: str):
    store = get_personal_notes_store()
    if not store.delete_note(note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True}
