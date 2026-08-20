"""Local embedding backends for semantic search.

The default local backend runs on ONNX Runtime via `fastembed`_ (onnxruntime +
tokenizers), which keeps the ``search`` install free of PyTorch and the CUDA
libraries. Model strings use the ``onnx:`` prefix followed by a fastembed model
name, e.g. ``onnx:sentence-transformers/all-MiniLM-L6-v2`` (the default) or
``onnx:BAAI/bge-small-en-v1.5`` (int8-quantised, smaller and faster).

:class:`FastEmbedAdapter` is an async ``embed_fn`` compatible with
:class:`stash_mcp.search.SearchEngine`: it runs the synchronous
``TextEmbedding.embed()`` in a worker thread via :func:`asyncio.to_thread`.
The model is downloaded/loaded lazily on first use so server start-up (and
health checks) are not blocked by the download; the model *name* is validated
eagerly so configuration typos fail fast.

.. _fastembed: https://github.com/qdrant/fastembed
"""

import asyncio
import logging
import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

ONNX_PREFIX = "onnx:"
DEFAULT_ONNX_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDER_MODEL = f"{ONNX_PREFIX}{DEFAULT_ONNX_MODEL}"

# Token limits applied after loading, keyed by lower-cased fastembed model
# name. fastembed's packaging of all-MiniLM-L6-v2 (qdrant/all-MiniLM-L6-v2-onnx)
# ships a tokenizer_config.json with ``max_length: 128`` and fixed 128-token
# padding, so it silently truncates at 128 tokens even though the model's
# documented limit — and sentence-transformers' ``max_seq_length`` — is 256.
# Stash's default 1000-character chunks are ~200-250 tokens, so restoring 256
# is what makes ONNX vectors match the PyTorch backend (to ~1e-7) instead of
# embedding only the first half of each chunk. Models not listed here keep
# fastembed's configuration.
_KNOWN_MAX_TOKENS: dict[str, int] = {
    DEFAULT_ONNX_MODEL.lower(): 256,
}

_INSTALL_HINT = (
    "Install with: pip install 'stash-mcp[search]' "
    "(Docker: build with --build-arg SEARCH_EXTRA=search)"
)


def is_onnx_model(model: str) -> bool:
    """Return True if *model* selects the ONNX Runtime (fastembed) backend."""
    return model.strip().lower().startswith(ONNX_PREFIX)


def onnx_model_name(model: str) -> str:
    """Return the fastembed model name from an ``onnx:<name>`` model string.

    Raises:
        ValueError: If the string does not carry the ``onnx:`` prefix or the
            model name after the prefix is empty.
    """
    if not is_onnx_model(model):
        raise ValueError(
            f"Expected an '{ONNX_PREFIX}' embedder model string, got {model!r}"
        )
    name = model.strip()[len(ONNX_PREFIX):].strip()
    if not name:
        raise ValueError(
            f"Missing model name after '{ONNX_PREFIX}' in {model!r} "
            f"(e.g. {DEFAULT_EMBEDDER_MODEL!r})"
        )
    return name


def _import_text_embedding():
    """Import and return ``fastembed.TextEmbedding`` with an install hint on failure."""
    try:
        from fastembed import TextEmbedding
    except ImportError as e:
        raise RuntimeError(
            f"fastembed is required for the '{ONNX_PREFIX}' embedding backend. "
            f"{_INSTALL_HINT}"
        ) from e
    return TextEmbedding


def _resolve_cache_dir(cache_dir: Path | str | None) -> str | None:
    """Ensure *cache_dir* exists and is writable, else fall back to fastembed's default.

    Writability is settled by creating a file rather than by asking
    :func:`os.access`, which answers for the *real* uid, ignores ACLs, and
    tests the write bit alone -- while creating a file in a directory also
    needs its execute (search) bit. Getting this wrong is expensive: the
    download only starts on the first embed, long after start-up, and by then
    there is no fallback left to take.

    Returns the directory as a string, or None to let fastembed choose
    (``FASTEMBED_CACHE_PATH`` or a temp directory).
    """
    if cache_dir is None:
        return None
    path = Path(cache_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".stash-write-test"):
            pass
    except OSError as e:
        logger.warning(
            "Model cache directory %s is not usable (%s); "
            "falling back to fastembed's default cache location",
            path,
            e,
        )
        return None
    return str(path)


