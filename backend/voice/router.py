import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.config import load_config

from .deepgram_stt import relay_stt
from .deepgram_tts import synthesize


class TtsRequest(BaseModel):
    text: str

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])


def _get_api_key() -> str:
    cfg = load_config()
    return (cfg.get("voice", {}) or {}).get("deepgram_api_key", "") or ""


@router.get("/status")
def status():
    key = _get_api_key()
    enabled = bool(key)
    return {
        "enabled": enabled,
        "stt": "deepgram",
        "tts": "deepgram",
        "note": "Voice handled via Deepgram STT (WebSocket) + TTS (REST)",
    }


@router.websocket("/stt")
async def voice_stt(ws: WebSocket):
    api_key = _get_api_key()
    if not api_key:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "Deepgram API key not configured"})
        await ws.close()
        return
    try:
        await relay_stt(ws, api_key)
    except WebSocketDisconnect:
        logger.info("Frontend STT WebSocket disconnected")
    except Exception as e:
        logger.error(f"STT WebSocket error: {e}")


@router.post("/tts")
async def voice_tts(body: TtsRequest):
    api_key = _get_api_key()
    if not api_key:
        return Response(status_code=400, content="Deepgram API key not configured")
    text = body.text.strip()
    if not text:
        return Response(status_code=400, content="No text provided")
    try:
        cfg = load_config()
        voice = (cfg.get("voice", {}) or {}).get("tts_voice", "aura-asteria-en")
        audio_bytes = await synthesize(text, api_key, voice)
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return Response(status_code=500, content=f"TTS failed: {e}")
