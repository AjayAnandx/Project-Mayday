import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest


_temp_dirs: list[Path] = []


def make_fresh():
    """Create isolated DataStore + KnowledgeGraph with their own temp files."""
    from backend.core.data_store import DataStore
    from backend.memory.knowledge_graph import KnowledgeGraph

    temp_dir = Path(tempfile.mkdtemp())
    _temp_dirs.append(temp_dir)
    data_file = temp_dir / "data.json"
    graph_file = temp_dir / "memory_graph.json"
    data_file.write_text(json.dumps({"todos": [], "events": []}), encoding="utf-8")
    graph_file.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")

    config = {
        "data": {"storage_path": str(data_file)},
        "memory": {"graph_path": str(graph_file)},
        "server": {"host": "0.0.0.0", "port": 8770},
        "personality": {"default_tone": "neutral", "traits": [], "rules": []},
        "mcp": {"servers": {}},
    }

    with mock.patch("backend.core.data_store.load_config", return_value=config), \
         mock.patch("backend.memory.knowledge_graph.load_config", return_value=config):
        store = DataStore()
        kg = KnowledgeGraph()

    return store, kg


@pytest.fixture(autouse=True)
def cleanup():
    import backend.core.data_store
    import backend.memory.knowledge_graph
    backend.core.data_store._store = None
    backend.memory.knowledge_graph._graph = None
    yield
    backend.core.data_store._store = None
    backend.memory.knowledge_graph._graph = None
    while _temp_dirs:
        d = _temp_dirs.pop()
        if d.exists():
            shutil.rmtree(str(d), ignore_errors=True)


class TestFix1CreateTodoSync:
    """Fix 1: create_todo result ID is parsed and synced to knowledge graph."""

    def test_create_todo_result_contains_id(self):
        store, kg = make_fresh()
        with mock.patch("backend.functions.todo_functions.get_store", return_value=store):
            from backend.functions.todo_functions import create_todo
            result = create_todo(title="Buy groceries", description="Milk and eggs")

        assert "Created todo:" in result
        m = re.search(r'\(id: ([a-f0-9]+)\)', result)
        assert m is not None, f"Result should contain '(id: <hex>)': {result}"
        assert len(m.group(1)) == 12

    def test_create_todo_id_parsed_and_synced(self):
        store, kg = make_fresh()
        with mock.patch("backend.functions.todo_functions.get_store", return_value=store):
            from backend.functions.todo_functions import create_todo
            result = create_todo(title="Buy groceries")

        m = re.search(r'\(id: ([a-f0-9]+)\)', result)
        todo_id = m.group(1)

        todo = store.get_todo(todo_id)
        assert todo is not None

        kg.sync_todo(todo)
        nodes = [n for n in kg.get_full_graph()["nodes"] if n["type"] == "todo"]
        assert len(nodes) == 1
        assert nodes[0]["label"] == "Buy groceries"
        assert nodes[0]["properties"]["todo_id"] == todo_id

    def test_create_event_result_contains_id(self):
        store, kg = make_fresh()
        with mock.patch("backend.functions.calendar_functions.get_store", return_value=store):
            from backend.functions.calendar_functions import create_event
            result = create_event(
                title="Team meeting",
                start_time="2026-06-17T14:00:00",
                end_time="2026-06-17T15:00:00",
            )

        assert "Created event:" in result
        m = re.search(r'\(id: ([a-f0-9]+)\)', result)
        assert m is not None, f"Result should contain '(id: <hex>)': {result}"
        assert len(m.group(1)) == 12

    def test_create_event_id_parsed_and_synced(self):
        store, kg = make_fresh()
        with mock.patch("backend.functions.calendar_functions.get_store", return_value=store):
            from backend.functions.calendar_functions import create_event
            result = create_event(
                title="Standup",
                start_time="2026-06-18T09:00:00",
                end_time="2026-06-18T09:15:00",
            )

        m = re.search(r'\(id: ([a-f0-9]+)\)', result)
        event_id = m.group(1)

        event = store.get_event(event_id)
        assert event is not None

        kg.sync_event(event)
        nodes = [n for n in kg.get_full_graph()["nodes"] if n["type"] == "event"]
        assert len(nodes) == 1
        assert nodes[0]["label"] == "Standup"
        assert nodes[0]["properties"]["event_id"] == event_id

    def test_delete_todo_removes_graph_node(self):
        store, kg = make_fresh()
        with mock.patch("backend.functions.todo_functions.get_store", return_value=store):
            from backend.functions.todo_functions import create_todo, delete_todo
            result = create_todo(title="Temp item")

        m = re.search(r'\(id: ([a-f0-9]+)\)', result)
        todo_id = m.group(1)

        kg.sync_todo(store.get_todo(todo_id))
        assert len(kg.search("Temp item")) == 1

        with mock.patch("backend.functions.todo_functions.get_store", return_value=store):
            delete_todo(todo_id)

        kg.delete_todo_node(todo_id)
        assert len(kg.search("Temp item")) == 0


