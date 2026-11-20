"""Brain V2 P3: capture what the user says into memory, with evidence.

    gate(text)          cheap check, no model call: is this turn worth reflecting on?
    reflect(llm, ...)   ONE model call -> proposed ops (facts, commitments, ideas, aliases)
    validate(ops, text) keep only ops whose verbatim quote is in the user's message,
                        whose names/numbers are supported, and decide auto / ask / drop
    apply(ops, ...)     write: facts table (+ mirror into the graph so recall and the
                        profile use them at once), supersede contradicted facts,
                        commitments -> planner tasks, ideas, aliases
    capture_turn(...)   the whole pipeline; what chat.py calls after a reply

Wrong memories are worse than none, so the validator is strict and every write keeps
its quote and source. Medium-confidence items wait as "pending" in the Learned feed
(GET /api/brain/learned) until the user confirms them.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from backend.core.config import load_config
from backend.core.research_evidence import quote_in_text
from backend.memory.sensitivity import is_sensitive

logger = logging.getLogger(__name__)

# Predicates with one current value: a new value supersedes the old one.
SINGLE_VALUED = {
    "lives_in", "city", "works_at", "job", "job_title", "role", "employer", "birthday",
    "age", "relationship_status", "phone_number", "email", "school", "college", "studies",
    "manager", "partner", "status", "deadline", "uses_database", "timezone", "mood",
}

_FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|i'll|i'd|me|my|mine|we|we're|we'll|our|us)\b", re.I)
# A commitment's quote must actually promise or plan an action.
_PROMISE = re.compile(
    r"\b(i'll|i will|i'm going to|im going to|gonna|i need to|i have to|i must|i promised?|"
    r"we'll|we will|will send|will call|will do|by (mon|tue|wed|thu|fri|sat|sun)\w*|tomorrow|tonight|"
    r"next week|remind me|don'?t let me forget|owes? me|said (he|she|they)'?l?l?)\b", re.I)
# Thinking out loud without "I": "random thought: …", "what if …", "idea: …"
_THINKING = re.compile(r"\b(thought|idea|what if|could work|might work|should build|note to self)\b", re.I)
_SMALL_TALK = re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok(ay)?|cool|great|nice|yes|no|sure|bye)\b[\s!.]*$",
                         re.I)


def _cfg() -> dict:
    c = (load_config().get("brain", {}) or {}).get("capture", {}) or {}
    return {"enabled": bool(c.get("enabled", True)),
            "auto": float(c.get("auto_threshold", 0.8)),
            "ask": float(c.get("ask_threshold", 0.5)),
            "max_ops": int(c.get("max_ops", 8))}


# ---------------------------------------------------------------- gate
def gate(text: str) -> bool:
    """True when the message may contain something worth remembering."""
    t = (text or "").strip()
    if len(t) < 12 or len(t.split()) < 3 or _SMALL_TALK.match(t):
        return False
    if t.endswith("?") and not re.search(r"\b(i'll|i will|i'm going to|remind)\b", t, re.I):
        return False          # questions ask, they rarely tell
    return (bool(_FIRST_PERSON.search(t)) or bool(re.search(r"\b[A-Z][a-z]{2,}\b", t[1:]))
            or bool(_THINKING.search(t)))


# ---------------------------------------------------------------- reflect
_PROMPT = """You maintain the long-term memory of a personal assistant for ONE user.
Read the user's latest message and extract only durable things worth remembering about
the user and their world. Today is {today}.

Return JSON only: {{"ops": [ ... ]}} with at most {max_ops} items. Item kinds:
- {{"kind":"fact","subject":"user" | "<person/project/org name>","subject_type":"user|person|project|org|place",
   "predicate":"<snake_case verb phrase, e.g. lives_in, allergic_to, goal, prefers, routine, decided, works_at, birthday, is>",
   "object":"<short value>","category":"fact|preference|habit|constraint|value|goal",
   "confidence":0..1,"quote":"<exact words copied from the message>"}}
  category: habit = something done regularly; constraint = a limit on time/money/availability
  ("no meetings before 10", "exams 25 Nov-1 Dec"); value = what matters to them ("family time on Sundays");
  goal = an aim; preference = a like/dislike or style; fact = anything else.
- {{"kind":"commitment","who":"user" | "<name>","text":"<what will be done>","due":"YYYY-MM-DD or null",
   "confidence":0..1,"quote":"..."}}       (a promise or plan with an owner: "I'll send X Friday")
