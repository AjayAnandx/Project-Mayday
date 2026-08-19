import json
import re
import httpx

from backend.core.config import load_config
from backend.assistant.function_registry import get_tool_definitions

_TOOL_CALL_BLOCK_RE = re.compile(
    r'<\|tool_call[^>]*>(.*?)<\|?tool_call\|?>',
    re.DOTALL,
)

_FUNC_CALL_RE = re.compile(
    r'call:(\w+)\(([^)]*)\)',
)

_ARG_RE = re.compile(
    r'(\w+)=(?:"([^"]*)"|\'([^\']*)\'|(\S+))',
)


def _parse_tool_call_text(text: str) -> tuple[str | None, list[dict] | None]:
    if not text or "<|tool" not in text:
        return text, None

    blocks = _TOOL_CALL_BLOCK_RE.findall(text)
    if not blocks:
        return text, None

    cleaned = _TOOL_CALL_BLOCK_RE.sub("", text).strip()

    parsed_tool_calls = []
    for block in blocks:
        block = block.strip()

        try:
            tc = json.loads(block)
            name = tc.get("name", tc.get("function", ""))
            args = tc.get("arguments", tc.get("parameters", {}))
            if isinstance(args, str):
                args = json.loads(args)
            parsed_tool_calls.append({
                "id": f"call_{name}",
                "type": "function",
                "function": {"name": name, "arguments": args},
            })
            continue
        except (json.JSONDecodeError, TypeError):
            pass

        m = _FUNC_CALL_RE.search(block)
        if m:
            name = m.group(1)
            args_str = m.group(2)
            args = {}
            for am in _ARG_RE.finditer(args_str):
                val = am.group(2) or am.group(3) or am.group(4)
                args[am.group(1)] = val
            parsed_tool_calls.append({
                "id": f"call_{name}",
                "type": "function",
                "function": {"name": name, "arguments": args},
            })
            continue

        try:
            tc = json.loads("{" + block + "}")
            name = tc.get("name", "")
            args = {k: v for k, v in tc.items() if k != "name"}
            if name:
                parsed_tool_calls.append({
                    "id": f"call_{name}",
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                })
        except (json.JSONDecodeError, TypeError):
            pass

    return cleaned or None, parsed_tool_calls if parsed_tool_calls else None


class LLMClient:
    def __init__(self, model: str | None = None, endpoint: str | None = None, api_key: str | None = None):
        cfg = load_config().get("ollama", {})
        self.api_key = api_key if api_key is not None else cfg.get("api_key", "")
        self.model = model if model is not None else cfg.get("model", "gemma4:31b-cloud")
        self.endpoint = endpoint if endpoint is not None else cfg.get("endpoint", "http://localhost:11434/v1/chat/completions")
        read_timeout = float(cfg.get("timeout", 600))
        # keep_alive: pin the model in VRAM so it is never unloaded/reloaded
        # between calls (a major latency source when two tiers alternate).
        # -1 = stay loaded forever, 0 = unload immediately, 300 = 5 minutes.
        self.keep_alive = cfg.get("keep_alive", -1)
        self._http = httpx.Client(timeout=httpx.Timeout(
            connect=15.0,
            read=read_timeout,
            write=60.0,
            pool=15.0,
        ))

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, messages: list[dict], stream: bool = False, tools: list[dict] | None = None,
              tool_choice: str | None = None, max_tokens: int | None = None):
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools if tools is not None else get_tool_definitions(),
            "stream": stream,
        }
        if tool_choice:
            body["tool_choice"] = tool_choice
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        if stream:
            return self._http.stream("POST", self.endpoint, json=body, headers=self._build_headers())
        return self._http.post(self.endpoint, json=body, headers=self._build_headers())

    def extract_response(self, response) -> tuple[str | None, list[dict] | None]:
        data = response.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")

        if tool_calls:
            return content, tool_calls

        return _parse_tool_call_text(content)

    def extract_stream_chunk(self, line: bytes) -> tuple[str | None, list[dict] | None, bool]:
        if line.startswith(b"data: "):
            payload = line[6:].strip()
            if payload == b"[DONE]":
                return None, None, True
            data = json.loads(payload)
            delta = data["choices"][0]["delta"]
            content = delta.get("content")
            tool_calls = delta.get("tool_calls")

            if tool_calls:
                return content, tool_calls, False

            if content and "<|tool" in content:
                cleaned, parsed = _parse_tool_call_text(content)
                if parsed:
                    return cleaned, parsed, False
                return content, None, False

            return content, tool_calls, False
        return None, None, False

    def stream_tokens(self, messages: list[dict], tools: list[dict] | None = None,
                      tool_choice: str | None = None):
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools if tools is not None else get_tool_definitions(),
            "stream": True,
        }
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        if tool_choice:
            body["tool_choice"] = tool_choice
        with self._http.stream("POST", self.endpoint, json=body, headers=self._build_headers()) as response:
            for line in response.iter_lines():
                line = line.strip()
                if not line:
                    continue
                if not isinstance(line, bytes):
                    line = line.encode()
                content, tool_calls, done = self.extract_stream_chunk(line)
                yield content, tool_calls, done
                if done:
                    break


_INTERACTIVE_CLIENT: "LLMClient | None" = None
_WORKER_CLIENT: "LLMClient | None" = None


def _client_for(role: str) -> "LLMClient":
    cfg = load_config().get("models", {}).get(role, {})
    return LLMClient(
        model=cfg.get("model") or None,
        endpoint=cfg.get("endpoint") or None,
        api_key=cfg.get("api_key") or None,
    )


def get_interactive_client() -> "LLMClient":
    """Local small model that talks to the user and humanizes worker answers."""
    global _INTERACTIVE_CLIENT
    if _INTERACTIVE_CLIENT is None:
        _INTERACTIVE_CLIENT = _client_for("interactive")
    return _INTERACTIVE_CLIENT


def get_worker_client() -> "LLMClient":
    """Capable model that performs the heavy tool/reasoning work."""
    global _WORKER_CLIENT
    if _WORKER_CLIENT is None:
        _WORKER_CLIENT = _client_for("worker")
    return _WORKER_CLIENT