class TestFix2RecallPollution:
    """Fix 2: recall should not create junk concept nodes on empty results."""

    def test_recall_no_junk_nodes_on_empty(self):
        store, kg = make_fresh()
        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import recall
            before = len(kg.get_full_graph()["nodes"])

            result = recall("nonexistent_query_xyz_123")

            assert "No memories found" in result
            assert len(kg.get_full_graph()["nodes"]) == before

    def test_recall_still_returns_results(self):
        store, kg = make_fresh()
        kg.add_node("concept", "test item", {})
        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import recall
            result = recall("test item")

            assert "No memories found" not in result
            assert "test item" in result


class TestDeleteEntity:
    """delete_entity removes a node + all edges from the knowledge graph."""

    def test_delete_entity_sets_status_scraped(self):
        store, kg = make_fresh()
        nid = kg.add_node("project", "TestProject", {"status": "active"})
        assert len(kg.get_full_graph()["nodes"]) == 1

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import delete_entity
            result = delete_entity("TestProject")

        assert "Scraped entity" in result
        assert "TestProject" in result
        node = kg.get_node(nid)
        assert node is not None
        assert node["properties"]["status"] == "scraped"

    def test_delete_entity_keeps_node_and_edges(self):
        store, kg = make_fresh()
        a = kg.add_node("concept", "A", {})
        b = kg.add_node("concept", "B", {})
        kg.add_edge(a, b, "relates_to")
        assert len(kg.get_full_graph()["edges"]) == 1

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import delete_entity
            delete_entity("A")

        # Node A still exists but status is scraped
        node_a = kg.get_node(a)
        assert node_a is not None
        assert node_a["properties"]["status"] == "scraped"
        # Edges are preserved
        assert len(kg.get_full_graph()["edges"]) == 1

    def test_delete_entity_not_found(self):
        store, kg = make_fresh()

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import delete_entity
            result = delete_entity("Nonexistent")

        assert "No entity found" in result

    def test_delete_entity_case_sensitive(self):
        store, kg = make_fresh()
        nid = kg.add_node("project", "MyProject", {})

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import delete_entity
            result = delete_entity("myproject")

        assert "Scraped entity" in result
        node = kg.get_node(nid)
        assert node is not None
        assert node["properties"]["status"] == "scraped"


class TestFix3AutoContext:
    """Fix 3: auto-context injection should also search data store."""

    def test_store_returns_items_by_keyword_title(self):
        store, kg = make_fresh()
        store.create_todo(title="Buy milk", description="From the grocery store")
        store.create_event(
            title="Grocery shopping",
            start_time="2026-06-17T10:00:00",
            end_time="2026-06-17T11:00:00",
        )

        q = "grocery"
        q = q.lower()
        matches = set()
        for t in store.list_todos(include_completed=True):
            if q in t["title"].lower() or q in t.get("description", "").lower():
                matches.add(t["title"])
        for e in store.list_events():
            if q in e["title"].lower() or q in e.get("description", "").lower():
                matches.add(e["title"])

        assert "Buy milk" in matches
        assert "Grocery shopping" in matches

    def test_combined_graph_and_store_search(self):
        store, kg = make_fresh()
        kg.add_node("concept", "groceries", {})
        store.create_todo(title="Buy groceries", description="Weekly shopping")

        q = "groceries"
        memories = kg.search(q)
        graph_labels = set(m["label"] for m in memories)

        q = q.lower()
        store_matches = set()
        for t in store.list_todos(include_completed=True):
            if q in t["title"].lower() or q in t.get("description", "").lower():
                store_matches.add(t["title"])

        assert "groceries" in graph_labels
        assert "Buy groceries" in store_matches


