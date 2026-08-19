"""R0 spike: validate the two-tier model architecture.

Proves:
  1. interactive (qwen2.5:0.5b, local) can classify intent  [few-shot, engineered]
  2. interactive can humanize a robotic worker answer        [few-shot, engineered]
  3. worker (gemma4:31b-cloud) produces substantive content

Run:  venv/Scripts/python.exe -u -m backend.scripts.spike_tiers
Set SKIP_WORKER=1 to validate only the fast local tier.
"""
import os
import re
import httpx
import sys

from backend.assistant.llm_client import get_interactive_client, get_worker_client


def _set_timeout(client, read=60.0):
    client._http = httpx.Client(timeout=httpx.Timeout(connect=15, read=read, write=30, pool=15))


def log(*a):
    print(*a, flush=True)


def _complete(client, prompt, sys_prompt="", temperature=0.3, max_tokens=400):
    messages = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat(messages, stream=False, tools=[], max_tokens=max_tokens)
    content, _ = client.extract_response(resp)
    return (content or "").strip()


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


def classify(client, message):
    out = _complete(client, _CLASSIFY_PROMPT.format(msg=message), temperature=0.2)
    m = re.search(r"\b(TRIVIAL|WHY|WHEN|ENTITY|TASK)\b", out.upper())
    return m.group(1) if m else f"UNPARSED({out!r})"


_HUMANIZE_PROMPT = """Rewrite the assistant's answer to sound natural and friendly, like a personal assistant talking to the user. Keep every fact. Do not invent anything.

Example:
Assistant: Query processed. Dentist appointment 2026-08-20 15:00. Reminder set.
Rewritten: Hey! Your dentist appointment is on August 20 at 3 PM - I've set a reminder for it.

Assistant: {answer}
Rewritten:"""


def humanize(client, worker_answer, temperature=0.7):
    return _complete(
        client,
        _HUMANIZE_PROMPT.format(answer=worker_answer),
        temperature=temperature,
        max_tokens=400,
    )


def worker_answer(client, query):
    return _complete(
        client,
        query,
        sys_prompt="You are a capable research assistant. Answer accurately and concisely.",
        temperature=0.3,
    )


def main():
    inter = get_interactive_client()
    _set_timeout(inter, read=60.0)
    log("=" * 70)
    log(f"INTERACTIVE MODEL : {inter.model}  ({inter.endpoint})")
    if os.environ.get("SKIP_WORKER"):
        log("(worker step skipped via SKIP_WORKER=1)")
    else:
        worker = get_worker_client()
        _set_timeout(worker, read=180.0)
        log(f"WORKER MODEL      : {worker.model}  ({worker.endpoint})")
    log("=" * 70)

    samples = [
        "hi there",
        "why did I miss the TCS exam deadline last month?",
        "when is my dentist appointment?",
        "tell me about my brother Arjun",
        "create a todo to buy milk",
    ]
    log("\n[1] INTENT CLASSIFICATION (local qwen2.5:0.5b)")
    for s in samples:
        label = classify(inter, s)
        log(f"  {label:10} <- {s}")

    log("\n[2] HUMANIZATION (local qwen2.5:0.5b)")
    robotic = (
        "Query processed. The dentist appointment is scheduled for 2026-08-20 at "
        "15:00. Reminder set. Conflict with calendar event 'team sync' at 14:30 noted."
    )
    human = humanize(inter, robotic)
    log(f"  ROBOTIC : {robotic}")
    log(f"  HUMAN   : {human}")

    if not os.environ.get("SKIP_WORKER"):
        log("\n[3] WORKER CONTENT (gemma4:31b-cloud)")
        wa = worker_answer(worker, "In one sentence, what is the benefit of a multi-graph memory architecture?")
        log(f"  WORKER  : {wa}")

    log("\nSPIKE COMPLETE")


if __name__ == "__main__":
    main()
