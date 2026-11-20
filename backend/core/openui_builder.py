"""Builds OpenUI Lang for Mayday's own component library (frontend/src/openui/library.tsx).

Specs are written deterministically from data; no model is involved, so they cannot be
malformed by an LLM. Arguments are POSITIONAL in the order the frontend's Zod schemas declare
them. If you change a component there, change it here and run the contract test
(`backend/test_openui_builder.py::test_contract_with_real_parser`).

A tool attaches a spec by returning JSON with a ``ui`` key:
    {"message": "...", "ui": {"lang": "...", "title": "...", "fallback_text": "..."}}
chat.py forwards it on the tool_call message; the frontend renders it inline; Telegram sends
``fallback_text`` (plus the chart PNG when there is one).
"""
from __future__ import annotations

import json
import math
import re
from typing import Any


class Ref:
    """A statement identifier inside a spec."""

    def __init__(self, name: str):
        self.name = name


class Raw:
    """Pre-encoded OpenUI Lang expression (used for actions)."""

    def __init__(self, text: str):
        self.text = text


def encode(v: Any) -> str:
    if isinstance(v, Ref):
        return v.name
    if isinstance(v, Raw):
        return v.text
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return "0"
        return repr(int(v)) if isinstance(v, float) and v.is_integer() and abs(v) < 1e15 else repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(str(k))}: {encode(x)}" for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(encode(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


class Spec:
    """Accumulates statements; ``root`` is always a Stack of the given children."""

    def __init__(self):
        self._lines: list[str] = []
        self._n = 0

    def add(self, component: str, *args) -> Ref:
        while args and args[-1] is None:  # trailing optional args are omitted
            args = args[:-1]
        self._n += 1
        ref = Ref(f"n{self._n}")
        self._lines.append(f"{ref.name} = {component}({', '.join(encode(a) for a in args)})")
        return ref

    def build(self, children: list[Ref]) -> str:
        return "\n".join([f"root = Stack({encode(children)})", *self._lines])

    # components (argument order mirrors library.tsx) ------------------------

    def text(self, content: str) -> Ref:
        return self.add("Text", content)

    def metric(self, label: str, value: str, hint: str | None = None) -> Ref:
        return self.add("Metric", label, str(value), hint)

    def metric_row(self, items: list[Ref]) -> Ref:
        return self.add("MetricRow", items)

    def chart(self, kind: str, title: str, labels: list[str], series: list[dict], unit: str | None = None) -> Ref:
        kind = kind if kind in ("bar", "line", "pie") else "bar"
        clean = [{"name": str(s.get("name") or "Value"),
                  "values": [float(x) if isinstance(x, (int, float)) and math.isfinite(x) else 0.0
                             for x in s.get("values", [])]} for s in series]
        return self.add("Chart", kind, title, [str(x) for x in labels], clean, unit or None)

    def table(self, columns: list[str], rows: list[list[Any]], caption: str | None = None) -> Ref:
        return self.add("Table", [str(c) for c in columns],
                        [["" if c is None else str(c) for c in r] for r in rows], caption)

    def source_list(self, items: list[dict]) -> Ref:
        tiers = ("primary", "secondary", "tertiary", "unknown")
        return self.add("SourceList", [{"n": int(s["n"]), "title": str(s.get("title") or s.get("url") or ""),
                                        "url": str(s.get("url") or ""),
                                        "tier": s.get("tier") if s.get("tier") in tiers else "unknown"}
                                       for s in items])

    def download(self, title: str, url: str, fmt: str) -> Ref:
        return self.add("Download", title, url, fmt)

    def button(self, label: str, action: Raw, variant: str | None = None) -> Ref:
        return self.add("Button", label, action, variant)

    def actions(self, buttons: list[Ref]) -> Ref:
        return self.add("Actions", buttons)

    def card(self, title: str, children: list[Ref], subtitle: str | None = None) -> Ref:
        return self.add("Card", title, children, subtitle)


def custom_action(action_type: str, **params) -> Raw:
    """Action object the frontend routes by ``type`` (see OpenUIBlock.onAction)."""
    return Raw(encode({"type": action_type, "params": params}))


def ask_action(message: str) -> Raw:
    """Sends ``message`` as a new user turn."""
    return Raw(f"@ToAssistant({encode(message)})")