class TestAddEdgeIfMissing:
    """add_edge_if_missing should not create duplicate edges."""

    def test_first_call_creates_edge(self):
        _, kg = make_fresh()
        a = kg.add_node("concept", "A", {})
        b = kg.add_node("concept", "B", {})
        eid = kg.add_edge_if_missing(a, b, "relates_to")
        assert eid is not None
        assert len(kg.get_full_graph()["edges"]) == 1

    def test_duplicate_call_returns_none(self):
        _, kg = make_fresh()
        a = kg.add_node("concept", "A", {})
        b = kg.add_node("concept", "B", {})
        kg.add_edge_if_missing(a, b, "relates_to")
        eid = kg.add_edge_if_missing(a, b, "relates_to")
        assert eid is None
        assert len(kg.get_full_graph()["edges"]) == 1

    def test_different_relation_creates_new_edge(self):
        _, kg = make_fresh()
        a = kg.add_node("concept", "A", {})
        b = kg.add_node("concept", "B", {})
        kg.add_edge_if_missing(a, b, "relates_to")
        eid = kg.add_edge_if_missing(a, b, "knows")
        assert eid is not None
        assert len(kg.get_full_graph()["edges"]) == 2


class TestRememberDedup:
    """remember() should not create duplicate edges."""

    def test_duplicate_remember_returns_already(self):
        _, kg = make_fresh()
        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import remember
            r1 = remember("TestEntity", "likes", "Pizza", node_type="concept")
            assert "Remembered" in r1
            r2 = remember("TestEntity", "likes", "Pizza", node_type="concept")
            assert "Already remembered" in r2

        g = kg.get_full_graph()
        assert len(g["edges"]) == 1

    def test_remember_whitespace_normalization(self):
        _, kg = make_fresh()
        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import remember
            r1 = remember("  Project:foo  ", "has_conversation", "conv-abc", node_type="project")
            assert "Remembered" in r1
            r2 = remember("Project:foo", "has_conversation", "  conv-abc  ", node_type="project")
            assert "Already remembered" in r2

        assert len(kg.get_full_graph()["nodes"]) == 2


class TestDeleteConversationNode:
    """delete_conversation_node removes conversation nodes by conv_id."""

    def test_delete_conversation_node_removes(self):
        _, kg = make_fresh()
        conv = {"id": "conv-123", "title": "Test", "messages": []}
        kg.sync_conversation(conv)
        assert len([n for n in kg.get_full_graph()["nodes"] if n["type"] == "conversation"]) == 1

        kg.delete_conversation_node("conv-123")
        assert len([n for n in kg.get_full_graph()["nodes"] if n["type"] == "conversation"]) == 0

    def test_delete_conversation_node_nonexistent(self):
        _, kg = make_fresh()
        kg.delete_conversation_node("nonexistent")
        assert len(kg.get_full_graph()["nodes"]) == 0


class TestUpdateReturnIds:
    """update_todo and update_event should include (id: ...) in result."""

    def test_update_todo_result_contains_id(self):
        store, kg = make_fresh()
        todo = store.create_todo(title="Buy milk")
        with mock.patch("backend.functions.todo_functions.get_store", return_value=store):
            from backend.functions.todo_functions import update_todo
            result = update_todo(todo["id"], completed=True)

        assert "Updated todo:" in result
        m = re.search(r'\(id: ([a-f0-9]+)\)', result)
        assert m is not None, f"Result should contain '(id: <hex>)': {result}"
        assert m.group(1) == todo["id"]

    def test_update_event_result_contains_id(self):
        store, kg = make_fresh()
        event = store.create_event(
            title="Standup",
            start_time="2026-06-18T09:00:00",
            end_time="2026-06-18T09:15:00",
        )
        with mock.patch("backend.functions.calendar_functions.get_store", return_value=store):
            from backend.functions.calendar_functions import update_event
            result = update_event(event["id"], description="Daily sync")

        assert "Updated event:" in result
        m = re.search(r'\(id: ([a-f0-9]+)\)', result)
        assert m is not None, f"Result should contain '(id: <hex>)': {result}"
        assert m.group(1) == event["id"]


