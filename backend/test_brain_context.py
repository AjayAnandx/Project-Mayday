"""Brain V2 P4: hybrid recall, coreference, adaptive embeddings, now block. No network."""
import pytest

from backend.brain import context as ctx


@pytest.fixture(autouse=True)
def _sqlite(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)
    emb = ctx.Embedder()
    monkeypatch.setattr(ctx, "_EMBEDDER", emb)
    yield emb


def kg():
    from backend.memory.knowledge_graph import get_graph
    return get_graph()


def _seed():
    from backend.memory.memory_tools import remember
    remember("Kiran Rao", "said", "Coorg trip moved to December", node_type="person")
    remember("Kiran Rao", "lives_in", "Bengaluru", node_type="person")
    remember("user", "allergic_to", "peanuts", node_type="user")
    remember("user", "phone_number", "9876543210", node_type="user")
    for i in range(20):
        kg().add_node("concept", f"unrelated note {i}")


def test_keyword_recall_with_relations():
    _seed()
    out = ctx.retrieve("who is Kiran Rao?")
    assert "[m:" in out and "Kiran Rao" in out and "lives in Bengaluru" in out


def test_pronoun_resolved_from_recent_messages():
    _seed()
    assert "Coorg" not in ctx.retrieve("what did he say?")
    out = ctx.retrieve("what did he say?", ["I had lunch with Kiran today"])
    assert "Coorg" in out


def test_alias_resolution():
    _seed()
    k = kg()
    k._store.set_alias("kr", k.get_node_by_label("Kiran Rao")["id"])
    assert "Bengaluru" in ctx.retrieve("where does kr live")


def test_embeddings_only_when_keywords_are_weak(_sqlite, monkeypatch):
    orig = ctx._cfg
    monkeypatch.setattr(ctx, "_cfg", lambda: {**orig(), "use_embeddings": True})
    _seed()
    calls = []
    vec_for = {"peanuts": [1.0, 0.0], "satay": [0.9, 0.1]}

    def fake_post(texts):
        calls.append(texts)
        return [vec_for.get(next((w for w in vec_for if w in t.lower()), ""), [0.0, 1.0]) for t in texts]
    _sqlite._post = fake_post
    _sqlite.warm(kg())
    calls.clear()
    out = ctx.retrieve("who is Kiran Rao?")            # strong lexical agreement -> no embed call
    assert "Kiran" in out and calls == []
    out = ctx.retrieve("can I order the thai satay?")   # no words in common -> embeddings
    assert len(calls) == 1 and "peanuts" in out


def test_embeddings_down_still_recalls(_sqlite):
    _seed()
    _sqlite._post = lambda texts: None
    assert "Coorg" in ctx.retrieve("tell me about the Coorg trip")


def test_sensitive_values_never_in_block():
    _seed()
    out = ctx.retrieve("what is my phone number")
    assert "9876543210" not in out


def test_budget_respected(monkeypatch):
    for i in range(40):
        kg().add_node("person", f"person:Kiran Clone {i}", {"name": f"Kiran Clone {i}", "bio": "x" * 200})
    cfg = {"enabled": True, "token_budget": 100, "max_items": 8, "embed_model": "x",
           "embed_url": "http://127.0.0.1:9/none", "embed_timeout": 0.1, "use_embeddings": False}
    monkeypatch.setattr(ctx, "_cfg", lambda: cfg)
    out = ctx.retrieve("Kiran Clone")
    assert 0 < len(out) <= 100 * 4


def test_now_block(monkeypatch):
    class P:
        def list_items(self, view="all", **k):
            return {"today": [{"title": "Gym", "due_at": "2026-11-20T06:00"}, {"title": "Call bank"}],
                    "waiting": [{"title": "Dinesh: feedback"}]}.get(view, [])
    monkeypatch.setattr("backend.core.planner_store.get_planner", lambda: P())
    kg()._store.add_commitment(text="send Meera the photos", status="open")
    out = ctx.now_block()
    assert "Today: Gym (06:00); Call bank" in out
    assert "Waiting on others: Dinesh: feedback" in out
    assert "send Meera the photos" in out
