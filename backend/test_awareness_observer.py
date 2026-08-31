import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")

from backend.core import awareness_observer as ao
from backend.core import user_awareness as ua


class FakeGraph:
    """In-memory stand-in for KnowledgeGraph (no file I/O)."""

    def __init__(self):
        self._nodes = {}
        self._by_label = {}
        self._edges = {}
        self._counter = 0

    def add_node(self, type, label, properties=None):
        nid = "n%d" % self._counter
        self._counter += 1
        node = {"id": nid, "type": type, "label": label, "properties": dict(properties or {})}
        self._nodes[nid] = node
        self._by_label[label] = node
        return nid

    def get_node_by_label(self, label):
        return self._by_label.get(label)

    def get_node(self, nid):
        return self._nodes.get(nid)

    def search(self, query):
        q = (query or "").lower()
        return [n for n in self._nodes.values()
                if q in n["label"].lower()
                or any(q in str(v).lower() for v in n["properties"].values())]

    def add_edge_if_missing(self, source, target, relation, properties=None):
        key = (source, target, relation)
        if key in self._edges:
            return None
        eid = "e%d" % len(self._edges)
        self._edges[key] = {"id": eid, "source": source, "target": target, "relation": relation}
        return eid

    def get_subgraph(self, node_id, depth=2):
        return {"edges": [e for e in self._edges.values()
                          if e["source"] == node_id or e["target"] == node_id]}

    def remove_node(self, nid):
        if nid not in self._nodes:
            return False
        del self._nodes[nid]
        for lab, n in list(self._by_label.items()):
            if n["id"] == nid:
                del self._by_label[lab]
        return True

    def _index_node(self, node):
        self._by_label[node["label"]] = node

    def _save(self):
        pass


class TestNameExtraction(unittest.TestCase):
    def test_lowercase_name_captured(self):
        cands = ao.extract_candidates("my name is john")
        names = [c for c in cands if c.get("is_name")]
        self.assertTrue(names, "lowercase 'my name is john' should yield a name candidate")
        self.assertEqual(names[0]["value"], "john")
        self.assertEqual(names[0]["slot"], "identity")

    def test_capitalized_name_captured(self):
        cands = ao.extract_candidates("My name is John Doe")
        names = [c for c in cands if c.get("is_name")]
        self.assertTrue(names)
        self.assertEqual(names[0]["value"], "John Doe")

    def test_call_me_captured(self):
        cands = ao.extract_candidates("call me maya")
        names = [c for c in cands if c.get("is_name")]
        self.assertTrue(names, "call me <name> should capture the name")
        self.assertEqual(names[0]["value"], "maya")

    def test_im_captured(self):
        cands = ao.extract_candidates("i'm alex")
        names = [c for c in cands if c.get("is_name")]
        self.assertTrue(names)
        self.assertEqual(names[0]["value"], "alex")

    def test_stopword_not_captured_as_name(self):
        cands = ao.extract_candidates("my name is and the dog")
        names = [c for c in cands if c.get("is_name")]
        self.assertFalse(names)

    def test_job_capture_allows_capitals(self):
        cands = ao.extract_candidates("i work as a Developer")
        jobs = [c for c in cands if c["slot"] == "identity" and c["value"].lower() == "developer"]
        self.assertTrue(jobs, "i work as <Job> should capture capitalized job title")

    def test_grandmother_captured(self):
        cands = ao.extract_candidates("My grandmother Alamelu passed last year. She raised me.")
        rel = [c for c in cands if c["slot"] == "relations" and c["value"].lower() == "alamelu"]
        self.assertTrue(rel, "relation 'grandmother Alamelu' should be captured")
        self.assertFalse(rel[0].get("is_name"), "relations must not be marked is_name")
        self.assertEqual(rel[0]["relation_type"], "family")

    def test_best_friend_captured(self):
        cands = ao.extract_candidates("my best friend Sara helped me move")
        rel = [c for c in cands if c["slot"] == "relations" and c["value"].lower() == "sara"]
        self.assertTrue(rel, "my best friend <Name> should be captured")

    def test_reverse_relation_captured(self):
        cands = ao.extract_candidates("Alamelu is my grandmother")
        rel = [c for c in cands if c["slot"] == "relations" and c["value"].lower() == "alamelu"]
        self.assertTrue(rel, "'<Name> is my grandmother' should capture the name")

    def test_relation_name_not_swallowed(self):
        cands = ao.extract_candidates("my friend is coming over later")
        rel = [c for c in cands if c["slot"] == "relations"]
        self.assertFalse(rel, "common following word must not be captured as a relation name")

    def test_friend_list_captured(self):
        cands = ao.extract_candidates("My friends are John, Mary, Alex")
        rels = [c for c in cands if c["slot"] == "relations"]
        vals = sorted(r["value"] for r in rels)
        self.assertEqual(vals, ["Alex", "John", "Mary"])
        self.assertTrue(all(r["relation_type"] == "friend" for r in rels))
        self.assertTrue(all(not r.get("is_name") for r in rels))

    def test_friend_list_with_and(self):
        cands = ao.extract_candidates("My friends are John and Mary")
        vals = sorted(c["value"] for c in cands if c["slot"] == "relations")
        self.assertEqual(vals, ["John", "Mary"])

    def test_friend_list_colon_form(self):
        cands = ao.extract_candidates("My close friends: Ajay, Bala, Chetan")
        vals = sorted(c["value"] for c in cands if c["slot"] == "relations")
        self.assertEqual(vals, ["Ajay", "Bala", "Chetan"])

    def test_friends_with_phrase(self):
        cands = ao.extract_candidates("I'm friends with John, Mary and Bala")
        vals = sorted(c["value"] for c in cands if c["slot"] == "relations")
        self.assertEqual(vals, ["Bala", "John", "Mary"])

    def test_add_friends_phrase(self):
        cands = ao.extract_candidates("add my friends John, Mary, Alex")
        vals = sorted(c["value"] for c in cands if c["slot"] == "relations")
        self.assertEqual(vals, ["Alex", "John", "Mary"])

    def test_friend_list_no_false_positive(self):
        cands = ao.extract_candidates("My friends are coming over later")
        rels = [c for c in cands if c["slot"] == "relations"]
        self.assertFalse(rels, "a friend list with no names must not invent a relation")

    def test_family_list_relation_type(self):
        cands = ao.extract_candidates("My cousins are Tom, Jerry")
        rels = [c for c in cands if c["slot"] == "relations"]
        self.assertEqual(sorted(r["value"] for r in rels), ["Jerry", "Tom"])
        self.assertTrue(all(r["relation_type"] == "family" for r in rels))


