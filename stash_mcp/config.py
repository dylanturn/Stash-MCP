"""Configuration for Stash-MCP server."""

import importlib.util
import os
from pathlib import Path


def _parse_content_paths(raw: str | None) -> list[str] | None:
    """Parse STASH_CONTENT_PATHS env var into a list of glob patterns.

    Returns None if raw is None, empty, or yields no patterns.
    Normalizes trailing '/' to '/**'.
    """
    if not raw:
        return None
    patterns = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        if p.endswith("/"):
            p += "**"
        patterns.append(p)
    return patterns if patterns else None


class Config:
    """Server configuration."""

    # Content directory - where files are stored
    # STASH_CONTENT_ROOT is the canonical env var; STASH_CONTENT_DIR is kept for backward compat
    CONTENT_DIR: Path = Path(
        os.getenv("STASH_CONTENT_ROOT", os.getenv("STASH_CONTENT_DIR", "/data/content"))
    )

    # Server settings
    HOST: str = os.getenv("STASH_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("STASH_PORT", "8000"))
    LOG_LEVEL: str = os.getenv("STASH_LOG_LEVEL", "info")

    # Content path patterns - glob-based filtering for file discovery
    CONTENT_PATHS: list[str] | None = _parse_content_paths(
        os.getenv("STASH_CONTENT_PATHS")
    )

    # MCP settings
    SERVER_NAME: str = os.getenv("STASH_SERVER_NAME", "stash-mcp")
    READ_ONLY: bool = os.getenv("STASH_READ_ONLY", "false").lower() == "true"
    SERVER_VERSION: str = "0.1.0"

    # Search settings
    SEARCH_ENABLED: bool = os.getenv("STASH_SEARCH_ENABLED", "false").lower() == "true"
    SEARCH_INDEX_DIR: Path = Path(
        os.getenv("STASH_SEARCH_INDEX_DIR", "/data/.stash-index")
    )
    # Embedder model string. "onnx:<fastembed model>" runs locally on ONNX
    # Runtime (default, no torch); "openai:", "cohere:" and
    # "sentence-transformers:" (torch, needs the search-torch extra) go
    # through Pydantic AI.
    #
    # bge-small-en-v1.5 is the default: same 384 dimensions as the older
    # all-MiniLM-L6-v2 (so the index is the same size) but a much stronger
    # retriever (MTEB retrieval 51.7 vs ~42) and a 512-token window, which
    # fits a default 1000-character chunk whole.
    SEARCH_EMBEDDER_MODEL: str = os.getenv(
        "STASH_SEARCH_EMBEDDER_MODEL", "onnx:BAAI/bge-small-en-v1.5"
    )
    # onnxruntime thread count for the onnx: backend. Unset = onnxruntime's
    # default (one thread per host core); set explicitly under container CPU
    # limits to avoid oversubscription.
    SEARCH_ONNX_THREADS: int | None = (
        int(os.getenv("STASH_SEARCH_ONNX_THREADS"))
        if os.getenv("STASH_SEARCH_ONNX_THREADS")
        else None
    )
    # Instruction prefixes for asymmetric embedding models. Unset = use the
    # model's documented prefix (e5 "query: "/"passage: ", nomic
    # "search_query: "/"search_document: ", ...); set to an empty string to
    # force none. Changing these re-indexes, since document vectors change.
    SEARCH_QUERY_PREFIX: str | None = os.getenv("STASH_SEARCH_QUERY_PREFIX")
    SEARCH_DOCUMENT_PREFIX: str | None = os.getenv("STASH_SEARCH_DOCUMENT_PREFIX")
    CONTEXTUAL_RETRIEVAL: bool = (
        os.getenv("STASH_CONTEXTUAL_RETRIEVAL", "false").lower() == "true"
    )
    CONTEXTUAL_MODEL: str = os.getenv(
        "STASH_CONTEXTUAL_MODEL", "claude-haiku-4-5-20251001"
    )
    SEARCH_CHUNK_SIZE: int = int(os.getenv("STASH_SEARCH_CHUNK_SIZE", "1000"))
    SEARCH_CHUNK_OVERLAP: int = int(os.getenv("STASH_SEARCH_CHUNK_OVERLAP", "100"))
    # Fold the "path > heading > subheading" breadcrumb into the embedded
    # text as well as showing it with results. Off by default: measured worse
    # than leaving it out on both corpora tested (-0.03 to -0.07 MRR), since
    # it dilutes the chunk's own wording. The breadcrumb is recorded and
    # displayed either way.
    SEARCH_HEADING_CONTEXT: bool = (
        os.getenv("STASH_SEARCH_HEADING_CONTEXT", "false").lower() == "true"
    )

    # Find tool settings
    FIND_MAX_RESULTS_CEILING: int = int(
        os.getenv("STASH_FIND_MAX_RESULTS_CEILING", "500")
    )

    # Search ranking — MMR diversification
    SEARCH_MMR_ENABLED: bool = (
        os.getenv("STASH_SEARCH_MMR_ENABLED", "true").lower() == "true"
    )
    SEARCH_MMR_LAMBDA: float = float(os.getenv("STASH_SEARCH_MMR_LAMBDA", "0.7"))
    SEARCH_MAX_PER_FILE: int = int(os.getenv("STASH_SEARCH_MAX_PER_FILE", "2"))
    SEARCH_CANDIDATE_POOL_MULTIPLIER: int = int(
        os.getenv("STASH_SEARCH_CANDIDATE_POOL_MULTIPLIER", "6")
    )

    # Search ranking — recency boost from git blame
    SEARCH_RECENCY_WEIGHT: float = float(
        os.getenv("STASH_SEARCH_RECENCY_WEIGHT", "0.0")
    )
    SEARCH_RECENCY_HALF_LIFE_DAYS: float = float(
        os.getenv("STASH_SEARCH_RECENCY_HALF_LIFE_DAYS", "180")
    )

    # Search retrieval — hybrid BM25 + dense via Reciprocal Rank Fusion.
    # On by default when bm25s is installed (the search, search-contextual
    # and search-hybrid extras include it; the API-provider and torch extras
    # do not): agent queries are full of literal tokens — env var names,
    # function names, paths, error strings — which lexical matching handles
    # far better than embeddings. Falls back to dense-only rather than
    # failing when the dependency is absent, so a hand-rolled install of
    # numpy + fastembed still works.
    SEARCH_HYBRID_ENABLED: bool = (
        os.getenv("STASH_SEARCH_HYBRID_ENABLED").lower() == "true"
        if os.getenv("STASH_SEARCH_HYBRID_ENABLED")
        else importlib.util.find_spec("bm25s") is not None
    )
    SEARCH_RRF_K: int = int(os.getenv("STASH_SEARCH_RRF_K", "60"))
    SEARCH_BM25_CANDIDATE_POOL: int = int(
        os.getenv("STASH_SEARCH_BM25_CANDIDATE_POOL", "30")
    )

    # Search ranking — cross-encoder reranking of the retrieved shortlist.
    # Off by default: it adds a ~120 MB model download and takes a query from
    # ~4 ms to ~470 ms (20 candidates, CPU) for a modest gain now that the
    # lexical index also covers headings and paths.
    SEARCH_RERANK_ENABLED: bool = (
        os.getenv("STASH_SEARCH_RERANK_ENABLED", "false").lower() == "true"
    )
    SEARCH_RERANK_MODEL: str = os.getenv(
        "STASH_SEARCH_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-12-v2"
    )
    # 10 measured as good as 20 (MRR 0.882 vs 0.880) at half the latency
    SEARCH_RERANK_CANDIDATES: int = int(
        os.getenv("STASH_SEARCH_RERANK_CANDIDATES", "10")
    )

    # Model cache directory for locally downloaded embedding weights. The ONNX
    # backend stores its files under <dir>/fastembed; the Docker image also
    # points HF_HOME here for the torch (sentence-transformers) path.
    MODEL_CACHE_DIR: Path = Path(
        os.getenv("STASH_MODEL_CACHE_DIR", "/data/models")
    )

    # Git clone-on-startup
    GIT_CLONE_URL: str | None = os.getenv("STASH_GIT_CLONE_URL")
    GIT_CLONE_BRANCH: str = os.getenv("STASH_GIT_CLONE_BRANCH", "main")
    GIT_CLONE_TOKEN: str | None = os.getenv(
        "STASH_GIT_CLONE_TOKEN", os.getenv("STASH_GIT_SYNC_TOKEN")
    )

    # Git tracking
    GIT_TRACKING: bool = os.getenv("STASH_GIT_TRACKING", "false").lower() == "true"

    # Git sync (requires GIT_TRACKING=true)
    GIT_SYNC_ENABLED: bool = os.getenv("STASH_GIT_SYNC_ENABLED", "false").lower() == "true"
    GIT_SYNC_URL: str | None = os.getenv("STASH_GIT_SYNC_URL")
    GIT_SYNC_REMOTE: str = os.getenv("STASH_GIT_SYNC_REMOTE", "origin")
    GIT_SYNC_BRANCH: str = os.getenv("STASH_GIT_SYNC_BRANCH", "main")
    GIT_SYNC_INTERVAL: int = int(os.getenv("STASH_GIT_SYNC_INTERVAL", "60"))
    GIT_SYNC_RECURSIVE: bool = os.getenv("STASH_GIT_SYNC_RECURSIVE", "false").lower() == "true"
    GIT_SYNC_TOKEN: str | None = os.getenv("STASH_GIT_SYNC_TOKEN")
    GIT_AUTHOR_DEFAULT: str = os.getenv("STASH_GIT_AUTHOR_DEFAULT", "stash-mcp <stash@local>")

    # Transaction settings (only relevant when GIT_TRACKING=true and READ_ONLY=false)
    TRANSACTION_TIMEOUT: int = int(os.getenv("STASH_TRANSACTION_TIMEOUT", "300"))
    TRANSACTION_LOCK_WAIT: int = int(os.getenv("STASH_TRANSACTION_LOCK_WAIT", "120"))

    # Metrics settings
    METRICS_ENABLED: bool = os.getenv("STASH_METRICS_ENABLED", "true").lower() == "true"
    METRICS_PATH: Path = Path(
        os.getenv(
            "STASH_METRICS_PATH",
            str(
                Path(
                    os.getenv("STASH_CONTENT_ROOT", os.getenv("STASH_CONTENT_DIR", "/data/content"))
                ).parent
                / "metrics.csv"
            ),
        )
    )
    METRICS_RETENTION_DAYS: int = int(os.getenv("STASH_METRICS_RETENTION_DAYS", "90"))

    @classmethod
    def get_effective_metrics_enabled(cls) -> bool:
        """Return whether metrics collection is effectively enabled.

        In read-only (stateless) mode the default flips to disabled to avoid
        file corruption when multiple pods write to the same CSV concurrently.
        Users can still explicitly opt in by setting STASH_METRICS_ENABLED=true.
        """
        if cls.READ_ONLY:
            return os.getenv("STASH_METRICS_ENABLED", "false").lower() == "true"
        return cls.METRICS_ENABLED

    @classmethod
    def ensure_content_dir(cls) -> None:
        """Ensure content directory exists."""
        cls.CONTENT_DIR.mkdir(parents=True, exist_ok=True)
