"""Tests for semantic search module."""

import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from stash_mcp.search import (
    BM25Store,
    IndexMeta,
    SearchEngine,
    SearchResult,
    VectorStore,
    _chunk_text,
    _chunk_text_sliding_window,
    _chunk_text_sliding_window_with_offsets,
    _content_hash,
    _even_split_params,
    _heading_breadcrumb,
    _heading_breadcrumbs,
    _normalize_path,
    _rrf_fuse,
)

# --- Mock embedding function (deterministic, no API calls) ---


async def mock_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic mock embedding: keyword-based 16-dim vectors.

    Uses a simple keyword-counting approach to produce somewhat meaningful
    embeddings for testing, ensuring related texts produce similar vectors.
    """
    keywords = [
        "auth", "oauth", "flow", "meeting", "notes",
        "config", "database", "test", "search", "content",
        "section", "project", "file", "data", "code", "doc",
    ]
    embeddings = []
    for text in texts:
        text_lower = text.lower()
        vec = []
        for kw in keywords:
            count = text_lower.count(kw)
            vec.append(float(count))
        # Add a small constant to avoid zero vectors
        vec[0] += 0.1
        embeddings.append(vec)
    return embeddings


# --- VectorStore tests ---


class TestVectorStore:

    def test_empty_store(self):
        """Test that a new store is empty."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            assert store.count == 0
            assert store.search([1.0, 0.0, 0.0]) == []

    def test_add_and_search(self):
        """Test adding vectors and searching."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            embeddings = [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ]
            metadata = [
                {"file_path": "a.md", "chunk_index": 0, "content": "about A"},
                {"file_path": "b.md", "chunk_index": 0, "content": "about B"},
                {"file_path": "c.md", "chunk_index": 0, "content": "about C"},
            ]
            store.add(embeddings, metadata)
            assert store.count == 3

            # Search for vector close to first embedding
            results = store.search([0.9, 0.1, 0.0], top_n=2)
            assert len(results) == 2
            assert results[0]["file_path"] == "a.md"
            assert "score" in results[0]

    def test_persistence(self):
        """Test that store persists across instances."""
        with TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "vectors.pkl"
            store = VectorStore(store_path)
            store.add(
                [[1.0, 0.0], [0.0, 1.0]],
                [
                    {"file_path": "a.md", "chunk_index": 0},
                    {"file_path": "b.md", "chunk_index": 0},
                ],
            )
            store.save()

            # Reload
            store2 = VectorStore(store_path)
            assert store2.count == 2
            results = store2.search([1.0, 0.0])
            assert len(results) > 0

    def test_remove_by_file(self):
        """Test removing vectors by file path."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            store.add(
                [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]],
                [
                    {"file_path": "a.md", "chunk_index": 0},
                    {"file_path": "a.md", "chunk_index": 1},
                    {"file_path": "b.md", "chunk_index": 0},
                ],
            )
            assert store.count == 3

            removed = store.remove_by_file("a.md")
            assert removed == 2
            assert store.count == 1

            results = store.search([1.0, 0.0])
            assert len(results) == 1
            assert results[0]["file_path"] == "b.md"

    def test_remove_by_file_nonexistent(self):
        """Test removing a file that doesn't exist returns 0."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            store.add(
                [[1.0, 0.0]],
                [{"file_path": "a.md", "chunk_index": 0}],
            )
            removed = store.remove_by_file("nonexistent.md")
            assert removed == 0
            assert store.count == 1

    def test_clear(self):
        """Test clearing the store."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            store.add(
                [[1.0, 0.0]],
                [{"file_path": "a.md", "chunk_index": 0}],
            )
            store.clear()
            assert store.count == 0

    def test_add_mismatched_lengths_raises(self):
        """Test that mismatched embeddings/metadata lengths raise ValueError."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            with pytest.raises(ValueError, match="same length"):
                store.add(
                    [[1.0, 0.0]],
                    [
                        {"file_path": "a.md"},
                        {"file_path": "b.md"},
                    ],
                )

    def test_search_zero_vector(self):
        """Test searching with a zero query vector returns empty."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            store.add(
                [[1.0, 0.0]],
                [{"file_path": "a.md", "chunk_index": 0}],
            )
            results = store.search([0.0, 0.0])
            assert results == []

    def test_remove_all_vectors(self):
        """Test removing all vectors leaves store empty."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            store.add(
                [[1.0, 0.0]],
                [{"file_path": "a.md", "chunk_index": 0}],
            )
            store.remove_by_file("a.md")
            assert store.count == 0
            assert store.search([1.0, 0.0]) == []


# --- Chunking tests ---


class TestChunking:

    def test_empty_text(self):
        """Test chunking empty text."""
        assert _chunk_text_sliding_window("") == []
        assert _chunk_text_sliding_window("   ") == []

    def test_short_text_single_chunk(self):
        """Test that text shorter than chunk_size returns a single chunk."""
        text = "Hello world"
        result = _chunk_text_sliding_window(text, chunk_size=1500)
        assert result == [text]

    def test_small_file_single_chunk(self):
        """Test that files smaller than chunk_size produce a single chunk naturally."""
        text = "A" * 100
        result = _chunk_text_sliding_window(text, chunk_size=1500)
        assert len(result) == 1
        assert result[0] == text

    def test_correct_number_of_chunks(self):
        """Test that the sliding window produces the correct number of chunks.

        With text=3000, chunk_size=1500, overlap=200 (step=1300):
        chunk 1: [0:1500], chunk 2: [1300:2800], chunk 3: [2600:3000]
        """
        text = "A" * 3000
        chunks = _chunk_text_sliding_window(text, chunk_size=1500, chunk_overlap=200)
        assert len(chunks) == 3

    def test_overlap_present(self):
        """Test that adjacent chunks share overlapping content."""
        # Place a distinctive string at the overlap boundary
        text = "X" * 1300 + "OVERLAP_MARKER" + "Y" * 1300
        chunks = _chunk_text_sliding_window(text, chunk_size=1500, chunk_overlap=200)
        # OVERLAP_MARKER should appear in at least two chunks
        overlap_count = sum(1 for c in chunks if "OVERLAP_MARKER" in c)
        assert overlap_count >= 2

    def test_chunks_cover_full_document(self):
        """Test that beginning and end of document appear in chunks."""
        # Use distinct start/end markers so we can verify full coverage
        text = "START " + "middle " * 250 + "END"
        chunks = _chunk_text_sliding_window(text, chunk_size=1000, chunk_overlap=100)
        assert len(chunks) > 1
        # The first chunk must contain the document start
        assert "START" in chunks[0]
        # The last chunk must contain the document end
        assert "END" in chunks[-1]

    def test_configurable_chunk_size(self):
        """Test that chunk_size parameter controls the chunk size."""
        text = "A" * 1000
        chunks = _chunk_text_sliding_window(text, chunk_size=400, chunk_overlap=50)
        assert len(chunks) > 1
        # Each chunk (except possibly the last) should be at most chunk_size chars
        for chunk in chunks[:-1]:
            assert len(chunk) <= 400

    def test_no_empty_chunks(self):
        """Test that no empty chunks are returned."""
        text = "A" * 3000
        chunks = _chunk_text_sliding_window(text, chunk_size=1500, chunk_overlap=200)
        assert all(c for c in chunks)

    def test_offsets_locate_each_chunk_in_the_source(self):
        """The offset variant reports where each chunk starts in the original text."""
        text = "START " + "middle " * 250 + "END"
        pairs = _chunk_text_sliding_window_with_offsets(
            text, chunk_size=1000, chunk_overlap=100
        )
        assert [c for _, c in pairs] == _chunk_text_sliding_window(text, 1000, 100)
        for offset, chunk in pairs:
            assert text[offset:offset + len(chunk)] == chunk

    def test_backward_compat_chunk_text(self):
        """Test that the legacy _chunk_text function still works."""
        assert _chunk_text("") == []
        assert _chunk_text("Hello world") == ["Hello world"]


# --- IndexMeta tests ---


class TestIndexMeta:

    def test_save_and_load(self):
        """Test saving and loading index metadata."""
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "meta.json"
            meta = IndexMeta(
                file_hashes={"a.md": "abc123"},
                chunk_counts={"a.md": 3},
                embedder_model="test-model",
            )
            meta.save(path)

            loaded = IndexMeta.load(path)
            assert loaded.file_hashes == {"a.md": "abc123"}
            assert loaded.chunk_counts == {"a.md": 3}
            assert loaded.embedder_model == "test-model"

    def test_load_missing_file(self):
        """Test loading from a missing file returns empty."""
        with TemporaryDirectory() as tmpdir:
            meta = IndexMeta.load(Path(tmpdir) / "nonexistent_meta.json")
            assert meta.file_hashes == {}
            assert meta.chunk_counts == {}


# --- Content hash tests ---


class TestContentHash:

    def test_deterministic(self):
        """Test that hash is deterministic."""
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_content(self):
        """Test that different content produces different hashes."""
        assert _content_hash("hello") != _content_hash("world")


# --- SearchEngine tests ---


class TestSearchEngine:

    @pytest.fixture
    def engine_dirs(self):
        """Create temporary content and index directories."""
        with TemporaryDirectory() as content_dir:
            with TemporaryDirectory() as index_dir:
                yield Path(content_dir), Path(index_dir)

    @pytest.fixture
    def engine(self, engine_dirs):
        """Create a SearchEngine with mock embeddings."""
        content_dir, index_dir = engine_dirs
        # Create sample content
        (content_dir / "docs").mkdir()
        (content_dir / "docs" / "auth.md").write_text(
            "# Authentication\n\nThe OAuth2 flow begins with a redirect."
        )
        (content_dir / "notes.md").write_text(
            "# Meeting Notes\n\nDiscussed project timeline and milestones."
        )
        (content_dir / "config.py").write_text(
            "# Configuration\nDB_HOST = 'localhost'\nDB_PORT = 5432\n"
        )
        return SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
        )

    async def test_build_index(self, engine):
        """Test building the index."""
        total = await engine.build_index([
            "docs/auth.md", "notes.md", "config.py"
        ])
        assert total > 0
        assert engine.ready
        assert engine.indexed_files == 3

    async def test_search_returns_results(self, engine):
        """Test that search returns relevant results."""
        await engine.build_index(["docs/auth.md", "notes.md", "config.py"])
        results = await engine.search("authentication")
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)
        assert all(r.score > 0 for r in results)

    async def test_search_empty_index(self, engine):
        """Test searching an empty index."""
        results = await engine.search("anything")
        assert results == []

    async def test_search_max_results(self, engine):
        """Test max_results limits output."""
        await engine.build_index(["docs/auth.md", "notes.md", "config.py"])
        results = await engine.search("anything", max_results=1)
        assert len(results) <= 1

    async def test_search_file_type_filter(self, engine):
        """Test file type filtering."""
        await engine.build_index(["docs/auth.md", "notes.md", "config.py"])
        results = await engine.search("anything", file_types=[".py"])
        for r in results:
            assert r.file_path.endswith(".py")

    async def test_index_file(self, engine):
        """Test indexing a single file."""
        chunks = await engine.index_file("docs/auth.md")
        assert chunks > 0
        assert engine.indexed_files == 1

    async def test_remove_file(self, engine):
        """Test removing a file from the index."""
        await engine.index_file("docs/auth.md")
        await engine.remove_file("docs/auth.md")
        assert engine.indexed_files == 0
        assert engine.indexed_chunks == 0

    async def test_incremental_indexing_skips_unchanged(self, engine):
        """Test that unchanged files are skipped during re-indexing."""
        await engine.build_index(["docs/auth.md"])
        first_count = engine.indexed_chunks

        # Re-index - should skip the unchanged file
        total = await engine.build_index(["docs/auth.md"])
        assert total == first_count

    async def test_reindex(self, engine):
        """Test full reindex."""
        await engine.build_index(["docs/auth.md"])
        total = await engine.reindex()
        assert total > 0
        assert engine.indexed_files == 3  # All files in content dir

    async def test_index_nonexistent_file(self, engine):
        """Test indexing a nonexistent file."""
        chunks = await engine.index_file("nonexistent.md")
        assert chunks == 0

    async def test_persistence_across_engine_instances(self, engine_dirs):
        """Test that index persists across engine instances."""
        content_dir, index_dir = engine_dirs
        (content_dir / "test.md").write_text("# Test\n\nSome content here.")

        # Build index with first engine
        engine1 = SearchEngine(
            content_dir=content_dir, index_dir=index_dir, embed_fn=mock_embed,
        )
        await engine1.build_index(["test.md"])
        assert engine1.indexed_chunks > 0

        # Create new engine - should load persisted index
        engine2 = SearchEngine(
            content_dir=content_dir, index_dir=index_dir, embed_fn=mock_embed,
        )
        assert engine2.indexed_chunks > 0
        assert engine2.ready

    async def test_embed_query_uses_mock(self, engine):
        """Test that _embed_query delegates to the mock embed function."""
        result = await engine._embed_query("authentication")
        assert isinstance(result, list)
        assert len(result) == 16  # 16-dim vectors from mock_embed

    async def test_stale_index_cleared_on_model_change(self, engine_dirs):
        """Test that changing embedder model clears stale index for rebuild."""
        content_dir, index_dir = engine_dirs
        (content_dir / "test.md").write_text("# Test\n\nContent here.")

        # Build index with model A
        engine1 = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embedder_model="model-a", embed_fn=mock_embed,
        )
        await engine1.build_index(["test.md"])
        assert engine1.ready
        assert engine1.store.count > 0

        # Create engine with model B — stale index should be cleared
        engine2 = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embedder_model="model-b", embed_fn=mock_embed,
        )
        assert not engine2.ready
        assert engine2.store.count == 0
        assert engine2.meta.file_hashes == {}
        assert engine2.meta.embedder_model == ""

        # Search should return empty when not ready
        results = await engine2.search("anything")
        assert results == []

        # build_index should re-embed all files (no skipping due to stale hash)
        chunks = await engine2.build_index(["test.md"])
        assert chunks > 0
        assert engine2.ready
        assert engine2.store.count > 0

    async def test_indexing_flag_during_build(self, engine_dirs):
        """Test that indexing property is True during build_index."""
        content_dir, index_dir = engine_dirs
        (content_dir / "test.md").write_text("# Test\n\nContent here.")

        seen_indexing = []

        async def tracking_embed(texts):
            seen_indexing.append(engine.indexing)
            return await mock_embed(texts)

        engine = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embed_fn=tracking_embed,
        )
        assert not engine.indexing
        await engine.build_index(["test.md"])
        # Flag was True during embedding
        assert any(seen_indexing), "indexing should be True during build"
        # After build completes, indexing should be False
        assert not engine.indexing
        assert engine.ready

    async def test_reindex_with_filesystem_filtering(self, engine_dirs):
        """Test that reindex uses FileSystem when provided."""
        content_dir, index_dir = engine_dirs
        (content_dir / "included.md").write_text("# Included\n\nMD content.")
        (content_dir / "excluded.py").write_text("# Excluded\nprint('hello')\n")

        from stash_mcp.filesystem import FileSystem
        fs = FileSystem(content_dir, include_patterns=["*.md"])

        engine = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embed_fn=mock_embed, filesystem=fs,
        )
        total = await engine.reindex()
        assert total > 0
        # Only .md files should be indexed
        assert "included.md" in engine.meta.file_hashes
        assert "excluded.py" not in engine.meta.file_hashes

    async def test_search_result_fields(self, engine):
        """Test that search results contain all expected fields."""
        await engine.build_index(["docs/auth.md", "notes.md"])
        results = await engine.search("authentication OAuth flow")
        assert len(results) > 0
        r = results[0]
        assert isinstance(r.file_path, str)
        assert r.chunk_index >= 0
        assert isinstance(r.content, str)
        assert r.score > 0

    async def test_chunk_size_param(self, engine_dirs):
        """Test that chunk_size and chunk_overlap params are respected."""
        content_dir, index_dir = engine_dirs
        # Write a file larger than a small chunk_size
        (content_dir / "large.md").write_text("Word " * 400)  # ~2000 chars

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            chunk_size=500,
            chunk_overlap=50,
        )
        chunks = await engine.index_file("large.md")
        # With chunk_size=500, overlap=50, step=450, ~2000 chars => more than 1 chunk
        assert chunks > 1


# --- REST API search endpoint tests ---


class TestSearchAPI:

    @pytest.fixture
    def search_client(self):
        """Create a test client with search engine enabled."""
        import asyncio

        from fastapi.testclient import TestClient

        from stash_mcp.api import create_api
        from stash_mcp.filesystem import FileSystem

        with TemporaryDirectory() as content_dir:
            with TemporaryDirectory() as index_dir:
                fs = FileSystem(Path(content_dir))
                fs.write_file("docs/auth.md", "# Auth\n\nOAuth2 flow here.")
                fs.write_file("notes.md", "# Notes\n\nMeeting notes.")

                engine = SearchEngine(
                    content_dir=Path(content_dir),
                    index_dir=Path(index_dir),
                    embed_fn=mock_embed,
                )

                # Build index directly since reindex endpoint is now non-blocking
                asyncio.run(engine.build_index(["docs/auth.md", "notes.md"]))

                app = create_api(fs, search_engine=engine)
                client = TestClient(app)

                yield client

    def test_search_endpoint(self, search_client):
        """Test GET /api/search returns results."""
        response = search_client.get("/api/search", params={"q": "authentication"})
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "results" in data
        assert "total" in data

    def test_search_status_endpoint(self, search_client):
        """Test GET /api/search/status returns engine info."""
        response = search_client.get("/api/search/status")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["ready"] is True
        assert data["indexing"] is False
        assert "indexed_files" in data
        assert "indexed_chunks" in data

    def test_reindex_endpoint(self, search_client):
        """Test POST /api/search/reindex returns in_progress status."""
        response = search_client.post("/api/search/reindex")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["message"] == "Reindex started"

    def test_search_with_file_types(self, search_client):
        """Test search with file_types filter."""
        response = search_client.get(
            "/api/search",
            params={"q": "anything", "file_types": ".md"},
        )
        assert response.status_code == 200
        data = response.json()
        for result in data["results"]:
            assert result["file_path"].endswith(".md")


# --- API without search engine ---


class TestAPIWithoutSearch:

    def test_no_search_endpoints_when_disabled(self):
        """Test that search endpoints are not registered when engine is None."""
        from fastapi.testclient import TestClient

        from stash_mcp.api import create_api
        from stash_mcp.filesystem import FileSystem

        with TemporaryDirectory() as tmpdir:
            fs = FileSystem(Path(tmpdir))
            app = create_api(fs)  # No search_engine
            client = TestClient(app)

            response = client.get("/api/search", params={"q": "test"})
            assert response.status_code == 404

            response = client.get("/api/search/status")
            assert response.status_code == 404


# --- MCP search tool tests ---


class TestMCPSearchTool:

    async def test_search_tool_registered_when_engine_present(self):
        """Test that search_content tool is registered when engine is given."""
        from stash_mcp.filesystem import FileSystem
        from stash_mcp.mcp_server import create_mcp_server

        with TemporaryDirectory() as content_dir:
            with TemporaryDirectory() as index_dir:
                fs = FileSystem(Path(content_dir))
                engine = SearchEngine(
                    content_dir=Path(content_dir),
                    index_dir=Path(index_dir),
                    embed_fn=mock_embed,
                )
                mcp = create_mcp_server(fs, search_engine=engine)
                tools = await mcp.get_tools()
                assert "search_content" in tools

    async def test_search_tool_not_registered_without_engine(self):
        """Test that search_content tool is NOT registered without engine."""
        from stash_mcp.filesystem import FileSystem
        from stash_mcp.mcp_server import create_mcp_server

        with TemporaryDirectory() as content_dir:
            fs = FileSystem(Path(content_dir))
            mcp = create_mcp_server(fs)
            tools = await mcp.get_tools()
            assert "search_content" not in tools

    async def test_search_tool_returns_results(self):
        """Test search_content tool returns formatted results."""
        from unittest.mock import AsyncMock, MagicMock

        from fastmcp.server.context import Context, _current_context

        from stash_mcp.filesystem import FileSystem
        from stash_mcp.mcp_server import create_mcp_server

        with TemporaryDirectory() as content_dir:
            with TemporaryDirectory() as index_dir:
                fs = FileSystem(Path(content_dir))
                fs.write_file("test.md", "# Test\n\nSome searchable content.")

                engine = SearchEngine(
                    content_dir=Path(content_dir),
                    index_dir=Path(index_dir),
                    embed_fn=mock_embed,
                )
                await engine.build_index(["test.md"])

                mcp = create_mcp_server(fs, search_engine=engine)
                tool = await mcp.get_tool("search_content")

                # Set up mock context
                ctx = MagicMock(spec=Context)
                ctx.session = AsyncMock()
                token = _current_context.set(ctx)
                try:
                    result = await tool.run({"query": "searchable content"})
                    text = str(result.content)
                    assert "test.md" in text
                finally:
                    _current_context.reset(token)

    async def test_search_tool_empty_index(self):
        """Test search_content tool with empty index."""
        from unittest.mock import AsyncMock, MagicMock

        from fastmcp.server.context import Context, _current_context

        from stash_mcp.filesystem import FileSystem
        from stash_mcp.mcp_server import create_mcp_server

        with TemporaryDirectory() as content_dir:
            with TemporaryDirectory() as index_dir:
                fs = FileSystem(Path(content_dir))
                engine = SearchEngine(
                    content_dir=Path(content_dir),
                    index_dir=Path(index_dir),
                    embed_fn=mock_embed,
                )
                mcp = create_mcp_server(fs, search_engine=engine)
                tool = await mcp.get_tool("search_content")

                ctx = MagicMock(spec=Context)
                ctx.session = AsyncMock()
                token = _current_context.set(ctx)
                try:
                    result = await tool.run({"query": "anything"})
                    assert "No results found" in str(result.content)
                finally:
                    _current_context.reset(token)


# --- Startup index build via lifespan ---


class TestStartupIndexBuild:

    def test_lifespan_builds_index_for_preexisting_files(self, monkeypatch):
        """Test that create_app's lifespan builds the search index for files
        that already exist when the server starts.

        Previously this used @app.on_event('startup') which is silently
        ignored when a lifespan handler is set on the FastAPI app.
        """
        import asyncio

        from fastapi.testclient import TestClient

        with TemporaryDirectory() as content_dir, TemporaryDirectory() as index_dir:
            cd = Path(content_dir)
            idx = Path(index_dir)

            # Pre-populate content
            (cd / "docs").mkdir()
            (cd / "docs" / "auth.md").write_text(
                "# Authentication\n\nThe OAuth2 flow begins."
            )
            (cd / "notes.md").write_text(
                "# Meeting Notes\n\nDiscussed project timeline."
            )

            monkeypatch.setattr("stash_mcp.config.Config.CONTENT_DIR", cd)
            monkeypatch.setattr("stash_mcp.config.Config.SEARCH_ENABLED", True)
            monkeypatch.setattr("stash_mcp.config.Config.SEARCH_INDEX_DIR", idx)
            monkeypatch.setattr("stash_mcp.config.Config.CONTENT_PATHS", None)

            # Patch _create_search_engine to use mock_embed
            from stash_mcp import main as main_mod

            _original = main_mod._create_search_engine

            def _patched():
                engine = SearchEngine(
                    content_dir=cd,
                    index_dir=idx,
                    embed_fn=mock_embed,
                )
                return engine

            monkeypatch.setattr(main_mod, "_create_search_engine", _patched)

            from stash_mcp.main import create_app

            app = create_app()

            # TestClient triggers the lifespan (startup + shutdown)
            with TestClient(app) as client:
                # Poll for background index build to complete
                import time
                for _ in range(50):
                    resp = client.get("/api/search/status")
                    data = resp.json()
                    if resp.status_code == 200 and data.get("ready") is True:
                        break
                    time.sleep(0.1)

                # Verify search status shows indexed files
                resp = client.get("/api/search/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["ready"] is True
                assert data["indexed_files"] == 2

                # Verify search returns results
                resp = client.get("/api/search", params={"q": "authentication"})
                assert resp.status_code == 200
                data = resp.json()
                assert data["total"] > 0


class TestSearchConfig:

    def test_search_disabled_by_default(self):
        """Test that search is disabled by default."""
        from stash_mcp.config import Config

        assert Config.SEARCH_ENABLED is False

    def test_search_config_defaults(self):
        """Test search config default values."""
        from stash_mcp.config import Config

        assert Config.SEARCH_INDEX_DIR == Path("/data/.stash-index")
        # Default local backend is ONNX Runtime (fastembed), not torch
        assert Config.SEARCH_EMBEDDER_MODEL == "onnx:BAAI/bge-small-en-v1.5"
        assert Config.CONTEXTUAL_RETRIEVAL is False
        assert Config.CONTEXTUAL_MODEL == "claude-haiku-4-5-20251001"
        assert Config.SEARCH_CHUNK_SIZE == 1000
        assert Config.SEARCH_CHUNK_OVERLAP == 100
        # Breadcrumbs join the embedded text; small stashes should opt out
        assert Config.SEARCH_HEADING_CONTEXT is True

    @pytest.mark.parametrize("module_name", ["stash_mcp.main", "stash_mcp.server"])
    def test_entrypoints_pass_search_settings_from_config(
        self, module_name, monkeypatch, tmp_path
    ):
        """Both entry points must forward the search settings they own."""
        import importlib

        module = importlib.import_module(module_name)
        from stash_mcp.config import Config

        captured = {}

        class FakeEngine:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self._filesystem = None

        monkeypatch.setattr("stash_mcp.search.SearchEngine", FakeEngine)
        monkeypatch.setattr(Config, "SEARCH_ENABLED", True)
        monkeypatch.setattr(Config, "SEARCH_EMBEDDER_MODEL", "onnx:test-model")
        monkeypatch.setattr(Config, "MODEL_CACHE_DIR", tmp_path / "models")
        monkeypatch.setattr(Config, "SEARCH_ONNX_THREADS", 3)
        monkeypatch.setattr(Config, "SEARCH_QUERY_PREFIX", "q: ")
        monkeypatch.setattr(Config, "SEARCH_DOCUMENT_PREFIX", "d: ")
        monkeypatch.setattr(Config, "SEARCH_HEADING_CONTEXT", False)
        monkeypatch.setattr(Config, "SEARCH_HYBRID_ENABLED", True)
        monkeypatch.setattr(Config, "SEARCH_RERANK_ENABLED", True)
        monkeypatch.setattr(Config, "SEARCH_RERANK_MODEL", "test-reranker")
        monkeypatch.setattr(Config, "SEARCH_RERANK_CANDIDATES", 7)
        monkeypatch.setattr(Config, "SEARCH_RERANK_MARGIN", 0.25)

        create = module._create_search_engine
        engine = create(None) if module_name == "stash_mcp.server" else create()

        assert engine is not None
        assert captured["embedder_model"] == "onnx:test-model"
        assert captured["model_cache_dir"] == tmp_path / "models"
        assert captured["onnx_threads"] == 3
        assert captured["query_prefix"] == "q: "
        assert captured["document_prefix"] == "d: "
        assert captured["heading_context"] is False
        assert captured["hybrid_enabled"] is True
        assert captured["rerank_enabled"] is True
        assert captured["rerank_model"] == "test-reranker"
        assert captured["rerank_candidates"] == 7
        assert captured["rerank_margin"] == 0.25

    def test_hybrid_retrieval_on_by_default_when_bm25s_is_installed(self):
        """BM25 catches the exact-token queries dense retrieval is worst at."""
        import importlib.util

        from stash_mcp.config import Config

        expected = importlib.util.find_spec("bm25s") is not None
        assert Config.SEARCH_HYBRID_ENABLED is expected

    def test_model_cache_dir_default(self):
        """Test that MODEL_CACHE_DIR defaults to /data/models."""
        from stash_mcp.config import Config

        assert Config.MODEL_CACHE_DIR == Path("/data/models")


class _StubBlameLine:
    """Minimal stand-in for git_backend.blame() output."""

    def __init__(self, line_number=1, author="a@example.com", summary="commit"):
        from datetime import UTC, datetime

        self.line_number = line_number
        self.author = author
        self.summary = summary
        self.timestamp = datetime(2026, 1, 1, tzinfo=UTC)


class _StubGitBackend:
    """Reports the same age for every file, so recency is a constant."""

    def blame(self, path):
        return [_StubBlameLine()]


# --- BM25 indexes the breadcrumb as well as the chunk ---


class TestBM25Breadcrumbs:
    """The heading breadcrumb is kept out of the *dense* vector (it dilutes
    the chunk's wording) but belongs in the *lexical* index, where terms are
    matched independently — a file path is otherwise unsearchable by keyword.
    """

    CHUNKS = [
        {
            "file_path": "_reports/frogpilot-deviations-ui.md",
            "chunk_index": 0,
            "content": "A diff scoped to the interface alone is misleading.",
            "context": "_reports/frogpilot-deviations-ui.md > Feature inventory",
        },
        {
            "file_path": "primitives/cereal.md",
            "chunk_index": 0,
            "content": "The message bus schema and its publish subscribe client.",
            "context": "primitives/cereal.md > Purpose",
        },
    ]

    def test_path_words_become_searchable(self, tmp_path):
        store = BM25Store(tmp_path)
        store.rebuild(self.CHUNKS)
        # None of these words appear in the chunk body — only in the path
        hits = store.search("frogpilot deviations", top_n=5)
        assert hits
        assert hits[0][0] == "_reports/frogpilot-deviations-ui.md"

    def test_heading_words_become_searchable(self, tmp_path):
        store = BM25Store(tmp_path)
        store.rebuild(self.CHUNKS)
        hits = store.search("feature inventory", top_n=5)
        assert hits
        assert hits[0][0] == "_reports/frogpilot-deviations-ui.md"

    def test_body_matches_still_win_for_body_queries(self, tmp_path):
        store = BM25Store(tmp_path)
        store.rebuild(self.CHUNKS)
        hits = store.search("publish subscribe client", top_n=5)
        assert hits[0][0] == "primitives/cereal.md"

    def test_chunks_without_context_still_index(self, tmp_path):
        store = BM25Store(tmp_path)
        store.rebuild([{**c, "context": None} for c in self.CHUNKS])
        assert store.search("misleading", top_n=5)

    def test_index_built_by_an_older_corpus_version_is_discarded(self, tmp_path):
        store = BM25Store(tmp_path)
        store.rebuild(self.CHUNKS)
        store.save()
        assert BM25Store(tmp_path).count == 2

        meta_path = tmp_path / BM25Store.META_FILE
        meta_path.write_text(json.dumps({"corpus_version": 0}))

        # Reloading must not silently serve an index built from different text
        reloaded = BM25Store(tmp_path)
        assert reloaded.count == 0

    async def test_hybrid_search_can_find_a_document_by_its_filename(self, tmp_path):
        content_dir = tmp_path / "content"
        (content_dir / "_reports").mkdir(parents=True)
        (content_dir / "_reports" / "frogpilot-deviations-ui.md").write_text(
            "# Feature inventory\n\nA diff scoped to the interface alone misleads.\n"
        )
        (content_dir / "other.md").write_text("Unrelated prose about something else.\n")

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=mock_embed,
            hybrid_enabled=True,
        )
        await engine.build_index(["_reports/frogpilot-deviations-ui.md", "other.md"])

        results = await engine.search("frogpilot deviations", max_results=2)
        assert results[0].file_path == "_reports/frogpilot-deviations-ui.md"


# --- Cross-encoder reranking ---


class TestReranking:
    """A cross-encoder reads query and chunk together, so it can reorder the
    retrieved candidates far more accurately than vector similarity."""

    class SpyReranker:
        """Scores by how many query words appear in the document."""

        def __init__(self):
            self.calls: list[tuple[str, list[str]]] = []

        async def rerank(self, query, documents):
            documents = list(documents)
            self.calls.append((query, documents))
            terms = set(query.lower().split())
            return [
                float(sum(w in terms for w in doc.lower().split()))
                for doc in documents
            ]

    @staticmethod
    async def _engine(tmp_path, **kwargs):
        content_dir = tmp_path / "content"
        content_dir.mkdir(exist_ok=True)
        # mock_embed ranks by keyword counts; "auth.md" wins on vectors while
        # "notes.md" is the better literal answer for the test query.
        (content_dir / "auth.md").write_text("auth auth auth oauth oauth flow\n")
        (content_dir / "notes.md").write_text("auth rotation policy explained\n")
        (content_dir / "other.md").write_text("config database settings\n")
        kwargs.setdefault("heading_context", False)
        # Rerank unconditionally unless a test is specifically exercising the
        # confidence margin, so "what does the reranker do" stays deterministic.
        kwargs.setdefault("rerank_margin", 0.0)
        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=mock_embed,
            **kwargs,
        )
        await engine.build_index(["auth.md", "notes.md", "other.md"])
        return engine

    async def test_disabled_by_default(self, tmp_path):
        engine = await self._engine(tmp_path)
        assert engine.rerank_enabled is False
        results = await engine.search("auth", max_results=2)
        assert results  # unchanged behaviour

    async def test_reranker_reorders_results(self, tmp_path):
        spy = self.SpyReranker()
        engine = await self._engine(tmp_path, rerank_enabled=True, reranker=spy)
        results = await engine.search("rotation policy", max_results=3)
        assert results[0].file_path == "notes.md"
        assert spy.calls  # the reranker actually ran

    async def test_reranked_results_expose_the_cross_encoder_score(self, tmp_path):
        spy = self.SpyReranker()
        engine = await self._engine(tmp_path, rerank_enabled=True, reranker=spy)
        results = await engine.search("rotation policy", max_results=1)
        assert results[0].score == 2.0

    async def test_rerank_sees_the_raw_chunk_without_the_breadcrumb(self, tmp_path):
        """The heading breadcrumb helps the embedding but hurts the
        cross-encoder (measured: MRR 0.938 chunk-only vs 0.868 with it)."""
        spy = self.SpyReranker()
        engine = await self._engine(
            tmp_path, rerank_enabled=True, reranker=spy, heading_context=True
        )
        await engine.reindex()
        assert any(m["context"] for m in engine.store._metadata)  # breadcrumbs exist

        await engine.search("rotation policy", max_results=2)
        _query, documents = spy.calls[-1]
        assert documents
        assert not any(doc.startswith("notes.md >") for doc in documents)
        assert any("rotation policy" in doc for doc in documents)

    async def test_candidate_cap_limits_the_work(self, tmp_path):
        spy = self.SpyReranker()
        engine = await self._engine(
            tmp_path, rerank_enabled=True, reranker=spy, rerank_candidates=2
        )
        await engine.search("auth", max_results=3)
        _query, documents = spy.calls[-1]
        assert len(documents) == 2

    async def test_file_type_filter_runs_before_reranking(self, tmp_path):
        spy = self.SpyReranker()
        engine = await self._engine(tmp_path, rerank_enabled=True, reranker=spy)
        (engine.content_dir / "code.py").write_text("auth rotation policy in code\n")
        await engine.index_file("code.py")
        await engine.search("rotation policy", max_results=3, file_types=[".py"])
        _query, documents = spy.calls[-1]
        assert len(documents) == 1  # only the .py chunk was worth scoring

    async def test_default_margin_skips_decided_result_sets(self, tmp_path):
        """Reranking defaults to running only on contested result sets."""
        engine = SearchEngine(
            content_dir=tmp_path / "content",
            index_dir=tmp_path / "index",
            embed_fn=mock_embed,
        )
        assert engine.rerank_margin == 0.1

    async def test_margin_zero_reranks_unconditionally(self, tmp_path):
        spy = self.SpyReranker()
        engine = await self._engine(
            tmp_path, rerank_enabled=True, reranker=spy, rerank_margin=0.0
        )
        engine._decide_rerank_scores = lambda results: [1.0, 0.1, 0.0]
        await engine.search("rotation policy", max_results=3)
        assert spy.calls

    async def test_a_confident_result_set_skips_the_cross_encoder(self, tmp_path):
        """When the top candidate is already well clear of the runner-up,
        reranking is unlikely to change the answer and not worth ~20 ms
        per candidate."""
        spy = self.SpyReranker()
        engine = await self._engine(
            tmp_path, rerank_enabled=True, reranker=spy, rerank_margin=0.2
        )
        engine._decide_rerank_scores = lambda results: [1.0, 0.5, 0.4]

        results = await engine.search("rotation policy", max_results=3)
        assert not spy.calls
        assert results  # still answered, from the retrieval ranking

    async def test_a_close_result_set_still_reranks(self, tmp_path):
        spy = self.SpyReranker()
        engine = await self._engine(
            tmp_path, rerank_enabled=True, reranker=spy, rerank_margin=0.2
        )
        engine._decide_rerank_scores = lambda results: [1.0, 0.95, 0.9]

        await engine.search("rotation policy", max_results=3)
        assert spy.calls

    async def test_margin_uses_the_two_best_scores_not_list_order(self, tmp_path):
        """MMR returns candidates in diversity order, so the list is not
        necessarily sorted by score."""
        spy = self.SpyReranker()
        engine = await self._engine(
            tmp_path, rerank_enabled=True, reranker=spy, rerank_margin=0.2
        )
        # Best two scores are 1.0 and 0.98 — close — but out of order
        engine._decide_rerank_scores = lambda results: [1.0, 0.3, 0.98]

        await engine.search("rotation policy", max_results=3)
        assert spy.calls

    async def test_reranker_failure_falls_back_to_retrieval_order(
        self, tmp_path, caplog
    ):
        class Broken:
            async def rerank(self, query, documents):
                raise RuntimeError("model download failed")

        engine = await self._engine(tmp_path, rerank_enabled=True, reranker=Broken())
        with caplog.at_level("WARNING", logger="stash_mcp.search"):
            results = await engine.search("auth", max_results=2)
        assert results  # search still answers
        assert any("rerank" in rec.message.lower() for rec in caplog.records)

    async def test_recency_blend_applies_after_reranking(self, tmp_path):
        """Recency must adjust the cross-encoder's ranking, not a stale one."""
        spy = self.SpyReranker()
        engine = await self._engine(tmp_path, rerank_enabled=True, reranker=spy)
        engine._git_backend = _StubGitBackend()  # every file equally old
        engine.recency_weight = 0.3

        results = await engine.search("rotation policy", max_results=3)
        # With recency identical for every file it must not change the order
        assert results[0].file_path == "notes.md"

    async def test_unreranked_tail_cannot_outrank_the_shortlist(self, tmp_path):
        """Only `rerank_candidates` results are rescored; the rest must stay
        below them rather than competing on an unrelated score scale."""
        spy = self.SpyReranker()
        engine = await self._engine(
            tmp_path, rerank_enabled=True, reranker=spy, rerank_candidates=1
        )
        engine._git_backend = _StubGitBackend()
        engine.recency_weight = 0.5

        results = await engine.search("rotation policy", max_results=3)
        _query, documents = spy.calls[-1]
        assert len(documents) == 1
        # The one reranked candidate stays first despite the recency blend
        assert results[0].content == documents[0]


# --- MMR must not discard the fused ranking ---


class TestMMRRelevanceSource:
    """MMR's relevance term defaults to cosine, but the hybrid path must be
    able to rank on the fused score instead — otherwise BM25 only widens the
    candidate pool and its ranking is thrown away."""

    @staticmethod
    def _store(tmp_path):
        store = VectorStore(tmp_path / "vectors.pkl")
        # c.md is the closest to the query vector, a.md the farthest
        store.add(
            [[1.0, 0.0], [0.9, 0.44], [0.99, 0.14]],
            [
                {"file_path": "a.md", "chunk_index": 0, "content": "a"},
                {"file_path": "b.md", "chunk_index": 0, "content": "b"},
                {"file_path": "c.md", "chunk_index": 0, "content": "c"},
            ],
        )
        return store

    def test_defaults_to_cosine_ordering(self, tmp_path):
        store = self._store(tmp_path)
        candidates = [
            {"file_path": "b.md", "chunk_index": 0, "score": 0.03},
            {"file_path": "a.md", "chunk_index": 0, "score": 0.01},
            {"file_path": "c.md", "chunk_index": 0, "score": 0.02},
        ]
        out = store.mmr_rerank([1.0, 0.0], candidates, top_n=3, mmr_lambda=1.0)
        assert [r["file_path"] for r in out] == ["a.md", "c.md", "b.md"]

    def test_supplied_relevance_drives_the_ordering(self, tmp_path):
        store = self._store(tmp_path)
        # Fused (RRF-style) scores rank b.md first even though a.md is the
        # closest vector — the lexical side found something.
        candidates = [
            {"file_path": "b.md", "chunk_index": 0, "score": 0.033},
            {"file_path": "a.md", "chunk_index": 0, "score": 0.016},
            {"file_path": "c.md", "chunk_index": 0, "score": 0.024},
        ]
        out = store.mmr_rerank(
            [1.0, 0.0],
            candidates,
            top_n=3,
            mmr_lambda=1.0,
            relevance=[c["score"] for c in candidates],
        )
        assert [r["file_path"] for r in out] == ["b.md", "c.md", "a.md"]

    def test_relevance_is_normalised_before_the_diversity_term(self, tmp_path):
        """Raw RRF scores (~0.02) would be swamped by the cosine diversity
        term; normalising to [0, 1] keeps the trade-off meaningful."""
        store = self._store(tmp_path)
        candidates = [
            {"file_path": "b.md", "chunk_index": 0, "score": 0.033},
            {"file_path": "a.md", "chunk_index": 0, "score": 0.016},
            {"file_path": "c.md", "chunk_index": 0, "score": 0.024},
        ]
        out = store.mmr_rerank(
            [1.0, 0.0], candidates, top_n=3, mmr_lambda=0.7,
            relevance=[c["score"] for c in candidates], max_per_file=None,
        )
        # Top hit is still the fused winner, not whatever is most "diverse"
        assert out[0]["file_path"] == "b.md"
        # Scores stay on the interpretable cosine scale for display
        assert all(0.0 <= r["score"] <= 1.0 for r in out)

    async def test_hybrid_search_ranks_on_the_fused_score(self, tmp_path):
        """End-to-end: a lexical-only match must be able to win the top slot.

        The embedder here puts a.md closest to the query, while the rare
        literal token exists only in b.md — exactly the case hybrid retrieval
        is for. Ranking on cosine after fusion would return a.md.
        """

        async def embed_by_topic(texts):
            # Models a synonym match: the query word ("primary") shares no
            # literal token with the document ("alpha"), so only the dense
            # side connects them.
            return [
                [1.0, 0.0]
                if ("alpha" in t.lower() or "primary" in t.lower())
                else [0.2, 0.98]
                for t in texts
            ]

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "a.md").write_text("alpha alpha alpha topical prose\n")
        (content_dir / "b.md").write_text(
            "STASH_GIT_SYNC_INTERVAL controls the pull cadence\n"
        )
        (content_dir / "c.md").write_text("beta gamma delta filler\n")

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=embed_by_topic,
            hybrid_enabled=True,
            heading_context=False,
        )
        await engine.build_index(["a.md", "b.md", "c.md"])
        assert engine.bm25_store.count == 3

        results = await engine.search("primary STASH_GIT_SYNC_INTERVAL", max_results=3)
        assert [r.file_path for r in results][0] == "b.md"
        # a.md is still retrieved — fusion reorders, it does not exclude
        assert "a.md" in [r.file_path for r in results]
        # The reported score must agree with the order it was ranked in,
        # otherwise the top hit shows a lower number than the runner-up.
        assert [r.score for r in results] == sorted(
            (r.score for r in results), reverse=True
        )

    async def test_recency_blend_preserves_the_fused_winner(self, tmp_path):
        """The recency blend must not re-sort on a signal fusion discarded."""

        async def embed_by_topic(texts):
            return [
                [1.0, 0.0]
                if ("alpha" in t.lower() or "primary" in t.lower())
                else [0.2, 0.98]
                for t in texts
            ]

        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "a.md").write_text("alpha alpha alpha topical prose\n")
        (content_dir / "b.md").write_text(
            "STASH_GIT_SYNC_INTERVAL controls the pull cadence\n"
        )
        (content_dir / "c.md").write_text("beta gamma delta filler\n")

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=embed_by_topic,
            hybrid_enabled=True,
            heading_context=False,
            recency_weight=0.3,
            git_backend=_StubGitBackend(),  # same age everywhere
        )
        await engine.build_index(["a.md", "b.md", "c.md"])
        results = await engine.search("primary STASH_GIT_SYNC_INTERVAL", max_results=3)
        assert results[0].file_path == "b.md"


