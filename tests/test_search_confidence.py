"""Search results must say how relevant they are in absolute terms.

``score`` is whatever the results were ordered by, and on the default hybrid
path that is normalised within the result set — the best hit scores 1.0 for
every query, including ones the store has nothing on. These tests cover the
absolute signal reported next to it (``similarity``), the noise floor it is
judged against, and the filters built on the two.
"""

import asyncio
import math
import statistics
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from stash_mcp.search import SearchEngine
from stash_mcp.search_probes import QUESTION_PROBES, TEXT_PROBES

TOPICS = ("quokka", "wombat", "axolotl")


def _vector(text: str) -> list[float]:
    """One axis per topic word, plus two weak axes every text has.

    Text naming no topic (every calibration probe) lands on the weak axes
    alone, so it is nearly orthogonal to any document that names one. The
    second weak axis varies with length so probes do not all coincide.
    """
    lower = text.lower()
    return [float(lower.count(t)) for t in TOPICS] + [0.3, (len(text) % 7) * 0.05]


async def topic_embed(texts: list[str]) -> list[list[float]]:
    return [_vector(t) for t in texts]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


DOCS = {
    "quokka.md": "quokka quokka quokka habitat notes\n",
    "wombat.md": "wombat wombat wombat burrow notes\n",
    "both.md": "quokka wombat comparison\n",
}


async def _engine(tmp_path, docs=DOCS, embed_fn=topic_embed, **kwargs):
    content_dir = tmp_path / "content"
    content_dir.mkdir(exist_ok=True)
    for name, text in docs.items():
        (content_dir / name).write_text(text)
    kwargs.setdefault("heading_context", False)
    engine = SearchEngine(
        content_dir=content_dir,
        index_dir=tmp_path / "index",
        embed_fn=embed_fn,
        **kwargs,
    )
    await engine.build_index(sorted(docs))
    return engine


RETRIEVAL_PATHS = [
    pytest.param({"hybrid_enabled": True, "mmr_enabled": True}, id="hybrid+mmr"),
    pytest.param({"hybrid_enabled": True, "mmr_enabled": False}, id="hybrid"),
    pytest.param({"hybrid_enabled": False, "mmr_enabled": True}, id="dense+mmr"),
    pytest.param({"hybrid_enabled": False, "mmr_enabled": False}, id="dense"),
]


class TestSimilarity:
    @pytest.mark.parametrize("config", RETRIEVAL_PATHS)
    async def test_similarity_is_the_query_to_chunk_cosine(self, tmp_path, config):
        engine = await _engine(tmp_path, **config)
        results = await engine.search("quokka", max_results=3)
        assert results[0].file_path == "quokka.md"
        for r in results:
            expected = _cosine(_vector("quokka"), _vector(DOCS[r.file_path].strip()))
            assert r.similarity == pytest.approx(expected, abs=1e-5)

    @pytest.mark.parametrize("config", RETRIEVAL_PATHS)
    async def test_an_unrelated_query_reports_low_similarity(self, tmp_path, config):
        """The regression: on the hybrid path the top ``score`` is 1.0 no
        matter what was asked, so it cannot show that nothing matched."""
        engine = await _engine(tmp_path, **config)
        results = await engine.search("axolotl", max_results=3)
        assert results  # nearest neighbours still come back
        assert all(r.similarity < 0.2 for r in results)

    async def test_keyword_only_hit_still_gets_a_similarity(self, tmp_path):
        """A chunk found by BM25 alone never passed through the dense search,
        so its cosine has to be looked up rather than carried along."""
        docs = {f"q{i}.md": "quokka " * (i + 2) + "\n" for i in range(7)}
        # Long enough in its own topic to sit last in the dense ranking, so
        # with a pool of three only the keyword index can surface it.
        docs["token.md"] = "wombat " * 9 + "STASH_RARE_TOKEN setting\n"
        engine = await _engine(
            tmp_path,
            docs=docs,
            hybrid_enabled=True,
            mmr_enabled=False,
            candidate_pool_multiplier=1,
        )
        results = await engine.search("axolotl STASH_RARE_TOKEN", max_results=3)
        hit = next(r for r in results if r.file_path == "token.md")
        expected = _cosine(
            _vector("axolotl STASH_RARE_TOKEN"), _vector(docs["token.md"].strip())
        )
        assert hit.similarity == pytest.approx(expected, abs=1e-5)

    async def test_reranking_replaces_score_but_not_similarity(self, tmp_path):
        class ConstantReranker:
            async def rerank(self, query, documents):
                return [-7.5 - i for i, _ in enumerate(documents)]

        engine = await _engine(
            tmp_path,
            rerank_enabled=True,
            rerank_margin=0.0,
            reranker=ConstantReranker(),
        )
        results = await engine.search("quokka", max_results=2)
        assert results[0].score == -7.5
        assert 0.0 < results[0].similarity <= 1.0