def payload(spec: Spec, children: list[Ref], title: str, fallback_text: str) -> dict:
    return {"lang": spec.build(children), "title": title, "fallback_text": fallback_text}


# ── ready-made specs ────────────────────────────────────────────────────────

def chart_from_chartjs(chart_json: dict, title: str, unit: str | None = None) -> dict:
    """Chart.js config (as written by report_generator) → inline chart spec."""
    data = chart_json.get("data", {})
    labels = [str(x) for x in data.get("labels", [])]
    series = [{"name": d.get("label") or "Value",
               "values": [x if isinstance(x, (int, float)) else 0 for x in d.get("data", [])]}
              for d in data.get("datasets", [])]
    kind = chart_json.get("type", "bar")
    spec = Spec()
    ch = spec.chart("pie" if kind in ("pie", "doughnut") else ("line" if kind == "line" else "bar"),
                    title, labels, series, unit)
    lines = [f"{title}:"] + [f"- {lb}: " + ", ".join(f"{s['name']} {s['values'][i]}" for s in series
                                                    if i < len(s["values"]))
                             for i, lb in enumerate(labels[:30])]
    return payload(spec, [ch], title, "\n".join(lines))


def research_run_ui(record: dict, run: dict) -> dict:
    """Cited answers + sources (+ downloads) for one research run."""
    from backend.core.research_report import _render_answer, _source_numbering
    answers = run.get("answers") or []
    claim_refs, sources = _source_numbering(record, answers)
    spec = Spec()
    u = run.get("usage") or {}
    children = [spec.metric_row([
        spec.metric("Status", run.get("status", "")),
        spec.metric("Questions answered", f"{sum(1 for a in answers if a.get('answer'))}/{len(answers)}"),
        spec.metric("Cited sources", str(len(sources)), f"{u.get('sources', 0)} gathered this run"),
        spec.metric("Cost", f"${u.get('cost_usd', 0):.3f}"),
    ])]
    fallback = [f"Research: {record['topic']} ({run.get('status')})"]
    urls = {n: s.get("url") for n, s in enumerate(sources, 1)}

    def link_refs(text: str) -> str:  # [3] → markdown link to source 3
        return re.sub(r"\[(\d+)\]", lambda m: f"[\\[{m.group(1)}\\]]({urls[int(m.group(1))]})"
                      if urls.get(int(m.group(1))) else m.group(0), text)

    for i, a in enumerate(answers, 1):
        text = _render_answer(a, claim_refs) if a.get("answer") else "_Not enough verified evidence._"
        children.append(spec.card(f"{i}. {a['question']}", [spec.text(link_refs(text))]))
        fallback.append(f"\n{i}. {a['question']}\n{text}")
    if sources:
        items = [{"n": n, "title": s.get("title"), "url": s.get("url"), "tier": s.get("tier")}
                 for n, s in enumerate(sources, 1)]
        children.append(spec.card("Sources", [spec.source_list(items)]))
        fallback.append("\nSources:\n" + "\n".join(f"[{x['n']}] {x['title'] or x['url']} {x['url']}" for x in items))
    children.append(spec.actions([
        spec.button("Show evidence", ask_action(f"Show the verified claims for research '{record['topic']}'"), "secondary"),
        spec.button("Export Word", ask_action(f"Export research '{record['topic']}' as docx"), "secondary"),
    ]))
    return payload(spec, children, record["topic"], "\n".join(fallback))


def download_ui(title: str, url: str, fmt: str, note: str = "") -> dict:
    spec = Spec()
    kids = ([spec.text(note)] if note else []) + [spec.download(title, url, fmt)]
    return payload(spec, kids, title, f"{title}: {url}")


def approval_ui(phase: str, message: str) -> dict:
    spec = Spec()
    card = spec.card(f"Approval needed: {phase}", [
        spec.text(message),
        spec.actions([
            spec.button("Approve and continue", custom_action("approve_phase", phase=phase)),
            spec.button("Stop", custom_action("reject_phase", phase=phase), "danger"),
        ]),
    ])
    return payload(spec, [card], f"Approval: {phase}", f"{message}\nReply 'confirm' to continue.")