# --- Index fingerprint ---


class TestIndexFingerprint:
    """Every setting that changes the stored vectors must invalidate the index,
    not just the model string."""

    @staticmethod
    def _build(tmp_path, **kwargs):
        content_dir = tmp_path / "content"
        content_dir.mkdir(exist_ok=True)
        (content_dir / "a.md").write_text("# Title\n\nSome authentication content.\n")
        return SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=mock_embed,
            **kwargs,
        )

    @pytest.mark.parametrize(
        "changed",
        [
            {"embedder_model": "model-b"},
            {"chunk_size": 500},
            {"chunk_overlap": 250},
            {"heading_context": False},
            {"document_prefix": "passage: "},
            {"contextual_retrieval": True, "anthropic_api_key": "k"},
        ],
    )
    async def test_changing_a_vector_affecting_setting_rebuilds(
        self, tmp_path, changed
    ):
        base = {"embedder_model": "model-a", "chunk_size": 1000, "chunk_overlap": 100}
        engine = self._build(tmp_path, **base)
        await engine.build_index(["a.md"])
        assert engine.store.count > 0

        engine2 = self._build(tmp_path, **{**base, **changed})
        assert engine2.store.count == 0
        assert engine2.meta.file_hashes == {}

    @pytest.mark.parametrize(
        "unchanged",
        [
            {"max_per_file": 5},
            {"mmr_lambda": 0.2},
            {"recency_weight": 0.5},
            {"candidate_pool_multiplier": 3},
        ],
    )
    async def test_retrieval_only_settings_keep_the_index(self, tmp_path, unchanged):
        base = {"embedder_model": "model-a"}
        engine = self._build(tmp_path, **base)
        await engine.build_index(["a.md"])
        before = engine.store.count

        engine2 = self._build(tmp_path, **{**base, **unchanged})
        assert engine2.store.count == before
        assert engine2.ready

    async def test_status_still_reports_the_model_string(self, tmp_path):
        engine = self._build(tmp_path, embedder_model="model-a")
        await engine.build_index(["a.md"])
        reloaded = IndexMeta.load(tmp_path / "index" / "index_meta.json")
        assert reloaded.embedder_model == "model-a"
        assert reloaded.embedder_fingerprint.startswith("model-a|")

    async def test_index_from_before_fingerprints_is_rebuilt(self, tmp_path):
        """An index written by an older version predates heading breadcrumbs
        and overflow splitting, so its vectors no longer match what we would
        produce — rebuild rather than mix two encodings in one index."""
        engine = self._build(tmp_path, embedder_model="model-a")
        await engine.build_index(["a.md"])
        meta_path = tmp_path / "index" / "index_meta.json"
        data = json.loads(meta_path.read_text())
        del data["embedder_fingerprint"]
        meta_path.write_text(json.dumps(data))

        engine2 = self._build(tmp_path, embedder_model="model-a")
        assert engine2.store.count == 0
        assert engine2.meta.file_hashes == {}

    async def test_matching_fingerprint_keeps_the_index(self, tmp_path):
        engine = self._build(tmp_path, embedder_model="model-a")
        await engine.build_index(["a.md"])
        before = engine.store.count

        engine2 = self._build(tmp_path, embedder_model="model-a")
        assert engine2.store.count == before
        assert engine2.ready


