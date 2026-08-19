"""Two-tier model orchestration for Mayday.

Architecture (see TWO_TIER_MAGMA_DSPY_PLAN):
  Interactive tier (local qwen2.5:0.5b): talks to the user, routes intent,
    and HUMAN-SYNTHESIZES the worker's answer into natural language.
  Worker tier (gemma4:31b-cloud): runs the heavy tool/reasoning loop and
    returns a substantive (but often robotic) answer to the interactive tier.

The interactive tier must NEVER receive tools (small models tool-call poorly);
it only does classification + natural-language generation.
"""
import re

from backend.assistant.llm_client import get_interactive_client, get_worker_client
from backend.core.config import load_config

try:
    from backend.dspy.modules import (
        humanize_dspy,
        classify_dspy,
        dspy_interactive_enabled,
    )
    _DSPY_OK = True
except Exception:  # pragma: no cover - dspy optional
    _DSPY_OK = False


INTENTS = ("TRIVIAL", "WHY", "WHEN", "ENTITY", "TASK")
# Intents that need the worker's heavy lifting vs. ones the interactive tier
# can answer directly/locally.
COMPLEX_INTENTS = {"WHY", "WHEN", "ENTITY", "TASK"}

_CLASSIFY_PROMPT = """You are a message router for a personal AI assistant.
Classify each message into exactly one category:
- TRIVIAL: greetings, thanks, simple chit-chat, "what time is it"
- WHY: questions about reasons or causes
- WHEN: questions about dates, times, or scheduling
- ENTITY: questions about a specific person, place, or thing
- TASK: requests to create or modify todos, events, reminders, or projects

Examples:
Message: hi there
Category: TRIVIAL

Message: why did I miss the exam
Category: WHY

Message: when is my dentist appointment
Category: WHEN

Message: tell me about my brother Arjun
Category: ENTITY

Message: create a todo to buy milk
Category: TASK

Message: {msg}
Category:"""

_HUMANIZE_PROMPT = """Rewrite the assistant's answer to sound natural and friendly, like a personal assistant talking to the user. Keep every fact. Do not invent anything.

Example:
Assistant: Query processed. Dentist appointment 2026-08-20 15:00. Reminder set.
Rewritten: Hey! Your dentist appointment is on August 20 at 3 PM - I've set a reminder for it.

Assistant: {answer}
Rewritten:"""


def tiering_enabled() -> bool:
    return bool(load_config().get("models", {}).get("tiering_enabled", False))


def _complete(client, prompt: str, sys_prompt: str = "", temperature: float = 0.3,
             max_tokens: int = 400, tools: list | None = None) -> str:
    messages = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat(messages, stream=False, tools=tools if tools is not None else [],
                       max_tokens=max_tokens)
    content, _ = client.extract_response(resp)
    return (content or "").strip()


def classify_intent(text: str) -> str:
    """Return one of INTENTS for the user message (local interactive model)."""
    if _DSPY_OK and dspy_interactive_enabled():
        intent, _ = classify_dspy(text)
        if intent and intent in INTENTS:
            return intent
    inter = get_interactive_client()
    out = _complete(inter, _CLASSIFY_PROMPT.format(msg=text), temperature=0.2)
    m = re.search(r"\b(" + "|".join(INTENTS) + r")\b", out.upper())
    return m.group(1) if m else "TRIVIAL"


def is_complex(text: str) -> bool:
    """True if the message needs the worker tier (heavy reasoning/tools)."""
    if _DSPY_OK and dspy_interactive_enabled():
        intent, complex_flag = classify_dspy(text)
        if intent is not None:
            return bool(complex_flag)
    return classify_intent(text) in COMPLEX_INTENTS


def humanize(worker_answer: str, user_question: str = "", style: str = "warm and professional") -> str:
    """Rewrite a worker's answer into natural, on-persona language (local model)."""
    if not worker_answer or not worker_answer.strip():
        return worker_answer
    if _DSPY_OK and dspy_interactive_enabled():
        out = humanize_dspy(worker_answer, user_question)
        if out:
            return out
    inter = get_interactive_client()
    out = _complete(
        inter,
        _HUMANIZE_PROMPT.format(answer=worker_answer),
        temperature=0.7,
        max_tokens=1024,
    )
    return out or worker_answer


def worker_complete(query: str, sys_prompt: str = "") -> str:
    """Run a substantive generation on the worker tier (capable model)."""
    worker = get_worker_client()
    return _complete(worker, query, sys_prompt=sys_prompt, temperature=0.3, max_tokens=1500)
