"""Brain V2 P1 graph clean-up rules (pure function, no files)."""
from backend.memory.cleanup_graph import plan_cleanup


def _n(i, t, label, **props):
    return {"id": i, "type": t, "label": label, "properties": props}


def _e(i, s, t, rel):
    return {"id": i, "source": s, "target": t, "relation": rel, "properties": {}}


def _graph():
    return {"nodes": [
        _n("u", "user", "user:Mayday-user"),
        _n("p1", "project", "project:Orbit"),
        _n("p2", "project", "project:Seed123"),          # not in projects.json
        _n("t2", "concept", "task:Seed123 build"),         # only linked to p2
        _n("p3", "project", "project:Car Showroom"),      # real past project, keep
        _n("m", "email", "email:abc"),
        _n("j", "preference", "pref:general/avoided/x", rule="opencode_read: src/app.tsx(3,10): error"),
        _n("g", "preference", "pref:landing/preferred/y", rule="use large hero typography"),
        _n("loc", "preference", "13.0,80.1", lat="13.0", lon="80.1"),
        _n("r", "person", "person:ML Engineer"),
        _n("o", "person", "person:QuantumScripts"),
        _n("a1", "person", "Ajay"),
        _n("a2", "person", "person:Ajay"),
        _n("k", "concept", "college friend"),
    ], "edges": [
        _e("e1", "p2", "t2", "has_task_result"),
        _e("e2", "u", "a1", "relations"),
        _e("e3", "a2", "k", "is"),
        _e("e4", "u", "r", "relations"),
        _e("e5", "u", "a2", "relations"),
    ]}


def test_rules():
    res = plan_cleanup(_graph(), {"orbit"})
    nodes = {n["id"]: n for n in res["graph"]["nodes"]}
    assert "p3" in nodes
    assert "p1" in nodes and "p2" not in nodes and "t2" not in nodes   # leftover + cascade
    assert "m" not in nodes and "j" not in nodes and "r" not in nodes
    assert nodes["g"]["type"] == "build_preference"
    assert nodes["loc"]["type"] == "location" and nodes["loc"]["properties"]["kind"] == "user_location"
    assert nodes["o"]["type"] == "organization" and nodes["o"]["label"] == "QuantumScripts"
    # duplicate people merged into one survivor, edges re-pointed and de-duplicated
    ajays = [n for n in nodes.values() if n["label"].lower().endswith("ajay")]
    assert len(ajays) == 1
    keep = ajays[0]["id"]
    rels = {(e["source"], e["target"], e["relation"]) for e in res["graph"]["edges"]}
    assert ("u", keep, "relations") in rels and (keep, "k", "is") in rels
    assert len([r for r in rels if r[2] == "relations"]) == 1
    assert "u" in nodes and "k" in nodes


def test_input_not_mutated_and_idempotent():
    g = _graph()
    before = repr(g)
    first = plan_cleanup(g, {"orbit"})
    assert repr(g) == before
    second = plan_cleanup(first["graph"], {"orbit"})
    assert second["after"] == first["after"]


def test_no_projects_json_keeps_projects():
    res = plan_cleanup(_graph(), set())
    assert any(n["id"] == "p2" for n in res["graph"]["nodes"])


def test_alias_merge_across_prefix_and_type():
    g = {"nodes": [_n("u", "user", "user:Mayday-user"),
                   _n("a", "person", "person:Ravi Kumarr"), _n("b", "person", "person:Ravi Kumar"),
                   _n("c", "concept", "Ravi Kumarr"), _n("d", "concept", "Ravi Kumar")],
         "edges": [_e("1", "u", "a", "relations"), _e("2", "u", "c", "friend"), _e("3", "u", "d", "friend")]}
    res = plan_cleanup(g, set(), {"Ravi Kumarr": "Ravi Kumar"})
    labels = sorted(n["label"] for n in res["graph"]["nodes"])
    assert labels == ["Ravi Kumar", "person:Ravi Kumar", "user:Mayday-user"]
    assert len([e for e in res["graph"]["edges"] if e["relation"] == "friend"]) == 1
