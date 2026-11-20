"""Brain V2 P5: tool planner, tool_search, memory-aware recipients, selection log."""
import pytest

from backend.brain import tools as bt


def _t(name, desc):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": {}}}}


TOOLS = [
    _t("gmail_send", "Send an email message from the Mayday mailbox to a recipient"),
    _t("gmail_search", "Search the inbox for email messages"),
    _t("plan_add", "Add a task, event or reminder to the planner"),
    _t("plan_list", "List planner items for today, upcoming, waiting"),
    _t("music_play", "Play a song or music playlist"),
    _t("git_commit", "Commit staged changes to the git repository"),
    _t("set_volume", "Set the system speaker volume"),
    _t("recall", "Search long-term memory"),
] + [_t(f"filler_{i}", f"unrelated capability number {i}") for i in range(40)]


@pytest.fixture(autouse=True)
def _sqlite(monkeypatch):
    import backend.memory.knowledge_graph as kgmod
    base = kgmod.load_config()
    cfg = {**base, "memory": {**base["memory"], "backend": "sqlite"}}
    monkeypatch.setattr(kgmod, "load_config", lambda: cfg)
    monkeypatch.setattr(kgmod, "_graph", None)


def test_index_ranks_by_name_and_description():
    idx = bt.ToolIndex(TOOLS)
    assert idx.search("send an email to Kiran")[0] == "gmail_send"
    assert idx.search("commit my changes")[0] == "git_commit"
    assert idx.search("it's too loud")[0] == "set_volume"      # synonym loud -> volume


def test_plan_tools_caps_orders_and_adds_tool_search():
    idx = bt.ToolIndex(TOOLS)
    out = bt.plan_tools(TOOLS, "email Kiran the report", idx, essentials={"recall"},
                        intent_names={"gmail_send", "gmail_search"}, max_tools=10)
    names = [t["function"]["name"] for t in out]
    assert len(names) == 10 and names[-1] == "tool_search"
    assert set(names[:2]) == {"gmail_send", "gmail_search"}   # matching intent tools first
    assert names[2] == "recall"                                 # then essentials
    assert "music_play" not in names[:3]


def test_tool_search_adds_missing_tools():
    idx = bt.ToolIndex(TOOLS)
    current = [TOOLS[0], TOOLS[7]]
    text, added = bt.handle_tool_search("commit to git", idx, current)
    assert [t["function"]["name"] for t in added][0] == "git_commit"
    assert "git_commit" in text
    text, added = bt.handle_tool_search("send email", idx, TOOLS)   # already have all
    assert added == [] and "No other tools" in text


def test_resolve_recipient_from_planner_people_and_pronoun(monkeypatch):
    class P:
        def find_person(self, name):
            return {"name": "Kiran Rao", "email": "kiran@example.com"} if name.lower().startswith("kiran") else None
    monkeypatch.setattr("backend.core.planner_store.get_planner", lambda: P())
    from backend.memory.knowledge_graph import get_graph
    get_graph().add_node("person", "person:Kiran Rao", {"name": "Kiran Rao"})
    args, note = bt.resolve_args("gmail_send", {"to": "Kiran", "subject": "hi"})
    assert args["to"] == "kiran@example.com" and "Kiran" in note
    args, note = bt.resolve_args("gmail_draft", {"to": "him"}, ["I met Kiran Rao today"])
    assert args["to"] == "kiran@example.com"
    # unknown person: unchanged, never invented
    args, note = bt.resolve_args("gmail_send", {"to": "Zed"})
    assert args == {"to": "Zed"} and note == ""
    # already an address: untouched
    assert bt.resolve_args("gmail_send", {"to": "a@b.co"})[0] == {"to": "a@b.co"}


def test_resolve_recipient_from_graph_email_property(monkeypatch):
    monkeypatch.setattr("backend.core.planner_store.get_planner",
                        lambda: type("P", (), {"find_person": lambda self, n: None})())
    from backend.memory.knowledge_graph import get_graph
    get_graph().add_node("person", "person:Meera", {"name": "Meera", "email": "meera@example.com"})
    assert bt.resolve_args("gmail_send", {"to": "Meera"})[0]["to"] == "meera@example.com"


def test_log_and_stats():
    bt.log_turn("c1", "email", "email kiran", ["gmail_send", "recall"], ["gmail_send"], [])
    bt.log_turn("c1", "general", "commit", ["recall"], ["git_commit"], ["git_commit"])
    s = bt.tool_stats()
    assert s["turns"] == 2 and dict(s["most_used"])["gmail_send"] == 1
    assert dict(s["found_via_search"])["git_commit"] == 1