- {{"kind":"idea","text":"<the idea>","confidence":0..1,"quote":"..."}}   (thinking out loud about something to build/try)
- {{"kind":"alias","alias":"<how the user refers to someone, e.g. mom>","canonical":"<full name>","confidence":0..1,"quote":"..."}}

Rules:
- "quote" MUST be copied word for word from the message (a short span is fine). No paraphrase.
- Facts about the user use subject "user". Name a person exactly as the user wrote it.
- Capture: identity, people and relationships, preferences and dislikes, health (allergies, conditions),
  goals, routines, decisions, work/study, mood that persists (e.g. stressed all week), commitments, ideas.
- Do NOT capture: questions, requests to the assistant, hypotheticals, small talk, facts about the world,
  or anything the user only asks about.
- A wish or aim ("I want to clear GATE") is a FACT with predicate "goal", never a commitment.
  A commitment is a concrete action someone said they WILL do ("I'll send…", "I need to call… tomorrow").
- Put the meaning in "object", not in "predicate": never use objects like true/false/yes.
  e.g. {{"predicate":"copes_with_stress_by","object":"taking a long walk"}}, not "takes_walks_when_stressed": "true".
- confidence: 0.9+ stated plainly; 0.6-0.8 implied or hedged ("I think", "maybe"); below 0.5 a guess.
- If nothing qualifies return {{"ops": []}}.
{context}
User message:
\"\"\"{text}\"\"\"
JSON:"""


def build_prompt(text: str, previous_assistant: str = "", known_people: list[str] | None = None) -> str:
    cfg = _cfg()
    ctx = []
    if previous_assistant:
        ctx.append("The assistant's previous message (context only, never quote it):\n"
                   f"\"\"\"{previous_assistant[:600]}\"\"\"")
    if known_people:
        ctx.append("People already known: " + ", ".join(known_people[:30]))
    return _PROMPT.format(today=date.today().isoformat(), max_ops=cfg["max_ops"],
                          context=("\n" + "\n".join(ctx) + "\n") if ctx else "", text=text)


def parse_ops(content: str) -> list[dict]:
    """Extract the ops list from a model reply (tolerates code fences / chatter)."""
    if not content:
        return []
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    ops = data.get("ops") if isinstance(data, dict) else None
    return [o for o in ops if isinstance(o, dict)] if isinstance(ops, list) else []


def reflect(llm, text: str, previous_assistant: str = "", known_people: list[str] | None = None) -> list[dict]:
    """ONE model call. Returns proposed (unvalidated) ops; [] on any failure."""
    try:
        resp = llm.chat(messages=[{"role": "user", "content": build_prompt(text, previous_assistant,
                                                                           known_people)}],
                        stream=False, tools=[], temperature=0)
        content, _ = llm.extract_response(resp)
        return parse_ops(content or "")
    except Exception as e:
        logger.warning("brain reflect failed: %s", e)
        return []


# ---------------------------------------------------------------- validate
def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+", s or ""))


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _snake(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40]


def validate(ops: list[dict], text: str, known_names: set[str] | None = None) -> list[dict]:
    """Return ops with a ``decision`` (auto | ask | drop) and ``reason``. Never raises."""
    cfg = _cfg()
    known = {n.lower() for n in (known_names or set())}
    out = []
    for raw in ops[: cfg["max_ops"]]:
        op = {k: _clean(v) if isinstance(v, str) else v for k, v in raw.items()}
        kind = op.get("kind", "")
        quote = op.get("quote", "")
        try:
            conf = max(0.0, min(1.0, float(op.get("confidence", 0))))
        except (TypeError, ValueError):
            conf = 0.0
        op["confidence"] = conf

        def drop(reason):
            out.append({**op, "decision": "drop", "reason": reason})

        if kind not in ("fact", "commitment", "idea", "alias"):
            drop("unknown kind")
            continue
        if not quote or not quote_in_text(quote, text):
            drop("quote not found in the message")
            continue
        if quote.rstrip().endswith("?"):
            drop("quote is a question")
            continue
        if kind == "fact":
            op["predicate"] = _snake(op.get("predicate", ""))
            if not op["predicate"] or not op.get("object"):
                drop("incomplete fact")
                continue
            if op["object"].strip().lower() in ("true", "false", "yes", "no", "none", "null"):
                drop("value is a flag, not a fact")
                continue
            subj = op.get("subject") or "user"
            if subj.lower() not in ("user", "me", "i") and subj.lower() not in known \
                    and subj.lower() not in text.lower():
                drop("subject not mentioned")
                continue
            body = op["object"]
        elif kind == "commitment":
            if not op.get("text"):
                drop("empty commitment")
                continue
            if not _PROMISE.search(quote):
                # a wish/goal is not a task: keep it as a goal fact instead
                op = {**op, "kind": "fact", "subject": op.get("who") or "user", "predicate": "goal",
                      "category": "goal",
                      "object": op["text"]}
                kind = "fact"
            body = op.get("object") or op["text"]
        elif kind == "idea":
            if not op.get("text"):
                drop("empty idea")
                continue
            body = op["text"]
        else:  # alias
            if not op.get("alias") or not op.get("canonical") or op["alias"].lower() not in text.lower():
                drop("alias not in the message")
                continue
            body = op["canonical"]
        if not _numbers(body) <= _numbers(text):
            drop("number not in the message")
            continue
        op["sensitivity"] = "private" if is_sensitive(op.get("predicate", ""), body) else "normal"
        if conf >= cfg["auto"]:
            out.append({**op, "decision": "auto", "reason": ""})
        elif conf >= cfg["ask"]:
            out.append({**op, "decision": "ask", "reason": "medium confidence"})
        else:
            drop("low confidence")
    return out


# ---------------------------------------------------------------- apply
def _store():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()._store


def _subject_node(kg, subject: str, subject_type: str) -> str | None:
    """Resolve or create the graph node a fact is about."""
    from backend.memory.memory_tools import _find_exact_node
    s = (subject or "user").strip()
    if s.lower() in ("user", "me", "i"):
        node = kg.get_node_by_label("user:Mayday-user") or kg.get_node_by_label("user")
        return node["id"] if node else kg.add_node("user", "user", {})
    store = kg._store
    if store is not None:
        aliased = store.resolve_alias(s)
        if aliased and kg.get_node(aliased):
            return aliased
    node = _find_exact_node(kg, s) or kg.get_node_by_label(f"person:{s}")
    if node:
        return node["id"]
    ntype = {"person": "person", "project": "project", "org": "organization",
             "place": "place"}.get(subject_type or "", "concept")
    label = f"person:{s}" if ntype == "person" else s
    return kg.add_node(ntype, label, {"name": s} if ntype == "person" else {})


TYPED_CATEGORIES = {"habit", "constraint", "value", "goal"}


def _category(op: dict) -> str:
    c = str(op.get("category") or "").lower().strip()
    if op.get("predicate") == "goal":
        return "goal"
    return c if c in TYPED_CATEGORIES | {"fact", "preference"} else "fact"


def _mirror_fact(kg, subject_id: str, predicate: str, obj: str, fact_id: str, category: str = "fact") -> None:
    """Graph edge for an active fact. Habits, constraints, values and goals get their own node type."""
    ntype = category if category in TYPED_CATEGORIES else "concept"
    label = f"{ntype}:{obj}" if ntype != "concept" else obj
    target = kg.get_node_by_label(label)
    tid = target["id"] if target else kg.add_node(ntype, label, {"text": obj} if ntype != "concept" else {})
    kg.add_edge_if_missing(subject_id, tid, predicate, {"fact_id": fact_id})


def _unmirror_fact(kg, fact: dict) -> None:
    cat = fact.get("category") or "fact"
    target = kg.get_node_by_label(f"{cat}:{fact['object']}" if cat in TYPED_CATEGORIES else fact["object"])
    if target and fact.get("subject_id"):
        kg.remove_edge(fact["subject_id"], target["id"], fact["predicate"])


def write_fact(kg, op: dict, source_ref: str, status: str) -> dict:
    store = kg._store
    sid = _subject_node(kg, op.get("subject", "user"), op.get("subject_type", ""))
    pred, obj = op["predicate"], op["object"]
    for f in store.find_facts(sid, pred):
        if f["object"].lower() == obj.lower():
            return {**f, "duplicate": True}
    supersedes = None
    if status == "active" and pred in SINGLE_VALUED:
        for old in store.find_facts(sid, pred):
            store.update_fact(old["id"], status="superseded", valid_to=store_now())
            _unmirror_fact(kg, old)
            supersedes = old["id"]
    cat = _category(op)
    fact = store.add_fact(subject_id=sid, predicate=pred, object=obj, confidence=op["confidence"],
                          quote=op["quote"], source_ref=source_ref, sensitivity=op.get("sensitivity", "normal"),
                          status=status, supersedes=supersedes, category=cat)
    if status == "active":
        _mirror_fact(kg, sid, pred, obj, fact["id"], cat)
        if kg._store is not None:
            tgt = kg.get_node_by_label(f"{cat}:{obj}" if cat in TYPED_CATEGORIES else obj)
            kg._store.touch([sid] + ([tgt["id"]] if tgt else []),
                            importance=0.9 if cat in TYPED_CATEGORIES else 0.6)
    return fact


def store_now() -> str:
    from backend.brain.store import _now
    return _now()


def write_commitment(kg, op: dict, source_ref: str, status: str) -> dict:
    store = kg._store
    planner_id = None
    if status == "open" and (op.get("who") or "user").lower() in ("user", "me", "i"):
        try:
            from backend.core.planner_store import get_planner
            due = op.get("due") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(op.get("due") or "")) else None
            item = get_planner().create_item(op["text"], kind="task", due_at=due,
                                             source={"type": "brain", "quote": op["quote"]})
            planner_id = item["id"]
        except Exception as e:
            logger.warning("commitment -> planner failed: %s", e)
    return store.add_commitment(text=op["text"], who=op.get("who") or "user", due=op.get("due"),
                                quote=op["quote"], source_ref=source_ref, status=status,
                                planner_item_id=planner_id)


def write_idea(kg, op: dict, source_ref: str) -> dict:
    store = kg._store
    nid = kg.add_node("idea", op["text"][:120], {"quote": op["quote"]})
    me = _subject_node(kg, "user", "user")
    kg.add_edge_if_missing(me, nid, "has_idea")
    return store.add_idea(text=op["text"], quote=op["quote"], source_ref=source_ref, linked_node_id=nid)


def apply(ops: list[dict], source_ref: str = "") -> list[dict]:
    """Write validated ops. Returns what was written (for logging / the Learned feed)."""
    from backend.memory.knowledge_graph import get_graph
    kg = get_graph()
    if kg._store is None:
        logger.info("brain capture needs memory.backend: sqlite; skipping")
        return []
    written = []
    for op in ops:
        d = op.get("decision")
        if d not in ("auto", "ask"):
            continue
        try:
            if op["kind"] == "fact":
                rec = write_fact(kg, op, source_ref, "active" if d == "auto" else "pending")
            elif op["kind"] == "commitment":
                rec = write_commitment(kg, op, source_ref, "open" if d == "auto" else "pending")
            elif op["kind"] == "idea":
                if d != "auto":
                    continue
                rec = write_idea(kg, op, source_ref)
            else:
                node = kg.get_node_by_label(op["canonical"]) or kg.get_node_by_label(f"person:{op['canonical']}")
                if not node or d != "auto":
                    continue
                kg._store.set_alias(op["alias"], node["id"])
                rec = {"alias": op["alias"], "node_id": node["id"]}
            written.append({"kind": op["kind"], "decision": d, **rec})
        except Exception as e:
            logger.warning("brain apply failed for %s: %s", op.get("kind"), e)
    return written


# ---------------------------------------------------------------- pipeline
def known_people(kg) -> list[str]:
    names = []
    for n in kg.get_nodes_by_type("person"):
        names.append(n.get("properties", {}).get("name") or re.sub(r"^person:", "", n["label"]))
    return sorted(set(names))


def capture_turn(llm, text: str, previous_assistant: str = "", source_ref: str = "") -> dict:
    """Gate -> reflect -> validate -> apply. Synchronous; run it off the event loop."""
    if not _cfg()["enabled"] or not gate(text):
        return {"gated": True, "ops": [], "written": []}
    from backend.memory.knowledge_graph import get_graph
    kg = get_graph()
    people = known_people(kg)
    ops = validate(reflect(llm, text, previous_assistant, people), text, set(people))
    written = apply(ops, source_ref)
    if ops:
        logger.info("brain capture: %d proposed, %d written (%s)", len(ops), len(written),
                    ", ".join(f"{o['kind']}:{o['decision']}" for o in ops))
    return {"gated": False, "ops": ops, "written": written}