# --- Token-aware chunk splitting ---


class TestChunkFitting:
    """Chunks longer than the model's context window get re-split instead of
    having their tail silently dropped by the tokenizer."""

    @staticmethod
    def _engine(tmp_path, visible, **kwargs):
        """Engine whose embed_fn reports only *visible* chars per text."""

        class Backend:
            def __init__(self):
                self.embedded: list[str] = []

            async def __call__(self, texts):
                self.embedded.extend(texts)
                return await mock_embed(texts)

            async def measure_visible_chars(self, texts):
                return [min(len(t), visible) for t in texts]

        backend = Backend()
        content_dir = tmp_path / "content"
        content_dir.mkdir(exist_ok=True)
        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=backend,
            heading_context=False,
            **kwargs,
        )
        return engine, backend, content_dir

    async def test_oversized_chunk_is_split_not_truncated(self, tmp_path):
        engine, backend, content_dir = self._engine(
            tmp_path, visible=100, chunk_size=400, chunk_overlap=0
        )
        (content_dir / "a.md").write_text("word " * 160)  # 800 chars -> 2 windows

        chunks = await engine.index_file("a.md")

        # Every embedded text is within what the model can actually read
        assert all(len(t) <= 100 for t in backend.embedded)
        assert chunks == len(backend.embedded) > 2
        # Chunk indices stay sequential after splitting
        assert [m["chunk_index"] for m in engine.store._metadata] == list(range(chunks))
        # And the whole document is still covered
        joined = " ".join(m["content"] for m in engine.store._metadata)
        assert joined.count("word") >= 160

    async def test_chunks_that_fit_are_left_alone(self, tmp_path):
        engine, backend, content_dir = self._engine(
            tmp_path, visible=10_000, chunk_size=400, chunk_overlap=0
        )
        (content_dir / "a.md").write_text("word " * 160)

        chunks = await engine.index_file("a.md")
        assert chunks == 2
        assert [len(t) for t in backend.embedded] == [399, 399]

    async def test_backend_without_measurement_keeps_old_behaviour(self, tmp_path):
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "a.md").write_text("word " * 160)
        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=mock_embed,  # plain callable, no measure_visible_chars
            chunk_size=400,
            chunk_overlap=0,
            heading_context=False,
        )
        assert await engine.index_file("a.md") == 2

    async def test_split_accounts_for_the_heading_breadcrumb(self, tmp_path):
        engine, backend, content_dir = self._engine(
            tmp_path, visible=120, chunk_size=400, chunk_overlap=0
        )
        engine.heading_context = True
        (content_dir / "a.md").write_text("# Title\n\n" + "word " * 160)

        await engine.index_file("a.md")
        # The breadcrumb is part of the embedded text, so it counts against
        # the window too
        assert all(len(t) <= 120 for t in backend.embedded)

    @pytest.mark.parametrize(
        ("length", "budget", "overlap"),
        [(1000, 864, 100), (1000, 500, 100), (399, 100, 0), (1500, 700, 250), (10, 5, 9)],
    )
    def test_even_split_params_cover_the_text_without_runts(
        self, length, budget, overlap
    ):
        size, step_overlap = _even_split_params(length, budget, overlap)
        assert size <= budget
        pieces = _chunk_text_sliding_window("x" * length, size, step_overlap)
        assert all(len(p) <= budget for p in pieces)
        # No piece is dramatically smaller than the others
        assert min(len(p) for p in pieces) >= 0.5 * max(len(p) for p in pieces)

    async def test_pathological_backend_still_terminates(self, tmp_path):
        """A backend that always reports a tiny window must not loop forever."""
        engine, backend, content_dir = self._engine(
            tmp_path, visible=1, chunk_size=400, chunk_overlap=0
        )
        (content_dir / "a.md").write_text("word " * 160)
        chunks = await engine.index_file("a.md")
        assert chunks > 0  # gives up at a sane floor rather than hanging