class TestMinSimilarity:
    async def test_drops_results_below_the_threshold(self, tmp_path):
        engine = await _engine(tmp_path, hybrid_enabled=True)
        results = await engine.search("quokka", max_results=3, min_similarity=0.9)
        assert [r.file_path for r in results] == ["quokka.md"]

    async def test_returns_nothing_when_nothing_clears_it(self, tmp_path):
        engine = await _engine(tmp_path, hybrid_enabled=True)
        assert await engine.search("axolotl", max_results=3, min_similarity=0.5) == []

    async def test_below_threshold_results_do_not_use_up_max_results(self, tmp_path):
        """Filtering happens before truncation: weak hits ranked first must
        not push the qualifying one out of a max_results=1 answer."""

        class PrefersWombat:
            async def rerank(self, query, documents):
                return [10.0 if "wombat" in d else 0.0 for d in documents]

        engine = await _engine(
            tmp_path,
            rerank_enabled=True,
            rerank_margin=0.0,
            reranker=PrefersWombat(),
        )
        unfiltered = await engine.search("quokka", max_results=1)
        assert unfiltered[0].file_path != "quokka.md"
        results = await engine.search("quokka", max_results=1, min_similarity=0.9)
        assert [r.file_path for r in results] == ["quokka.md"]


class TestNoiseFloor:
    async def test_is_a_robust_upper_bound_on_what_the_probes_score(self, tmp_path):
        """Median plus 1.75 robust standard deviations (1.4826 x MAD) of each
        probe's best match — median-based so that probes which happen to be
        on-topic for a store cannot drag the floor up."""
        engine = await _engine(tmp_path)
        doc_vectors = [_vector(text.strip()) for text in DOCS.values()]
        tops = sorted(
            max(_cosine(_vector(probe), d) for d in doc_vectors)
            for probe in QUESTION_PROBES
        )
        median = statistics.median(tops)
        mad = statistics.median(abs(t - median) for t in tops)
        assert mad > 0  # the fixture must actually exercise the spread term
        assert await engine.noise_floor("question") == pytest.approx(
            median + 1.75 * 1.4826 * mad, abs=1e-5
        )

    async def test_separates_a_covered_query_from_an_uncovered_one(self, tmp_path):
        engine = await _engine(tmp_path, hybrid_enabled=True)
        floor = await engine.noise_floor("question")
        covered = await engine.search("quokka", max_results=1)
        uncovered = await engine.search("axolotl", max_results=1)
        assert uncovered[0].similarity < floor < covered[0].similarity

    async def test_text_inputs_have_their_own_floor(self, tmp_path):
        seen: list[str] = []

        async def recording_embed(texts):
            seen.extend(texts)
            return await topic_embed(texts)

        engine = await _engine(tmp_path, embed_fn=recording_embed)
        seen.clear()
        await engine.noise_floor("text")
        assert set(seen) == set(TEXT_PROBES)

    async def test_unknown_kind_is_rejected(self, tmp_path):
        engine = await _engine(tmp_path)
        with pytest.raises(ValueError, match="question"):
            await engine.noise_floor("essay")

    async def test_is_none_for_an_empty_index(self, tmp_path):
        engine = SearchEngine(
            content_dir=tmp_path, index_dir=tmp_path / "index", embed_fn=topic_embed
        )
        assert await engine.noise_floor("question") is None

    async def test_probes_are_embedded_once_and_the_floor_tracks_the_corpus(
        self, tmp_path
    ):
        calls = 0

        async def counting_embed(texts):
            nonlocal calls
            calls += len(texts)
            return await topic_embed(texts)

        engine = await _engine(tmp_path, embed_fn=counting_embed)
        calls = 0
        before = await engine.noise_floor("question")
        assert calls == len(QUESTION_PROBES)
        assert await engine.noise_floor("question") == before
        assert calls == len(QUESTION_PROBES)

        # A document sitting on the probes' own axis raises what unrelated
        # input scores; the floor has to follow without re-embedding probes.
        (engine.content_dir / "generic.md").write_text("plain filler prose\n")
        await engine.index_file("generic.md")
        calls = 0
        after = await engine.noise_floor("question")
        assert after > before
        assert calls == 0

    async def test_overlapping_first_calls_embed_the_probes_once(self, tmp_path):
        """Several searches can arrive before the first has finished embedding
        the probes; on a remote embedder each duplicate set is paid for."""
        calls = 0

        async def yielding_embed(texts):
            nonlocal calls
            calls += len(texts)
            await asyncio.sleep(0)  # let the other callers run, as real I/O would
            return await topic_embed(texts)

        engine = await _engine(tmp_path, embed_fn=yielding_embed)
        calls = 0
        floors = await asyncio.gather(
            *(engine.noise_floor("question") for _ in range(4))
        )
        assert calls == len(QUESTION_PROBES)
        assert len(set(floors)) == 1

    async def test_a_failed_probe_embedding_is_retried_by_the_next_call(self, tmp_path):
        fail = False

        async def flaky_embed(texts):
            if fail:
                raise RuntimeError("rate limited")
            return await topic_embed(texts)

        engine = await _engine(tmp_path, embed_fn=flaky_embed)
        fail = True
        with pytest.raises(RuntimeError, match="rate limited"):
            await engine.noise_floor("question")
        fail = False
        assert await engine.noise_floor("question") is not None

    async def test_a_configured_floor_replaces_the_measured_one(self, tmp_path):
        """The escape hatch for a store the probes do not suit (a non-English
        corpus, or one that covers many of the probe subjects)."""
        calls = 0

        async def counting_embed(texts):
            nonlocal calls
            calls += len(texts)
            return await topic_embed(texts)

        engine = await _engine(
            tmp_path, embed_fn=counting_embed, noise_floor_question=0.42
        )
        measured = await _engine(tmp_path)
        calls = 0
        assert await engine.noise_floor("question") == 0.42
        assert calls == 0  # nothing to measure, so no probes are embedded
        # Each kind is overridden on its own; the other is still measured.
        assert await engine.noise_floor("text") == pytest.approx(
            await measured.noise_floor("text")
        )

    async def test_a_plain_search_does_not_embed_the_probes(self, tmp_path):
        calls = 0

        async def counting_embed(texts):
            nonlocal calls
            calls += len(texts)
            return await topic_embed(texts)

        engine = await _engine(tmp_path, embed_fn=counting_embed)
        calls = 0
        await engine.search("quokka", max_results=3)
        assert calls == 1


