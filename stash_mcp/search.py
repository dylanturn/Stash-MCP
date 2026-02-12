"""Semantic search with vector index for Stash-MCP.

Provides VectorStore (numpy-based cosine similarity search with pickle persistence)
and SearchEngine (chunking → optional contextual enrichment → embedding → storage → query).
"""

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
        self._load()

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

    def add(self, embeddings: list[list[float]], metadata: list[dict]) -> None:
        """Append vectors and metadata. Auto-saves to disk.

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
        self.save()

    def remove_by_file(self, file_path: str) -> int:
        """Remove all vectors belonging to a file.

        Args:
            file_path: Relative file path to remove.

        Returns:
            Count of vectors removed.
        """
        if not self._metadata:
            return 0

        keep_indices = [
            i for i, m in enumerate(self._metadata) if m.get("file_path") != file_path
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

        self.save()
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

    def clear(self) -> None:
        """Remove all vectors and metadata."""
        self._vectors = None
        self._metadata = []
        self.save()

    @property
    def count(self) -> int:
        """Number of stored vectors."""
        return len(self._metadata)


def _chunk_text(text: str, max_chunk_size: int = 1500) -> list[str]:
    """Split text into chunks using a markdown-aware strategy.

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

        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.store = VectorStore(index_dir / "vectors.pkl")
        self.meta = IndexMeta.load(index_dir / "index_meta.json")

        # If embedder model changed, refuse queries until reindexed
        if self.meta.embedder_model and self.meta.embedder_model != embedder_model:
            logger.warning(
                f"Embedder model changed from '{self.meta.embedder_model}' "
                f"to '{embedder_model}'. Index invalidated — reindex required."
            )
            self._ready = False
        else:
            self._ready = self.store.count > 0

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document texts using the configured embedder.

        Args:
            texts: Texts to embed.

        Returns:
            List of embedding vectors.
        """
        if self._embed_fn is not None:
            return await self._embed_fn(texts)

        if self._embedder is None:
            try:
                from pydantic_ai import Embedder

                self._embedder = Embedder(self.embedder_model)
            except ImportError:
                raise RuntimeError(
                    "pydantic-ai is required for semantic search. "
                    "Install with: pip install 'stash-mcp[search]'"
                )

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

        if self._embedder is None:
            try:
                from pydantic_ai import Embedder

                self._embedder = Embedder(self.embedder_model)
            except ImportError:
                raise RuntimeError(
                    "pydantic-ai is required for semantic search. "
                    "Install with: pip install 'stash-mcp[search]'"
                )

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

        Args:
            file_paths: List of relative file paths to index.

        Returns:
            Total number of chunks indexed.
        """
        total_chunks = 0

        for rel_path in file_paths:
            full_path = self.content_dir / rel_path
            if not full_path.is_file():
                continue

            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not read {rel_path}: {e}")
                continue

            content_h = _content_hash(content)

            # Skip if unchanged
            if self.meta.file_hashes.get(rel_path) == content_h:
                total_chunks += self.meta.chunk_counts.get(rel_path, 0)
                continue

            chunks_added = await self.index_file(rel_path, content=content)
            total_chunks += chunks_added

        self.meta.embedder_model = self.embedder_model
        self.meta.save(self.index_dir / "index_meta.json")
        self._ready = True
        return total_chunks

    async def index_file(
        self, relative_path: str, *, content: str | None = None
    ) -> int:
        """Index or re-index a single file.

        Args:
            relative_path: Relative path to the file.
            content: Optional file content (read from disk if not provided).

        Returns:
            Number of chunks indexed.
        """
        # Remove old chunks for this file
        self.store.remove_by_file(relative_path)

        if content is None:
            full_path = self.content_dir / relative_path
            if not full_path.is_file():
                return 0
            try:
                content = full_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not read {relative_path}: {e}")
                return 0

        chunks = _chunk_text(content)
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
                file_path=relative_path,
                chunk_index=i,
                content=chunk,
                context=context,
                content_hash=content_h,
            )
            metadata_list.append(asdict(meta))

        embeddings = await self._embed(texts_to_embed)
        self.store.add(embeddings, metadata_list)

        self.meta.file_hashes[relative_path] = content_h
        self.meta.chunk_counts[relative_path] = len(chunks)
        self.meta.save(self.index_dir / "index_meta.json")

        return len(chunks)

    async def remove_file(self, relative_path: str) -> None:
        """Remove a file from the index.

        Args:
            relative_path: Relative path to the file.
        """
        removed = self.store.remove_by_file(relative_path)
        self.meta.file_hashes.pop(relative_path, None)
        self.meta.chunk_counts.pop(relative_path, None)
        self.meta.save(self.index_dir / "index_meta.json")
        if removed:
            logger.info(f"Removed {removed} chunks for {relative_path}")

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

        # Get more results than needed so we can filter
        fetch_n = max_results * 3 if file_types else max_results
        raw_results = self.store.search(query_embedding, top_n=fetch_n)

        results: list[SearchResult] = []
        for r in raw_results:
            fp = r.get("file_path", "")
            if file_types:
                if not any(fp.endswith(ext) for ext in file_types):
                    continue

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

        return results

    async def reindex(self) -> int:
        """Full reindex of all content files.

        Uses the FileSystem instance (if provided) to respect
        STASH_CONTENT_PATHS filtering, otherwise falls back to
        discovering all files under content_dir.

        Returns:
            Total number of chunks indexed.
        """
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
    def indexed_files(self) -> int:
        """Number of indexed files."""
        return len(self.meta.file_hashes)

    @property
    def indexed_chunks(self) -> int:
        """Number of indexed chunks."""
        return self.store.count