# --- Heading breadcrumbs ---


class TestHeadingBreadcrumb:
    """Chunks carry a `path > H1 > H2` breadcrumb so the embedding knows
    where in the document the text came from."""

    DOC = (
        "# Authentication\n\n"
        "Intro paragraph.\n\n"
        "## OAuth2\n\n"
        "The flow begins with a redirect.\n\n"
        "### PKCE\n\n"
        "Public clients must use PKCE.\n\n"
        "## Sessions\n\n"
        "Cookies are HttpOnly.\n"
    )

    def test_offset_before_any_heading_uses_path_only(self):
        text = "Preamble text\n\n# Title\n\nBody"
        assert _heading_breadcrumb("docs/a.md", text, 0) == "docs/a.md"

    def test_nested_headings_are_joined(self):
        offset = self.DOC.index("Public clients")
        assert (
            _heading_breadcrumb("docs/auth.md", self.DOC, offset)
            == "docs/auth.md > Authentication > OAuth2 > PKCE"
        )

    def test_sibling_heading_replaces_deeper_levels(self):
        offset = self.DOC.index("Cookies are HttpOnly")
        assert (
            _heading_breadcrumb("docs/auth.md", self.DOC, offset)
            == "docs/auth.md > Authentication > Sessions"
        )

    def test_heading_on_the_chunk_boundary_is_included(self):
        offset = self.DOC.index("## OAuth2")
        assert (
            _heading_breadcrumb("docs/auth.md", self.DOC, offset)
            == "docs/auth.md > Authentication > OAuth2"
        )

    def test_hash_inside_fenced_code_is_not_a_heading(self):
        text = (
            "# Real Heading\n\n"
            "```bash\n"
            "# not a heading, a shell comment\n"
            "echo hi\n"
            "```\n\n"
            "Body text here.\n"
        )
        offset = text.index("Body text here")
        assert _heading_breadcrumb("a.md", text, offset) == "a.md > Real Heading"

    def test_non_markdown_file_gets_path_only(self):
        text = "# a python comment\nDB_HOST = 'localhost'\n"
        offset = text.index("DB_HOST")
        assert _heading_breadcrumb("config.py", text, offset) == "config.py"

    def test_breadcrumb_is_length_capped(self):
        text = "# " + "very long heading " * 40 + "\n\nbody\n"
        crumb = _heading_breadcrumb("a.md", text, text.index("body"))
        assert len(crumb) <= 200

    def test_batch_matches_single_lookups(self):
        offsets = [0, self.DOC.index("## OAuth2"), self.DOC.index("Cookies")]
        assert _heading_breadcrumbs("docs/auth.md", self.DOC, offsets) == [
            _heading_breadcrumb("docs/auth.md", self.DOC, o) for o in offsets
        ]

    def test_batch_is_a_single_pass_over_the_document(self):
        """One walk for all offsets, not one walk per chunk — a 1.7 MB file
        with ~2000 chunks took seconds under the per-chunk version."""
        section = "## Section {}\n\n" + ("filler text " * 60) + "\n\n"
        doc = "# Title\n\n" + "".join(section.format(i) for i in range(4000))
        offsets = list(range(0, len(doc), 500))

        start = time.perf_counter()
        crumbs = _heading_breadcrumbs("big.md", doc, offsets)
        elapsed = time.perf_counter() - start

        assert len(crumbs) == len(offsets)
        assert crumbs[-1].startswith("big.md > Title > Section ")
        assert elapsed < 2.0, f"breadcrumbs took {elapsed:.1f}s for {len(offsets)} chunks"

    def test_batch_handles_unsorted_and_duplicate_offsets(self):
        offsets = [self.DOC.index("Cookies"), 0, self.DOC.index("Cookies")]
        crumbs = _heading_breadcrumbs("docs/auth.md", self.DOC, offsets)
        assert crumbs[0] == crumbs[2] == "docs/auth.md > Authentication > Sessions"
        assert crumbs[1] == "docs/auth.md > Authentication"

    def test_batch_with_no_offsets(self):
        assert _heading_breadcrumbs("a.md", self.DOC, []) == []


