"""Semantic search with vector index for Stash-MCP.

Provides VectorStore (numpy-based cosine similarity search with pickle persistence)
and SearchEngine (chunking → optional contextual enrichment → embedding → storage → query).
"""

import asyncio
import hashlib
import json
import logging
import pickle
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum characters to pass to contextual retrieval model (~200k tokens ≈ 150k chars)
MAX_CONTEXTUAL_DOCUMENT_CHARS = 150_000


def _normalize_path(path: str) -> str:
    """Normalize a file path for consistent matching.

    Strips leading/trailing slashes and normalizes backslashes to forward slashes.
    This ensures paths from different sources (MCP tools, REST API, UI, filesystem)
    match correctly in the vector store.

    Args:
        path: The raw file path string.

    Returns:
        Normalized path string.
    """
    return path.replace("\\", "/").strip("/")


@dataclass
class ChunkMetadata:
    """Metadata for a single chunk in the vector store."""

    file_path: str
    chunk_index: int
    content: str
    context: str | None = None
    content_hash: str = ""


@dataclass
class SearchResult:
    """A single search result."""

    file_path: str
    chunk_index: int
    content: str
    context: str | None
    score: float
    last_changed_at: str | None = None
    changed_by: str | None = None
    commit_message: str | None = None


class VectorStore:
    """Lightweight embedded vector database using numpy.

    Stores pre-computed embedding vectors and metadata, performs cosine
    similarity search, and persists to disk via pickle.
    """

    def __init__(self, store_path: Path):
        """Load existing store from disk, or start empty.

        Args:
            store_path: Path to the pickle file for persistence.
        """
        self.store_path = store_path
        self._vectors = None  # np.ndarray | None, shape: (n, dim)
        self._metadata: list[dict] = []
        # Lazy caches keyed by (file_path, chunk_index). Built on first
        # access, invalidated together on any mutation.
        self._meta_index_cache: dict[tuple[str, int], dict] | None = None
        self._pos_index_cache: dict[tuple[str, int], int] | None = None
        self._load()

    def _invalidate_caches(self) -> None:
        self._meta_index_cache = None
        self._pos_index_cache = None

    @property
    def metadata_index(self) -> dict[tuple[str, int], dict]:
        """Return a (file_path, chunk_index) → metadata dict, cached.

        Cached across queries between mutations; invalidated by ``add``,
        ``remove_by_file``, and ``clear``. Callers must treat the
        returned dict as read-only.
        """
        if self._meta_index_cache is None:
            self._meta_index_cache = {
                (m.get("file_path", ""), int(m.get("chunk_index", 0))): m
                for m in self._metadata
            }
        return self._meta_index_cache

    @property
    def vector_index(self) -> dict[tuple[str, int], int]:
        """Return a (file_path, chunk_index) → position-in-_vectors map.

        Same caching/invalidation contract as ``metadata_index``. Used
        by MMR reranking to locate each candidate's vector for the
        diversity term without scanning ``_metadata`` per query.
        """
        if self._pos_index_cache is None:
            self._pos_index_cache = {
                (m.get("file_path", ""), int(m.get("chunk_index", 0))): i
                for i, m in enumerate(self._metadata)
            }
        return self._pos_index_cache

    def _load(self) -> None:
        """Load vectors and metadata from disk if available."""
        if self.store_path.exists():
            try:
                with open(self.store_path, "rb") as f:
                    data = pickle.load(f)  # noqa: S301
                self._vectors = data.get("vectors")
                self._metadata = data.get("metadata", [])
                count = len(self._metadata)
                logger.info(f"Loaded {count} vectors from {self.store_path}")
            except Exception as e:
                logger.warning(f"Failed to load vector store: {e}")
                self._vectors = None
                self._metadata = []

    def save(self) -> None:
        """Persist vectors and metadata to disk."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, "wb") as f:
            pickle.dump({"vectors": self._vectors, "metadata": self._metadata}, f)

    async def save_async(self) -> None:
        """Persist vectors and metadata to disk without blocking the event loop."""
        await asyncio.to_thread(self.save)

    def add(self, embeddings: list[list[float]], metadata: list[dict]) -> None:
        """Append vectors and metadata.

        Note: caller is responsible for persistence (call save/save_async).

        Args:
            embeddings: List of embedding vectors.
            metadata: List of metadata dicts, one per embedding.
        """
        if len(embeddings) != len(metadata):
            raise ValueError("embeddings and metadata must have the same length")
        if not embeddings:
            return

        import numpy as np

        new_vectors = np.array(embeddings, dtype=np.float32)
        if self._vectors is None or len(self._vectors) == 0:
            self._vectors = new_vectors
        else:
            self._vectors = np.vstack([self._vectors, new_vectors])
        self._metadata.extend(metadata)
        self._invalidate_caches()

    def remove_by_file(self, file_path: str) -> int:
        """Remove all vectors belonging to a file.

        Note: caller is responsible for persistence (call save/save_async).

        Args:
            file_path: Relative file path to remove.

        Returns:
            Count of vectors removed.
        """
        if not self._metadata:
            return 0

        normalized = _normalize_path(file_path)
        keep_indices = [
            i for i, m in enumerate(self._metadata)
            if _normalize_path(m.get("file_path", "")) != normalized
        ]
        removed = len(self._metadata) - len(keep_indices)

        if removed == 0:
            return 0

        if keep_indices:
            self._vectors = self._vectors[keep_indices]
            self._metadata = [self._metadata[i] for i in keep_indices]
        else:
            self._vectors = None
            self._metadata = []
        self._invalidate_caches()

        return removed

    def search(
        self, query_embedding: list[float], top_n: int = 10
    ) -> list[dict]:
        """Cosine similarity search.

        Args:
            query_embedding: The query embedding vector.
            top_n: Maximum number of results to return.

        Returns:
            List of metadata dicts with added 'score' field, sorted by
            descending similarity.
        """
        if self._vectors is None or len(self._vectors) == 0:
            return []

        import numpy as np

        query = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []
        query = query / query_norm

        norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        normed = self._vectors / norms

        similarities = normed @ query
        top_k = min(top_n, len(similarities))
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            if score <= 0:
                continue
            result = dict(self._metadata[idx])
            result["score"] = score
            results.append(result)

        return results

    def search_mmr(
        self,
        query_embedding: list[float],
        *,
        top_n: int = 10,
        candidate_pool: int = 30,
        mmr_lambda: float = 0.7,
        max_per_file: int | None = 2,
    ) -> list[dict]:
        """Cosine retrieval followed by Maximal Marginal Relevance reranking.

        Pulls ``candidate_pool`` raw chunks by cosine similarity, then
        greedily picks up to ``top_n`` of them while balancing relevance
        against diversity. ``mmr_lambda=1.0`` collapses to pure cosine
        ordering; ``0.0`` ignores relevance and maximises diversity.
        ``max_per_file`` (if set) hard-caps how many chunks from any one
        file can land in the final result.

        Returns the same metadata-with-score shape as ``search``.
        """
        if self._vectors is None or len(self._vectors) == 0:
            return []
        if top_n <= 0 or candidate_pool <= 0:
            return []

        import numpy as np

        query = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(query)
        if q_norm == 0:
            return []
        query = query / q_norm

        norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        normed = self._vectors / norms

        similarities = normed @ query
        pool_size = min(candidate_pool, len(similarities))
        # argpartition is O(n) vs argsort's O(n log n); fine either way at
        # this scale, but argsort makes the post-sort cleaner.
        pool_indices = np.argsort(similarities)[-pool_size:][::-1]

        # Drop non-positive scores up front — they would never beat any
        # positive candidate even with the diversity term.
        pool = [int(i) for i in pool_indices if similarities[int(i)] > 0]
        if not pool:
            return []

        selected: list[int] = []
        per_file: dict[str, int] = {}

        while pool and len(selected) < top_n:
            if not selected:
                best = pool[0]
                best_pos = 0
            else:
                # Cosine sim between each remaining candidate and the
                # already-selected set, using pre-normalised vectors.
                selected_mat = normed[selected]
                cand_mat = normed[pool]
                cross_sim = cand_mat @ selected_mat.T
                max_sim = cross_sim.max(axis=1)
                rel = similarities[pool]
                mmr_scores = mmr_lambda * rel - (1 - mmr_lambda) * max_sim
                best_pos = int(np.argmax(mmr_scores))
                best = pool[best_pos]

            file_path = self._metadata[best].get("file_path", "")
            if (
                max_per_file is not None
                and per_file.get(file_path, 0) >= max_per_file
            ):
                pool.pop(best_pos)
                continue

            selected.append(best)
            per_file[file_path] = per_file.get(file_path, 0) + 1
            pool.pop(best_pos)

        results = []
        for idx in selected:
            result = dict(self._metadata[idx])
            result["score"] = float(similarities[idx])
            results.append(result)
        return results

    def mmr_rerank(
        self,
        query_embedding: list[float],
        candidates: list[dict],
        *,
        top_n: int,
        mmr_lambda: float = 0.7,
        max_per_file: int | None = 2,
    ) -> list[dict]:
        """MMR over a pre-selected candidate set (used after hybrid fusion).

        Each candidate dict must carry ``file_path`` and ``chunk_index``;
        we look the vector up in the store by that key and run the same
        relevance-vs-diversity MMR loop as ``search_mmr``. Candidates
        whose vector can't be found are skipped.
        """
        if not candidates or self._vectors is None or len(self._vectors) == 0:
            return []
        if top_n <= 0:
            return []

        import numpy as np

        # Use VectorStore.vector_index — cached across queries and only
        # invalidated on mutations — so this loop is O(len(candidates))
        # rather than O(total_chunks) per call.
        key_to_idx = self.vector_index

        cand_vec_idx: list[int] = []
        cand_meta: list[dict] = []
        for c in candidates:
            key = (c.get("file_path", ""), int(c.get("chunk_index", 0)))
            idx = key_to_idx.get(key)
            if idx is not None:
                cand_vec_idx.append(idx)
                cand_meta.append(c)
        if not cand_vec_idx:
            return []

        query = np.array(query_embedding, dtype=np.float32)
        qn = np.linalg.norm(query)
        if qn == 0:
            return []
        query = query / qn

        norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        normed = self._vectors / norms

        similarities = normed @ query

        pool = list(range(len(cand_vec_idx)))
        selected: list[int] = []
        per_file: dict[str, int] = {}

        while pool and len(selected) < top_n:
            if not selected:
                best_pos = 0
            else:
                sel_vec = normed[[cand_vec_idx[p] for p in selected]]
                pool_vec = normed[[cand_vec_idx[p] for p in pool]]
                cross = pool_vec @ sel_vec.T
                max_sim = cross.max(axis=1)
                rel = np.array(
                    [similarities[cand_vec_idx[p]] for p in pool]
                )
                mmr_scores = mmr_lambda * rel - (1 - mmr_lambda) * max_sim
                best_pos = int(np.argmax(mmr_scores))

            candidate_pos = pool[best_pos]
            fp = cand_meta[candidate_pos].get("file_path", "")
            if (
                max_per_file is not None
                and per_file.get(fp, 0) >= max_per_file
            ):
                pool.pop(best_pos)
                continue
            selected.append(candidate_pos)
            per_file[fp] = per_file.get(fp, 0) + 1
            pool.pop(best_pos)

        # Overwrite score with cosine similarity to the query so the
        # returned items carry a consistent, interpretable relevance
        # signal (matching VectorStore.search_mmr's behaviour). This
        # is especially important in the hybrid path, where the input
        # `score` was the RRF fused score — not the cosine similarity.
        out: list[dict] = []
        for p in selected:
            item = dict(cand_meta[p])
            item["score"] = float(similarities[cand_vec_idx[p]])
            out.append(item)
        return out

    def clear(self) -> None:
        """Remove all vectors and metadata."""
        self._vectors = None
        self._metadata = []
        self._invalidate_caches()
        self.save()

    @property
    def count(self) -> int:
        """Number of stored vectors."""
        return len(self._metadata)


class BM25Store:
    """Lightweight BM25 index backed by `bm25s`.

    Indexes the same chunks as VectorStore. The persisted on-disk layout
    is a directory containing the bm25s scores plus a JSON sidecar
    mapping the bm25s integer doc IDs back to (file_path, chunk_index)
    tuples in the SearchEngine's metadata.

    Incremental updates aren't supported by BM25 cleanly — instead we
    expose a `mark_dirty` flag and the engine rebuilds from
    `VectorStore._metadata` at every save batch. This trades a small
    O(n) rebuild cost for much simpler lifecycle code.
    """

    INDEX_SUBDIR = "bm25_index"
    IDS_FILE = "chunk_ids.json"

    def __init__(self, store_path: Path):
        """Initialize the store; load from disk if available.

        Args:
            store_path: Directory under which the index subdir and ID
                sidecar live (typically the engine's index_dir).
        """
        self.store_path = store_path
        self._retriever = None
        self._chunk_ids: list[tuple[str, int]] = []
        self._dirty = False
        self._load()

    def _index_dir(self) -> Path:
        return self.store_path / self.INDEX_SUBDIR

    def _ids_path(self) -> Path:
        return self.store_path / self.IDS_FILE

    def _load(self) -> None:
        """Load the persisted BM25 index, or start empty."""
        index_dir = self._index_dir()
        ids_path = self._ids_path()
        if not index_dir.exists() or not ids_path.exists():
            return
        try:
            import bm25s
            self._retriever = bm25s.BM25.load(str(index_dir), load_corpus=False)
            with open(ids_path) as f:
                raw = json.load(f)
            self._chunk_ids = [(fp, ci) for fp, ci in raw]
            logger.info(
                "Loaded BM25 index with %d chunks from %s",
                len(self._chunk_ids),
                index_dir,
            )
        except Exception as e:
            logger.warning("Failed to load BM25 index: %s", e)
            self._retriever = None
            self._chunk_ids = []

    def rebuild(self, chunks: list[dict]) -> None:
        """Rebuild the BM25 index from a list of chunk metadata.

        The chunks list is the full VectorStore metadata. Each entry must
        carry 'content', 'file_path', and 'chunk_index'. Order of chunks
        defines the integer doc IDs the retriever returns.
        """
        try:
            import bm25s
        except ImportError as e:
            raise RuntimeError(
                "bm25s is required for hybrid search. "
                "Install with: pip install 'stash-mcp[search-hybrid]'"
            ) from e

        if not chunks:
            self._retriever = None
            self._chunk_ids = []
            self._dirty = False
            return

        corpus = [m.get("content", "") for m in chunks]
        self._chunk_ids = [
            (m.get("file_path", ""), int(m.get("chunk_index", 0)))
            for m in chunks
        ]
        tokens = bm25s.tokenize(corpus, stopwords="en", show_progress=False)
        retriever = bm25s.BM25()
        retriever.index(tokens, show_progress=False)
        self._retriever = retriever
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    @property
    def dirty(self) -> bool:
        return self._dirty

    def search(
        self, query: str, top_n: int = 30
    ) -> list[tuple[str, int, float]]:
        """Return (file_path, chunk_index, score) tuples, sorted descending."""
        if self._retriever is None or not self._chunk_ids:
            return []
        try:
            import bm25s
        except ImportError:
            return []
        if not query.strip():
            return []
        query_tokens = bm25s.tokenize([query], stopwords="en", show_progress=False)
        k = min(top_n, len(self._chunk_ids))
        if k <= 0:
            return []
        results, scores = self._retriever.retrieve(
            query_tokens, k=k, show_progress=False
        )
        out: list[tuple[str, int, float]] = []
        for doc_id, score in zip(results[0], scores[0]):
            score = float(score)
            if score <= 0:
                continue
            fp, ci = self._chunk_ids[int(doc_id)]
            out.append((fp, ci, score))
        return out

    def save(self) -> None:
        """Persist the BM25 index and ID sidecar to disk."""
        self.store_path.mkdir(parents=True, exist_ok=True)
        if self._retriever is None or not self._chunk_ids:
            # Empty state — remove any stale on-disk files.
            ids_path = self._ids_path()
            if ids_path.exists():
                ids_path.unlink()
            index_dir = self._index_dir()
            if index_dir.exists():
                import shutil
                shutil.rmtree(index_dir)
            return
        self._retriever.save(str(self._index_dir()), corpus=None)
        with open(self._ids_path(), "w") as f:
            json.dump(self._chunk_ids, f)

    async def save_async(self) -> None:
        await asyncio.to_thread(self.save)

    def clear(self) -> None:
        self._retriever = None
        self._chunk_ids = []
        self._dirty = False
        self.save()

    @property
    def count(self) -> int:
        return len(self._chunk_ids)


def _rrf_fuse(
    dense_results: list[dict],
    sparse_results: list[tuple[str, int, float]],
    *,
    k: int = 60,
) -> list[dict]:
    """Combine dense and sparse rankings via Reciprocal Rank Fusion.

    Score per item = sum(1 / (k + rank_in_each_list)). Items appearing
    in only one list still get a partial score from that list. The
    returned items carry metadata from the dense side when present;
    sparse-only items get a stub (file_path, chunk_index, score) that
    the caller must hydrate before display.
    """
    scores: dict[tuple[str, int], float] = {}
    meta_by_id: dict[tuple[str, int], dict] = {}

    for rank, r in enumerate(dense_results):
        key = (r.get("file_path", ""), int(r.get("chunk_index", 0)))
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        meta_by_id[key] = r

    for rank, (fp, ci, _score) in enumerate(sparse_results):
        key = (fp, int(ci))
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        meta_by_id.setdefault(key, {"file_path": fp, "chunk_index": ci})

    fused = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [{**meta_by_id[key], "score": s} for key, s in fused]


def _chunk_text_sliding_window(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
) -> list[str]:
    """Split text into fixed-size overlapping chunks.

    Simple sliding window — no structural parsing, no boundary detection.

    Args:
        text: The text to chunk.
        chunk_size: Number of characters per chunk.
        chunk_overlap: Number of characters to overlap between adjacent chunks.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end].strip())
        start += chunk_size - chunk_overlap

    # Drop any trailing empty chunk
    return [c for c in chunks if c.strip()]


