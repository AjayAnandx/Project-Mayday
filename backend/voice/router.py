import logging
import tempfile
import os
from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


class TranscribeResponse(BaseModel):
    text: str | None = None
    error: str | None = None


@router.get("/status")
def status():
    return {"enabled": True, "stt": "puter", "tts": "puter", "note": "Voice handled client-side via Puter.js with browser SpeechRecognition fallback"}


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        filename = f"voice_{id(contents)}.webm"
        filepath = os.path.join(tempfile.gettempdir(), filename)

        with open(filepath, "wb") as f:
            f.write(contents)

        logger.info(f"Received audio file: {len(contents)} bytes, saved to {filepath}")

        # Backend transcription is a stub — frontend handles STT via Puter.js or browser API
        return TranscribeResponse(text=None, error="Backend STT not available; use frontend-based Puter.js or browser SpeechRecognition")
    except Exception as e:
        logger.error(f"Transcribe error: {e}")
        return TranscribeResponse(error=str(e))
    finally:
        try:
            os.unlink(filepath)
        except Exception:
            pass
