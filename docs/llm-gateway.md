# LLM Gateway — Ollama Local + Ollama Cloud + OpenRouter

One OpenAI-compatible interface (`backend/assistant/llm_client.py`) routed
through `backend/assistant/providers/` across three providers:

| Provider | Endpoint | Auth | Notes |
|---|---|---|---|
| `ollama_local` | `http://localhost:11434/v1/chat/completions` | none | Bodies byte-identical to pre-gateway client; no tool cap |
| `ollama_cloud` | `https://api.ollama.com/v1/chat/completions` | `OLLAMA_API_KEY` | No `keep_alive`; **1 concurrent request** (gateway serializes) |
| `openrouter` | `https://openrouter.ai/api/v1/chat/completions` | `OPENROUTER_API_KEY` | `tool_choice` + `provider.require_parameters` supported |

Default routing (`config.yaml → providers:`): **worker = `openrouter`
(`nvidia/nemotron-3-super-120b-a12b:free`)**, interactive tier stays on
`ollama_local`. One attempt per provider, then the next link — every failure
is announced loudly with the real provider message (no silent model swaps,
no same-provider retries by default; opt in with `providers.retry_same: true`).
Terminal failures use the same tailored cards as the old Ollama path
(timeout hint, connection hint).

Without a `providers:` block, everything resolves from the `ollama:` block
exactly as before the gateway (covered by wire-parity tests).

## Setup

```bash
cp .env.example .env
# .env:
OPENROUTER_API_KEY=sk-or-...     # https://openrouter.ai/keys
OLLAMA_API_KEY=...               # ollama.com → Settings → API Keys (fallback)
# OPENROUTER_MODEL=openai/gpt-5-mini   # optional override
```

No keys at all? The gateway skips cloud providers and runs on local Ollama —
nothing breaks, you just lose the cloud fallback. **Restart the backend**
after key/config changes (the worker client is a cached singleton).

## Quota guards (free tier)

- Free variants: **20 req/min**, **50 req/day** (<10 credits) / **1000 req/day**.
  `402` = out of credits (fails over immediately, no retry).
- `providers.free_max_iterations` (default 20 = parity; lower to bound
  free-tier burn, e.g. 8 ≈ ~10 requests/turn instead of ~22).
- `providers.max_tools` (default 0 = off, full set like Ollama; raise only
  if a provider 400s on size).
- `providers.retry_same` (default false = single attempt per provider).
- Check quota: `GET https://openrouter.ai/api/v1/key` with your key.

If free models fumble tool calls, switch one line (`OPENROUTER_MODEL` or
`config.yaml → openrouter.model`), e.g. paid `nvidia/nemotron-3-super-120b-a12b`
or `openai/gpt-5-mini`, and restart.

## Changing the default worker

```yaml
providers:
  default: ollama_cloud      # or ollama_local — no code changes needed
  fallback_order: [ollama_cloud, openrouter, ollama_local]
```

## Troubleshooting

- `401` card → key missing/wrong; check `.env` names.
- `402` card → top up credits or switch model; chat already failed over.
- Model replies in text but never calls tools → backend log line
  `LLM <provider> model=… tools_sent=… finish=… tool_calls=…` tells why;
  `finish=tool_calls, tool_calls=0` with huge `tools_sent` = payload
  overwhelm → lower `providers.max_tools` (default 64, cloud only).
- `EMPTY choices` warnings (HTTP 200, zero choices — free-provider blip) →
  retried once automatically, then failed over; message preserved on the card.
- Repeated `timeout` cards → raise `ollama.timeout` in `config.yaml`.
- Local model keeps reloading → `ollama.keep_alive: -1` (local only).

## For developers

- Per-request override: `llm.chat(msgs, tools=[...], provider="ollama_cloud")`.
- After `chat()`: `llm.last_provider`, `llm.last_fallbacks`, `llm.fallback_notice()`.
- `temperature` is forwarded to all providers (fixes the old dead param).
- Tests: `pytest backend/test_llm_gateway.py` (mocked transport, no network).