class TestHeadingContextInEngine:

    @pytest.fixture
    def content_dir(self, tmp_path):
        d = tmp_path / "content"
        (d / "docs").mkdir(parents=True)
        # Long enough (at chunk_size=200) that the second chunk starts inside
        # the OAuth2 section rather than at the document heading.
        (d / "docs" / "auth.md").write_text(
            "# Authentication\n\n"
            + "Intro paragraph about identity. " * 8
            + "\n\n## OAuth2\n\n"
            + "The flow begins with a redirect. " * 8
        )
        return d

    async def test_each_chunk_gets_its_own_section_breadcrumb(
        self, content_dir, tmp_path
    ):
        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=mock_embed,
            chunk_size=200,
            chunk_overlap=20,
        )
        await engine.index_file("docs/auth.md")
        contexts = [m["context"] for m in engine.store._metadata]

        # The first chunk starts at the document heading...
        assert contexts[0] == "docs/auth.md > Authentication"
        # ...and later chunks pick up the section they start in.
        assert "docs/auth.md > Authentication > OAuth2" in contexts
        assert engine.store._metadata[0]["content"].startswith("# Authentication")

    async def test_breadcrumb_is_embedded_by_default(self, content_dir, tmp_path):
        """Telling the embedding which document and section a chunk came from
        pays off in proportion to how many documents must be told apart."""
        embedded: list[str] = []

        async def spy_embed(texts):
            embedded.extend(texts)
            return await mock_embed(texts)

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=spy_embed,
        )
        await engine.index_file("docs/auth.md")

        assert engine.store._metadata[0]["context"] == "docs/auth.md > Authentication"
        assert embedded[0].startswith("docs/auth.md > Authentication\n\n")

    async def test_breadcrumb_can_be_kept_out_of_the_embedding(
        self, content_dir, tmp_path
    ):
        """Small collections do better without it — but it is still recorded,
        still returned with results, and still indexed lexically."""
        embedded: list[str] = []

        async def spy_embed(texts):
            embedded.extend(texts)
            return await mock_embed(texts)

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=spy_embed,
            heading_context=False,
        )
        await engine.index_file("docs/auth.md")

        assert engine.store._metadata[0]["context"] == "docs/auth.md > Authentication"
        assert embedded[0].startswith("# Authentication")

    async def test_contextual_retrieval_wins_over_breadcrumbs(
        self, content_dir, tmp_path, monkeypatch
    ):
        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embed_fn=mock_embed,
            contextual_retrieval=True,
            anthropic_api_key="test-key",
        )

        async def fake_contextualise(chunk, full_document):
            return "LLM-generated context"

        monkeypatch.setattr(engine, "_contextualise_chunk", fake_contextualise)
        await engine.index_file("docs/auth.md")
        assert engine.store._metadata[0]["context"] == "LLM-generated context"


