"""Scoring for brain_eval cases. Pure functions, no I/O."""
from __future__ import annotations

import re
import statistics


def _rx(p: str):
    return re.compile(p, re.I)


def score_recall(case: dict, block: str, ms: float, profile: str = "") -> dict:
    """The always-on profile counts as one item that is always in the top 5."""
    lines = [l for l in block.splitlines() if l.strip()]
    # An item is a top-level line plus its indented relation lines.
    items: list[list[str]] = []
    for l in lines:
        if l.startswith((" ", "\t")) and items:
            items[-1].append(l)
        else:
            items.append([l])
    top5 = "\n".join([profile] + ["\n".join(i) for i in items[:5]])
    block = "\n".join([profile, block])
    exp = [_rx(p) for p in case["expect"]]
    hit_any = all(r.search(block) for r in exp) if exp else not block.strip()
    hit5 = all(r.search(top5) for r in exp) if exp else not block.strip()
    return {"id": case["id"], "q": case["q"], "hit": hit_any, "hit_at5": hit5,
            "tokens": len(block) // 4, "items": len(items), "ms": round(ms, 1),
            "block_head": top5}


def score_tool(case: dict, routed: dict) -> dict:
    names = set(routed["tools"])
    want = case.get("expect_any", [])
    ok = any(n in names for n in want) if want else len(names) == 0
    forbid = [n for n in case.get("forbid", []) if n in names]
    return {"id": case["id"], "q": case["q"], "ok": ok and not forbid,
            "intent": routed["intent"], "sent": len(names), "forbidden_sent": forbid,
            "ms": round(routed["ms"], 2)}


def score_capture(case: dict, captured: list[dict]) -> dict:
    items = [f"{c['slot']}: {c['value']}" for c in captured]
    exp = [_rx(p) for p in case.get("expect", [])]
    forbid = [_rx(p) for p in case.get("forbid", [])]
    tp = sum(1 for r in exp if any(r.search(i) for i in items))
    correct_items = sum(1 for i in items if any(r.search(i) for r in exp))
    wrong = [i for i in items if any(r.search(i) for r in forbid)
             or (exp and not any(r.search(i) for r in exp))]
    return {"id": case["id"], "text": case["text"], "captured": items,
            "tp": tp, "expected": len(exp), "n_captured": len(items),
            "correct_items": correct_items, "wrong": wrong}


def summarize(recall: list[dict], tools: list[dict], capture: list[dict]) -> dict:
    s: dict = {}
    if recall:
        s["recall_hit"] = round(sum(r["hit"] for r in recall) / len(recall), 3)
        s["recall_at5"] = round(sum(r["hit_at5"] for r in recall) / len(recall), 3)
        s["recall_tokens_avg"] = round(statistics.mean(r["tokens"] for r in recall))
        s["recall_ms_p50"] = round(statistics.median(r["ms"] for r in recall), 1)
    if tools:
        s["tool_correct"] = round(sum(t["ok"] for t in tools) / len(tools), 3)
        s["tools_sent_avg"] = round(statistics.mean(t["sent"] for t in tools), 1)
        s["tools_sent_max"] = max(t["sent"] for t in tools)
        s["general_fallback_rate"] = round(
            sum(t["intent"] == "general" for t in tools) / len(tools), 3)
    if capture:
        tp = sum(c["tp"] for c in capture)
        exp = sum(c["expected"] for c in capture)
        ncap = sum(c["n_captured"] for c in capture)
        correct = sum(c["correct_items"] for c in capture)
        p = correct / ncap if ncap else 0.0
        r = tp / exp if exp else 0.0
        s["capture_precision"] = round(p, 3)
        s["capture_recall"] = round(r, 3)
        s["capture_f1"] = round(2 * p * r / (p + r), 3) if p + r else 0.0
        s["capture_wrong_writes"] = sum(len(c["wrong"]) for c in capture)
    return s


SUMMARY_KEYS = ["recall_at5", "recall_hit", "recall_tokens_avg", "recall_ms_p50",
                "tool_correct", "tools_sent_avg", "tools_sent_max", "general_fallback_rate",
                "capture_f1", "capture_precision", "capture_recall", "capture_wrong_writes"]
# For these, lower is better (used for delta arrows).
LOWER_IS_BETTER = {"recall_tokens_avg", "recall_ms_p50", "tools_sent_avg", "tools_sent_max",
                   "general_fallback_rate", "capture_wrong_writes"}
