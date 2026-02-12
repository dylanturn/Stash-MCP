"""Tests for semantic search module."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from stash_mcp.search import (
    IndexMeta,
    SearchEngine,
    SearchResult,
    VectorStore,
    _chunk_text,
    _content_hash,
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
        assert _chunk_text("") == []
        assert _chunk_text("   ") == []

    def test_short_text(self):
        """Test that short text returns a single chunk."""
        result = _chunk_text("Hello world")
        assert result == ["Hello world"]

    def test_markdown_heading_split(self):
        """Test splitting on markdown headings."""
        text = "# Section 1\nContent for section one.\n\n# Section 2\nContent for section two."
        chunks = _chunk_text(text, max_chunk_size=40)
        assert len(chunks) == 2
        assert "Section 1" in chunks[0]
        assert "Section 2" in chunks[1]

    def test_paragraph_split(self):
        """Test splitting on paragraph boundaries."""
        text = "Paragraph one. " * 20 + "\n\n" + "Paragraph two. " * 20
        chunks = _chunk_text(text, max_chunk_size=200)
        assert len(chunks) >= 2

    def test_preserves_content(self):
        """Test that chunking preserves all content."""
        text = "# Title\n\nParagraph 1\n\nParagraph 2\n\n# Section 2\n\nContent"
        chunks = _chunk_text(text, max_chunk_size=50)
        combined = " ".join(chunks)
        assert "Title" in combined
        assert "Paragraph 1" in combined
        assert "Section 2" in combined


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


# --- REST API search endpoint tests ---


class TestSearchAPI:

    @pytest.fixture
    def search_client(self):
        """Create a test client with search engine enabled."""
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

                app = create_api(fs, search_engine=engine)
                client = TestClient(app)

                # Build index synchronously via the reindex endpoint
                response = client.post("/api/search/reindex")
                assert response.status_code == 200

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
        """Test POST /api/search/reindex triggers reindex."""
        response = search_client.post("/api/search/reindex")
        assert response.status_code == 200
        data = response.json()
        assert "indexed_chunks" in data
        assert data["indexed_chunks"] > 0

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
                for _ in range(20):
                    resp = client.get("/api/search/status")
                    if resp.status_code == 200 and resp.json().get("indexed_files", 0) > 0:
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
        assert "sentence-transformers" in Config.SEARCH_EMBEDDER_MODEL
        assert Config.CONTEXTUAL_RETRIEVAL is False
        assert Config.CONTEXTUAL_MODEL == "claude-haiku-4-5-20251001"
