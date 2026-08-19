import re
from typing import Optional

from backend.core.user_awareness import (
    get_awareness_store, SLOTS, PROVENANCE_CONFIDENCE,
)


# Extraction rules: (regex, slot, value_group, provenance, is_name)
# Order matters — more specific first.
# Names are captured case-insensitively now (so "my name is john" works), with a
# stopword guard so filler like "and"/"the" is never swallowed into a name.
_NAME = r"([A-Za-z][a-z]*(?:\s+[A-Za-z][a-z]*){0,2})"
_NAME_STOPWORDS = {
    "and", "the", "a", "an", "my", "me", "i", "is", "are", "was", "were",
    "for", "to", "of", "in", "on", "at", "with", "that", "this", "it",
    "you", "he", "she", "we", "they", "but", "or", "so", "do", "does",
    "did", "have", "has", "had", "not", "no", "yes", "ok", "okay",
    "name", "named", "called", "who", "what", "they're", "im", "i'm",
}

# Broad kinship capture: handles grandmother/uncle/cousin/best friend + optional
# modifiers (late/best/close...). Name must be a capitalized proper noun so we never
# swallow a following word like "is"/"and" into the name.
_KIN = (r"(?:grandmother|grandma|grandfather|grandpa|grandparent|mother|mom|mum|father|dad|"
        r"brother|sister|aunt|uncle|cousin|niece|nephew|friend|wife|husband|spouse|"
        r"son|daughter|partner|fianc[ée]|girlfriend|boyfriend|soulmate|lover)")
_MOD = r"(?:late |beloved |best |close |good |dear |old )?"
# (?-i:...) keeps the name group case-SENSITIVE even though rules run with re.I,
# so we never swallow a following lowercase word (e.g. "my friend is" -> "is").
_NAME_CAP = r"((?-i:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*))"
# Phone number capture: handles "my (new/old/current) number is <digits>" and
# "my number changed to <digits>". Group 1 is the digits (+ optional separators).
_PHONE = r"(\+?\d[\d\s\-().]{6,18}\d)"
_PHONE_RULE = r"\bmy (?:new |old |current |updated )?number (?:is |is now |changed to |-> )?" + _PHONE + r"\b"
_RELATION_BROAD = r"\bmy " + _MOD + _KIN + r"\s+(?:named |called )?" + _NAME_CAP + r"\b"
_RELATION_BROAD_REV = r"\b" + _NAME_CAP + r" is my " + _MOD + _KIN + r"\b"

# List-of-relations capture: the single-name rules above only handle one person
# per sentence, so "my friends are John, Mary, Alex" / "I'm friends with A and B"
# / "add my friends X, Y" slipped through entirely. These pull every proper-noun
# name out of a relation list and emit one belief per person.
_KIN_OR_FRIEND = (
    r"(?:grandmother|grandma|grandfather|grandpa|grandparent|mother|mom|mum|father|dad|"
    r"brother|sister|aunt|uncle|cousin|niece|nephew|friend|wife|husband|spouse|"
    r"son|daughter|partner|fianc[ée]|girlfriend|boyfriend|soulmate|lover)"
)
_REL_LIST_HEAD = re.compile(
    r"\b(?:"
    # my/our <kin/friend>(s) <connector> <list>
    r"(?:my|our)\s+(?:close\s+|best\s+|good\s+|dear\s+|old\s+)?" + _KIN_OR_FRIEND + r"s?\s+(?:are|is|:|named|called|with)\s*"
    # my/our friends: <list>
    r"|(?:my|our)\s+(?:close\s+|best\s+)?friends?\s*:\s*"
    # I'm / I am friends with <list>
    r"|i(?:'m| am)?\s+friends?\s+with\s+"
    # I have (close/best) friends (named/called)? <list>
    r"|i\s+have\s+(?:close\s+|best\s+)?friends?(?:\s+(?:named|called))?\s+"
    # add my/our (close/best) friends <list>
    r"|add\s+(?:my|our)\s+(?:close\s+|best\s+)?friends?\s+"
    r")(?P<tail>[^\n.!?]+)",
    re.I,
)
# A name inside a list: one or more Capitalized words (so "Mary Jane" stays one).
_NAME_IN_LIST = re.compile(r"(?-i:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)")