class TestForgetEntityFallback:
    """forget(entity) without relation/value should delete the entire entity."""

    def test_forget_entity_only_sets_status_scraped(self):
        _, kg = make_fresh()
        kg.add_node("project", "AGI Personal Assistant", {"status": "active"})
        kg.add_node("project", "Personal Development", {"status": "started"})
        assert len(kg.get_full_graph()["nodes"]) == 2

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import forget
            result = forget("AGI Personal Assistant")

        assert "Scraped entity" in result
        assert "AGI Personal Assistant" in result
        # Node still exists but status changed
        assert len(kg.get_full_graph()["nodes"]) == 2
        for n in kg.get_full_graph()["nodes"]:
            if n["label"] == "AGI Personal Assistant":
                assert n["properties"]["status"] == "scraped"

    def test_forget_entity_keeps_connected_edges(self):
        _, kg = make_fresh()
        a = kg.add_node("project", "MyProject", {})
        b = kg.add_node("concept", "some idea", {})
        kg.add_edge(a, b, "relates_to")
        assert len(kg.get_full_graph()["edges"]) == 1

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import forget
            forget("MyProject")

        # Node A still exists, edges are preserved
        assert len(kg.get_full_graph()["nodes"]) == 2
        assert len(kg.get_full_graph()["edges"]) == 1

    def test_forget_with_relation_value_still_works(self):
        _, kg = make_fresh()
        a = kg.add_node("project", "P", {})
        b = kg.add_node("concept", "target", {})
        kg.add_edge(a, b, "relates_to")
        kg.add_edge(a, b, "knows")

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import forget
            result = forget("P", "relates_to", "target")

        assert "Forgot" in result
        assert len(kg.get_full_graph()["edges"]) == 1
        assert kg.get_full_graph()["edges"][0]["relation"] == "knows"

    def test_forget_entity_not_found_returns_message(self):
        _, kg = make_fresh()

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import forget
            result = forget("Nonexistent")

        assert "No entity found" in result


