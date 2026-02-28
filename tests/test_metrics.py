"""Tests for MetricsCollector."""

import os
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory

import pytest

from stash_mcp.metrics import MetricsCollector, get_metrics, init_metrics


@pytest.fixture
def metrics_dir():
    """Provide a temporary directory for the metrics DB."""
    with TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def collector(metrics_dir):
    """A fresh enabled MetricsCollector backed by a temp CSV file."""
    db_path = os.path.join(metrics_dir, "metrics.csv")
    return MetricsCollector(db_path=db_path, enabled=True, retention_days=0)


@pytest.fixture
def disabled_collector(metrics_dir):
    """A disabled MetricsCollector (no-op)."""
    return MetricsCollector(db_path="", enabled=False)


# ---------------------------------------------------------------------------
# Disabled mode — zero overhead, no DB opened
# ---------------------------------------------------------------------------


class TestDisabledMode:
    def test_disabled_creates_no_db(self):
        c = MetricsCollector(db_path="/nonexistent/path/metrics.csv", enabled=False)
        assert c._db is None

    def test_disabled_record_tool_call_is_noop(self):
        c = MetricsCollector(db_path="", enabled=False)
        # Must not raise
        c.record_tool_call("test_tool", 10.0, True)

    def test_disabled_record_request_is_noop(self):
        c = MetricsCollector(db_path="", enabled=False)
        c.record_request("GET", "/api/content", 200, 5.0)

    def test_disabled_record_content_event_is_noop(self):
        c = MetricsCollector(db_path="", enabled=False)
        c.record_content_event("created", "docs/test.md", size_bytes=100)

    def test_disabled_record_search_query_is_noop(self):
        c = MetricsCollector(db_path="", enabled=False)
        c.record_search_query("hello", "local", 3, 20.0)

    def test_disabled_record_server_event_is_noop(self):
        c = MetricsCollector(db_path="", enabled=False)
        c.record_server_event("startup")

    def test_disabled_close_is_noop(self):
        c = MetricsCollector(db_path="", enabled=False)
        c.close()  # Must not raise


# ---------------------------------------------------------------------------
# Insert / query
# ---------------------------------------------------------------------------


class TestInsert:
    def test_record_tool_call_success(self, collector):
        collector.record_tool_call("read_content", 12.5, True, transport="http")
        results = collector._db.all()
        assert len(results) == 1
        pt = results[0]
        assert pt.measurement == "tool_call"
        assert pt.tags["tool"] == "read_content"
        assert pt.tags["success"] == "true"
        assert pt.tags["transport"] == "http"
        assert abs(pt.fields["duration_ms"] - 12.5) < 1e-6

    def test_record_tool_call_failure(self, collector):
        collector.record_tool_call("create_content", 5.0, False, error_type="ValueError")
        results = collector._db.all()
        assert len(results) == 1
        pt = results[0]
        assert pt.tags["success"] == "false"
        assert pt.tags["error_type"] == "ValueError"

    def test_record_request(self, collector):
        collector.record_request("POST", "/api/content/test.md", 201, 8.3)
        results = collector._db.all()
        assert len(results) == 1
        pt = results[0]
        assert pt.measurement == "http_request"
        assert pt.tags["method"] == "POST"
        assert pt.tags["status_class"] == "2xx"
        assert abs(pt.fields["status_code"] - 201.0) < 1e-6

    def test_record_content_event(self, collector):
        collector.record_content_event("created", "docs/hello.md", size_bytes=512)
        results = collector._db.all()
        assert len(results) == 1
        pt = results[0]
        assert pt.measurement == "content_event"
        assert pt.tags["event"] == "created"
        assert pt.tags["file_extension"] == ".md"
        assert abs(pt.fields["size_bytes"] - 512.0) < 1e-6

    def test_record_search_query(self, collector):
        collector.record_search_query("hello world", "local", 3, 42.0)
        results = collector._db.all()
        assert len(results) == 1
        pt = results[0]
        assert pt.measurement == "search_query"
        assert pt.tags["provider"] == "local"
        assert pt.fields["result_count"] == 3.0
        assert abs(pt.fields["duration_ms"] - 42.0) < 1e-6

    def test_record_server_event(self, collector):
        collector.record_server_event("startup", uptime_seconds=0)
        results = collector._db.all()
        assert len(results) == 1
        pt = results[0]
        assert pt.measurement == "server_event"
        assert pt.tags["event"] == "startup"

    def test_multiple_points_accumulate(self, collector):
        for i in range(5):
            collector.record_tool_call(f"tool_{i}", float(i), True)
        assert len(collector._db.all()) == 5


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


class TestPruning:
    def test_prune_removes_old_points(self, metrics_dir):
        from tinyflux import Point, TinyFlux

        db_path = os.path.join(metrics_dir, "prune_test.csv")
        db = TinyFlux(db_path)
        old_time = datetime.now(UTC) - timedelta(days=100)
        db.insert(
            Point(
                time=old_time,
                measurement="tool_call",
                tags={"tool": "old_tool", "success": "true"},
                fields={"duration_ms": 1.0},
            )
        )
        db.insert(
            Point(
                time=datetime.now(UTC),
                measurement="tool_call",
                tags={"tool": "new_tool", "success": "true"},
                fields={"duration_ms": 1.0},
            )
        )
        db.close()

        # Re-open with retention_days=90 → should prune the old point
        c = MetricsCollector(db_path=db_path, enabled=True, retention_days=90)
        results = c._db.all()
        assert len(results) == 1
        assert results[0].tags["tool"] == "new_tool"

    def test_retention_zero_keeps_all(self, metrics_dir):
        from tinyflux import Point, TinyFlux

        db_path = os.path.join(metrics_dir, "prune_zero.csv")
        db = TinyFlux(db_path)
        old_time = datetime.now(UTC) - timedelta(days=200)
        db.insert(
            Point(
                time=old_time,
                measurement="tool_call",
                tags={"tool": "ancient", "success": "true"},
                fields={"duration_ms": 1.0},
            )
        )
        db.close()

        # retention_days=0 → keep everything
        c = MetricsCollector(db_path=db_path, enabled=True, retention_days=0)
        assert len(c._db.all()) == 1


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_init_metrics_returns_collector(self, metrics_dir):
        db_path = os.path.join(metrics_dir, "singleton.csv")
        c = init_metrics(db_path=db_path, enabled=True, retention_days=0)
        assert isinstance(c, MetricsCollector)
        assert c.enabled is True

    def test_get_metrics_returns_singleton(self, metrics_dir):
        db_path = os.path.join(metrics_dir, "singleton2.csv")
        init_metrics(db_path=db_path, enabled=True, retention_days=0)
        c = get_metrics()
        assert isinstance(c, MetricsCollector)
        assert c.enabled is True

    def test_get_metrics_before_init_returns_disabled(self):
        import stash_mcp.metrics as metrics_module

        original = metrics_module._collector
        metrics_module._collector = None
        try:
            c = get_metrics()
            assert not c.enabled
        finally:
            metrics_module._collector = original


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_idempotent(self, collector):
        collector.close()
        collector.close()  # second close must not raise

    def test_record_after_close_is_noop(self, collector):
        collector.close()
        # Must not raise after close
        collector.record_tool_call("any_tool", 1.0, True)