# --- ONNX Runtime (fastembed) backend wiring ---


class TestOnnxBackendWiring:
    """SearchEngine picks the fastembed adapter for ``onnx:`` model strings."""

    ONNX_MODEL = "onnx:sentence-transformers/all-MiniLM-L6-v2"

    async def test_onnx_model_string_installs_fastembed_adapter(
        self, fake_fastembed, tmp_path
    ):
        from stash_mcp.embedders import FastEmbedAdapter

        engine = SearchEngine(
            content_dir=tmp_path / "content",
            index_dir=tmp_path / "index",
            embedder_model=self.ONNX_MODEL,
            model_cache_dir=tmp_path / "models",
        )
        assert isinstance(engine._embed_fn, FastEmbedAdapter)
        assert engine._embedder is None  # pydantic-ai is not involved
        assert engine._embed_fn.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        # Weights are cached in a fastembed subdir of the model cache dir
        assert engine._embed_fn.cache_dir == str(tmp_path / "models" / "fastembed")
        # Nothing is downloaded/loaded at construction time
        assert fake_fastembed.calls["init"] == []

    async def test_onnx_engine_indexes_and_searches_via_adapter(
        self, fake_fastembed, tmp_path
    ):
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "a.md").write_text("alpha")
        (content_dir / "b.md").write_text("beta text is longer")
        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=tmp_path / "index",
            embedder_model=self.ONNX_MODEL,
            model_cache_dir=tmp_path / "models",
        )
        total = await engine.build_index(["a.md", "b.md"])
        assert total == 2
        assert len(fake_fastembed.calls["init"]) == 1
        results = await engine.search("alpha", max_results=1)
        assert results and results[0].file_path == "a.md"

    async def test_custom_embed_fn_wins_over_onnx_model_string(self, fake_fastembed, tmp_path):
        engine = SearchEngine(
            content_dir=tmp_path / "content",
            index_dir=tmp_path / "index",
            embedder_model=self.ONNX_MODEL,
            embed_fn=mock_embed,
        )
        assert engine._embed_fn is mock_embed
        vec = await engine._embed_query("auth")
        assert len(vec) == 16

    def test_no_model_cache_dir_uses_fastembed_default(self, fake_fastembed, tmp_path):
        engine = SearchEngine(
            content_dir=tmp_path / "content",
            index_dir=tmp_path / "index",
            embedder_model=self.ONNX_MODEL,
        )
        assert engine._embed_fn.cache_dir is None

    def test_unknown_onnx_model_fails_at_construction(self, fake_fastembed, tmp_path):
        with pytest.raises(ValueError, match="not-a-model"):
            SearchEngine(
                content_dir=tmp_path / "content",
                index_dir=tmp_path / "index",
                embedder_model="onnx:nope/not-a-model",
            )

    def test_missing_fastembed_gives_install_hint(self, monkeypatch, tmp_path):
        import sys

        monkeypatch.setitem(sys.modules, "fastembed", None)
        with pytest.raises(RuntimeError, match=r"fastembed is required.*stash-mcp\[search\]"):
            SearchEngine(
                content_dir=tmp_path / "content",
                index_dir=tmp_path / "index",
                embedder_model=self.ONNX_MODEL,
            )

    def test_torch_model_string_without_pydantic_ai_points_at_search_torch(
        self, monkeypatch, tmp_path
    ):
        """The old default on the torch-free image explains how to get it back."""
        import sys

        monkeypatch.setitem(sys.modules, "pydantic_ai", None)
        with pytest.raises(RuntimeError) as exc_info:
            SearchEngine(
                content_dir=tmp_path / "content",
                index_dir=tmp_path / "index",
                embedder_model="sentence-transformers:all-MiniLM-L6-v2",
            )
        message = str(exc_info.value)
        assert "sentence-transformers:" in message
        assert "stash-mcp[search-torch]" in message
        assert "onnx:sentence-transformers/all-MiniLM-L6-v2" in message

    @pytest.mark.parametrize(
        "model", ["all-MiniLM-L6-v2", "notaprovider:some-model"],
    )
    def test_unknown_provider_does_not_guess_an_extra(
        self, monkeypatch, tmp_path, model
    ):
        """A dropped or unrecognised prefix must not be sold as an OpenAI problem."""
        import sys

        monkeypatch.setitem(sys.modules, "pydantic_ai", None)
        with pytest.raises(RuntimeError) as exc_info:
            SearchEngine(
                content_dir=tmp_path / "content",
                index_dir=tmp_path / "index",
                embedder_model=model,
            )
        message = str(exc_info.value)
        assert "search-openai" not in message.partition("handled by")[0]
        assert model in message
        assert "onnx:" in message

    async def test_invalid_model_string_does_not_wipe_existing_index(
        self, fake_fastembed, tmp_path
    ):
        """Backend validation must run before the model-changed index clear."""
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        (content_dir / "test.md").write_text("# Test\n\nContent here.")

        engine = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embedder_model="model-a", embed_fn=mock_embed,
        )
        await engine.build_index(["test.md"])
        assert engine.store.count > 0

        # A typo in the new model string must fail fast without touching disk
        with pytest.raises(ValueError, match="not-a-model"):
            SearchEngine(
                content_dir=content_dir, index_dir=index_dir,
                embedder_model="onnx:nope/not-a-model",
            )

        # Coming back with the original model finds the index intact
        engine_again = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embedder_model="model-a", embed_fn=mock_embed,
        )
        assert engine_again.store.count > 0
        assert engine_again.ready

    async def test_query_uses_the_adapter_query_path(self, fake_fastembed, tmp_path):
        """Queries must go through embed_query so query prefixes are applied."""
        engine = SearchEngine(
            content_dir=tmp_path / "content",
            index_dir=tmp_path / "index",
            embedder_model=self.ONNX_MODEL,
            query_prefix="query: ",
            document_prefix="passage: ",
        )
        assert engine._embed_fn.query_prefix == "query: "
        assert engine._embed_fn.document_prefix == "passage: "
        await engine._embed(["a document"])
        await engine._embed_query("a question")
        assert fake_fastembed.calls["embed"] == [
            ["passage: a document"],
            ["query: a question"],
        ]

    async def test_plain_embed_fn_without_embed_query_still_works(self, tmp_path):
        """A bare async callable (the documented embed_fn contract) is enough."""
        engine = SearchEngine(
            content_dir=tmp_path / "content",
            index_dir=tmp_path / "index",
            embed_fn=mock_embed,
        )
        assert len(await engine._embed_query("authentication")) == 16

    def test_onnx_threads_are_passed_to_adapter(self, fake_fastembed, tmp_path):
        engine = SearchEngine(
            content_dir=tmp_path / "content",
            index_dir=tmp_path / "index",
            embedder_model=self.ONNX_MODEL,
            onnx_threads=2,
        )
        assert engine._embed_fn.threads == 2

    async def test_switching_torch_to_onnx_model_string_clears_index(self, tmp_path):
        """Upgrading from the torch default to the ONNX default triggers a rebuild."""
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        (content_dir / "test.md").write_text("# Test\n\nContent here.")

        engine1 = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embedder_model="sentence-transformers:all-MiniLM-L6-v2", embed_fn=mock_embed,
        )
        await engine1.build_index(["test.md"])
        assert engine1.store.count > 0

        engine2 = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embedder_model=self.ONNX_MODEL, embed_fn=mock_embed,
        )
        assert engine2.store.count == 0
        assert engine2.meta.file_hashes == {}
        assert not engine2.ready
        chunks = await engine2.build_index(["test.md"])
        assert chunks > 0
        assert IndexMeta.load(index_dir / "index_meta.json").embedder_model == self.ONNX_MODEL

    async def test_incremental_index_stamps_embedder_model(self, tmp_path):
        """index_file() records the model string so a later model change is detected."""
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        (content_dir / "test.md").write_text("# Test\n\nContent here.")

        engine = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embedder_model="model-a", embed_fn=mock_embed,
        )
        await engine.index_file("test.md")
        assert IndexMeta.load(index_dir / "index_meta.json").embedder_model == "model-a"

        engine2 = SearchEngine(
            content_dir=content_dir, index_dir=index_dir,
            embedder_model="model-b", embed_fn=mock_embed,
        )
        assert engine2.store.count == 0


# --- Path normalization tests ---


class TestNormalizePath:

    def test_forward_slash_unchanged(self):
        """Test that a well-formed path is unchanged."""
        assert _normalize_path("docs/api.md") == "docs/api.md"

    def test_strips_leading_slash(self):
        """Test that a leading slash is stripped."""
        assert _normalize_path("/docs/api.md") == "docs/api.md"

    def test_strips_trailing_slash(self):
        """Test that a trailing slash is stripped."""
        assert _normalize_path("docs/api.md/") == "docs/api.md"

    def test_strips_both_slashes(self):
        """Test that leading and trailing slashes are both stripped."""
        assert _normalize_path("/docs/api.md/") == "docs/api.md"

    def test_normalizes_backslashes(self):
        """Test that backslashes are converted to forward slashes (Windows paths)."""
        assert _normalize_path("docs\\api.md") == "docs/api.md"

    def test_normalizes_backslashes_and_leading_slash(self):
        """Test backslash normalization combined with leading slash removal."""
        assert _normalize_path("\\docs\\api.md") == "docs/api.md"

    def test_empty_string(self):
        """Test that empty string stays empty."""
        assert _normalize_path("") == ""


