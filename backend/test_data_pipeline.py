"""Tests for the universal data analysis pipeline.

Covers:
- Year-column detection in _detect_column_types (2020-2024 => date_cols)
- _fmt_value display normalization (2020.0 -> "2020")
- dispatch_call argument repair for web_search_and_fetch / extract_data_from_sources / batch_add_data_points
- research_store.list_outputs and project_store.list_outputs chart history scanning
- DATA_ANALYSIS_PROTOCOL wiring in chat.py + query_classifier

All network/store dependencies mocked — zero repo pollution.
"""
import asyncio
import json
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from backend.assistant.function_registry import dispatch_call, _repair_arguments, _expected_params

_temp_dirs: list[Path] = []


def _fresh_dir() -> Path:
    d = Path(tempfile.mkdtemp())
    _temp_dirs.append(d)
    return d


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    while _temp_dirs:
        d = _temp_dirs.pop()
        if d.exists():
            import shutil
            shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def _search_mock():
    with mock.patch("backend.functions.web_research._search_and_fetch") as m:
        m.return_value = [
            {"url": "https://example.com/1", "title": "Stats 2024", "content": "2024: 100 postings"},
            {"url": "https://example.com/2", "title": "Stats 2025", "content": "2025: 140 postings"},
        ]
        yield m


@pytest.fixture
def _extract_mock():
    with mock.patch("backend.functions.web_research._extract") as m:
        m.return_value = [
            {"year": 2024, "role": "engineer", "postings": 100},
            {"year": 2025, "role": "engineer", "postings": 140},
        ]
        yield m


@pytest.fixture
def _batch_mock():
    with mock.patch("backend.functions.web_research._batch_add") as m:
        m.return_value = {
            "store_type": "research",
            "topic": "Engineering Growth",
            "stored_count": 2,
            "suggested_chart": "line",
        }
        yield m


class TestDetectColumnTypes:
    def test_year_column_detected_as_date(self):
        from backend.functions.data_import import _detect_column_types
        df = pd.DataFrame({"year": [2020, 2021, 2022], "postings": [10, 20, 30]})
        detected = _detect_column_types(df)
        assert detected["date_cols"] == ["year"]
        assert detected["numeric_cols"] == ["postings"]

    def test_small_int_column_stays_numeric(self):
        from backend.functions.data_import import _detect_column_types
        df = pd.DataFrame({"count": [1, 2, 3], "name": ["a", "b", "c"]})
        detected = _detect_column_types(df)
        assert detected["numeric_cols"] == ["count"]
        assert detected["date_cols"] == []
        assert detected["categorical_cols"] == ["name"]

    def test_out_of_range_year_not_date(self):
        from backend.functions.data_import import _detect_column_types
        df = pd.DataFrame({"epoch": [1880, 1890], "v": [1, 2]})
        detected = _detect_column_types(df)
        assert "epoch" in detected["numeric_cols"]
        assert "epoch" not in detected["date_cols"]

    def test_string_date_column_detected_without_warning(self):
        from backend.functions.data_import import _detect_column_types
        df = pd.DataFrame({
            "date": ["2020-01-15", "2021-06-30", "2022-12-01"],
            "region": ["north", "south", "east"],
        })
        detected = _detect_column_types(df)
        assert detected["date_cols"] == ["date"]
        assert detected["categorical_cols"] == ["region"]

    def test_comma_thousands_detected_as_numeric(self):
        from backend.functions.data_import import _detect_column_types
        df = pd.DataFrame({"year": [2015, 2016], "postings": ["1,234", "1,567"]})
        detected = _detect_column_types(df)
        assert detected["numeric_cols"] == ["postings"]

    def test_currency_and_percent_suffixes_detected_as_numeric(self):
        from backend.functions.data_import import _detect_column_types
        df = pd.DataFrame({
            "revenue": ["$1.2M", "$1.5M", "$2.1M"],
            "growth": ["12%", "18%", "24%"],
        })
        detected = _detect_column_types(df)
        assert set(detected["numeric_cols"]) == {"revenue", "growth"}

    def test_mixed_text_stays_categorical(self):
        from backend.functions.data_import import _detect_column_types
        df = pd.DataFrame({"region": ["north", "12", "south"]})
        detected = _detect_column_types(df)
        assert detected["numeric_cols"] == []
        assert detected["categorical_cols"] == ["region"]

    def test_convert_df_coerces_formatted_numbers(self):
        from backend.functions.data_import import _convert_df_to_data_points
        df = pd.DataFrame({
            "year": [2015, 2016],
            "postings": ["1,234", "1,567"],
            "growth": ["12%", "18%"],
            "role": ["ML", "FS"],
        })
        detected = {"date_cols": ["year"], "numeric_cols": ["postings", "growth"], "categorical_cols": ["role"]}
        points = _convert_df_to_data_points(df, detected)
        values = [p["value"] for p in points]
        assert "1234" in values
        assert "1567" in values
        assert "12" in values
        assert "18" in values

    def test_convert_df_labels_use_int_years(self):
        from backend.functions.data_import import _convert_df_to_data_points
        df = pd.DataFrame({"year": [2020.0, 2021.0], "postings": [100.0, 140.0]})
        detected = {"date_cols": ["year"], "numeric_cols": ["postings"], "categorical_cols": []}
        points = _convert_df_to_data_points(df, detected)
        assert points[0]["label"] == "2020"
        assert points[0]["value"] == "100"
        assert len(points) == 2


