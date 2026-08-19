import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")

from backend.core import awareness_observer as ao
from backend.core import user_awareness as ua


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
        # "and" / filler must not be swallowed into a name
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
        self.assertFalse(rel[0].get("is_name"), "relations must not be marked is_name (would overwrite user name)")
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
        # "my friend is coming" must NOT capture "is" as a relation name
        cands = ao.extract_candidates("my friend is coming over later")
        rel = [c for c in cands if c["slot"] == "relations"]
        self.assertFalse(rel, "common following word must not be captured as a relation name")

    def test_friend_list_captured(self):
        # A list of friends must yield one belief per person (the bug: nothing captured).
        cands = ao.extract_candidates("My friends are John, Mary, Alex")
        rels = [c for c in cands if c["slot"] == "relations"]
        vals = sorted(r["value"] for r in rels)
        self.assertEqual(vals, ["Alex", "John", "Mary"])
        self.assertTrue(all(r["relation_type"] == "friend" for r in rels))
        self.assertTrue(all(not r.get("is_name") for r in rels),
                         "list friends must not be marked is_name (would overwrite user name)")

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
        # "My friends are coming over" has no proper-noun names -> nothing captured.
        cands = ao.extract_candidates("My friends are coming over later")
        rels = [c for c in cands if c["slot"] == "relations"]
        self.assertFalse(rels, "a friend list with no names must not invent a relation")

    def test_family_list_relation_type(self):
        cands = ao.extract_candidates("My cousins are Tom, Jerry")
        rels = [c for c in cands if c["slot"] == "relations"]
        self.assertEqual(sorted(r["value"] for r in rels), ["Jerry", "Tom"])
        self.assertTrue(all(r["relation_type"] == "family" for r in rels))


class TestUserNameStore(unittest.TestCase):
    def test_name_normalized_and_persisted(self):
        cfg = {"awareness": {"profile_path": self._tmp, "consented_tiers": ["T0"]}}
        with mock.patch.object(ua, "load_config", lambda: cfg):
            store = ua.AwarenessStore()
            store.set_user_name("ajay")
            self.assertEqual(store.get_user_name(), "Ajay")
            # reload from disk
            store2 = ua.AwarenessStore()
            self.assertEqual(store2.get_user_name(), "Ajay")

    def _get_tmp(self):
        import tempfile, os
        return os.path.join(tempfile.mkdtemp(), "profile.json")

    def setUp(self):
        self._tmp = self._get_tmp()


class TestPhoneSupersede(unittest.TestCase):
    def setUp(self):
        import tempfile, os
        self._tmp = os.path.join(tempfile.mkdtemp(), "profile.json")
        self._cfg = {"awareness": {"profile_path": self._tmp, "consented_tiers": ["T0"]}}
        with mock.patch.object(ua, "load_config", lambda: self._cfg):
            self.store = ua.AwarenessStore()

    def _phones(self):
        return [b for b in self.store._beliefs.values() if ua._is_phone(b["value"])]

    def test_new_number_retires_old(self):
        with mock.patch.object(ua, "load_config", lambda: self._cfg):
            self.store.add_belief("context", "917608033", provenance="explicit")
            self.store.add_belief("context", "9123456789", provenance="explicit")
            phones = self._phones()
            self.assertEqual(len(phones), 1, "should keep only the latest number")
            self.assertEqual(ua._norm_phone(phones[0]["value"]), "9123456789")

    def test_number_change_across_slots(self):
        # Observer may store under 'context'; LLM may store under 'identity'. Both must collapse.
        with mock.patch.object(ua, "load_config", lambda: self._cfg):
            self.store.add_belief("context", "917608033", provenance="explicit")
            self.store.add_belief("identity", "9123456789", provenance="explicit")
            phones = self._phones()
            self.assertEqual(len(phones), 1)
            self.assertEqual(ua._norm_phone(phones[0]["value"]), "9123456789")

    def test_same_number_not_duplicated(self):
        with mock.patch.object(ua, "load_config", lambda: self._cfg):
            self.store.add_belief("context", "917608033", provenance="explicit")
            self.store.add_belief("context", "917608033", provenance="explicit")
            self.assertEqual(len(self._phones()), 1)

    def test_observer_pipeline_supersedes(self):
        # End-to-end through the same code path the chat uses.
        with mock.patch.object(ua, "load_config", lambda: self._cfg), \
             mock.patch.object(ao, "get_awareness_store", lambda: self.store):
            ao.ingest_text("my number is 917608033")
            ao.ingest_text("my new number is 9123456789")
            phones = self._phones()
            self.assertEqual(len(phones), 1, "observer must not keep both numbers")
            self.assertEqual(ua._norm_phone(phones[0]["value"]), "9123456789")

    def test_non_phone_values_untouched(self):
        with mock.patch.object(ua, "load_config", lambda: self._cfg):
            self.store.add_belief("favorites", "pizza", provenance="explicit")
            self.store.add_belief("favorites", "biryani", provenance="explicit")
            self.assertEqual(len(self._phones()), 0)
            self.assertEqual(len([b for b in self.store._beliefs.values() if b["slot"] == "favorites"]), 2)


if __name__ == "__main__":
    unittest.main()