# --- Search index integrity tests (delete/move) ---


class TestSearchIndexIntegrity:

    @pytest.fixture
    def engine_with_files(self):
        """Create a SearchEngine with pre-indexed files."""
        with TemporaryDirectory() as content_dir:
            with TemporaryDirectory() as index_dir:
                cd = Path(content_dir)
                (cd / "docs").mkdir()
                (cd / "docs" / "auth.md").write_text(
                    "# Authentication\n\nThe OAuth2 flow is used for authorization."
                )
                (cd / "notes.md").write_text(
                    "# Meeting Notes\n\nDiscussed project milestones and deliverables."
                )
                engine = SearchEngine(
                    content_dir=cd,
                    index_dir=Path(index_dir),
                    embed_fn=mock_embed,
                )
                yield engine, cd

    async def test_delete_file_removed_from_search(self, engine_with_files):
        """Test that deleted files no longer appear in search results."""
        engine, content_dir = engine_with_files
        await engine.build_index(["docs/auth.md", "notes.md"])
        assert engine.indexed_files == 2

        # Delete the file and remove from index
        (content_dir / "docs" / "auth.md").unlink()
        await engine.remove_file("docs/auth.md")

        assert engine.indexed_files == 1
        assert engine.indexed_chunks < engine.store.count or engine.indexed_chunks >= 0
        assert "docs/auth.md" not in engine.meta.file_hashes

        # Search should no longer return results for the deleted file
        results = await engine.search("OAuth2 authorization")
        file_paths = [r.file_path for r in results]
        assert "docs/auth.md" not in file_paths

    async def test_delete_file_with_leading_slash_normalization(self, engine_with_files):
        """Test that remove_file works even when path has a leading slash."""
        engine, content_dir = engine_with_files
        await engine.build_index(["docs/auth.md", "notes.md"])

        (content_dir / "docs" / "auth.md").unlink()
        # Pass path with leading slash (as might come from user input/API)
        await engine.remove_file("/docs/auth.md")

        assert "docs/auth.md" not in engine.meta.file_hashes
        results = await engine.search("OAuth2 authorization")
        file_paths = [r.file_path for r in results]
        assert "docs/auth.md" not in file_paths

    async def test_move_file_updates_index(self, engine_with_files):
        """Test that moved files: old path gone, new path searchable."""
        engine, content_dir = engine_with_files
        await engine.build_index(["docs/auth.md", "notes.md"])

        # Move the file on disk
        old_path = content_dir / "docs" / "auth.md"
        new_path = content_dir / "docs" / "auth-guide.md"
        old_path.rename(new_path)

        # Use the atomic move_file_index method
        await engine.move_file_index("docs/auth.md", "docs/auth-guide.md")

        # Old path should be gone
        assert "docs/auth.md" not in engine.meta.file_hashes
        # New path should be indexed
        assert "docs/auth-guide.md" in engine.meta.file_hashes

        # Search should return the new path, not the old
        results = await engine.search("OAuth2 authorization")
        file_paths = [r.file_path for r in results]
        assert "docs/auth.md" not in file_paths
        assert "docs/auth-guide.md" in file_paths

    async def test_move_file_with_path_normalization(self, engine_with_files):
        """Test move_file_index with paths that need normalization."""
        engine, content_dir = engine_with_files
        await engine.build_index(["docs/auth.md"])

        old_path = content_dir / "docs" / "auth.md"
        new_path = content_dir / "docs" / "auth-guide.md"
        old_path.rename(new_path)

        # Pass with leading slashes (as from user input)
        await engine.move_file_index("/docs/auth.md", "/docs/auth-guide.md")

        assert "docs/auth.md" not in engine.meta.file_hashes
        assert "docs/auth-guide.md" in engine.meta.file_hashes

    async def test_embedder_loaded_at_init(self):
        """Test that the embedder is None when embed_fn is provided (not lazily created)."""
        with TemporaryDirectory() as content_dir:
            with TemporaryDirectory() as index_dir:
                engine = SearchEngine(
                    content_dir=Path(content_dir),
                    index_dir=Path(index_dir),
                    embed_fn=mock_embed,
                )
                # With embed_fn, _embedder should be None (no model to load)
                assert engine._embedder is None

    async def test_path_normalization_in_vector_store(self):
        """Test that remove_by_file normalizes paths for correct matching."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            store.add(
                [[1.0, 0.0], [0.0, 1.0]],
                [
                    {"file_path": "docs/api.md", "chunk_index": 0},
                    {"file_path": "notes.md", "chunk_index": 0},
                ],
            )
            assert store.count == 2

            # Remove with leading slash - should still match "docs/api.md"
            removed = store.remove_by_file("/docs/api.md")
            assert removed == 1
            assert store.count == 1

            results = store.search([0.0, 1.0])
            assert results[0]["file_path"] == "notes.md"


# --- MMR + per-file cap tests ---


class TestVectorStoreMMR:
    """search_mmr() reranks the cosine pool for diversity + per-file cap."""

    def _store(self, tmpdir):
        store = VectorStore(Path(tmpdir) / "vectors.pkl")
        # vec_a and vec_b nearly identical, vec_c has a small positive
        # component on the query axis so it survives the >0 filter but
        # is far away from a/b in the orthogonal direction.
        store.add(
            [
                [1.0, 0.0, 0.0],
                [0.99, 0.1, 0.0],
                [0.1, 0.0, 1.0],
            ],
            [
                {"file_path": "a.md", "chunk_index": 0, "content": "A"},
                {"file_path": "b.md", "chunk_index": 0, "content": "B"},
                {"file_path": "c.md", "chunk_index": 0, "content": "C"},
            ],
        )
        return store

    def test_mmr_diversifies_vs_pure_cosine(self):
        """MMR with lambda<1 prefers the diverse vector over the redundant one."""
        with TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            cosine = store.search([1.0, 0.0, 0.0], top_n=2)
            assert [r["file_path"] for r in cosine] == ["a.md", "b.md"]

            mmr = store.search_mmr(
                [1.0, 0.0, 0.0], top_n=2, candidate_pool=3, mmr_lambda=0.3
            )
            assert [r["file_path"] for r in mmr] == ["a.md", "c.md"]

    def test_mmr_lambda_one_matches_cosine(self):
        """mmr_lambda=1.0 collapses to pure relevance ordering."""
        with TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            mmr = store.search_mmr(
                [1.0, 0.0, 0.0],
                top_n=3,
                candidate_pool=3,
                mmr_lambda=1.0,
                max_per_file=None,
            )
            assert [r["file_path"] for r in mmr] == ["a.md", "b.md", "c.md"]

    def test_mmr_enforces_max_per_file(self):
        """When all chunks come from one file, max_per_file caps the result."""
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            store.add(
                [
                    [1.0, 0.0, 0.0],
                    [0.95, 0.05, 0.0],
                    [0.9, 0.1, 0.0],
                ],
                [
                    {"file_path": "same.md", "chunk_index": i, "content": f"C{i}"}
                    for i in range(3)
                ],
            )
            mmr = store.search_mmr(
                [1.0, 0.0, 0.0],
                top_n=5,
                candidate_pool=10,
                mmr_lambda=1.0,
                max_per_file=2,
            )
            assert len(mmr) == 2
            assert all(r["file_path"] == "same.md" for r in mmr)

    def test_mmr_empty_store_returns_empty(self):
        with TemporaryDirectory() as tmpdir:
            store = VectorStore(Path(tmpdir) / "vectors.pkl")
            assert store.search_mmr([1.0, 0.0, 0.0], top_n=5) == []

    def test_mmr_zero_query_returns_empty(self):
        with TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            assert store.search_mmr([0.0, 0.0, 0.0], top_n=2) == []

    def test_mmr_rerank_seeds_by_cosine_not_input_order(self):
        """mmr_rerank's first pick must be the highest-cosine candidate,
        not whatever the caller put at index 0 of the candidate list.

        Regression guard for the hybrid path, where the input is
        RRF-ranked rather than similarity-ranked.
        """
        with TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            # Pass candidates in *reverse* similarity order (c, b, a).
            # If MMR seeded from input order it would pick c.md first;
            # the cosine-correct seed is a.md.
            candidates = [
                {"file_path": "c.md", "chunk_index": 0,
                 "content": "C", "score": 999.0},
                {"file_path": "b.md", "chunk_index": 0,
                 "content": "B", "score": 100.0},
                {"file_path": "a.md", "chunk_index": 0,
                 "content": "A", "score": 1.0},
            ]
            picked = store.mmr_rerank(
                [1.0, 0.0, 0.0],
                candidates,
                top_n=1,
                mmr_lambda=1.0,
                max_per_file=None,
            )
            assert picked[0]["file_path"] == "a.md"


# --- SearchEngine recency reranking tests ---


class TestSearchEngineRecency:
    """SearchEngine blends a recency boost into the final score when enabled."""

    @pytest.fixture
    def engine_with_recency(self, tmp_path):
        """Build a small engine with a fake git_backend serving controlled blame."""
        from datetime import datetime, timedelta, timezone
        from stash_mcp.git_backend import BlameLine

        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        index_dir.mkdir()
        (content_dir / "fresh.md").write_text("authentication content")
        (content_dir / "stale.md").write_text("authentication content")

        now = datetime.now(timezone.utc)

        class FakeGit:
            def blame(self, path):
                ts = now if path == "fresh.md" else now - timedelta(days=720)
                return [
                    BlameLine(
                        line_number=1,
                        commit_hash="abc",
                        author="dev",
                        timestamp=ts,
                        summary="msg",
                        content="authentication content",
                    )
                ]

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            git_backend=FakeGit(),
            mmr_enabled=False,
            recency_weight=0.0,
            recency_half_life_days=180.0,
        )
        return engine, now

    async def test_recency_off_preserves_semantic_order(self, engine_with_recency):
        """recency_weight=0 leaves ordering driven by semantic score alone."""
        engine, _ = engine_with_recency
        await engine.build_index(["fresh.md", "stale.md"])
        # Both files have identical content → identical embeddings; the
        # order is implementation-defined but blame must NOT swap them
        # when recency is disabled.
        results = await engine.search("authentication", max_results=2)
        scores = [r.score for r in results]
        # Scores equal because content is identical and recency is off.
        assert scores[0] == pytest.approx(scores[1])

    async def test_recency_on_boosts_fresh_over_stale(self, engine_with_recency):
        """With recency_weight>0 and equal semantic scores, fresh wins."""
        engine, _ = engine_with_recency
        engine.recency_weight = 0.5
        await engine.build_index(["fresh.md", "stale.md"])
        results = await engine.search("authentication", max_results=2)
        assert results[0].file_path == "fresh.md"
        assert results[0].score > results[1].score

    async def test_recency_neutral_for_unblamed_files(self, tmp_path):
        """Files the git_backend cannot blame fall back to neutral (0.5) recency."""
        from stash_mcp.git_backend import BlameLine

        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        index_dir.mkdir()
        (content_dir / "tracked.md").write_text("authentication content")
        (content_dir / "untracked.md").write_text("authentication content")

        class PartialGit:
            def blame(self, path):
                if path == "untracked.md":
                    return []
                from datetime import datetime, timedelta, timezone
                return [
                    BlameLine(
                        line_number=1,
                        commit_hash="abc",
                        author="dev",
                        # 5 half-lives old → boost ~0.03
                        timestamp=datetime.now(timezone.utc) - timedelta(days=900),
                        summary="msg",
                        content="authentication content",
                    )
                ]

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            git_backend=PartialGit(),
            mmr_enabled=False,
            recency_weight=0.5,
            recency_half_life_days=180.0,
        )
        await engine.build_index(["tracked.md", "untracked.md"])
        results = await engine.search("authentication", max_results=2)
        # Untracked file gets neutral 0.5 recency; tracked file gets a
        # near-zero recency (very old). Untracked should rank higher.
        order = [r.file_path for r in results]
        assert order[0] == "untracked.md"


# --- MMR config integration tests ---


class TestSearchEngineMMRConfig:
    """SearchEngine pipeline behaviour with mmr_enabled toggled."""

    async def test_mmr_caps_results_per_file(self, tmp_path):
        """A single file with many overlapping chunks is capped by max_per_file."""
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        index_dir.mkdir()
        # Generate a long file so it produces many overlapping chunks.
        body = "authentication " * 500
        (content_dir / "auth.md").write_text(body)
        (content_dir / "other.md").write_text("authentication once")

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            mmr_enabled=True,
            max_per_file=2,
            candidate_pool_multiplier=6,
        )
        await engine.build_index(["auth.md", "other.md"])
        results = await engine.search("authentication", max_results=5)
        auth_hits = [r for r in results if r.file_path == "auth.md"]
        assert len(auth_hits) <= 2

    async def test_mmr_disabled_skips_per_file_cap(self, tmp_path):
        """mmr_enabled=False matches the legacy pipeline (no per-file cap)."""
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        index_dir.mkdir()
        body = "authentication " * 500
        (content_dir / "auth.md").write_text(body)

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            mmr_enabled=False,
            max_per_file=2,
        )
        await engine.build_index(["auth.md"])
        results = await engine.search("authentication", max_results=5)
        # No cap when MMR is off — all results may come from the one file.
        assert all(r.file_path == "auth.md" for r in results)
        assert len(results) > 2


# --- BM25Store unit tests ---


class TestBM25Store:
    """BM25Store mirrors VectorStore shape and persists to disk."""

    def test_bm25_search_finds_literal_term(self, tmp_path):
        store = BM25Store(tmp_path / "bm25")
        store.rebuild([
            {"file_path": "a.md", "chunk_index": 0,
             "content": "the transaction manager handles rollback"},
            {"file_path": "b.md", "chunk_index": 0,
             "content": "search engine indexes embeddings nightly"},
        ])
        results = store.search("transaction", top_n=2)
        assert results
        assert results[0][0] == "a.md"

    def test_bm25_empty_query_returns_empty(self, tmp_path):
        store = BM25Store(tmp_path / "bm25")
        store.rebuild([
            {"file_path": "a.md", "chunk_index": 0, "content": "anything"},
        ])
        assert store.search("", top_n=5) == []

    def test_bm25_persists_across_instances(self, tmp_path):
        store_a = BM25Store(tmp_path / "bm25")
        store_a.rebuild([
            {"file_path": "a.md", "chunk_index": 0,
             "content": "authentication and oauth flows"},
        ])
        store_a.save()
        store_b = BM25Store(tmp_path / "bm25")
        assert store_b.count == 1
        assert store_b.search("authentication", top_n=1)

    def test_bm25_clear_wipes_disk(self, tmp_path):
        store = BM25Store(tmp_path / "bm25")
        store.rebuild([
            {"file_path": "a.md", "chunk_index": 0, "content": "alpha"},
        ])
        store.save()
        assert (tmp_path / "bm25" / BM25Store.IDS_FILE).exists()
        store.clear()
        assert not (tmp_path / "bm25" / BM25Store.IDS_FILE).exists()
        reloaded = BM25Store(tmp_path / "bm25")
        assert reloaded.count == 0

    def test_bm25_dirty_flag_resets_on_rebuild(self, tmp_path):
        store = BM25Store(tmp_path / "bm25")
        store.mark_dirty()
        assert store.dirty
        store.rebuild([
            {"file_path": "a.md", "chunk_index": 0, "content": "alpha"},
        ])
        assert not store.dirty


# --- RRF fusion tests ---


class TestRRFFuse:
    """_rrf_fuse combines dense and sparse rankings."""

    def test_rrf_disjoint_lists(self):
        dense = [{"file_path": "a.md", "chunk_index": 0, "content": "A"}]
        sparse = [("b.md", 0, 5.0)]
        fused = _rrf_fuse(dense, sparse, k=60)
        keys = [(r["file_path"], r["chunk_index"]) for r in fused]
        assert ("a.md", 0) in keys
        assert ("b.md", 0) in keys
        # Both at rank 0 in their lists → identical fused score
        assert fused[0]["score"] == pytest.approx(fused[1]["score"])

    def test_rrf_overlap_boosts_shared_item(self):
        """An item ranked in both lists outscores items in only one."""
        dense = [
            {"file_path": "shared.md", "chunk_index": 0, "content": "S"},
            {"file_path": "dense.md", "chunk_index": 0, "content": "D"},
        ]
        sparse = [
            ("shared.md", 0, 9.0),
            ("sparse.md", 0, 4.0),
        ]
        fused = _rrf_fuse(dense, sparse, k=60)
        # shared appears in both lists at rank 0 → should be #1
        assert fused[0]["file_path"] == "shared.md"
        # And it carries the dense metadata (content "S")
        assert fused[0].get("content") == "S"

    def test_rrf_preserves_dense_metadata_when_present(self):
        """When an item is in dense, RRF preserves the dense dict's keys."""
        dense = [{
            "file_path": "a.md",
            "chunk_index": 0,
            "content": "full text",
            "context": "section header",
        }]
        sparse = [("a.md", 0, 3.0)]
        fused = _rrf_fuse(dense, sparse, k=60)
        assert fused[0]["context"] == "section header"
        assert fused[0]["content"] == "full text"

    def test_rrf_sparse_only_returns_stub(self):
        """Sparse-only items get a minimal stub the caller must hydrate."""
        fused = _rrf_fuse([], [("only.md", 7, 2.0)], k=60)
        assert len(fused) == 1
        assert fused[0]["file_path"] == "only.md"
        assert fused[0]["chunk_index"] == 7
        # No 'content' key — caller is expected to look it up
        assert "content" not in fused[0]