class TestFmtValue:
    def test_float_int(self):
        from backend.functions.data_import import _fmt_value
        assert _fmt_value(2020.0) == "2020"
        assert _fmt_value(2020) == "2020"
        assert _fmt_value(3.14) == "3.14"
        assert _fmt_value("abc") == "abc"


class TestPipelineDispatchRepair:
    def test_web_search_q_alias(self, _search_mock):
        result = run(dispatch_call("web_search_and_fetch", {"q": "engineering growth 2025"}))
        assert "Found 2 sources" in result
        assert _search_mock.call_args[0][0] == "engineering growth 2025"

    def test_web_search_missing_query_actionable(self):
        result = run(dispatch_call("web_search_and_fetch", {}))
        assert "Missing required parameter" in result or "Expected parameters" in result

    def test_extract_sources_alias(self, _extract_mock):
        sources = [{"url": "u", "title": "t", "content": "c"}]
        result = run(dispatch_call("extract_data_from_sources", {"sources": sources}))
        assert "Extracted **2** rows" in result

    def test_extract_missing_sources_actionable(self):
        result = run(dispatch_call("extract_data_from_sources", {}))
        assert "Expected parameters" in result
        assert "sources" in result
        assert "Call this tool again" in result

    def test_extract_accepts_markdown_sources_json_block(self, _extract_mock):
        # The real-world trigger: LLM passes the web_search_and_fetch output
        # (markdown + embedded SOURCES_JSON block) straight into extract.
        md = (
            "Found 2 sources...\n---\nSOURCES_JSON:\n```json\n"
            '[{"url":"https://x.com/1","title":"T1","content":"2024: 100"}]\n```'
        )
        result = run(dispatch_call("extract_data_from_sources", {"sources": md}))
        assert "Extracted **2** rows" in result
        assert _extract_mock.called

    def test_extract_list_of_strings_does_not_crash(self):
        result = run(dispatch_call("extract_data_from_sources",
                                   {"sources": ["https://a", "https://b"]}))
        assert "str" not in result
        assert "Error" in result or "no rows" in result.lower()

    def test_batch_add_aliases(self, _batch_mock):
        rows = [{"year": 2024, "postings": 100}, {"year": 2025, "postings": 140}]
        result = run(dispatch_call("batch_add_data_points", {
            "topic_name": "Engineering Growth", "rows": rows, "store": "research",
        }))
        assert "Engineering Growth" in result
        assert "line" in result
        args, _ = _batch_mock.call_args
        assert args[0] == "Engineering Growth"
        assert args[1] == rows
        assert args[2] == "research"

    def test_batch_add_missing_topic_actionable(self):
        result = run(dispatch_call("batch_add_data_points", {"data_points": [{"a": 1}]}))
        assert "Expected parameters" in result
        assert "Call this tool again" in result


