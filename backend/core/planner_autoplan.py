"""'Plan my day' — propose time blocks for open tasks in the free gaps of a day.

Proposals only: nothing is written until the user accepts (plan_schedule /
POST /api/planner/items/{id}/schedule for each block).
"""
from __future__ import annotations

from datetime import datetime, timedelta

DEFAULT_ESTIMATE_MIN = 30
SLOT_ROUND_MIN = 15


def _round_up(dt: datetime) -> datetime:
    extra = (-dt.minute) % SLOT_ROUND_MIN
    return (dt + timedelta(minutes=extra)).replace(second=0, microsecond=0)


def propose_day(date: str | None = None, day_start: str = "09:00", day_end: str = "18:00") -> dict:
    from backend.core.planner_store import get_planner, now_local, parse_time
    p = get_planner()
    now = now_local()
    day = datetime.fromisoformat(date).date() if date else now.date()
    sh, sm = (int(x) for x in day_start.split(":"))
    eh, em = (int(x) for x in day_end.split(":"))
    lo = datetime.combine(day, datetime.min.time()).replace(hour=sh, minute=sm)
    hi = datetime.combine(day, datetime.min.time()).replace(hour=eh, minute=em)
    if day == now.date():
        lo = max(lo, _round_up(now))
    if lo >= hi:
        return {"date": day.isoformat(), "blocks": [], "unplaced": [],
                "summary": "No working time left today."}

    # busy intervals: timed events + already-blocked tasks
    busy: list[tuple[datetime, datetime]] = []
    day0 = datetime.combine(day, datetime.min.time())
    for it in p.all_items():
        if it["status"] != "open":
            continue
        if it["kind"] == "event":
            for inst in p.expand(it, day0, day0 + timedelta(days=1, minutes=-1)):
                s, has_time = parse_time(inst["start_at"])
                if not has_time:
                    continue
                e, _ = parse_time(inst.get("end_at") or inst["start_at"])
                busy.append((s, max(e, s + timedelta(minutes=15))))
        blk = it.get("scheduled_block")
        if blk and blk["start"][:10] == day.isoformat():
            busy.append((parse_time(blk["start"])[0], parse_time(blk["end"])[0]))
    busy.sort()

    gaps: list[list[datetime]] = []
    cur = lo
    for s, e in busy:
        if e <= cur:
            continue
        if s > cur:
            gaps.append([cur, min(s, hi)])
        cur = max(cur, e)
        if cur >= hi:
            break
    if cur < hi:
        gaps.append([cur, hi])
    gaps = [g for g in gaps if g[1] > g[0]]

    iso = day.isoformat()
    candidates = [
        i for i in p.all_items()
        if i["status"] == "open" and i["kind"] == "task" and not i.get("scheduled_block")
        and (not i.get("due_at") or i["due_at"][:10] <= iso)
    ]
    # overdue first, then due today, then undated; priority breaks ties
    candidates.sort(key=lambda i: (
        0 if i.get("due_at") and i["due_at"][:10] < iso else 1 if i.get("due_at") else 2,
        i.get("priority", 4), i.get("due_at") or "", i["created_at"]))

    blocks, unplaced = [], []
    for task in candidates:
        need = timedelta(minutes=task.get("estimate_min") or DEFAULT_ESTIMATE_MIN)
        for g in gaps:
            if g[1] - g[0] >= need:
                start = g[0]
                blocks.append({"item_id": task["id"], "title": task["title"],
                               "start": start.strftime("%Y-%m-%dT%H:%M"),
                               "end": (start + need).strftime("%Y-%m-%dT%H:%M")})
                g[0] = start + need
                break
        else:
            unplaced.append({"item_id": task["id"], "title": task["title"]})

    free_min = int(sum(((g[1] - g[0]) for g in gaps), timedelta()).total_seconds() // 60)
    if blocks:
        summary = f"Proposed {len(blocks)} block(s) for {day.strftime('%a %d %b')}"
        if unplaced:
            summary += f", {len(unplaced)} task(s) didn't fit"
        summary += f". {free_min} min still free."
    elif not candidates:
        summary = "No open tasks to plan."
    else:
        summary = "No free slots big enough for your open tasks."
    return {"date": iso, "blocks": blocks, "unplaced": unplaced, "summary": summary}
