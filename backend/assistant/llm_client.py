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
    def __init__(self):
        cfg = load_config().get("ollama", {})
        self.api_key = cfg.get("api_key", "")
        self.model = cfg.get("model", "gemma4:31b-cloud")
        self.endpoint = cfg.get("endpoint", "http://localhost:11434/v1/chat/completions")
        read_timeout = float(cfg.get("timeout", 600))
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
             tool_choice: str | None = None):
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools if tools is not None else get_tool_definitions(),
            "stream": stream,
        }
        if tool_choice:
            body["tool_choice"] = tool_choice
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