# --- Hybrid SearchEngine integration tests ---


class TestHybridSearchEngine:
    """End-to-end hybrid search behavior."""

    @pytest.fixture
    def hybrid_engine(self, tmp_path):
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        index_dir.mkdir()
        (content_dir / "auth.md").write_text(
            "OAuth2 authentication flow and tokens"
        )
        (content_dir / "db.md").write_text(
            "Database transaction handling and rollback"
        )
        (content_dir / "search.md").write_text(
            "Search engine config STASH_SEARCH_CHUNK_SIZE"
        )
        return SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            hybrid_enabled=True,
            mmr_enabled=True,
        )

    async def test_hybrid_returns_results(self, hybrid_engine):
        engine = hybrid_engine
        await engine.build_index(["auth.md", "db.md", "search.md"])
        results = await engine.search("authentication", max_results=2)
        assert results
        assert all(isinstance(r, SearchResult) for r in results)

    async def test_hybrid_finds_literal_token_dense_misses(self, hybrid_engine):
        """A literal token only the BM25 side knows about still surfaces."""
        engine = hybrid_engine
        # mock_embed doesn't know "STASH_SEARCH_CHUNK_SIZE" — but BM25 does.
        await engine.build_index(["auth.md", "db.md", "search.md"])
        results = await engine.search(
            "STASH_SEARCH_CHUNK_SIZE", max_results=3
        )
        paths = [r.file_path for r in results]
        assert "search.md" in paths

    async def test_hybrid_disabled_is_dense_only(self, tmp_path):
        """hybrid_enabled=False bypasses BM25 entirely."""
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        index_dir.mkdir()
        (content_dir / "a.md").write_text("authentication content")
        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            hybrid_enabled=False,
        )
        await engine.build_index(["a.md"])
        # BM25 index should never have been built
        assert engine.bm25_store.count == 0
        results = await engine.search("authentication", max_results=1)
        assert results

    async def test_hybrid_dep_missing_at_init_raises(
        self, tmp_path, monkeypatch
    ):
        """Init fails fast when hybrid_enabled but bm25s import fails."""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "bm25s":
                raise ImportError("not installed")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(RuntimeError, match="bm25s is required"):
            SearchEngine(
                content_dir=tmp_path / "c",
                index_dir=tmp_path / "i",
                embed_fn=mock_embed,
                hybrid_enabled=True,
            )

    async def test_hybrid_lifecycle_remove_keeps_indexes_consistent(
        self, hybrid_engine
    ):
        """Removing a file drops it from both vector and BM25 indexes."""
        engine = hybrid_engine
        await engine.build_index(["auth.md", "db.md"])
        bm25_before = engine.bm25_store.count
        await engine.remove_file("auth.md")
        # Both indexes shrink — vector store directly, BM25 via rebuild
        assert engine.indexed_chunks < bm25_before
        assert engine.bm25_store.count == engine.indexed_chunks
        # BM25 should no longer return auth content
        sparse = engine.bm25_store.search("authentication", top_n=5)
        paths = [s[0] for s in sparse]
        assert "auth.md" not in paths

    async def test_hybrid_upgrade_path_rebuilds_bm25_from_vectors(
        self, tmp_path
    ):
        """Pre-existing vectors.pkl without BM25 → BM25 rebuilt on init."""
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        index_dir.mkdir()
        (content_dir / "a.md").write_text("authentication content")
        # First engine: hybrid OFF so BM25 is never built/saved.
        engine_legacy = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            hybrid_enabled=False,
        )
        await engine_legacy.build_index(["a.md"])
        assert engine_legacy.bm25_store.count == 0  # never built

        # Second engine: hybrid ON, no bm25 index on disk yet → rebuild.
        engine_hybrid = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embed_fn=mock_embed,
            hybrid_enabled=True,
        )
        assert engine_hybrid.bm25_store.count == engine_hybrid.indexed_chunks
        assert engine_hybrid.bm25_store.count > 0

    async def test_hybrid_embedder_change_clears_both_indexes(self, tmp_path):
        """Changing embedder_model wipes vector AND bm25 indexes."""
        content_dir = tmp_path / "content"
        index_dir = tmp_path / "index"
        content_dir.mkdir()
        index_dir.mkdir()
        (content_dir / "a.md").write_text("authentication content")

        engine = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embedder_model="model-A",
            embed_fn=mock_embed,
            hybrid_enabled=True,
        )
        await engine.build_index(["a.md"])
        assert engine.indexed_chunks > 0
        assert engine.bm25_store.count > 0

        # New engine with different model — both indexes should be cleared.
        engine2 = SearchEngine(
            content_dir=content_dir,
            index_dir=index_dir,
            embedder_model="model-B",
            embed_fn=mock_embed,
            hybrid_enabled=True,
        )
        assert engine2.indexed_chunks == 0
        assert engine2.bm25_store.count == 0
