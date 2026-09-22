"""Shared provider primitives: spec, errors, body/header builders."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Raised when a provider request fails in a classifiable way."""

    def __init__(self, provider: str, message: str, status_code: int | None = None,
                 error_type: str = "provider_error"):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.error_type = error_type

    @property
    def failover(self) -> bool:
        """True when the router should try the next provider in the chain."""
        if self.status_code in (401, 402, 429, 502, 503, 504):
            return True
        if self.error_type in ("timeout", "connect", "mid_stream"):
            return True
        return False

    @property
    def retryable(self) -> bool:
        """True when a single immediate retry on the SAME provider is worth it."""
        if self.status_code in (429, 502, 503, 504):
            return True
        return self.error_type in ("timeout", "mid_stream")


@dataclass
class ProviderSpec:
    """Everything needed to send one OpenAI-compatible chat request."""

    name: str
    endpoint: str
    model: str
    api_key: str = ""
    # Ollama-local only: pin model in VRAM. Never sent to cloud providers.
    keep_alive: int | None = None
    supports_tool_choice: bool = True
    supports_keep_alive: bool = False
    requires_api_key: bool = False
    omit_empty_tools: bool = False
    # OpenRouter attribution headers (optional, rankings only).
    referer: str = ""
    title: str = ""
    # OpenRouter provider routing object, e.g. {"require_parameters": True}.
    provider_routing: dict = field(default_factory=dict)
    read_timeout: float = 600.0

    def build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.name == "openrouter":
            if self.referer:
                headers["HTTP-Referer"] = self.referer
            if self.title:
                headers["X-OpenRouter-Title"] = self.title
        return headers

    def build_body(self, messages: list[dict], tools: list[dict] | None,
                   tool_choice: str | None = None,
                   max_tokens: int | None = None,
                   temperature: float | None = None,
                   stream: bool = False) -> dict:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        # Parity wire format (legacy client): the tools key is ALWAYS sent,
        # tool_choice passed through when truthy — on every provider.
        body["tools"] = tools if tools is not None else []
        if tool_choice and self.supports_tool_choice:
            body["tool_choice"] = tool_choice
        elif tool_choice and not self.supports_tool_choice:
            logger.debug("%s does not support tool_choice — omitting", self.name)
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if self.supports_keep_alive and self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        if self.name == "openrouter" and self.provider_routing:
            body["provider"] = dict(self.provider_routing)
        return body

    def check_ready(self) -> None:
        """Raise ProviderError when a required credential is missing."""
        if self.requires_api_key and not self.api_key:
            raise ProviderError(
                self.name,
                f"{self.name} needs an API key "
                f"({'OPENROUTER_API_KEY' if self.name == 'openrouter' else 'OLLAMA_API_KEY'} "
                "env var or config block) — skipping to next provider",
                status_code=401,
                error_type="missing_key",
            )
