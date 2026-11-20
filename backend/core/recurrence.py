"""Recurrence engine for Planner items.

Rule shape (all keys optional except freq):
    {"freq": "daily"|"weekly"|"monthly"|"yearly", "interval": 1,
     "byweekday": [0..6]  (Mon=0, weekly only), "bymonthday": 1..31 (monthly only),
     "until": "YYYY-MM-DD", "count": int, "repeat_from": "due"|"completion"}

Legacy todo/event rules ({"pattern": "biweekly", "end_date": ...}) are accepted
via normalize_rule().

Times are naive *local* datetimes — the planner stores local wall-clock time.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

FREQS = ("daily", "weekly", "monthly", "yearly")
MAX_EXPANSION = 1000


def normalize_rule(rule: dict | None) -> dict | None:
    """Return a canonical rule dict, or None when there is no (valid) recurrence."""
    if not rule or not isinstance(rule, dict):
        return None
    freq = (rule.get("freq") or rule.get("pattern") or "").strip().lower()
    interval = rule.get("interval") or 1
    if freq == "biweekly":
        freq, interval = "weekly", 2 * int(interval)
    if freq in ("weekdays", "weekday"):
        freq, rule = "weekly", {**rule, "byweekday": [0, 1, 2, 3, 4]}
    if freq not in FREQS:
        return None
    out: dict = {"freq": freq, "interval": max(1, int(interval))}
    byweekday = rule.get("byweekday")
    if freq == "weekly" and byweekday:
        days = sorted({int(d) % 7 for d in byweekday})
        if days:
            out["byweekday"] = days
    if freq == "monthly" and rule.get("bymonthday"):
        out["bymonthday"] = max(1, min(31, int(rule["bymonthday"])))
    until = rule.get("until") or rule.get("end_date")
    if until:
        out["until"] = str(until)[:10]
    if rule.get("count") is not None:
        out["count"] = max(0, int(rule["count"]))
    out["repeat_from"] = "completion" if rule.get("repeat_from") == "completion" else "due"
    return out


def _add_months(dt: datetime, months: int, day: int | None = None) -> datetime:
    total = dt.month - 1 + months
    year, month = dt.year + total // 12, total % 12 + 1
    d = min(day or dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=d)


def next_occurrence(current: datetime, rule: dict) -> datetime:
    """The occurrence strictly after `current` (ignores until/count)."""
    freq, n = rule["freq"], rule.get("interval", 1)
    if freq == "daily":
        return current + timedelta(days=n)
    if freq == "weekly":
        days = rule.get("byweekday")
        if not days:
            return current + timedelta(weeks=n)
        wd = current.weekday()
        later = [d for d in days if d > wd]
        if later:
            return current + timedelta(days=later[0] - wd)
        # wrap to the first listed weekday, `n` weeks on from this week's Monday
        monday = current - timedelta(days=wd)
        return monday + timedelta(weeks=n, days=days[0])
    if freq == "monthly":
        return _add_months(current, n, rule.get("bymonthday"))
    return _add_months(current, 12 * n)


def _within_limits(occ: datetime, index: int, rule: dict) -> bool:
    until = rule.get("until")
    if until and occ.date() > date.fromisoformat(until):
        return False
    count = rule.get("count")
    if count is not None and index >= count:
        return False
    return True


def occurrences(anchor: datetime, rule: dict, start: datetime, end: datetime) -> list[datetime]:
    """All occurrences of a series anchored at `anchor` falling in [start, end]."""
    out: list[datetime] = []
    cur, i = anchor, 0
    while cur <= end and i < MAX_EXPANSION:
        if not _within_limits(cur, i, rule):
            break
        if cur >= start:
            out.append(cur)
        cur = next_occurrence(cur, rule)
        i += 1
    return out


def advance(due: datetime, rule: dict, completed_at: datetime | None = None,
            done_count: int = 0) -> datetime | None:
    """Next due datetime after completing one instance, or None when the series ended.

    repeat_from="completion" schedules relative to when it was actually done
    ("water plants 3 days after I last did it"); otherwise the calendar cadence holds
    and skipped past instances are fast-forwarded to the first future one.
    """
    base = due
    if rule.get("repeat_from") == "completion" and completed_at:
        base = completed_at.replace(hour=due.hour, minute=due.minute, second=0, microsecond=0)
    nxt = next_occurrence(base, rule)
    if rule.get("repeat_from") != "completion" and completed_at:
        guard = 0
        while nxt.date() < completed_at.date() and guard < MAX_EXPANSION:
            nxt = next_occurrence(nxt, rule)
            guard += 1
    if not _within_limits(nxt, done_count + 1, rule):
        return None
    return nxt


def describe(rule: dict | None) -> str:
    """Human label, e.g. 'every 2 weeks on Mon, Wed'."""
    r = normalize_rule(rule)
    if not r:
        return ""
    unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[r["freq"]]
    n = r["interval"]
    s = f"every {unit}" if n == 1 else f"every {n} {unit}s"
    if r.get("byweekday"):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        s += " on " + ", ".join(names[d] for d in r["byweekday"])
    if r.get("bymonthday"):
        s += f" on day {r['bymonthday']}"
    if r.get("repeat_from") == "completion":
        s += " after completion"
    return s
