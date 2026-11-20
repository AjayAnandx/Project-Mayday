"""Natural-language quick-add parser for the Planner.

    "Pay rent every month on the 1st at 9am #home !p1"
    "Call mom tomorrow 6pm"
    "Ravi to send the deck by friday"          → waiting-on Ravi
    "@Ravi review PR next tue"                   → waiting-on Ravi
    "Standup every weekday 10:00 for 15m event"  → event

Deterministic regexes only — fast, private, no LLM call. Anything unparsed stays
in the title. Returns fields ready for PlannerStore.create_item / delegate.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WD = {d: i for i, d in enumerate(WEEKDAYS)} | {d[:3]: i for i, d in enumerate(WEEKDAYS)} | {"tues": 1, "thur": 3, "thurs": 3}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MONTHS |= {m[:3]: n for m, n in list(MONTHS.items())} | {"sept": 9}

_WD_ALT = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|nesday|sday|urday|rsday)?"
_TIME = r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"


def _ordinal(n: str) -> int:
    return int(re.sub(r"\D", "", n))


def _wd_index(word: str) -> int | None:
    w = word.lower()
    for k, v in _WD.items():
        if w.startswith(k):
            return v
    return None


def parse_quick_add(text: str, now: datetime | None = None) -> dict:
    now = now or datetime.now().replace(second=0, microsecond=0)
    s = " " + text.strip() + " "
    out: dict = {"kind": "task"}

    def cut(pattern: str, flags=re.I):
        nonlocal s
        m = re.search(pattern, s, flags)
        if m:
            s = s[:m.start()] + " " + s[m.end():]
        return m

    # kind hints
    if cut(r"\s(?:as\s+an?\s+)?event\s"):
        out["kind"] = "event"
    elif cut(r"\s(?:remind\s+me\s+(?:to\s+)?)", ):
        out["kind"] = "reminder"

    # priority  !p1 / p1 / !!!
    m = cut(r"\s!?p([1-4])\b")
    if m:
        out["priority"] = int(m.group(1))
    elif cut(r"\s!!!\s"):
        out["priority"] = 1

    # tags and list  #tag  ~list
    tags = re.findall(r"\s#([\w-]+)", s)
    if tags:
        out["tags"] = tags
        s = re.sub(r"\s#[\w-]+", " ", s)
    m = cut(r"\s~([\w-]+)")
    if m:
        out["list"] = m.group(1)

    # duration "for 45m / for 1h / for 1.5 hours"
    m = cut(r"\sfor\s+(\d+(?:\.\d+)?)\s*(m|min|mins|minutes|h|hr|hrs|hours?)\b")
    if m:
        qty = float(m.group(1))
        out["estimate_min"] = int(qty * 60 if m.group(2).lower().startswith("h") else qty)

    # delegation: "@Name ..." or "Name to <verb> ..." at the start
    m = cut(r"\s@([A-Z][\w]*(?:\s[A-Z][\w]*)?)", flags=0)
    if m:
        out["kind"], out["person"] = "waiting", m.group(1)
    else:
        m = re.match(r"\s([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:to|will|should|needs?\s+to)\s+", s)
        if m and m.group(1).lower() not in ("i", "remind", "call", "email", "pay", "buy", "book"):
            out["kind"], out["person"] = "waiting", m.group(1)
            s = " " + s[m.end():]

    # recurrence
    rule = None
    m = cut(r"\severy\s+(weekday|weekdays)\b")
    if m:
        rule = {"freq": "weekly", "byweekday": [0, 1, 2, 3, 4]}
    if not rule:
        m = cut(r"\severy\s+(?:(\d+)\s+)?(day|week|month|year)s?\b(?:\s+on\s+the\s+(\d{1,2})(?:st|nd|rd|th)?)?")
        if m:
            rule = {"freq": {"day": "daily", "week": "weekly", "month": "monthly", "year": "yearly"}[m.group(2).lower()],
                    "interval": int(m.group(1) or 1)}
            if m.group(3):
                rule["bymonthday"] = int(m.group(3))
    if not rule:
        m = cut(r"\severy\s+((?:" + _WD_ALT + r")(?:\s*(?:,|and)\s*" + _WD_ALT + r")*)\b")
        if m:
            days = sorted({_wd_index(w) for w in re.findall(_WD_ALT, m.group(1), re.I)} - {None})
            rule = {"freq": "weekly", "byweekday": days}
    if not rule:
        m = cut(r"\s(daily|weekly|monthly|yearly)\b")
        if m:
            rule = {"freq": m.group(1).lower()}
    if not rule:
        m = cut(r"\severy\s+(\d{1,2})(?:st|nd|rd|th)\b")
        if m:
            rule = {"freq": "monthly", "bymonthday": _ordinal(m.group(1))}
    if rule:
        out["recurrence"] = rule

    # date
    day = None
    if cut(r"\s(?:by\s+|on\s+)?today\b"):
        day = now.date()
    elif cut(r"\s(?:by\s+|on\s+)?tonight\b"):
        day = now.date()
        out.setdefault("_default_time", (20, 0))
    elif cut(r"\s(?:by\s+|on\s+)?tomorrow\b|\stmr\b|\stmrw\b"):
        day = now.date() + timedelta(days=1)
    elif (m := cut(r"\s(?:by\s+|on\s+)?in\s+(\d+)\s+(day|week|month)s?\b")):
        n, unit = int(m.group(1)), m.group(2).lower()
        day = now.date() + timedelta(days=n * {"day": 1, "week": 7, "month": 30}[unit])
    elif (m := cut(r"\s(?:by\s+|on\s+)?(next\s+)?(" + _WD_ALT + r")\b")):
        target = _wd_index(m.group(2))
        if m.group(1):  # "next friday" = the Friday of next calendar week
            delta = (7 - now.weekday()) + target
        else:           # "friday" = the coming Friday (a week out if today is Friday)
            delta = (target - now.weekday()) % 7 or 7
        day = now.date() + timedelta(days=delta)
    elif (m := cut(r"\s(?:by\s+|on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\b")):
        day = _future_date(now, MONTHS[m.group(2).lower()], int(m.group(1)))
    elif (m := cut(r"\s(?:by\s+|on\s+)?(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b")):
        day = _future_date(now, MONTHS[m.group(1).lower()], int(m.group(2)))
    elif (m := cut(r"\s(?:by\s+|on\s+)?(\d{4}-\d{2}-\d{2})\b")):
        day = datetime.fromisoformat(m.group(1)).date()
    elif cut(r"\s(?:by\s+)?next\s+week\b"):
        day = now.date() + timedelta(days=(7 - now.weekday()))

    # time
    hm = None
    m = cut(r"\s(?:at\s+)?(noon|midnight|morning|evening)\b")
    if m:
        hm = {"noon": (12, 0), "midnight": (0, 0), "morning": (9, 0), "evening": (18, 0)}[m.group(1).lower()]
    else:
        m = cut(r"\s(?:at\s+|@\s*)?(\d{1,2}):(\d{2})\s*(am|pm)?\b") or cut(r"\s(?:at\s+)?(\d{1,2})()\s*(am|pm)\b")
        if m:
            h = int(m.group(1)) % 24
            mi = int(m.group(2) or 0)
            ap = (m.group(3) or "").lower()
            if ap == "pm" and h < 12:
                h += 12
            if ap == "am" and h == 12:
                h = 0
            hm = (h, mi)
    hm = hm or out.pop("_default_time", None)
    out.pop("_default_time", None)

    if day is None and rule:
        day = _first_occurrence(now, rule, hm)
    if hm and day is None:
        day = now.date() if (hm[0], hm[1]) > (now.hour, now.minute) else now.date() + timedelta(days=1)
    if day:
        when = datetime.combine(day, datetime.min.time())
        stamp = when.replace(hour=hm[0], minute=hm[1]).strftime("%Y-%m-%dT%H:%M") if hm else day.isoformat()
        out["start_at" if out["kind"] == "event" else "due_at"] = stamp
        if out["kind"] == "event" and out.get("estimate_min") and hm:
            out["end_at"] = (when.replace(hour=hm[0], minute=hm[1]) + timedelta(minutes=out["estimate_min"])).strftime("%Y-%m-%dT%H:%M")

    title = re.sub(r"\s+", " ", s).strip(" ,.-")
    title = re.sub(r"^(?:to|by)\s+", "", title, flags=re.I)
    title = re.sub(r"\s+(?:by|on|at)$", "", title, flags=re.I)
    out["title"] = title[:1].upper() + title[1:] if title else text.strip()
    return out


def _first_occurrence(now: datetime, rule: dict, hm: tuple | None):
    """First date a new series should start on (today counts if its time hasn't passed)."""
    today = now.date()
    passed = hm is not None and (hm[0], hm[1]) <= (now.hour, now.minute)
    if rule.get("bymonthday"):
        d = rule["bymonthday"]
        for months_ahead in range(0, 13):
            y, m = divmod(today.month - 1 + months_ahead, 12)
            try:
                cand = datetime(today.year + y, m + 1, d).date()
            except ValueError:
                continue
            if cand > today or (cand == today and not passed):
                return cand
    if rule.get("byweekday"):
        for ahead in range(0, 8):
            cand = today + timedelta(days=ahead)
            if cand.weekday() in rule["byweekday"] and (ahead > 0 or not passed):
                return cand
    return today + timedelta(days=1) if passed else today


def _future_date(now: datetime, month: int, day: int):
    year = now.year
    try:
        d = datetime(year, month, day).date()
    except ValueError:
        return None
    if d < now.date():
        d = d.replace(year=year + 1)
    return d
