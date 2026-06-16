import json
import httpx
import yaml
from pathlib import Path

from assistant.function_registry import TOOL_DEFINITIONS


def _load_config():
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


class LLMClient:
    def __init__(self):
        cfg = _load_config().get("ollama", {})
        self.api_key = cfg.get("api_key", "")
        self.model = cfg.get("model", "gemma3:12b")
        self.endpoint = cfg.get("endpoint", "http://localhost:11434/v1/chat/completions")
        self._http = httpx.Client(timeout=60)

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, messages: list[dict], stream: bool = False):
        body = {
            "model": self.model,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
            "stream": stream,
        }
        if stream:
            return self._http.stream("POST", self.endpoint, json=body, headers=self._build_headers())
        return self._http.post(self.endpoint, json=body, headers=self._build_headers())

    def extract_response(self, response) -> tuple[str | None, list[dict] | None]:
        data = response.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")
        return content, tool_calls

    def extract_stream_chunk(self, line: bytes) -> tuple[str | None, list[dict] | None, bool]:
        if line.startswith(b"data: "):
            payload = line[6:].strip()
            if payload == b"[DONE]":
                return None, None, True
            data = json.loads(payload)
            delta = data["choices"][0]["delta"]
            content = delta.get("content")
            tool_calls = delta.get("tool_calls")
            return content, tool_calls, False
        return None, None, False
