"""Local usage metrics collection backed by TinyFlux.

Metrics are stored in a local CSV file — nothing is sent externally.
Collection is opt-out via the STASH_METRICS_ENABLED environment variable.
"""

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

# Module-level singleton, initialised by init_metrics()
_collector: "MetricsCollector | None" = None


class MetricsCollector:
    """Local usage metrics backed by TinyFlux."""

    def __init__(self, db_path: str, enabled: bool = True, retention_days: int = 90) -> None:
        self.enabled = enabled
        self._db = None
        if enabled:
            try:
                from tinyflux import TinyFlux

                self._db = TinyFlux(db_path)
                logger.info("Metrics collector initialised (path=%s)", db_path)
                if retention_days > 0:
                    self._prune(retention_days)
            except Exception as exc:
                logger.warning("Failed to initialise metrics DB: %s", exc)
                self._db = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert(self, point) -> None:
        """Insert a Point, silently swallowing errors to never impact callers."""
        if self._db is None:
            return
        try:
            self._db.insert(point)
        except Exception as exc:
            logger.debug("Metrics insert error: %s", exc)

    def _prune(self, retention_days: int) -> None:
        """Remove data points older than *retention_days*."""
        if self._db is None or retention_days <= 0:
            return
        try:
            from tinyflux import TimeQuery

            cutoff = datetime.now(UTC) - timedelta(days=retention_days)
            removed = self._db.remove(TimeQuery() < cutoff)
            if removed:
                logger.info("Metrics: pruned %d points older than %d days", removed, retention_days)
        except Exception as exc:
            logger.debug("Metrics pruning error: %s", exc)

    # ------------------------------------------------------------------
    # Public recording API
    # ------------------------------------------------------------------

    def record_tool_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
        error_type: str | None = None,
        transport: str = "stdio",
    ) -> None:
        """Record a single MCP tool invocation."""
        if not self.enabled or self._db is None:
            return
        try:
            from tinyflux import Point

            tags = {
                "tool": tool_name,
                "success": str(success).lower(),
                "transport": transport,
            }
            if error_type:
                tags["error_type"] = error_type
            self._insert(
                Point(
                    time=datetime.now(UTC),
                    measurement="tool_call",
                    tags=tags,
                    fields={"duration_ms": duration_ms},
                )
            )
        except Exception as exc:
            logger.debug("Metrics record_tool_call error: %s", exc)

    def record_request(
        self,
        method: str,
        endpoint: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """Record an HTTP API request (HTTP mode only)."""
        if not self.enabled or self._db is None:
            return
        try:
            from tinyflux import Point

            status_class = f"{status_code // 100}xx"
            self._insert(
                Point(
                    time=datetime.now(UTC),
                    measurement="http_request",
                    tags={
                        "method": method,
                        "endpoint": endpoint,
                        "status_class": status_class,
                    },
                    fields={"duration_ms": duration_ms, "status_code": float(status_code)},
                )
            )
        except Exception as exc:
            logger.debug("Metrics record_request error: %s", exc)

    def record_content_event(
        self,
        event: str,
        path: str,
        size_bytes: int = 0,
    ) -> None:
        """Record content lifecycle events (create, update, delete, move)."""
        if not self.enabled or self._db is None:
            return
        try:
            import os

            from tinyflux import Point

            ext = os.path.splitext(path)[1].lower() or "none"
            self._insert(
                Point(
                    time=datetime.now(UTC),
                    measurement="content_event",
                    tags={"event": event, "file_extension": ext},
                    fields={"size_bytes": float(size_bytes)},
                )
            )
        except Exception as exc:
            logger.debug("Metrics record_content_event error: %s", exc)

    def record_search_query(
        self,
        query: str,
        provider: str,
        result_count: int,
        duration_ms: float,
    ) -> None:
        """Record semantic search queries and performance."""
        if not self.enabled or self._db is None:
            return
        try:
            import hashlib

            from tinyflux import Point

            query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
            self._insert(
                Point(
                    time=datetime.now(UTC),
                    measurement="search_query",
                    tags={"provider": provider, "query_hash": query_hash},
                    fields={
                        "duration_ms": duration_ms,
                        "result_count": float(result_count),
                    },
                )
            )
        except Exception as exc:
            logger.debug("Metrics record_search_query error: %s", exc)

    def record_server_event(self, event: str, **fields) -> None:
        """Record server lifecycle events (startup, shutdown, errors)."""
        if not self.enabled or self._db is None:
            return
        try:
            from tinyflux import Point

            float_fields = {k: float(v) for k, v in fields.items() if isinstance(v, (int, float))}
            if not float_fields:
                float_fields = {"_marker": 1.0}
            self._insert(
                Point(
                    time=datetime.now(UTC),
                    measurement="server_event",
                    tags={"event": event},
                    fields=float_fields,
                )
            )
        except Exception as exc:
            logger.debug("Metrics record_server_event error: %s", exc)

    def close(self) -> None:
        """Flush and close the TinyFlux database."""
        if self._db is not None:
            try:
                self._db.close()
            except Exception as exc:
                logger.debug("Metrics close error: %s", exc)
            finally:
                self._db = None


def init_metrics(db_path: str, enabled: bool = True, retention_days: int = 90) -> MetricsCollector:
    """Initialise the module-level metrics singleton and return it."""
    global _collector
    _collector = MetricsCollector(db_path=db_path, enabled=enabled, retention_days=retention_days)
    return _collector


def get_metrics() -> MetricsCollector:
    """Return the module-level metrics collector.

    Returns a disabled no-op collector if init_metrics() has not been called.
    """
    if _collector is None:
        return MetricsCollector(db_path="", enabled=False)
    return _collector