def _chunk_text(text: str, max_chunk_size: int = 1500) -> list[str]:
    """Split text into chunks using a markdown-aware strategy.

    .. deprecated::
        Use :func:`_chunk_text_sliding_window` instead.

    Splitting priority:
    1. Markdown headings (``#``, ``##``, etc.)
    2. Paragraph boundaries (double newline)
    3. Sentence boundaries (last-resort hard split)

    Args:
        text: The text to chunk.
        max_chunk_size: Target maximum characters per chunk.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    if len(text) <= max_chunk_size:
        return [text.strip()]

    # Split on markdown headings (keep heading with section)
    heading_pattern = re.compile(r"(?=^#{1,6}\s)", re.MULTILINE)
    sections = heading_pattern.split(text)
    sections = [s for s in sections if s.strip()]

    chunks: list[str] = []
    for section in sections:
        if len(section) <= max_chunk_size:
            chunks.append(section.strip())
        else:
            # Split on paragraph boundaries
            paragraphs = re.split(r"\n\s*\n", section)
            current = ""
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                if len(current) + len(para) + 2 <= max_chunk_size:
                    current = f"{current}\n\n{para}" if current else para
                else:
                    if current:
                        chunks.append(current)
                    if len(para) <= max_chunk_size:
                        current = para
                    else:
                        # Last resort: split on sentences
                        sentences = re.split(r"(?<=[.!?])\s+", para)
                        current = ""
                        for sent in sentences:
                            if len(current) + len(sent) + 1 <= max_chunk_size:
                                current = f"{current} {sent}" if current else sent
                            else:
                                if current:
                                    chunks.append(current)
                                current = sent
            if current:
                chunks.append(current)

    return chunks if chunks else [text.strip()]


def _content_hash(content: str) -> str:
    """Compute SHA-256 hash of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class IndexMeta:
    """Tracks file hashes and chunk counts for incremental indexing."""

    file_hashes: dict[str, str] = field(default_factory=dict)
    chunk_counts: dict[str, int] = field(default_factory=dict)
    embedder_model: str = ""

    def save(self, path: Path) -> None:
        """Persist to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(
                {
                    "file_hashes": self.file_hashes,
                    "chunk_counts": self.chunk_counts,
                    "embedder_model": self.embedder_model,
                },
                f,
                indent=2,
            )

    async def save_async(self, path: Path) -> None:
        """Persist to JSON file without blocking the event loop."""
        await asyncio.to_thread(self.save, path)

    @classmethod
    def load(cls, path: Path) -> "IndexMeta":
        """Load from JSON file, or return empty if not found."""
        if not path.exists():
            return cls()
        try:
            with open(path) as f:
                data = json.load(f)
            return cls(
                file_hashes=data.get("file_hashes", {}),
                chunk_counts=data.get("chunk_counts", {}),
                embedder_model=data.get("embedder_model", ""),
            )
        except Exception as e:
            logger.warning(f"Failed to load index meta: {e}")
            return cls()


class SearchEngine:
    """Orchestrates the semantic search pipeline.

    Pipeline: chunking → optional contextual enrichment → embedding → storage → query.
    """

    def __init__(
        self,
        content_dir: Path,
        index_dir: Path,
        *,
        embedder_model: str = "sentence-transformers:all-MiniLM-L6-v2",
        contextual_retrieval: bool = False,
        contextual_model: str = "claude-haiku-4-5-20251001",
        anthropic_api_key: str | None = None,
        embed_fn=None,
        filesystem=None,
        git_backend=None,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        mmr_enabled: bool = True,
        mmr_lambda: float = 0.7,
        max_per_file: int = 2,
        candidate_pool_multiplier: int = 6,
        recency_weight: float = 0.0,
        recency_half_life_days: float = 180.0,
        hybrid_enabled: bool = False,
        rrf_k: int = 60,
        bm25_candidate_pool: int = 30,
    ):
        """Initialize the search engine.

        Args:
            content_dir: Root directory for content files.
            index_dir: Directory for index persistence.
            embedder_model: Pydantic AI embedder model string.
            contextual_retrieval: Whether to use Claude-powered chunk enrichment.
            contextual_model: Model string for contextual retrieval.
            anthropic_api_key: API key for contextual retrieval (required if enabled).
            embed_fn: Optional custom embedding function for testing.
                      Signature: async (texts: list[str]) -> list[list[float]]
            filesystem: Optional FileSystem instance for content path filtering.
            git_backend: Optional GitBackend instance for blame-enriched results.
            chunk_size: Number of characters per chunk for the sliding window.
            chunk_overlap: Number of characters to overlap between adjacent chunks.
            mmr_enabled: Apply MMR diversification + per-file cap to the
                cosine candidate pool before truncating to max_results.
            mmr_lambda: MMR relevance/diversity balance (1.0 = relevance-only,
                0.0 = diversity-only). Default 0.7.
            max_per_file: Hard cap on chunks from a single file in the
                final result set.
            candidate_pool_multiplier: How many cosine candidates to fetch
                per requested result (e.g. 6 means fetch 30 for max_results=5).
            recency_weight: Blend factor for the git-blame recency boost
                (0.0 = ignore recency, 1.0 = recency only). Off by default.
            recency_half_life_days: Days for the recency boost to decay
                from 1.0 to 0.5. Default 180 (6 months).
            hybrid_enabled: Run BM25 alongside dense retrieval and fuse
                via Reciprocal Rank Fusion before MMR. Requires the
                bm25s dependency. Off by default.
            rrf_k: RRF smoothing constant. 60 is the standard value
                from the original paper.
            bm25_candidate_pool: How many sparse candidates to fetch
                per query before fusion.
        """
        self.content_dir = content_dir
        self.index_dir = index_dir
        self.embedder_model = embedder_model
        self.contextual_retrieval = contextual_retrieval
        self.contextual_model = contextual_model
        self.anthropic_api_key = anthropic_api_key
        self._embed_fn = embed_fn
        self._embedder = None
        self._filesystem = filesystem
        self._git_backend = git_backend
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.mmr_enabled = mmr_enabled
        self.mmr_lambda = mmr_lambda
        self.max_per_file = max_per_file
        self.candidate_pool_multiplier = max(1, candidate_pool_multiplier)
        self.recency_weight = recency_weight
        self.recency_half_life_days = recency_half_life_days
        self.hybrid_enabled = hybrid_enabled
        self.rrf_k = rrf_k
        self.bm25_candidate_pool = bm25_candidate_pool

        # Validate numpy dependency at init time so we fail fast
        # rather than crashing on first file operation.
        if self._embed_fn is None:
            try:
                import numpy as np  # noqa: F401
            except ImportError:
                raise RuntimeError(
                    "numpy is required for semantic search. "
                    "Install with: pip install 'stash-mcp[search]'"
                )

        # Fail fast if hybrid is on but the sparse backend isn't installed.
        if self.hybrid_enabled:
            try:
                import bm25s  # noqa: F401
            except ImportError:
                raise RuntimeError(
                    "bm25s is required for hybrid search. "
                    "Install with: pip install 'stash-mcp[search-hybrid]'"
                )

        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.store = VectorStore(index_dir / "vectors.pkl")
        self.meta = IndexMeta.load(index_dir / "index_meta.json")
        self.bm25_store = BM25Store(index_dir)

        # If embedder model changed, clear stale index for rebuild —
        # the BM25 store must be wiped in the same block so the two
        # indexes don't drift.
        if self.meta.embedder_model and self.meta.embedder_model != embedder_model:
            logger.warning(
                f"Embedder model changed from '{self.meta.embedder_model}' "
                f"to '{embedder_model}'. Clearing stale index for rebuild."
            )
            self.store.clear()
            self.bm25_store.clear()
            self.meta = IndexMeta()
            self.meta.save(self.index_dir / "index_meta.json")

        # Upgrade path: vectors.pkl exists from a pre-hybrid deployment
        # but no BM25 index yet — rebuild it now so the first query
        # doesn't need to wait.
        if (
            self.hybrid_enabled
            and self.store.count > 0
            and self.bm25_store.count == 0
        ):
            logger.info("Building BM25 index from existing vector metadata")
            self.bm25_store.rebuild(self.store._metadata)
            self.bm25_store.save()

        self._ready = self.store.count > 0
        self._indexing = False
        self._lock = asyncio.Lock()

        # Eagerly initialise the embedder so the first search query is fast
        self._embedder = self._create_embedder()

    def _create_embedder(self):
        """Create and return the embedding model instance, or None for custom embed_fn.

        Returns:
            Embedder instance, or None if a custom embed_fn is provided.

        Raises:
            RuntimeError: If pydantic-ai is not installed.
        """
        if self._embed_fn is not None:
            return None
        try:
            from pydantic_ai import Embedder

            return Embedder(self.embedder_model)
        except ImportError:
            raise RuntimeError(
                "pydantic-ai is required for semantic search. "
                "Install with: pip install 'stash-mcp[search]'"
            )

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document texts using the configured embedder.

        Args:
            texts: Texts to embed.

        Returns:
            List of embedding vectors.
        """
        if self._embed_fn is not None:
            return await self._embed_fn(texts)

        result = await self._embedder.embed_documents(texts)
        return result.embeddings

    async def _embed_query(self, text: str) -> list[float]:
        """Embed a single query text using the configured embedder.

        Uses the query-specific embedding path which some providers
        (e.g. Cohere) optimise differently from document embeddings.

        Args:
            text: Query text to embed.

        Returns:
            Single embedding vector.
        """
        if self._embed_fn is not None:
            result = await self._embed_fn([text])
            return result[0]

        result = await self._embedder.embed_query(text)
        return result.embeddings[0]

    async def _contextualise_chunk(
        self, chunk: str, full_document: str
    ) -> str | None:
        """Generate contextual preamble for a chunk using Claude.

        Args:
            chunk: The chunk content.
            full_document: The full document content.

        Returns:
            Context string, or None if contextual retrieval is disabled/unavailable.
        """
        if not self.contextual_retrieval or not self.anthropic_api_key:
            return None

        try:
            import anthropic

            # Truncate document to stay within context window
            if len(full_document) > MAX_CONTEXTUAL_DOCUMENT_CHARS:
                full_document = full_document[:MAX_CONTEXTUAL_DOCUMENT_CHARS] + "\n...[truncated]"

            client = anthropic.AsyncAnthropic(api_key=self.anthropic_api_key)
            prompt = (
                f"<document>{full_document}</document>\n"
                f"Here is the chunk we want to situate within the whole document:\n"
                f"<chunk>{chunk}</chunk>\n"
                f"Please give a short succinct context to situate this chunk "
                f"within the overall document for the purposes of improving "
                f"search retrieval of the chunk. "
                f"Answer only with the succinct context and nothing else."
            )
            response = await client.messages.create(
                model=self.contextual_model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            logger.warning(f"Contextual retrieval failed: {e}")
            return None

    async def build_index(self, file_paths: list[str]) -> int:
        """Build or rebuild the index for the given files.

        Only re-embeds files whose content has changed (hash-detected).
        Yields to the event loop between files and batches persistence
        every 10 files to avoid blocking.

        Args:
            file_paths: List of relative file paths to index.

        Returns:
            Total number of chunks indexed.
        """
        self._indexing = True
        total_chunks = 0
        files_since_save = 0
        _SAVE_BATCH_SIZE = 10

        try:
            for rel_path in file_paths:
                normalized = _normalize_path(rel_path)
                full_path = self.content_dir / normalized
                if not full_path.is_file():
                    continue

                try:
                    content = await asyncio.to_thread(
                        full_path.read_text, encoding="utf-8"
                    )
                except Exception as e:
                    logger.warning(f"Could not read {normalized}: {e}")
                    continue

                content_h = _content_hash(content)

                # Skip if unchanged
                if self.meta.file_hashes.get(normalized) == content_h:
                    total_chunks += self.meta.chunk_counts.get(normalized, 0)
                    continue

                async with self._lock:
                    chunks_added = await self._index_file_locked(
                        normalized, content=content
                    )
                total_chunks += chunks_added
                files_since_save += 1

                # Batch persistence
                if files_since_save >= _SAVE_BATCH_SIZE:
                    await self.store.save_async()
                    await self.meta.save_async(self.index_dir / "index_meta.json")
                    await self._rebuild_bm25_if_dirty()
                    files_since_save = 0

                # Yield to the event loop between files
                await asyncio.sleep(0)

            # Final save
            self.meta.embedder_model = self.embedder_model
            await self.store.save_async()
            await self.meta.save_async(self.index_dir / "index_meta.json")
            await self._rebuild_bm25_if_dirty()
            self._ready = True
            return total_chunks
        finally:
            self._indexing = False

    async def _rebuild_bm25_if_dirty(self) -> None:
        """Rebuild and persist the BM25 index from current metadata if dirty.

        No-op unless hybrid retrieval is enabled — the BM25 store may
        still mark itself dirty (e.g. during indexing), but we avoid the
        rebuild cost when nothing will query it.

        Holds ``self._lock`` for the whole rebuild + save: serializing
        against concurrent ``search()`` (which also takes the lock) and
        against other mutators ensures BM25 is never observed in a
        partially-swapped state. The metadata list is snapshotted to a
        local before being passed to the worker thread so the worker
        doesn't iterate the live ``_metadata`` reference.
        """
        if not self.hybrid_enabled or not self.bm25_store.dirty:
            return
        async with self._lock:
            # Re-check dirty: another waiter may have already rebuilt.
            if not self.bm25_store.dirty:
                return
            snapshot = list(self.store._metadata)
            await asyncio.to_thread(self.bm25_store.rebuild, snapshot)
            await self.bm25_store.save_async()

    async def _index_file_locked(
        self, relative_path: str, *, content: str | None = None
    ) -> int:
        """Index or re-index a single file (no persistence, no lock acquisition).

        Must be called while holding ``self._lock``. Used by ``build_index()``
        which manages its own lock and batched saves.

        Args:
            relative_path: Relative path to the file.
            content: Optional file content (read from disk if not provided).

        Returns:
            Number of chunks indexed.
        """
        # Remove old chunks for this file
        normalized_path = _normalize_path(relative_path)
        removed = self.store.remove_by_file(normalized_path)
        if removed:
            self.bm25_store.mark_dirty()

        if content is None:
            full_path = self.content_dir / normalized_path
            if not full_path.is_file():
                return 0
            try:
                content = await asyncio.to_thread(
                    full_path.read_text, encoding="utf-8"
                )
            except Exception as e:
                logger.warning(f"Could not read {normalized_path}: {e}")
                return 0

        chunks = _chunk_text_sliding_window(content, self.chunk_size, self.chunk_overlap)
        if not chunks:
            return 0

        content_h = _content_hash(content)
        metadata_list: list[dict] = []
        texts_to_embed: list[str] = []

        for i, chunk in enumerate(chunks):
            context = None
            if self.contextual_retrieval:
                context = await self._contextualise_chunk(chunk, content)

            embed_text = f"{context}\n\n{chunk}" if context else chunk
            texts_to_embed.append(embed_text)

            meta = ChunkMetadata(
                file_path=normalized_path,
                chunk_index=i,
                content=chunk,
                context=context,
                content_hash=content_h,
            )
            metadata_list.append(asdict(meta))

        embeddings = await self._embed(texts_to_embed)
        self.store.add(embeddings, metadata_list)
        self.bm25_store.mark_dirty()

        self.meta.file_hashes[normalized_path] = content_h
        self.meta.chunk_counts[normalized_path] = len(chunks)

        return len(chunks)

    async def index_file(
        self, relative_path: str, *, content: str | None = None
    ) -> int:
        """Index or re-index a single file (public API).

        Acquires the lock, indexes the file, and persists to disk.
        Used for incremental updates from event listeners.

        Args:
            relative_path: Relative path to the file.
            content: Optional file content (read from disk if not provided).

        Returns:
            Number of chunks indexed.
        """
        async with self._lock:
            chunks = await self._index_file_locked(relative_path, content=content)
        await self.store.save_async()
        await self.meta.save_async(self.index_dir / "index_meta.json")
        await self._rebuild_bm25_if_dirty()
        return chunks

    async def remove_file(self, relative_path: str) -> None:
        """Remove a file from the index.

        Args:
            relative_path: Relative path to the file.
        """
        normalized_path = _normalize_path(relative_path)
        async with self._lock:
            removed = self.store.remove_by_file(normalized_path)
            if removed:
                self.bm25_store.mark_dirty()
            self.meta.file_hashes.pop(normalized_path, None)
            self.meta.chunk_counts.pop(normalized_path, None)
        await self.store.save_async()
        await self.meta.save_async(self.index_dir / "index_meta.json")
        await self._rebuild_bm25_if_dirty()
        if removed:
            logger.info(f"Removed {removed} chunks for {normalized_path}")

    async def move_file_index(self, old_path: str, new_path: str) -> None:
        """Atomically remove old path and index new path under a single lock acquisition.

        This prevents race conditions where two independent tasks for remove and
        index could interleave with other operations.

        Args:
            old_path: Relative path of the file at its old location.
            new_path: Relative path of the file at its new location.
        """
        old_normalized = _normalize_path(old_path)
        async with self._lock:
            removed = self.store.remove_by_file(old_normalized)
            if removed:
                self.bm25_store.mark_dirty()
            self.meta.file_hashes.pop(old_normalized, None)
            self.meta.chunk_counts.pop(old_normalized, None)
            if removed:
                logger.info(f"Removed {removed} chunks for moved file {old_normalized}")
            await self._index_file_locked(new_path)
        await self.store.save_async()
        await self.meta.save_async(self.index_dir / "index_meta.json")
        await self._rebuild_bm25_if_dirty()

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        file_types: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search for relevant content.

        Args:
            query: Search query text.
            max_results: Maximum number of results.
            file_types: Optional list of file extensions to filter (e.g. [".md", ".py"]).

        Returns:
            List of SearchResult sorted by relevance.
        """
        if not self._ready or self.store.count == 0:
            return []

        query_embedding = await self._embed_query(query)

        # Fetch a larger candidate pool so MMR + per-file cap + file_types
        # filter have room to work. file_types over-fetches further since
        # the filter happens post-retrieval.
        candidate_pool = max(
            max_results * self.candidate_pool_multiplier,
            max_results,
        )
        fetch_n = candidate_pool * 3 if file_types else candidate_pool

        async with self._lock:
            if (
                self.hybrid_enabled
                and self.bm25_store.count > 0
                and not self.bm25_store.dirty
            ):
                # Hybrid: run both retrievers, fuse via RRF, then MMR
                # over the fused candidate set. We skip BM25 (and fall
                # back to dense-only below) when the BM25 index is
                # dirty — fusing fresh dense results with a stale
                # sparse index would produce inconsistent rankings.
                dense = self.store.search(query_embedding, top_n=fetch_n)
                sparse = self.bm25_store.search(
                    query, top_n=self.bm25_candidate_pool
                )
                fused = _rrf_fuse(dense, sparse, k=self.rrf_k)
                # Hydrate sparse-only entries (which lack content/context)
                # by looking up the full metadata from the vector store.
                # VectorStore.metadata_index is cached across queries and
                # only rebuilt on mutations, so the lookup is O(1) per
                # candidate without paying O(N) on every search.
                meta_lookup = self.store.metadata_index
                hydrated: list[dict] = []
                for r in fused:
                    if r.get("content"):
                        hydrated.append(r)
                        continue
                    key = (
                        r.get("file_path", ""),
                        int(r.get("chunk_index", 0)),
                    )
                    meta = meta_lookup.get(key)
                    if meta is None:
                        continue
                    merged = dict(meta)
                    merged["score"] = r.get("score", 0.0)
                    hydrated.append(merged)
                if self.mmr_enabled:
                    raw_results = self.store.mmr_rerank(
                        query_embedding,
                        hydrated,
                        top_n=fetch_n,
                        mmr_lambda=self.mmr_lambda,
                        max_per_file=self.max_per_file,
                    )
                else:
                    raw_results = hydrated[:fetch_n]
            elif self.mmr_enabled:
                raw_results = self.store.search_mmr(
                    query_embedding,
                    top_n=fetch_n,
                    candidate_pool=fetch_n,
                    mmr_lambda=self.mmr_lambda,
                    max_per_file=self.max_per_file,
                )
            else:
                raw_results = self.store.search(query_embedding, top_n=fetch_n)

        if file_types:
            raw_results = [
                r
                for r in raw_results
                if any(r.get("file_path", "").endswith(ext) for ext in file_types)
            ]

        # Blame is needed up-front only when recency reranking is on
        # (it needs every candidate's timestamp before truncation). When
        # recency is off, defer the fetch until after truncation so we
        # only pay for the files that actually make it into the result.
        blame_cache: dict[str, list] = {}
        recency_enabled = (
            self.recency_weight > 0
            and self._git_backend is not None
            and raw_results
        )
        if recency_enabled:
            unique_paths = list({
                r.get("file_path", "")
                for r in raw_results
                if r.get("file_path")
            })
            blame_cache = await self._fetch_blame_batch(unique_paths)

            # Min-max normalize the candidate scores into [0, 1] before
            # blending with the recency boost (which is already in that
            # range). Without this, the dense path's cosine scores (~0–1)
            # and the hybrid path's RRF scores (~0.01–0.05) would blend
            # very differently against the same recency weight, letting
            # recency disproportionately dominate the fused-score path.
            scores = [float(r.get("score", 0.0)) for r in raw_results]
            smin, smax = min(scores), max(scores)
            span = smax - smin

            def _normalize(s: float) -> float:
                if span <= 0:
                    return 0.5  # all equal — treat semantic as neutral
                return (s - smin) / span

            reranked = []
            for r in raw_results:
                semantic = _normalize(float(r.get("score", 0.0)))
                ts = self._most_recent_timestamp(
                    blame_cache.get(r.get("file_path", ""), [])
                )
                recency = self._recency_boost(ts)
                final = (
                    semantic * (1 - self.recency_weight)
                    + recency * self.recency_weight
                )
                rr = dict(r)
                rr["score"] = final
                reranked.append(rr)
            reranked.sort(key=lambda d: d.get("score", 0.0), reverse=True)
            raw_results = reranked

        results: list[SearchResult] = []
        for r in raw_results:
            fp = r.get("file_path", "")
            results.append(
                SearchResult(
                    file_path=fp,
                    chunk_index=r.get("chunk_index", 0),
                    content=r.get("content", ""),
                    context=r.get("context"),
                    score=r.get("score", 0.0),
                )
            )
            if len(results) >= max_results:
                break

        if self._git_backend is not None and results:
            # Backfill blame for any final-result files not already in
            # the cache (i.e. the recency-off path that skipped the
            # candidate-pool fetch).
            missing_paths = list({
                r.file_path
                for r in results
                if r.file_path and r.file_path not in blame_cache
            })
            if missing_paths:
                fetched = await self._fetch_blame_batch(missing_paths)
                blame_cache.update(fetched)
            for result in results:
                blame_lines = blame_cache.get(result.file_path)
                if blame_lines:
                    await self._enrich_with_blame(result, blame_lines)

        return results

    async def _fetch_blame_batch(
        self, file_paths: list[str]
    ) -> dict[str, list]:
        """Fetch blame for many files in parallel, returning {path: lines}."""

        async def _one(path: str) -> tuple[str, list]:
            try:
                lines = await asyncio.to_thread(self._git_backend.blame, path)
            except Exception as e:
                logger.debug("blame fetch failed for %s: %s", path, e)
                return path, []
            return path, lines or []

        pairs = await asyncio.gather(*(_one(p) for p in file_paths))
        return dict(pairs)

    @staticmethod
    def _most_recent_timestamp(blame_lines: list):
        """Return the most recent timestamp in a blame line list, or None."""
        if not blame_lines:
            return None
        return max(bl.timestamp for bl in blame_lines)

    def _recency_boost(self, last_changed_at) -> float:
        """Exponential-decay boost in [0, 1]. Files without history → 0.5."""
        if last_changed_at is None:
            return 0.5
        from datetime import datetime, timezone
        import math

        ts = last_changed_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - ts).days
        if self.recency_half_life_days <= 0:
            return 1.0 if age_days <= 0 else 0.0
        return math.exp(-math.log(2) * max(age_days, 0) / self.recency_half_life_days)

    async def _enrich_with_blame(
        self, result: "SearchResult", blame_lines: list
    ) -> None:
        """Populate blame fields on *result* from a pre-fetched blame list.

        Scopes blame to the chunk's line range when possible, then takes
        the most recent line in that range.
        """
        if not blame_lines:
            return

        # Find the chunk in the file to determine its line range
        relevant = blame_lines  # default: all lines
        try:
            full_path = self.content_dir / result.file_path
            file_content = await asyncio.to_thread(
                full_path.read_text, encoding="utf-8"
            )
            chunk_start = file_content.find(result.content)
            if chunk_start != -1:
                chunk_end = chunk_start + len(result.content)
                start_line = file_content[:chunk_start].count("\n") + 1
                end_line = file_content[:chunk_end].count("\n") + 1
                scoped = [
                    bl
                    for bl in blame_lines
                    if start_line <= bl.line_number <= end_line
                ]
                if scoped:
                    relevant = scoped
        except Exception as e:
            logger.debug(
                "Could not scope blame to chunk lines for %s: %s",
                result.file_path,
                e,
            )

        most_recent = max(relevant, key=lambda bl: bl.timestamp)
        result.last_changed_at = most_recent.timestamp.isoformat()
        result.changed_by = most_recent.author
        result.commit_message = most_recent.summary

    async def reindex(self) -> int:
        """Full reindex of all content files.

        Uses the FileSystem instance (if provided) to respect
        STASH_CONTENT_PATHS filtering, otherwise falls back to
        discovering all files under content_dir.

        Returns:
            Total number of chunks indexed.
        """
        async with self._lock:
            self.store.clear()
            self.meta = IndexMeta()

        file_paths = []
        if self._filesystem is not None:
            file_paths = self._filesystem.list_all_files()
        elif self.content_dir.exists():
            for item in self.content_dir.rglob("*"):
                if not item.is_file():
                    continue
                rel = item.relative_to(self.content_dir)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                file_paths.append(str(rel))

        return await self.build_index(sorted(file_paths))

    @property
    def ready(self) -> bool:
        """Whether the index is built and ready for queries."""
        return self._ready

    @property
    def indexing(self) -> bool:
        """Whether the index is currently being built."""
        return self._indexing

    @property
    def indexed_files(self) -> int:
        """Number of indexed files."""
        return len(self.meta.file_hashes)

    @property
    def indexed_chunks(self) -> int:
        """Number of indexed chunks."""
        return self.store.count
