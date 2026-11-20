"""Brain V2 P1: sensitivity gating, core profile, evolution hygiene, ranked search."""
from backend.memory.knowledge_graph import get_graph
from backend.memory.sensitivity import is_sensitive, redact


def test_sensitivity():
    assert is_sensitive("phone_number", "x")
    assert is_sensitive("identity", "Phone number: 9876543210")
    assert is_sensitive("contact", "me@example.com")
    assert not is_sensitive("like", "biryani")
    assert not is_sensitive("birthday", "March 14")
    assert redact("call 98765 43210 or a@b.co") == "call [number] or [email]"


def test_profile_reads_all_self_nodes_and_hides_phone():
    from backend.core.phf import personal_facts
    from backend.core.user_awareness import get_awareness_store
    from backend.memory.memory_tools import remember
    get_awareness_store().set_user_name("Asha")
    remember("user", "allergic_to", "peanuts", node_type="user")
    remember("user", "phone_number", "9876543210", node_type="user")
    remember("Asha", "goal", "clear GATE", node_type="person")
    kg = get_graph()
    me = kg.get_node_by_label("user:Mayday-user")
    ph = kg.add_node("concept", "Phone number: 9876543210")
    kg.add_edge(me["id"], ph, "identity")
    out = personal_facts()
    assert "peanuts" in out and "clear GATE" in out and "Asha" in out
    assert "9876543210" not in out


def test_evolution_skips_tool_output():
    from backend.core.evolution import BUILD_PREF_TYPE, _store_preference
    kg = get_graph()
    _store_preference(kg, "general", "opencode_read: src/app.tsx(3,10): error", "avoided", 0.5, 2)
    _store_preference(kg, "landing", "use large hero typography", "preferred", 0.5, 2)
    assert kg.get_nodes_by_type("preference") == []
    rules = [n["properties"]["rule"] for n in kg.get_nodes_by_type(BUILD_PREF_TYPE)]
    assert rules == ["use large hero typography"]


def test_search_ranked_or_ignores_stopwords():
    kg = get_graph()
    kiran = kg.add_node("person", "Kiran Rao")
    kg.add_node("concept", "Kiran said the Coorg trip moved")
    for i in range(30):
        kg.add_node("concept", f"what is item {i}")
    res = kg.search("who is Kiran Rao?")
    assert res and res[0]["id"] == kiran
    assert all("item" not in n["label"] for n in res)
    # one rare word still finds a memory even when the rest of the phrasing differs
    assert any("Coorg" in n["label"] for n in kg.search("tell me about coorg plans"))


def test_everyday_phrasing_routes_to_the_right_intent():
    from backend.core.query_classifier import QueryClassifier
    q = QueryClassifier()
    cases = {
        "add buy milk to my list": "todo",
        "I need to call the bank tomorrow, don't let me forget": "todo",
        "what does my day look like?": "todo",
        "finished the gym today": "todo",
        "let's continue working on Orbit": "project",
        "it's too loud": "system",
        "open spotify": "system",
        "thanks, that helped": "greeting",
        "forget what I told you about my old job": "memory",
    }
    for text, want in cases.items():
        assert q.classify(text).intent == want, text
    assert q.classify("open the pdf about taxes").intent != "system"


def test_selector_max_groups_keeps_best():
    from backend.core.tool_selector import ToolSelector
    tools = [{"type": "function", "function": {"name": n, "description": d, "parameters": {}}}
             for n, d in [("a1", "send email message inbox"), ("b1", "play music song"),
                          ("c1", "email draft reply message")]]
    sel = ToolSelector(threshold=0.01)
    sel.build_index(tools, {"mail": {"a1"}, "music": {"b1"}, "draft": {"c1"}})
    ranked = sel.select_ranked("email message reply draft")
    assert ranked and ranked[0][1] >= ranked[-1][1]
    assert len(sel.select_tool_names("email message reply draft music", max_groups=1)) == 1


def test_redact_keeps_dates_and_times():
    t = "<t:2026-07-23T10:31:39.643486+00:00> exam on 2026-02-24, call +91 98765 43210"
    out = redact(t)
    assert "2026-07-23T10:31:39" in out and "2026-02-24" in out
    assert "98765" not in out and "[number]" in out
    assert not is_sensitive("birthday", "2026-03-14")
