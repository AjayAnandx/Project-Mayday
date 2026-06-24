import json
import logging
import asyncio
import os
import struct
import hashlib
import base64
import ssl

from fastapi import WebSocket

logger = logging.getLogger(__name__)

DEEPGRAM_HOST = "api.deepgram.com"
DEEPGRAM_PORT = 443
DEEPGRAM_PATH = "/v1/listen?encoding=linear16&sample_rate=16000&channels=1&model=nova-2&interim_results=true&endpointing=200&language=en"


class _RawWebSocket:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self._buf = b""

    async def send_binary(self, data: bytes):
        await self._send_frame(0x2, data)

    async def close(self):
        await self._send_frame(0x8, b"")
        self.writer.close()

    async def recv(self):
        while True:
            opcode, payload = await self._read_frame()
            if opcode == 0x8:
                return None
            if opcode == 0x9:
                await self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                return payload.decode()
            if opcode == 0x2:
                return payload

    async def _send_frame(self, opcode: int, payload: bytes):
        header = bytearray()
        header.append(0x80 | opcode)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.writer.write(bytes(header) + masked)
        await self.writer.drain()

    async def _read_frame(self):
        first = await self.reader.readexactly(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            (length,) = struct.unpack("!H", await self.reader.readexactly(2))
        elif length == 127:
            (length,) = struct.unpack("!Q", await self.reader.readexactly(8))
        if masked:
            mask = await self.reader.readexactly(4)
        payload = await self.reader.readexactly(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload


async def _connect_deepgram(api_key: str) -> _RawWebSocket:
    ctx = ssl.create_default_context()
    reader, writer = await asyncio.open_connection(DEEPGRAM_HOST, DEEPGRAM_PORT, ssl=ctx)
    ws_key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {DEEPGRAM_PATH} HTTP/1.1\r\n"
        f"Host: {DEEPGRAM_HOST}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {ws_key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"Authorization: Token {api_key}\r\n"
        f"\r\n"
    )
    writer.write(request.encode())
    await writer.drain()
    response = b""
    while True:
        line = await reader.readline()
        response += line
        if line == b"\r\n":
            break
    if b"101" not in response:
        raise ConnectionError(f"Deepgram WS upgrade failed: {response.decode()[:200]}")
    return _RawWebSocket(reader, writer)


async def relay_stt(frontend_ws: WebSocket, api_key: str):
    await frontend_ws.accept()
    dg_ws = None
    try:
        logger.info("Connecting to Deepgram STT...")
        dg_ws = await _connect_deepgram(api_key)
        logger.info("Connected to Deepgram STT")

        async def relay_frontend_to_deepgram():
            try:
                while True:
                    data = await frontend_ws.receive_bytes()
                    await dg_ws.send_binary(data)
            except Exception:
                pass

        async def relay_deepgram_to_frontend():
            try:
                while True:
                    msg = await dg_ws.recv()
                    if msg is None:
                        break
                    if isinstance(msg, str):
                        data = json.loads(msg)
                        if data.get("type") == "Results":
                            channel = data.get("channel", {})
                            alt = (channel.get("alternatives") or [{}])[0]
                            transcript = alt.get("transcript", "")
                            is_final = data.get("is_final", False)
                            if transcript.strip():
                                await frontend_ws.send_json({
                                    "type": "transcript",
                                    "text": transcript,
                                    "is_final": is_final,
                                })
            except Exception:
                pass

        await asyncio.gather(
            relay_frontend_to_deepgram(),
            relay_deepgram_to_frontend(),
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Deepgram STT error: {e}\n{tb}")
        try:
            await frontend_ws.send_json({"type": "error", "message": f"STT unavailable: {e}"})
        except Exception:
            pass
    finally:
        if dg_ws:
            try:
                await dg_ws.close()
            except Exception:
                pass
