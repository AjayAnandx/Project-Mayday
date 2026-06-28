"""Tests for OperationLog: record, query, stats, indexing, and lazy loading."""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from backend.core.operation_log import OperationLog, get_operation_log, _tokenize


def make_fresh_log() -> OperationLog:
    """Return an OperationLog backed by a temp directory (fresh state)."""
    log = OperationLog.__new__(OperationLog)
    log._dir = Path(tempfile.mkdtemp())
    log._lock = threading.RLock()
    log._by_id = {}
    log._by_action = {}
    log._by_type = {}
    log._by_date = {}
    log._text_idx = {}
    log._loaded_months = set()
    return log


class TestRecord:
    def test_record_creates_entry(self):
        log = make_fresh_log()
        op = log.record("create", "todo", "abc123", "Buy milk", {"priority": 1})
        assert op["action"] == "create"
        assert op["entity_type"] == "todo"
        assert op["entity_id"] == "abc123"
        assert op["entity_name"] == "Buy milk"
        assert op["details"] == {"priority": 1}
        assert len(op["id"]) == 12

    def test_record_indexes_by_action(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task A")
        log.record("delete", "todo", "b", "Task B")
        assert len(log._by_action.get("create", set())) == 1
        assert len(log._by_action.get("delete", set())) == 1

    def test_record_indexes_by_type(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task")
        log.record("create", "event", "b", "Meeting")
        assert len(log._by_type.get("todo", set())) == 1
        assert len(log._by_type.get("event", set())) == 1

    def test_record_indexes_full_text(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Buy groceries", user_message="need milk")
        assert "groceries" in log._text_idx
        assert "need" in log._text_idx
        assert "milk" in log._text_idx

    def test_record_writes_to_month_file(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Test")
        month = list(log._loaded_months)[0]
        month_path = log._month_path(month)
        assert month_path.exists()
        lines = [l for l in month_path.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["entity_name"] == "Test"


class TestQuery:
    def test_query_empty(self):
        log = make_fresh_log()
        assert log.query() == []

    def test_query_all(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task A")
        log.record("create", "todo", "b", "Task B")
        assert len(log.query()) == 2

    def test_query_filter_action(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task A")
        log.record("delete", "todo", "b", "Task B")
        results = log.query(action="delete")
        assert len(results) == 1
        assert results[0]["entity_name"] == "Task B"

    def test_query_filter_type(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task")
        log.record("create", "event", "b", "Meeting")
        results = log.query(entity_type="event")
        assert len(results) == 1
        assert results[0]["entity_name"] == "Meeting"

    def test_query_filter_action_and_type(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task A")
        log.record("delete", "todo", "b", "Task B")
        log.record("create", "event", "c", "Meeting")
        results = log.query(action="create", entity_type="todo")
        assert len(results) == 1
        assert results[0]["entity_name"] == "Task A"

    def test_query_full_text(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Buy groceries", user_message="need milk")
        log.record("create", "todo", "b", "Write report", user_message="for work")
        results = log.query(query="groceries")
        assert len(results) == 1
        assert results[0]["entity_name"] == "Buy groceries"
        results = log.query(query="milk")
        assert len(results) == 1

    def test_query_limit(self):
        log = make_fresh_log()
        for i in range(10):
            log.record("create", "todo", str(i), f"Task {i}")
        assert len(log.query(limit=3)) == 3
        assert len(log.query(limit=100)) == 10

    def test_query_date_range(self):
        log = make_fresh_log()
        # Override timestamp by directly injecting ops
        from datetime import datetime, timezone
        op1 = log.record("create", "todo", "a", "Old task")
        op2 = log.record("create", "todo", "b", "New task")
        assert len(log.query(date_from="2000-01-01")) == 2

    def test_query_returns_newest_first(self):
        log = make_fresh_log()
        op_a = log.record("create", "todo", "a", "A")
        op_b = log.record("create", "todo", "b", "B")
        results = log.query()
        assert results[0]["entity_name"] == "B"
        assert results[1]["entity_name"] == "A"


class TestStats:
    def test_stats_empty(self):
        log = make_fresh_log()
        assert "0" in log.get_stats()

    def test_stats_counts(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task A")
        log.record("delete", "todo", "b", "Task B")
        stats = log.get_stats()
        assert "2 operations" in stats

    def test_stats_filtered(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task")
        log.record("delete", "todo", "b", "Task B")
        stats = log.get_stats(action="delete")
        assert "1 operations" in stats
        assert "(delete)" in stats


class TestFullTextIndex:
    def test_tokenize_empty(self):
        assert _tokenize("") == set()

    def test_tokenize_basic(self):
        assert _tokenize("Buy groceries") == {"buy", "groceries"}

    def test_tokenize_case(self):
        assert _tokenize("Buy MILK") == {"buy", "milk"}

    def test_tokenize_punctuation(self):
        assert _tokenize("What's up? (yes)") == {"what", "s", "up", "yes"}


class TestIndexPersistence:
    def test_saves_and_loads_index(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task A")
        log.record("create", "event", "b", "Meeting")

        # Create a new log instance backed by same directory
        log2 = OperationLog.__new__(OperationLog)
        log2._dir = log._dir
        log2._lock = threading.RLock()
        log2._by_id = {}
        log2._by_action = {}
        log2._by_type = {}
        log2._by_date = {}
        log2._text_idx = {}
        log2._loaded_months = set()
        log2._load_index()

        assert len(log2._by_id) == 2
        assert len(log2.query()) == 2
        assert log2.query(entity_type="todo")[0]["entity_name"] == "Task A"

    def test_index_file_tracks_months(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task")
        index_path = log._index_path()
        assert index_path.exists()
        data = json.loads(index_path.read_text(encoding="utf-8"))
        assert data["total"] == 1
        assert len(data["months"]) == 1


class TestEdgeCases:
    def test_record_without_details(self):
        log = make_fresh_log()
        op = log.record("create", "todo", "a", "Task")
        assert op["details"] == {}

    def test_query_nonexistent_action(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task")
        assert log.query(action="nonexistent") == []

    def test_query_nonexistent_type(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task")
        assert log.query(entity_type="nonexistent") == []

    def test_query_nonexistent_text(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task")
        assert log.query(query="nonexistent") == []

    def test_get_stats_nonexistent_filter(self):
        log = make_fresh_log()
        log.record("create", "todo", "a", "Task")
        stats = log.get_stats(action="nonexistent")
        assert "0 operations" in stats


class TestConcurrency:
    def test_concurrent_record(self):
        log = make_fresh_log()
        errors = []

        def worker(i):
            try:
                log.record("create", "todo", str(i), f"Task {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(log._by_id) == 20


class TestSingleton:
    def test_get_operation_log_returns_same_instance(self):
        log1 = get_operation_log()
        log2 = get_operation_log()
        assert log1 is log2
