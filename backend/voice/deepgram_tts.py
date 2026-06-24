import logging

import httpx

logger = logging.getLogger(__name__)

DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"


async def synthesize(text: str, api_key: str, voice: str = "aura-asteria-en") -> bytes:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            DEEPGRAM_TTS_URL,
            json={"text": text},
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json",
            },
            params={"model": voice, "encoding": "mp3"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.content
