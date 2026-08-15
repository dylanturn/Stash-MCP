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
import os
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

# Query/document instruction prefixes, keyed by lower-cased model name prefix
# (longest match wins). Asymmetric models are trained with these and lose a
# lot of retrieval quality without them; symmetric models (all-MiniLM, gte,
# and the bge *v1.5* family) are deliberately absent.
#
# Sources: model cards for intfloat/*e5*, nomic-ai/nomic-embed-text*,
# Snowflake/snowflake-arctic-embed-*, mixedbread-ai/mxbai-embed-large-v1 and
# BAAI/bge-*-en (v1). BAAI's bge v1.5 card states retrieval improves *without*
# the instruction, which a side-by-side check on this corpus confirmed, so
# v1.5 models are left bare.
_BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
_MODEL_PREFIXES: dict[str, tuple[str, str]] = {
    # (query prefix, document prefix)
    "intfloat/e5-": ("query: ", "passage: "),
    "intfloat/multilingual-e5-": ("query: ", "passage: "),
    "nomic-ai/nomic-embed-text": ("search_query: ", "search_document: "),
    "snowflake/snowflake-arctic-embed": (_BGE_QUERY_INSTRUCTION, ""),
    "mixedbread-ai/mxbai-embed-large": (_BGE_QUERY_INSTRUCTION, ""),
    "baai/bge-small-en": (_BGE_QUERY_INSTRUCTION, ""),
    "baai/bge-base-en": (_BGE_QUERY_INSTRUCTION, ""),
    "baai/bge-large-en": (_BGE_QUERY_INSTRUCTION, ""),
    # v1.5 retrieves better with no instruction — override the v1 entries above
    "baai/bge-small-en-v1.5": ("", ""),
    "baai/bge-base-en-v1.5": ("", ""),
    "baai/bge-large-en-v1.5": ("", ""),
    "baai/bge-small-zh-v1.5": ("", ""),
}


def prefixes_for_model(model_name: str) -> tuple[str, str]:
    """Return the ``(query_prefix, document_prefix)`` a model was trained with.

    Unknown models get ``("", "")`` — no prefix is the safe default, since a
    wrong instruction hurts more than a missing one on symmetric models.
    """
    name = model_name.strip().lower()
    match = ""
    for key in _MODEL_PREFIXES:
        if name.startswith(key) and len(key) > len(match):
            match = key
    return _MODEL_PREFIXES[match] if match else ("", "")


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

    Returns the directory as a string, or None to let fastembed choose
    (``FASTEMBED_CACHE_PATH`` or a temp directory).
    """
    if cache_dir is None:
        return None
    path = Path(cache_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        writable = os.access(path, os.W_OK)
    except OSError as e:
        logger.warning(
            "Model cache directory %s is not usable (%s); "
            "falling back to fastembed's default cache location",
            path,
            e,
        )
        return None
    if not writable:
        logger.warning(
            "Model cache directory %s is not writable; "
            "falling back to fastembed's default cache location",
            path,
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
        query_prefix: Instruction prepended to queries. None uses the model's
            documented prefix (see :func:`prefixes_for_model`); pass ``""`` to
            force none.
        document_prefix: Instruction prepended to documents, same defaulting.

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
        query_prefix: str | None = None,
        document_prefix: str | None = None,
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
        default_query, default_document = prefixes_for_model(model_name)
        self.query_prefix = default_query if query_prefix is None else query_prefix
        self.document_prefix = (
            default_document if document_prefix is None else document_prefix
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

    def embed_sync(
        self, texts: Iterable[str], *, prefix: str | None = None
    ) -> list[list[float]]:
        """Embed *texts* synchronously (blocking). Prefer awaiting the adapter.

        Args:
            texts: Texts to embed.
            prefix: Instruction to prepend. None uses ``document_prefix``.
        """
        texts = list(texts)
        if not texts:
            return []
        prefix = self.document_prefix if prefix is None else prefix
        if prefix:
            texts = [f"{prefix}{text}" for text in texts]
        model = self._get_model()
        return [vector.tolist() for vector in model.embed(texts)]

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* as documents in a worker thread, one vector per text."""
        if not texts:
            return []
        return await asyncio.to_thread(self.embed_sync, texts)

    def measure_visible_chars_sync(self, texts: Iterable[str]) -> list[int] | None:
        """How many leading characters of each text the model actually reads.

        Tokenizers truncate silently, so a chunk longer than the model's
        context window is embedded only up to the cut — the tail contributes
        nothing to the vector and can never be retrieved. Encoding each text
        (with its document prefix, which consumes part of the window) and
        taking the largest character offset in the result tells us exactly
        where that cut lands, without mutating tokenizer state or guessing a
        characters-per-token ratio.

        Returns:
            One character count per text (equal to ``len(text)`` when it fits),
            or None if the tokenizer is not reachable.
        """
        texts = list(texts)
        if not texts:
            return []
        try:
            tokenizer = self._get_model().model.tokenizer
            prefix_len = len(self.document_prefix)
            encodings = tokenizer.encode_batch(
                [f"{self.document_prefix}{text}" for text in texts]
            )
            visible: list[int] = []
            for text, encoding in zip(texts, encodings):
                # Padding tokens carry (0, 0) offsets, so take the maximum end
                # rather than the last one.
                end = max((span[1] for span in encoding.offsets), default=0)
                visible.append(max(0, min(len(text), end - prefix_len)))
            return visible
        except Exception as e:
            logger.debug(
                "Could not measure the context window for %s (%s)", self.model_name, e
            )
            return None

    async def measure_visible_chars(self, texts: list[str]) -> list[int] | None:
        """Async wrapper around :meth:`measure_visible_chars_sync`."""
        if not texts:
            return []
        return await asyncio.to_thread(self.measure_visible_chars_sync, texts)

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query, applying the model's query instruction.

        Asymmetric models (e5, nomic, arctic, ...) are trained with different
        instructions for queries and passages; using the document path for a
        query measurably degrades retrieval on those models.
        """
        vectors = await asyncio.to_thread(
            self.embed_sync, [text], prefix=self.query_prefix
        )
        return vectors[0]