_RULES = [
    (r"\bmy name is " + _NAME + r"\b", "identity", 1, "explicit", True),
    (r"\bmy name's " + _NAME + r"\b", "identity", 1, "explicit", True),
    (r"\bi'm " + _NAME + r"\b", "identity", 1, "explicit", True),
    (r"\bcall me " + _NAME + r"\b", "identity", 1, "explicit", True),
    (r"\bthis is " + _NAME + r"\b", "identity", 1, "explicit", True),
    (r"\bi work as (?:an? )?([A-Za-z ]{2,30}?)(?: at| for| in|\.|$)", "identity", 1, "explicit", True),
    (r"\bi work at (?:an? )?([A-Za-z ]{2,30}?)(?:,| and| but|\.|$)", "identity", 1, "explicit", False),
    (r"\bi'm a[n]? ([A-Za-z ]{2,30}?)(?: at| for| in|\.|$)", "identity", 1, "explicit", False),
    (r"\bi am a[n]? ([A-Za-z ]{2,30}?)(?: at| for| in|\.|$)", "identity", 1, "explicit", True),
    (r"\bi live (?:in|at|near) ([A-Za-z0-9 .]{2,30}?)(?:,| and| but|\.|$)", "context", 1, "explicit", False),
    (r"\bi am from ([A-Za-z0-9 .]{2,30}?)(?:,| and| but|\.|$)", "context", 1, "explicit", False),
    (r"\bi (?:like|love|enjoy) ([a-z0-9 ]{2,30}?)(?:,| and| but|\.|$)", "favorites", 1, "explicit", False),
    (r"\bmy favorite ([a-z]+) is ([A-Za-z0-9 ]{2,30}?)(?:,| and| but|\.|$)", "favorites", 2, "explicit", False),
    (r"\bi have a[n]? (?!loved one\b|girlfriend\b|boyfriend\b|partner\b|soulmate\b|lover\b)([a-z0-9 ]{2,20}?)(?:,| and| but|\.| called| named|$)", "belongings", 1, "explicit", False),
    (r"\bmy (?!name\b)([a-z]+) is ([A-Za-z0-9 ]{2,20}?)(?:,| and| but|\.|$)", "context", 2, "inference", False),
    # Phone number (placed before the generic context rule so it wins the dedupe)
    (_PHONE_RULE, "context", 1, "explicit", False),
    (r"\bi am studying ([a-z0-9 ]{2,30}?)(?:,| for| and| but|\.|$)", "goals", 1, "explicit", False),
    (r"\bmy exam (?:on|in|for) ([A-Za-z0-9 ]{2,30}?)(?: is| on|$)", "goals", 1, "explicit", False),
    (r"\bmy (mom|dad|mother|father|brother|sister|friend|wife|husband|son|daughter) ((?-i:[A-Z][a-z]+))\b",
     "relations", 2, "explicit", False),
    # Broad kinship capture (grandmother/uncle/cousin/best friend + modifiers)
    (_RELATION_BROAD, "relations", 1, "explicit", False),
    (_RELATION_BROAD_REV, "relations", 1, "explicit", False),
    # Loved ones / partners (capitalized name captured by _NAME group 1)
    (r"\bmy (?:loved one|love|lover|girlfriend|boyfriend|partner|fianc[ée]|soulmate) "
     r"(?:is named|is called|are named|was named|is|are|was|called|named)\s*" + _NAME + r"\b", "relations", 1, "explicit"),
    (r"\bi have a (?:loved one|lover|girlfriend|boyfriend|partner|soulmate) "
     r"(?:called|named)\s*" + _NAME + r"\b", "relations", 1, "explicit"),
    (r"\b(?:meet|met|dating|dated|with) (?:my )?(?:loved one|girlfriend|boyfriend|partner|fianc[ée]|soulmate) "
     r"(?:named )?" + _NAME + r"\b", "relations", 1, "explicit"),
    (r"\bi (?:feel|am|get) (?:so )?(stressed|anxious|sick|tired|overwhelmed)\b", "problems", 1, "explicit"),
    (r"\bi have (?:a|no) (?:money|savings|debt|financial) (?:problem|issue|stress)\b", "problems", 1, "explicit"),
]

_RELATION_TYPE = {
    "loved one": "partner", "soulmate": "partner", "partner": "partner",
    "fiancé": "partner", "fiancée": "partner", "girlfriend": "partner",
    "boyfriend": "partner", "lover": "partner", "love": "partner",
    "mom": "family", "mother": "family", "dad": "family", "father": "family",
    "brother": "family", "sister": "family", "wife": "family", "husband": "family",
    "son": "family", "daughter": "family", "friend": "friend",
    "grandmother": "family", "grandma": "family", "grandfather": "family",
    "grandpa": "family", "grandparent": "family", "aunt": "family", "uncle": "family",
    "cousin": "family", "niece": "family", "nephew": "family",
    "spouse": "partner", "best friend": "friend",
}

