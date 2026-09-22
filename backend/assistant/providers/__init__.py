"""Unified LLM provider gateway for Mayday.

Three OpenAI-compatible providers behind one interface:

- ``ollama_local`` — http://localhost:11434/v1/chat/completions, no auth.
  Request bodies are byte-identical to the pre-gateway client.
- ``ollama_cloud`` — https://api.ollama.com/v1/chat/completions, Bearer
  ``OLLAMA_API_KEY``, 1 concurrent request (serialized in router).
- ``openrouter`` — https://openrouter.ai/api/v1/chat/completions, Bearer
  ``OPENROUTER_API_KEY`` + optional ``HTTP-Referer`` / ``X-OpenRouter-Title``,
  ``provider`` routing object. Free variants: 20 RPM, 50 RPD (<10 credits
  purchased) / 1000 RPD (>=10 credits); 402 = out of credits.

``LLMClient`` (backend/assistant/llm_client.py) keeps its public signature and
delegates provider resolution + fallback to :mod:`router`. With no
``providers:`` block in config, everything resolves from the ``ollama:``
block exactly as before the gateway existed.
"""
