"""Brain evaluation runner (Brain V2, P0 baseline).

    python -m backend.brain_eval.run                       # smoke suite, live graph as background noise
    python -m backend.brain_eval.run --background empty    # hermetic (no live data at all)
    python -m backend.brain_eval.run --label after-p1 --show-failures

Measures what the model receives TODAY (probes.py mirrors chat.py):
  recall   - seeded memories, differently-phrased questions -> is the fact in the injected block (top 5)?
  tools    - personal phrasing -> does routing send the right tool, and how many tools?
  capture  - user statements -> what the observer would learn (precision / recall / wrong writes)

Everything runs in a temp graph (isolation.py). The live memory_graph.json is only
read (copied as noise), never written. No LLM or network calls.
Results: backend/brain_eval/results/<suite>/<timestamp>[-label]/ (gitignored).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

from backend.brain_eval import metrics, probes
from backend.brain_eval.isolation import LIVE_GRAPH, isolated_brain

HERE = Path(__file__).resolve().parent
SUITES = HERE / "suites"
RESULTS = HERE / "results"


def load_suite(name: str) -> dict:
    data = yaml.safe_load((SUITES / f"{name}.yaml").read_text(encoding="utf-8"))
    personal = SUITES / f"{name}.personal.yaml"  # optional, gitignored, real-data cases
    if personal.exists():
        extra = yaml.safe_load(personal.read_text(encoding="utf-8")) or {}
        for k in ("seed", "recall", "tools", "capture"):
            data.setdefault(k, []).extend(extra.get(k, []) or [])
    return data


def run_suite(suite: dict, background: str = "live", background_file: Path | None = None,
              capture_mode: str = "regex") -> dict:
    import time
    from backend.memory.memory_tools import remember

    bg = background_file or (LIVE_GRAPH if background == "live" else None)
    recall_rows, tool_rows, capture_rows = [], [], []
    with isolated_brain(bg) as kg:
        bg_nodes = len(kg._nodes)
        for m in suite.get("seed", []) or []:
            remember(m["entity"], m["relation"], m["value"],
                     context=m.get("context", ""), node_type=m.get("type", "concept"))
        if kg._store is not None:
            try:
                from backend.brain.context import get_embedder
                get_embedder()._vecs.clear()
                get_embedder().warm(kg)
            except Exception:
                pass
        profile = probes.profile_block()
        for case in suite.get("recall", []) or []:
            t0 = time.perf_counter()
            block = probes.recall_block(case["q"], case.get("history"))
            recall_rows.append(metrics.score_recall(case, block, (time.perf_counter() - t0) * 1000,
                                                    profile=profile))

    for case in suite.get("capture", []) or []:
        got = (probes.capture_reflector(case["text"]) if capture_mode == "reflector"
               else probes.capture(case["text"]))
        capture_rows.append(metrics.score_capture(case, got))

    if suite.get("tools"):
        probe = probes.ToolRoutingProbe()
        for case in suite["tools"]:
            tool_rows.append(metrics.score_tool(case, probe.route(case["q"])))
        n_tools = len(probe.tools)
    else:
        n_tools = 0

    return {"summary": metrics.summarize(recall_rows, tool_rows, capture_rows),
            "meta": {"capture": capture_mode, "background": str(background_file) if background_file else background, "background_nodes": bg_nodes,
                     "builtin_tools": n_tools},
            "recall": recall_rows, "tools": tool_rows, "capture": capture_rows}


def _previous(suite_dir: Path) -> dict | None:
    runs = sorted(p for p in suite_dir.glob("*") if (p / "results.json").exists())
    if not runs:
        return None
    return json.loads((runs[-1] / "results.json").read_text(encoding="utf-8"))


def scorecard(res: dict, prev: dict | None, suite: str) -> str:
    s, ps = res["summary"], (prev or {}).get("summary", {})
    out = [f"# Brain eval: {suite}", "",
           f"background: {res['meta']['background']} ({res['meta']['background_nodes']} nodes), "
           f"built-in tools: {res['meta']['builtin_tools']}, capture: {res['meta']['capture']}", "",
           "| metric | value | prev | delta |", "|---|---|---|---|"]
    for k in metrics.SUMMARY_KEYS:
        if k not in s:
            continue
        v, p = s[k], ps.get(k)
        d = ""
        if isinstance(p, (int, float)) and v != p:
            better = (v < p) if k in metrics.LOWER_IS_BETTER else (v > p)
            d = f"{v - p:+.3g} {'better' if better else 'WORSE'}"
        out.append(f"| {k} | {v} | {'' if p is None else p} | {d} |")
    fails = ([f"- recall `{r['id']}`: {r['q']}" for r in res["recall"] if not r["hit_at5"]]
             + [f"- tools `{t['id']}` ({t['intent']}, {t['sent']} sent): {t['q']}"
                for t in res["tools"] if not t["ok"]]
             + [f"- capture `{c['id']}`: got {c['captured']}" for c in res["capture"]
                if c["tp"] < c["expected"] or c["wrong"]])
    out += ["", f"## Failures ({len(fails)})", *fails]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="smoke")
    ap.add_argument("--background", choices=["live", "empty"], default="live")
    ap.add_argument("--background-file", type=Path, default=None,
                    help="use this graph JSON (read-only copy) as background, e.g. a cleaned graph")
    ap.add_argument("--offline", action="store_true",
                    help="no model calls: measure capture with the legacy regex observer")
    ap.add_argument("--label", default="")
    ap.add_argument("--show-failures", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args(argv)

    res = run_suite(load_suite(a.suite), a.background, a.background_file,
                    capture_mode="regex" if a.offline else "reflector")
    bg_name = "file" if a.background_file else a.background
    suite_dir = RESULTS / f"{a.suite}-{bg_name}" if not a.offline else RESULTS / f"{a.suite}-{bg_name}-offline"
    prev = _previous(suite_dir)
    card = scorecard(res, prev, a.suite)
    if not a.no_save:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{a.label}" if a.label else "")
        out = suite_dir / ts
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        (out / "scorecard.md").write_text(card, encoding="utf-8")
    text = card if a.show_failures else card.split("## Failures")[0] + \
        card[card.index("## Failures"):].splitlines()[0] + "\n"
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