# Cold-start stereotype slots (Rich 1979): weak prior beliefs at 0.3.
_STEREOTYPE_RULES = [
    (r"\b(dog|cat|pet)\b", "belongings", "pet", "stereotype"),
    (r"\b(coffee|tea|pizza|biryani|music|movies?)\b", "favorites", None, "stereotype"),
]


def extract_candidates(text: str) -> list[dict]:
    """Return candidate beliefs: {slot, value, provenance, confidence, is_name}."""
    candidates = []
    seen = set()
    for rule in _RULES:
        pattern, slot, grp, prov = rule[0], rule[1], rule[2], rule[3]
        is_name = rule[4] if len(rule) > 4 else False
        for m in re.finditer(pattern, text, re.I):
            value = m.group(grp).strip()
            if not value:
                continue
            # stopword guard for name values (avoid swallowing filler words)
            if is_name and (
                not value.replace(" ", "").isalpha()
                or len(value) < 2
                or any(tok.lower() in _NAME_STOPWORDS for tok in value.split())
            ):
                continue
            key = (slot, value.lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "slot": slot,
                "value": value,
                "provenance": prov,
                "confidence": PROVENANCE_CONFIDENCE.get(prov, 0.55),
                "is_name": is_name,
            })
    # relation type tagging via source_refs-like annotation
    for c in candidates:
        if c["slot"] == "relations":
            for pat, rtype in _RELATION_TYPE.items():
                if re.search(r"\b" + re.escape(pat) + r"\b", text, re.I):
                    c["relation_type"] = rtype
                    break
    # situational / coping patterns (e.g. "I take coffee when I'm stressed, it's refreshing")
    for c in _extract_situations(text):
        key = (c["slot"], c["value"].lower())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(c)
    # lists of relations ("my friends are John, Mary, Alex")
    for c in _extract_relation_lists(text):
        key = (c["slot"], c["value"].lower())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(c)
    return candidates


# Situational / coping rules: "when <trigger state>, I <action>" (either order).
# Captured as a single 'context' belief so it can be recalled when the trigger
# re-appears. Effect (refreshing/calm/...) is appended when present.
_SIT_ACTION = r"(?:take|drink|eat|have|do|go(?:\s+for)?|use|listen to|watch|play)"
_SIT_TRIGGER = r"([a-z]{2,20})"
_SIT_ACTION_GRP = r"([a-z0-9 ]{2,25}?)"
_SITUATION_RULES = [
    # action-first: "I take coffee when I am stressed"
    (r"\b(?:i|i'?ll|i will)\s+" + _SIT_ACTION + r"\s+" + _SIT_ACTION_GRP +
     r"\s+(?:when|if|whenever)\s+(?:i\s+(?:am|feel|get)\s+)?" + _SIT_TRIGGER + r"\b", 1, 2),
    # trigger-first: "when I am stressed, I take coffee"
    (r"\b(?:when|if|whenever)\s+(?:i\s+(?:am|feel|get)\s+)?" + _SIT_TRIGGER +
     r",?\s+(?:i|i'?ll|i will)\s+" + _SIT_ACTION + r"\s+" + _SIT_ACTION_GRP +
     r"(?:,| because| it|$)", 2, 1),
]
_EFFECT_RE = re.compile(
    r"\b(?:feel[s]?|feels|keep[s]? me|makes? me|it['’]?s|is)\s+"
    r"(refreshing|refreshed|calm|calming|relaxed|relaxing|better|good|peaceful|happy|focused|energized)\b",
    re.I,
)


def _extract_situations(text: str) -> list[dict]:
    out = []
    for pattern, action_grp, trigger_grp in _SITUATION_RULES:
        for m in re.finditer(pattern, text, re.I):
            action = m.group(action_grp).strip()
            trigger = m.group(trigger_grp).strip()
            if not action or not trigger:
                continue
            action = re.sub(r"^(?:some|a|an|the)\s+", "", action, flags=re.I).strip()
            if not action:
                continue
            value = f"when {trigger} → {action}"
            eff = _EFFECT_RE.search(text)
            if eff:
                value += f" (feels {eff.group(1)})"
            out.append({
                "slot": "context",
                "value": value,
                "provenance": "explicit",
                "confidence": 0.9,
            })
    return out


