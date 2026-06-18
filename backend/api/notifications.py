import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from backend.core.scheduler import get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class ReminderCreate(BaseModel):
    message: str
    datetime: str


@router.get("/reminders")
def list_reminders():
    return get_scheduler().list_reminders()


@router.post("/reminders", status_code=201)
def create_reminder(body: ReminderCreate):
    rid, adjusted, stored_dt = get_scheduler().add_reminder(body.message, body.datetime)
    result = {"id": rid, "message": body.message, "datetime": stored_dt}
    if adjusted:
        result["warning"] = "Time was in the past — adjusted to 1 minute from now"
    return result


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: str):
    if not get_scheduler().delete_reminder(reminder_id):
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"deleted": True}


@router.websocket("/ws")
async def notification_ws(websocket: WebSocket):
    await websocket.accept()
    queue = get_scheduler().get_queue()
    try:
        while True:
            msg = await queue.get()
            try:
                await websocket.send_json(msg)
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@router.get("/fired")
def get_fired_notifications():
    return get_scheduler().get_fired_notifications()