class TestStatusSystem:
    """delete_entity sets status to 'scraped'; remember() warns and suggests set_status()."""

    def test_delete_entity_sets_status_scraped(self):
        _, kg = make_fresh()
        nid = kg.add_node("project", "MyProject", {})
        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import delete_entity
            delete_entity("MyProject")

        node = kg.get_node(nid)
        assert node is not None
        assert node["properties"]["status"] == "scraped"

    def test_remember_warns_on_scraped_node(self):
        _, kg = make_fresh()
        kg.add_node("project", "ScrappedProject", {"status": "scraped"})

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import remember
            result = remember("ScrappedProject", "status", "active", node_type="project")

        assert "already exists with status 'scraped'" in result
        assert "set_status()" in result

    def test_remember_normal_still_works(self):
        _, kg = make_fresh()
        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import remember
            result = remember("FreshEntity", "likes", "Cats", node_type="concept")

        assert "Remembered" in result
        assert len(kg.get_full_graph()["nodes"]) == 2

    def test_set_status_reactivates(self):
        _, kg = make_fresh()
        nid = kg.add_node("project", "MyProject", {"status": "scraped"})

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import set_status
            result = set_status("MyProject", "active")

        assert "Updated 'MyProject' status" in result
        assert "scraped → active" in result
        node = kg.get_node(nid)
        assert node["properties"]["status"] == "active"

    def test_set_status_nonexistent(self):
        _, kg = make_fresh()
        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import set_status
            result = set_status("Nonexistent", "active")
        assert "No entity found" in result

    def test_repair_scrapes_junk_and_projects(self):
        _, kg = make_fresh()
        kg._nodes["a"] = {"id": "a", "type": "concept", "label": "project", "properties": {"search_result": "true"}}
        kg._nodes["b"] = {"id": "b", "type": "concept", "label": "project", "properties": {"search_result": "true"}}
        kg._nodes["c"] = {"id": "c", "type": "project", "label": "project:AGI Personal Assistant", "properties": {"status": "active"}}
        kg._nodes["d"] = {"id": "d", "type": "project", "label": "project:Personal Development", "properties": {"status": "active"}}
        kg._nodes["e"] = {"id": "e", "type": "concept", "label": "Alex", "properties": {"status": "active"}}
        kg._nodes["f"] = {"id": "f", "type": "project", "label": "project:RealProject", "properties": {"status": "active"}}
        kg._edges.append({"id": "e1", "source": "c", "target": "e", "relation": "relates_to", "properties": {}})

        report = kg.repair_graph()

        assert report["junk_scraped"] == 2
        assert "project:AGI Personal Assistant" in report["projects_scraped"]
        assert "project:Personal Development" in report["projects_scraped"]
        assert report["total_scraped"] == 4
        # All nodes still exist
        assert len(kg.get_full_graph()["nodes"]) == 6
        # Scraped ones have status set
        assert kg._nodes["a"]["properties"]["status"] == "scraped"
        assert kg._nodes["c"]["properties"]["status"] == "scraped"
        # Alex and RealProject remain active
        assert kg._nodes["e"]["properties"]["status"] == "active"
        assert kg._nodes["f"]["properties"]["status"] == "active"

    def test_clean_graph_filters_junk_and_scraped(self):
        _, kg = make_fresh()
        kg._nodes["j1"] = {"id": "j1", "type": "concept", "label": "project", "properties": {"search_result": "true"}}
        kg._nodes["s1"] = {"id": "s1", "type": "project", "label": "project:Scrapped", "properties": {"status": "scraped"}}
        kg._nodes["g1"] = {"id": "g1", "type": "project", "label": "project:Real", "properties": {"status": "active"}}
        kg._edges.append({"id": "e1", "source": "s1", "target": "g1", "relation": "x", "properties": {}})

        clean = kg.get_clean_graph()
        assert len(clean["nodes"]) == 1
        assert clean["nodes"][0]["label"] == "project:Real"
        assert len(clean["edges"]) == 0

    def test_clean_graph_includes_scraped_when_requested(self):
        _, kg = make_fresh()
        kg._nodes["s1"] = {"id": "s1", "type": "project", "label": "project:Scrapped", "properties": {"status": "scraped"}}
        kg._nodes["g1"] = {"id": "g1", "type": "project", "label": "project:Real", "properties": {"status": "active"}}
        kg._nodes["j1"] = {"id": "j1", "type": "concept", "label": "junk", "properties": {"search_result": "true"}}

        clean = kg.get_clean_graph(include_scraped=True)
        assert len(clean["nodes"]) == 2
        labels = {n["label"] for n in clean["nodes"]}
        assert labels == {"project:Scrapped", "project:Real"}

    def test_add_node_has_default_status(self):
        _, kg = make_fresh()
        nid = kg.add_node("concept", "Hello World", {})
        node = kg.get_node(nid)
        assert node["properties"]["status"] == "active"

    def test_add_node_custom_status(self):
        _, kg = make_fresh()
        nid = kg.add_node("concept", "Hello World", {"status": "inactive"})
        node = kg.get_node(nid)
        assert node["properties"]["status"] == "inactive"

    def test_repair_on_clean_graph_is_noop(self):
        _, kg = make_fresh()
        kg.add_node("project", "project:Real", {})
        report = kg.repair_graph()
        assert report["junk_scraped"] == 0
        assert report["projects_scraped"] == []
        assert report["total_scraped"] == 0

    def test_remember_scraped_at_new_session(self):
        """Simulate: project scrapped, then new session tries to recreate via remember()."""
        _, kg = make_fresh()
        kg.add_node("project", "project:AGI Personal Assistant", {"status": "scraped"})

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import remember
            result = remember("project:AGI Personal Assistant", "status", "started", node_type="project")

        assert "already exists with status 'scraped'" in result
        # Node is still there
        assert any("AGI Personal Assistant" in n["label"] for n in kg.get_full_graph()["nodes"])

    def test_forget_then_set_status_reactivates(self):
        """Full end-to-end: LLM scraps a project, then reactivates it."""
        _, kg = make_fresh()
        nid = kg.add_node("project", "project:AGI Personal Assistant", {"status": "active"})

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import delete_entity
            result = delete_entity("AGI Personal Assistant")

        assert "Scraped entity" in result

        node = kg.get_node(nid)
        assert node is not None
        assert node["properties"]["status"] == "scraped"

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import set_status
            result = set_status("project:AGI Personal Assistant", "active")

        assert "scraped → active" in result
        node = kg.get_node(nid)
        assert node["properties"]["status"] == "active"

    def test_delete_entity_finds_prefixed_node(self):
        """delete_entity('MyProject') should find node stored as 'project:MyProject'."""
        _, kg = make_fresh()
        nid = kg.add_node("project", "project:MyProject", {})

        with mock.patch("backend.memory.memory_tools.get_graph", return_value=kg):
            from backend.memory.memory_tools import delete_entity
            result = delete_entity("MyProject")

        assert "Scraped entity" in result
        node = kg.get_node(nid)
        assert node is not None
        assert node["properties"]["status"] == "scraped"
