"""Regression: None-content (tool-call-only) assistant messages must never crash
indexing or search. Root cause of `WebSocket error: can only concatenate str
(not "NoneType") to str` — native tool_calls arrive with content=None and the
indexer did `" " + None`.
"""
import backend.core.data_store as dsmod


def _store(monkeypatch, tmp_path):
    data = tmp_path / "data.json"
    conv_dir = tmp_path / "conversations"
    conv_dir.mkdir()
    cfg = {"data": {"storage_path": str(data)}}
    monkeypatch.setattr(dsmod, "load_config", lambda: cfg)
    dsmod._store = None
    store = dsmod.get_store()
    store._conv_dir = conv_dir
    return store


def test_none_content_message_roundtrip(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    conv = store.create_conversation("t")
    cid = conv["id"]
    # Exact crash shape: assistant turn with content=None + tool_calls.
    store.add_message(cid, "assistant", None,
                      tool_calls=[{"id": "c1", "type": "function",
                                   "function": {"name": "list_todos", "arguments": "{}"}}])
    msgs = store.get_recent_messages(cid, 5)
    assert msgs[-1]["content"] == ""
    assert msgs[-1]["tool_calls"][0]["function"]["name"] == "list_todos"
    # Re-index path (startup rebuild) must also survive.
    full = store.get_conversation(cid)
    store._index_conversation(full)


def test_indexer_tolerates_legacy_none_on_disk(monkeypatch, tmp_path):
    store = _store(monkeypatch, tmp_path)
    conv = store.create_conversation("t")
    cid = conv["id"]
    store.add_message(cid, "user", "hello")
    full = store.get_conversation(cid)
    full["messages"].append({"role": "assistant", "content": None,
                             "timestamp": "2026-01-01"})
    store._index_conversation(full)  # must not raise