class TestIngestToGraph(unittest.TestCase):
    def setUp(self):
        import backend.memory.knowledge_graph as kgmod
        self._orig = getattr(kgmod, "_graph", None)
        self.graph = FakeGraph()
        kgmod._graph = self.graph
        ua.get_awareness_store()._instance = None

    def tearDown(self):
        import backend.memory.knowledge_graph as kgmod
        kgmod._graph = self._orig
        ua.get_awareness_store()._instance = None

    def test_name_persisted_to_graph(self):
        ao.ingest_text("my name is john")
        store = ua.get_awareness_store()
        self.assertEqual(store.get_user_name(), "John")
        self.assertIsNotNone(self.graph.get_node_by_label("user:Mayday-user"))

    def test_relation_creates_person_node(self):
        ao.ingest_text("my friend Sara helped me move")
        person = self.graph.get_node_by_label("person:sara")
        self.assertIsNotNone(person, "a person node should be created for the relation")
        user = self.graph.get_node_by_label("user:Mayday-user")
        self.assertIsNotNone(user)
        edge = None
        for e in self.graph._edges.values():
            if e["source"] == user["id"] and e["target"] == person["id"]:
                edge = e
        self.assertIsNotNone(edge, "user should link to the person via 'knows'")
        self.assertEqual(edge["relation"], "knows")

    def test_favorite_written_to_graph(self):
        ao.ingest_text("i love pizza")
        user = self.graph.get_node_by_label("user:Mayday-user")
        self.assertIsNotNone(user)
        # a 'favorites' edge from user to a 'pizza' concept node should exist
        found = any(e["relation"] == "favorites"
                    for e in self.graph._edges.values()
                    if e["source"] == user["id"])
        self.assertTrue(found, "favorite fact should be stored in the graph")

    def test_dedup_on_repeat(self):
        added1 = ao.ingest_text("i love pizza")
        added2 = ao.ingest_text("i love pizza")
        new1 = [a for a in added1 if a.get("new")]
        new2 = [a for a in added2 if a.get("new")]
        self.assertTrue(new1)
        self.assertFalse(new2, "repeating the same fact should not be marked new")

    def test_person_brief_resolves(self):
        ao.ingest_text("my sister Maya lives abroad")
        brief = ua.get_awareness_store().person_brief("Maya")
        self.assertIn("Maya", brief)
        self.assertIn("family", brief)

    def test_explicit_persists_immediately(self):
        # Explicit statements are learned on the very first mention even with a
        # high soft-signal threshold (which only gates implicit signals).
        with mock.patch("backend.core.config.load_config",
                        return_value={"awareness": {"soft_signal_threshold": 5}}):
            added = ao.ingest_text("i love biriyani")
            new = [a for a in added if a.get("new")]
            self.assertTrue(new, "explicit fact should persist on first mention")
            self.assertTrue(any(e["relation"] == "favorites"
                                for e in self.graph._edges.values()
                                if e["source"] == self.graph.get_node_by_label("user:Mayday-user")["id"]))

    def test_soft_signal_requires_repeats(self):
        with mock.patch("backend.core.config.load_config",
                        return_value={"awareness": {"soft_signal_threshold": 2}}):
            # "lonely" is only a situational/context trigger, not an explicit problem,
            # so this is a pure soft signal.
            added1 = ao.ingest_text("when I am lonely, I listen to music")
            self.assertFalse([a for a in added1 if a.get("new")],
                             "soft signal must NOT persist on first mention")
            added2 = ao.ingest_text("when I am lonely, I listen to music")
            self.assertTrue([a for a in added2 if a.get("new")],
                            "soft signal must persist after threshold mentions")


class TestPhfPersonalFacts(unittest.TestCase):
    def setUp(self):
        import backend.memory.knowledge_graph as kgmod
        self._orig = getattr(kgmod, "_graph", None)
        self.graph = FakeGraph()
        kgmod._graph = self.graph
        ua.get_awareness_store()._instance = None

    def tearDown(self):
        import backend.memory.knowledge_graph as kgmod
        kgmod._graph = self._orig
        ua.get_awareness_store()._instance = None

    def test_personal_facts_surfaced(self):
        import backend.core.phf as phf
        ao.ingest_text("my name is john")
        ao.ingest_text("i love pizza")
        facts = phf.personal_facts()
        self.assertIn("Name: John", facts)
        self.assertIn("Favorites: pizza", facts)

    def test_disposition_combines_facts_and_habitus(self):
        import backend.core.phf as phf
        ao.ingest_text("my name is john")
        # habitus is empty without practice log; facts must still appear.
        summary = phf.disposition_summary()
        self.assertIn("About you", summary)
        self.assertIn("Name: John", summary)


if __name__ == "__main__":
    unittest.main()