class TestListOutputs:
    def test_research_outputs_scans_chart_dirs(self):
        from backend.core.research_store import ResearchStore
        root = _fresh_dir()
        store = object.__new__(ResearchStore)
        store._lock = threading.Lock()
        store._outputs_dir = root
        store._find_by_topic = lambda topic: {"slug": "growth", "topic": topic}

        newer = root / "growth" / "outputs" / "chart_20260811_120000"
        older = root / "growth" / "outputs" / "chart_20260810_090000"
        newer.mkdir(parents=True)
        older.mkdir(parents=True)
        (newer / "chart.json").write_text(
            json.dumps({"type": "line", "data": {"labels": ["2024", "2025"]}}), encoding="utf-8")
        (older / "chart.json").write_text(json.dumps({"type": "bar", "data": {}}), encoding="utf-8")

        results = store.list_outputs("Growth")
        assert [r["dir"] for r in results] == ["chart_20260811_120000", "chart_20260810_090000"]
        assert results[0]["chart_type"] == "line"
        assert results[0]["data_points"] == 2
        assert results[0]["relative_url"].startswith("/research/growth/outputs/")
        assert results[1]["chart_type"] == "bar"

    def test_research_outputs_missing_topic(self):
        from backend.core.research_store import ResearchStore
        store = object.__new__(ResearchStore)
        store._lock = threading.Lock()
        store._find_by_topic = lambda topic: None
        result = store.list_outputs("Nope")
        assert "error" in result

    def test_project_outputs_scans_chart_dirs(self):
        from backend.core.project_store import ProjectStore
        root = _fresh_dir()
        store = object.__new__(ProjectStore)
        store._lock = threading.Lock()
        store._projects_dir = root
        store.get_project = lambda pid: {"id": pid, "folder": "growth", "name": "Growth"}

        chart_dir = root / "growth" / "outputs" / "chart_20260811_120000"
        chart_dir.mkdir(parents=True)
        (chart_dir / "chart.json").write_text(
            json.dumps({"type": "pie", "data": {"labels": ["a", "b", "c"]}}), encoding="utf-8")

        results = store.list_outputs("proj_1")
        assert len(results) == 1
        assert results[0]["chart_type"] == "pie"
        assert results[0]["data_points"] == 3
        assert results[0]["relative_url"].startswith("/projects/growth/outputs/")

    def test_project_outputs_missing_project(self):
        from backend.core.project_store import ProjectStore
        store = object.__new__(ProjectStore)
        store._lock = threading.Lock()
        store.get_project = lambda pid: None
        result = store.list_outputs("nope")
        assert "error" in result


class TestChatPromptWiring:
    def test_data_analysis_protocol_defined(self):
        import backend.api.chat as chat
        assert "DATA_ANALYSIS_PROTOCOL" in dir(chat)
        text = chat.DATA_ANALYSIS_PROTOCOL
        assert "web_search_and_fetch" in text
        assert "extract_data_from_sources" in text
        assert "batch_add_data_points" in text
        assert "generate_chart" in text

    def test_sections_include_data(self):
        import backend.api.chat as chat
        assert chat.DATA_ANALYSIS_PROTOCOL is not None

    def test_classifier_research_intent_includes_data_section(self):
        from backend.core.query_classifier import QueryClassifier
        clf = QueryClassifier()
        intent = clf.classify("show me usage growth over time", "general")
        assert "DATA" in intent.active_sections


class TestExtractSchemaNormalization:
    """Regression: schema columns as objects [{'name': ...}] crashed with
    'unhashable type: dict' inside types.get() (Aug 14)."""

    def test_extract_schema_object_columns_no_crash(self, _extract_mock):
        result = run(dispatch_call("extract_data_from_sources", {
            "sources": [{"url": "u", "title": "t", "content": "2024: 100"}],
            "schema": {"columns": [{"name": "year"}, {"name": "postings"}]},
        }))
        assert "Extracted **2** rows" in result
        assert "unhashable" not in result
        assert "Error" not in result

    def test_extract_schema_mixed_columns(self, _extract_mock):
        result = run(dispatch_call("extract_data_from_sources", {
            "sources": [{"url": "u", "title": "t", "content": "data"}],
            "schema": {"columns": ["year", {"column": "postings"}]},
        }))
        assert "Extracted **2** rows" in result
        assert "unhashable" not in result

    def test_extract_schema_dict_type_values(self, _extract_mock):
        result = run(dispatch_call("extract_data_from_sources", {
            "sources": [{"url": "u", "title": "t", "content": "data"}],
            "schema": {"columns": ["year"], "types": {"year": {"type": "int"}}},
        }))
        assert "Extracted **2** rows" in result
        assert "unhashable" not in result

    def test_column_type_hint_coerces_scalars(self):
        from backend.core.extraction_pipeline import _column_type_hint, _normalize_columns
        assert _column_type_hint({"year": {"type": "int"}}, "year") == "int"
        assert _column_type_hint({"year": "float"}, "year") == "float"
        assert _column_type_hint({"year": 42}, "year") == "string"
        assert _column_type_hint({}, "year") == "string"
        assert _normalize_columns([{"name": "a"}, {"column": "b"}, "c", 7]) == ["a", "b", "c", "7"]


