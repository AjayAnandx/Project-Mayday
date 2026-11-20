"""OpenUI spec builder: unit tests + a contract test against the real frontend parser/library."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.core import openui_builder as ob

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
NASTY = 'Say "hi" \\ back\\slash\nnew line ₹ é </script> {braces} [x]'


def _chartjs():
    return {"type": "line", "data": {"labels": ["2023", "2024"], "datasets": [
        {"label": "India", "data": [1.5, None]}, {"label": "US", "data": [3, 4.25]}]}}


def test_encode_values():
    assert ob.encode("a\"b") == '"a\\"b"'
    assert ob.encode([1, 2.0, 2.5, float("nan")]) == "[1, 2, 2.5, 0]"
    assert ob.encode({"k": [True, None]}) == '{"k": [true, null]}'


def test_trailing_optional_args_dropped():
    s = ob.Spec()
    s.metric("A", "1")
    assert s._lines[-1] == 'n1 = Metric("A", "1")'


def test_chart_from_chartjs_keeps_series_and_fallback():
    ui = ob.chart_from_chartjs(_chartjs(), "Growth")
    assert 'Chart("line", "Growth", ["2023", "2024"]' in ui["lang"]
    assert '"values": [1.5, 0]' in ui["lang"] and "India" in ui["fallback_text"]


def test_approval_ui_uses_custom_actions():
    ui = ob.approval_ui("build", "Paused before build.")
    assert '{"type": "approve_phase", "params": {"phase": "build"}}' in ui["lang"]
    assert "confirm" in ui["fallback_text"]


def _all_specs():
    s = ob.Spec()
    kids = [
        s.text(NASTY),
        s.metric_row([s.metric("Rev", "$4.2B", "FY24"), s.metric("Δ", "-3%")]),
        s.table(["Name", "Value"], [["a", 1], [NASTY, None]], "caption"),
        s.source_list([{"n": 1, "title": NASTY, "url": "https://x.org", "tier": "primary"},
                       {"n": 2, "title": "", "url": "https://y.org", "tier": "weird"}]),
        s.download("Report", "/research/x/report.docx", "docx"),
        s.actions([s.button("Ask", ob.ask_action(NASTY)), s.button("Go", ob.custom_action("x", a=1), "danger")]),
    ]
    card = s.card("Title", [s.chart("pie", "P", ["a"], [{"name": "s", "values": [1]}])], "sub")
    record = {"topic": "T", "claims": [], "sources": []}
    run = {"status": "completed", "usage": {}, "answers": [
        {"question": NASTY, "answer": "", "claim_ids": [], "cite_map": {}}]}
    return [
        {"name": "everything", "lang": s.build(kids + [card])},
        {"name": "chart", "lang": ob.chart_from_chartjs(_chartjs(), NASTY)["lang"]},
        {"name": "approval", "lang": ob.approval_ui("build", NASTY)["lang"]},
        {"name": "download", "lang": ob.download_ui("D", "/u/x.csv", "csv", NASTY)["lang"]},
        {"name": "research", "lang": ob.research_run_ui(record, run)["lang"]},
    ]


@pytest.mark.skipif(not shutil.which("node") or not (FRONTEND / "node_modules/@openuidev").exists(),
                    reason="node or frontend deps not installed")
def test_contract_with_real_parser(tmp_path):
    specs = tmp_path / "specs.json"
    specs.write_text(json.dumps(_all_specs(), ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(["node", "scripts/openui-contract.mjs", str(specs)], cwd=FRONTEND,
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.stdout, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    bad = [(r["name"], r["problems"]) for r in out["report"] if not r["ok"]]
    assert not bad, bad
    # strings survive exactly (quotes, backslashes, newlines, unicode, markup)
    text = next(r for r in out["report"] if r["name"] == "everything")["root"]["props"]["children"][0]
    assert text["props"]["content"] == NASTY


def test_model_context_strips_ui_but_storage_keeps_it():
    from backend.core.data_store import _without_ui
    raw = json.dumps({"message": "Chart ready", "ui": ob.chart_from_chartjs(_chartjs(), "G")})
    m = _without_ui({"role": "tool", "content": raw, "tool_call_id": "t1"})
    data = json.loads(m["content"])
    assert "ui" not in data and data["message"] == "Chart ready" and data["shown_to_user"].startswith("inline card: G.")
    assert m["tool_call_id"] == "t1"
    assert _without_ui({"role": "assistant", "content": raw})["content"] == raw   # only tool messages
    assert _without_ui({"role": "tool", "content": "plain text"})["content"] == "plain text"


def test_research_tools_attach_ui():
    from unittest import mock
    from backend.functions import research_flow_functions as fns
    with mock.patch("backend.core.research_export.export_run",
                    return_value={"path": "C:/x/run.docx", "url": "/research/t/run.docx", "format": "docx", "run_id": "r1"}):
        out = json.loads(fns.research_export("T"))
    assert 'Download("T (DOCX)", "/research/t/run.docx", "docx")' in out["ui"]["lang"]
    assert out["file_path"] == "C:/x/run.docx" and "artifact" not in out


def test_research_card_links_citations_to_sources():
    record = {"topic": "T", "sources": [{"id": "src_a", "url": "https://a.org/x", "title": "A", "tier": "primary"}],
              "claims": [{"id": "c1", "evidence": [{"source_id": "src_a", "verified": True, "stance": "supports"}]}]}
    run = {"status": "completed", "usage": {"sources": 3}, "answers": [
        {"question": "Q?", "answer": "Fact [C1].", "claim_ids": ["c1"], "cite_map": {"C1": "c1"}}]}
    ui = ob.research_run_ui(record, run)
    text_line = next(l for l in ui["lang"].splitlines() if "= Text(" in l and "Fact" in l)
    content = json.loads(text_line.split("Text(", 1)[1].rstrip(")"))
    assert content == r"Fact [\[1\]](https://a.org/x)."               # markdown link to source 1
    assert "Fact [1]." in ui["fallback_text"]                         # Telegram keeps plain refs


def test_telegram_sends_file_for_ui_tool_call(tmp_path):
    import asyncio
    from unittest import mock
    from backend.telegram.sender import TelegramSender
    docx = tmp_path / "run.docx"
    docx.write_bytes(b"PK fake docx")
    bot = mock.AsyncMock()
    sender = TelegramSender(bot, chat_id=1, verbose_tools=False)
    raw = json.dumps({"message": "Exported", "ui": ob.download_ui("T", "/research/t/run.docx", "docx"),
                      "file_path": str(docx)})
    msg = {"type": "tool_call", "name": "research_export", "result": "Exported",
           "ui": json.loads(raw)["ui"], "raw_result": raw}
    asyncio.run(sender.send_json(msg))
    sent = [c for c in bot.send_document.call_args_list]
    assert sent, "the exported file must still reach Telegram when result is flattened"