@pytest.fixture
def api_client():
    from fastapi.testclient import TestClient

    from stash_mcp.api import create_api
    from stash_mcp.filesystem import FileSystem

    with TemporaryDirectory() as content_dir, TemporaryDirectory() as index_dir:
        fs = FileSystem(Path(content_dir))
        for name, text in DOCS.items():
            fs.write_file(name, text)
        engine = SearchEngine(
            content_dir=Path(content_dir),
            index_dir=Path(index_dir),
            embed_fn=topic_embed,
            hybrid_enabled=True,
            heading_context=False,
        )
        asyncio.run(engine.build_index(sorted(DOCS)))
        client = TestClient(create_api(fs, search_engine=engine))
        client.engine = engine
        yield client


class TestSearchAPIConfidence:
    def test_results_carry_similarity_and_the_floor_they_are_judged_by(
        self, api_client
    ):
        data = api_client.get("/api/search", params={"q": "quokka"}).json()
        assert data["results"][0]["similarity"] > 0.9
        assert 0.0 < data["similarity_floor"] < 0.9
        assert data["results"][0]["above_floor"] is True

    def test_an_uncovered_query_is_marked_below_the_floor(self, api_client):
        data = api_client.get("/api/search", params={"q": "axolotl"}).json()
        assert data["results"]
        assert all(r["above_floor"] is False for r in data["results"])

    def test_relevant_only_returns_nothing_for_an_uncovered_query(self, api_client):
        data = api_client.get(
            "/api/search", params={"q": "axolotl", "relevant_only": "true"}
        ).json()
        assert data["results"] == []
        assert data["total"] == 0

    def test_relevant_only_keeps_what_clears_the_floor(self, api_client):
        data = api_client.get(
            "/api/search", params={"q": "quokka", "relevant_only": "true"}
        ).json()
        assert data["results"][0]["file_path"] == "quokka.md"
        assert all(r["above_floor"] for r in data["results"])

    def test_min_similarity_is_an_explicit_threshold(self, api_client):
        data = api_client.get(
            "/api/search", params={"q": "quokka", "min_similarity": 0.9}
        ).json()
        assert [r["file_path"] for r in data["results"]] == ["quokka.md"]

    def test_input_type_selects_the_floor(self, api_client):
        floors = {}
        for kind in ("question", "text"):
            data = api_client.get(
                "/api/search", params={"q": "quokka", "input_type": kind}
            ).json()
            assert data["input_type"] == kind
            floors[kind] = data["similarity_floor"]
            assert floors[kind] == pytest.approx(
                asyncio.run(api_client.engine.noise_floor(kind))
            )
        assert floors["question"] != floors["text"]

    def test_unknown_input_type_is_a_client_error(self, api_client):
        response = api_client.get(
            "/api/search", params={"q": "quokka", "input_type": "essay"}
        )
        assert response.status_code == 422