class FastEmbedAdapter:
    """Async ``embed_fn`` adapter around ``fastembed.TextEmbedding`` (ONNX Runtime).

    Instances are callables with the signature expected by
    :class:`stash_mcp.search.SearchEngine`::

        vectors = await adapter(["text one", "text two"])  # -> list[list[float]]

    Args:
        model_name: fastembed model name (without the ``onnx:`` prefix), e.g.
            ``sentence-transformers/all-MiniLM-L6-v2``.
        cache_dir: Directory for downloaded model files. Created if missing;
            if it cannot be used, fastembed's default cache is used instead.
        threads: onnxruntime intra/inter-op thread count (None = library default).
        max_tokens: Truncation limit applied after loading. Defaults to a
            per-model correction table (see ``_KNOWN_MAX_TOKENS``); pass an int
            to force a value, or leave None for models not in the table to keep
            fastembed's configuration.

    Raises:
        RuntimeError: If fastembed is not installed.
        ValueError: If *model_name* is not a fastembed-supported model.
    """

    def __init__(
        self,
        model_name: str,
        *,
        cache_dir: Path | str | None = None,
        threads: int | None = None,
        max_tokens: int | None = None,
    ):
        self._text_embedding_cls = _import_text_embedding()
        self.model_name = model_name
        self.cache_dir = _resolve_cache_dir(cache_dir)
        self.threads = threads
        self.max_tokens = (
            max_tokens
            if max_tokens is not None
            else _KNOWN_MAX_TOKENS.get(model_name.lower())
        )
        self._model = None
        self._load_lock = threading.Lock()
        self._validate_model_name()

    def _validate_model_name(self) -> None:
        """Fail fast (no network) if the model name is unknown to fastembed."""
        supported = [
            str(m.get("model", ""))
            for m in self._text_embedding_cls.list_supported_models()
        ]
        if self.model_name.lower() not in {m.lower() for m in supported}:
            raise ValueError(
                f"{self.model_name!r} is not a fastembed-supported embedding model. "
                f"Supported models: {', '.join(sorted(supported))}"
            )

    @property
    def loaded(self) -> bool:
        """Whether the ONNX model has been downloaded and loaded."""
        return self._model is not None

    def _get_model(self):
        """Return the loaded ``TextEmbedding``, loading it on first use (thread-safe)."""
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    self._model = self._load()
        return self._model

    def _load(self):
        kwargs: dict = {}
        if self.cache_dir is not None:
            kwargs["cache_dir"] = self.cache_dir
        if self.threads is not None:
            kwargs["threads"] = self.threads
        logger.info(
            "Loading ONNX embedding model %s (cache_dir=%s)",
            self.model_name,
            self.cache_dir or "fastembed default",
        )
        model = self._text_embedding_cls(model_name=self.model_name, **kwargs)
        if self.max_tokens is not None:
            self._apply_max_tokens(model, self.max_tokens)
        return model

    def _apply_max_tokens(self, model, max_tokens: int) -> None:
        """Re-enable truncation at *max_tokens* with dynamic (batch-longest) padding.

        Reaches into ``TextEmbedding.model.tokenizer`` (a ``tokenizers.Tokenizer``)
        and keeps every other truncation/padding parameter the model shipped
        with (stride, strategy, pad token/id, ...). If fastembed's internals
        change, log a warning and leave the tokenizer exactly as it was —
        never half-configured (truncating longer than the fixed padding length
        would produce ragged batches).
        """
        try:
            tokenizer = model.model.tokenizer
            truncation = dict(tokenizer.truncation or {})
            padding = dict(tokenizer.padding or {})
        except Exception as e:  # never let a tuning step break embedding
            logger.warning(
                "Could not set truncation to %d tokens for %s (%s); "
                "using fastembed's default tokenizer settings",
                max_tokens,
                self.model_name,
                e,
            )
            return
        try:
            tokenizer.enable_truncation(**{**truncation, "max_length": max_tokens})
            tokenizer.enable_padding(**{**padding, "length": None})
        except Exception as e:
            logger.warning(
                "Could not set truncation to %d tokens for %s (%s); "
                "using fastembed's default tokenizer settings",
                max_tokens,
                self.model_name,
                e,
            )
            # Best-effort rollback so truncation and padding stay consistent.
            try:
                if truncation:
                    tokenizer.enable_truncation(**truncation)
                if padding:
                    tokenizer.enable_padding(**padding)
            except Exception:
                logger.debug("Tokenizer rollback failed for %s", self.model_name)
            return
        logger.info(
            "Truncating inputs at %d tokens for %s (fastembed's packaging "
            "configured %s)",
            max_tokens,
            self.model_name,
            truncation.get("max_length", "no truncation"),
        )

    def embed_sync(self, texts: Iterable[str]) -> list[list[float]]:
        """Embed *texts* synchronously (blocking). Prefer awaiting the adapter."""
        texts = list(texts)
        if not texts:
            return []
        model = self._get_model()
        return [[float(x) for x in vector] for vector in model.embed(texts)]

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* in a worker thread, returning one vector per text."""
        if not texts:
            return []
        return await asyncio.to_thread(self.embed_sync, texts)