class TestChartNumericRobustness:
    """Regression: float/int values stored by the LLM crashed _extract_numeric
    with 'float' object has no attribute 'replace' (Aug 14)."""

    def test_extract_numeric_accepts_numbers_and_garbage(self):
        from backend.core.report_generator import _extract_numeric
        assert _extract_numeric(12500.0) == 12500.0
        assert _extract_numeric(12500) == 12500.0
        assert _extract_numeric("12.5K") == 12500.0
        assert _extract_numeric(True) is None
        assert _extract_numeric(None) is None
        assert _extract_numeric({"x": 1}) is None

    def test_chart_data_with_float_values(self):
        from backend.core.report_generator import _data_points_to_chart_data
        dps = [
            {"label": "ML Engineer | 2020", "value": 100.0, "unit": "M"},
            {"label": "ML Engineer | 2021", "value": 140.0, "unit": "M"},
            {"label": 2022, "value": "160", "unit": {"x": 1}},
        ]
        cd = _data_points_to_chart_data(dps)
        assert cd == {"labels": ["ML Engineer | 2020", "ML Engineer | 2021", "2022"], "values": [100.0, 140.0, 160.0]}

    def test_suggest_chart_type_with_weird_labels_and_units(self):
        from backend.core.report_generator import suggest_chart_type
        dps = [
            {"label": "ML | 2020", "value": 100.0, "unit": "M"},
            {"label": "ML | 2021", "value": 140.0, "unit": {"x": 1}},
        ]
        assert suggest_chart_type(dps) in ("line", "bar")

    def test_generate_chart_end_to_end_float_values(self):
        from backend.core.research_store import ResearchStore
        from backend.core.report_generator import generate_chart
        root = _fresh_dir()
        store = object.__new__(ResearchStore)
        store._lock = threading.Lock()
        store._outputs_dir = root
        store._path = root / "research.json"
        store._projects = []
        project = {
            "topic": "Growth", "slug": "growth", "data_points": [
                {"label": "2024", "value": 100.0, "unit": "M", "sources": []},
                {"label": "2025", "value": 140.0, "unit": "M", "sources": []},
            ],
            "generated_outputs": [],
        }
        store._get_by_topic = lambda topic: project
        store._find_by_topic = lambda topic: project
        with mock.patch("backend.core.report_generator.get_research_store", return_value=store):
            result = generate_chart("Growth", "auto")
        assert "error" not in result
        assert result["chart_type"] == "line"
        assert result["data_points"] == 2


class TestBatchAddValueNormalization:
    """Data collected through batch_add_data_points must be stored as clean
    strings so reports, exports and charts never see floats/dicts."""

    def test_batch_add_normalizes_already_labeled_rows(self):
        from backend.core.extraction_pipeline import batch_add_data_points as core_batch
        calls = []

        class FakeStore:
            def _get_by_topic(self, topic):
                return {"topic": topic, "data_points": []}

            def add_data_point(self, topic, label, value, unit, confidence, sources):
                calls.append((label, value, unit, confidence, sources))
                return {"label": label, "value": value, "unit": unit,
                        "confidence": confidence, "sources": sources}

        with mock.patch("backend.core.research_store.get_research_store", return_value=FakeStore()):
            result = core_batch("Growth", [
                {"label": "revenue", "value": 12500.0, "unit": "USD",
                 "confidence": "high", "sources": ["s1"]},
            ], "research")
        assert result["stored_count"] == 1
        label, value, unit, confidence, sources = calls[0]
        assert label == "revenue"
        assert value == "12500"          # float -> clean string
        assert unit == "USD"
        assert confidence == "high"
        assert sources == ["s1"]

    def test_rows_to_data_points_clean_float_year(self):
        from backend.core.extraction_pipeline import _rows_to_data_points
        rows = _rows_to_data_points([{"year": 2024.0, "postings": 100}])
        assert rows[0]["label"] == "row 1 | 2024"
        assert rows[0]["value"] == "100"