class TestMCPSearchToolConfidence:
    @staticmethod
    async def _run(query: str) -> str:
        from unittest.mock import AsyncMock, MagicMock

        from fastmcp.server.context import Context, _current_context

        from stash_mcp.filesystem import FileSystem
        from stash_mcp.mcp_server import create_mcp_server

        with TemporaryDirectory() as content_dir, TemporaryDirectory() as index_dir:
            fs = FileSystem(Path(content_dir))
            for name, text in DOCS.items():
                fs.write_file(name, text)
            engine = SearchEngine(
                content_dir=Path(content_dir),
                index_dir=Path(index_dir),
                embed_fn=topic_embed,
                hybrid_enabled=True,
                heading_context=False,
            )
            await engine.build_index(sorted(DOCS))
            tool = await create_mcp_server(fs, search_engine=engine).get_tool(
                "search_content"
            )
            ctx = MagicMock(spec=Context)
            ctx.session = AsyncMock()
            token = _current_context.set(ctx)
            try:
                result = await tool.run({"query": query})
                return result.content[0].text
            finally:
                _current_context.reset(token)

    async def test_covered_query_shows_similarity_without_a_warning(self):
        text = await self._run("quokka")
        assert "quokka.md (similarity 0.97)" in text
        assert "No close match" not in text
        assert "score" not in text

    async def test_uncovered_query_says_nothing_matched_closely(self):
        text = await self._run("axolotl")
        assert text.startswith("No close match")
        assert "below noise floor" in text
