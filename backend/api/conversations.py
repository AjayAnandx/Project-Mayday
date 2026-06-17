from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.core.data_store import get_store

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = "New conversation"


class MessageCreate(BaseModel):
    role: str
    content: str


@router.get("")
def list_conversations(date: str = ""):
    store = get_store()
    return store.list_conversations(date=date or None)


@router.post("", status_code=201)
def create_conversation(body: ConversationCreate):
    store = get_store()
    return store.create_conversation(title=body.title)


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str):
    store = get_store()
    conv = store.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str):
    store = get_store()
    if not store.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True}


@router.post("/{conversation_id}/messages", status_code=201)
def add_message(conversation_id: str, body: MessageCreate):
    store = get_store()
    msg = store.add_message(conversation_id, body.role, body.content)
    if not msg:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return msg


@router.get("/{conversation_id}/messages")
def get_messages(conversation_id: str, limit: int = 20):
    store = get_store()
    conv = store.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return store.get_recent_messages(conversation_id, limit=limit)