def _extract_relation_lists(text: str) -> list[dict]:
    """Capture a LIST of relations from one sentence.

    The single-name rules only handle one person; this pulls every proper-noun
    name out of a relation list ("my friends are John, Mary", "I'm friends with
    A and B", "add my friends X, Y") and emits one belief per person.
    """
    out = []
    for m in _REL_LIST_HEAD.finditer(text):
        tail = m.group("tail").strip().rstrip(".!?;,")
        # Inherit the right relation_type from the matched head (e.g. cousins->family).
        rtype = "friend"
        for pat, rt in _RELATION_TYPE.items():
            if re.search(r"\b" + re.escape(pat) + r"s?\b", m.group(0), re.I):
                rtype = rt
                break
        for raw in _NAME_IN_LIST.findall(tail):
            name = " ".join(w[:1].upper() + w[1:] for w in raw.strip().split() if w)
            if len(name) < 2:
                continue
            out.append({
                "slot": "relations",
                "value": name,
                "provenance": "explicit",
                "confidence": 0.9,
                "is_name": False,
                "relation_type": rtype,
            })
    return out



def _auto_flag_conversation(source_refs: Optional[list[str]]):
    """When a personal fact is learned, mark the originating chat as important."""
    if not source_refs:
        return
    conv_id = next((r.split("conv:", 1)[1] for r in source_refs if r.startswith("conv:")), None)
    if not conv_id:
        return
    try:
        from backend.core.data_store import get_store
        get_store().set_conversation_important(conv_id, True)
    except Exception:
        pass


def ingest_text(text: str, source_refs: Optional[list[str]] = None) -> list[dict]:
    """Extract candidates from text and persist them as beliefs (flag-gated by caller).

    Side effects for newly learned personal facts:
      - mark the originating conversation "important"
      - schedule a gentle proactive follow-up when a relationship is learned
    """
    store = get_awareness_store()
    added = []
    for cand in extract_candidates(text):
        slot, value = cand["slot"], cand["value"]
        # De-dupe: a name stated as a generic "my X is Y" fact should upgrade to
        # the identity slot if an identity belief with the same value exists.
        if slot == "context" and store.find_belief("identity", value):
            slot = "identity"
        # Normalize name values (ajay -> Ajay) so the canonical name is consistent.
        if cand.get("is_name"):
            value = " ".join(w[:1].upper() + w[1:] for w in value.split() if w)
        pre_existing = store.find_belief(slot, value)
        res = store.add_belief(
            slot, value, provenance=cand["provenance"],
            confidence=cand["confidence"], source_refs=source_refs,
            relation_type=cand.get("relation_type", ""),
        )
        # Capture the user's name as a first-class, always-available fact.
        if cand.get("is_name") and isinstance(res, dict) and "id" in res:
            store.set_user_name(value)
        if not (isinstance(res, dict) and "id" in res):
            continue
        added.append(res)
        # only fire side effects on genuinely new beliefs
        if pre_existing is not None:
            continue
        if slot in ("relations", "identity"):
            _auto_flag_conversation(source_refs)
        if slot == "relations":
            try:
                store.create_followup(value, cand.get("relation_type", "relation"))
            except Exception:
                pass
    return added


# ---------------------------------------------------------------------------
# Observation hooks — wired into the existing save/CRUD paths (no-op unless
# awareness.enabled). Each hook is additive and returns without raising.
# ---------------------------------------------------------------------------
def hook_conversation_saved(conversation: dict):
    from backend.core.config import load_config
    if not load_config().get("awareness", {}).get("enabled", False):
        return
    for msg in conversation.get("messages", []):
        if msg.get("role") == "user":
            ingest_text(msg.get("content", ""), source_refs=[f"conv:{conversation.get('id')}"])


def hook_todo_created(todo: dict):
    from backend.core.config import load_config
    if not load_config().get("awareness", {}).get("enabled", False):
        return
    text = f"{todo.get('title', '')} {todo.get('description', '')}"
    if text.strip():
        ingest_text(text, source_refs=[f"todo:{todo.get('id')}"])


def hook_event_created(event: dict):
    from backend.core.config import load_config
    if not load_config().get("awareness", {}).get("enabled", False):
        return
    text = f"{event.get('title', '')} {event.get('description', '')}"
    if text.strip():
        ingest_text(text, source_refs=[f"event:{event.get('id')}"])
