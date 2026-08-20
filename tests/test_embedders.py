"""Tests for the ONNX Runtime (fastembed) embedding backend.

The adapter is exercised against the fake ``fastembed`` module from
``conftest.py`` (injected into ``sys.modules``) so no model download or
network access happens in CI.
"""

import asyncio
import sys
import threading

import pytest

from stash_mcp.embedders import (
    DEFAULT_EMBEDDER_MODEL,
    DEFAULT_RERANK_MODEL,
    ONNX_PREFIX,
    FastEmbedAdapter,
    FastEmbedReranker,
    is_onnx_model,
    onnx_model_name,
    prefixes_for_model,
)

# Model names known to the fake fastembed module (see conftest.fake_fastembed)
MINILM = "sentence-transformers/all-MiniLM-L6-v2"
BGE_SMALL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

# --- Prefix parsing -------------------------------------------------------


class TestModelPrefix:

    def test_default_model_uses_onnx_prefix(self):
        assert ONNX_PREFIX == "onnx:"
        assert DEFAULT_EMBEDDER_MODEL == f"onnx:{BGE_SMALL}"

    def test_is_onnx_model_true_for_prefix(self):
        assert is_onnx_model(f"onnx:{MINILM}") is True

    def test_is_onnx_model_is_case_insensitive_and_strips_whitespace(self):
        assert is_onnx_model(f"  ONNX:{MINILM} ") is True

    @pytest.mark.parametrize(
        "model",
        [
            f"sentence-transformers:{MINILM}",
            "openai:text-embedding-3-small",
            "cohere:embed-english-v3.0",
            "onnx",  # no colon
            "",
        ],
    )
    def test_is_onnx_model_false_for_other_providers(self, model):
        assert is_onnx_model(model) is False

    def test_onnx_model_name_strips_prefix(self):
        assert onnx_model_name(f"onnx:{MINILM}") == MINILM

    def test_onnx_model_name_strips_surrounding_whitespace(self):
        assert onnx_model_name(f" onnx: {MINILM} ") == MINILM

    def test_onnx_model_name_rejects_empty_name(self):
        with pytest.raises(ValueError, match="model name"):
            onnx_model_name("onnx:")

    def test_onnx_model_name_rejects_other_prefix(self):
        with pytest.raises(ValueError, match="onnx:"):
            onnx_model_name("openai:text-embedding-3-small")


# --- Query / document prefixes -------------------------------------------


class TestModelPrefixes:
    """Asymmetric models need their documented query/passage instructions;
    symmetric ones must be left alone."""

    @pytest.mark.parametrize(
        ("model", "query", "document"),
        [
            # e5 family: "query: " / "passage: "
            ("intfloat/multilingual-e5-large", "query: ", "passage: "),
            # nomic: task instruction prefixes are mandatory
            ("nomic-ai/nomic-embed-text-v1.5", "search_query: ", "search_document: "),
            ("nomic-ai/nomic-embed-text-v1.5-Q", "search_query: ", "search_document: "),
            # arctic / mxbai / bge v1: query instruction only
            (
                "snowflake/snowflake-arctic-embed-s",
                "Represent this sentence for searching relevant passages: ",
                "",
            ),
            (
                "mixedbread-ai/mxbai-embed-large-v1",
                "Represent this sentence for searching relevant passages: ",
                "",
            ),
            (
                "BAAI/bge-small-en",
                "Represent this sentence for searching relevant passages: ",
                "",
            ),
        ],
    )
    def test_asymmetric_models_get_their_documented_prefixes(
        self, model, query, document
    ):
        assert prefixes_for_model(model) == (query, document)

    @pytest.mark.parametrize(
        "model",
        [
            # bge v1.5 explicitly retrieves better WITHOUT the instruction
            "BAAI/bge-small-en-v1.5",
            "BAAI/bge-base-en-v1.5",
            MINILM,
            "thenlper/gte-base",
            "some/unknown-model",
        ],
    )
    def test_symmetric_and_unknown_models_get_no_prefix(self, model):
        assert prefixes_for_model(model) == ("", "")

    def test_lookup_is_case_insensitive(self):
        assert prefixes_for_model("NOMIC-AI/Nomic-Embed-Text-v1.5") == (
            "search_query: ",
            "search_document: ",
        )


# --- FastEmbedAdapter (uses the `fake_fastembed` fixture from conftest) ---


class TestFastEmbedAdapter:

    async def test_returns_python_float_lists(self, fake_fastembed):
        adapter = FastEmbedAdapter(MINILM)
        vectors = await adapter(["a", "bbb"])
        assert vectors == [[1.0, 1.0, 0.5], [3.0, 1.0, 0.5]]
        assert all(type(x) is float for vec in vectors for x in vec)

    async def test_loads_model_lazily_and_only_once(self, fake_fastembed):
        adapter = FastEmbedAdapter(MINILM)
        assert fake_fastembed.calls["init"] == []
        assert adapter.loaded is False

        await adapter(["first"])
        await adapter(["second"])
        assert len(fake_fastembed.calls["init"]) == 1
        assert adapter.loaded is True

    async def test_empty_input_returns_empty_without_loading(self, fake_fastembed):
        adapter = FastEmbedAdapter(MINILM)
        assert await adapter([]) == []
        assert fake_fastembed.calls["init"] == []

    async def test_embeds_off_the_event_loop_thread(self, fake_fastembed):
        adapter = FastEmbedAdapter(MINILM)
        await adapter(["x"])
        assert fake_fastembed.calls["embed_threads"] == [
            t for t in fake_fastembed.calls["embed_threads"]
            if t is not threading.main_thread()
        ]

    async def test_passes_model_cache_dir_and_threads(self, fake_fastembed, tmp_path):
        cache = tmp_path / "models" / "fastembed"
        adapter = FastEmbedAdapter(MINILM, cache_dir=cache, threads=2)
        await adapter(["x"])
        init = fake_fastembed.calls["init"][0]
        assert init["model_name"] == MINILM
        assert init["cache_dir"] == str(cache)
        assert init["threads"] == 2
        assert cache.is_dir()

    async def test_no_cache_dir_leaves_fastembed_default(self, fake_fastembed):
        adapter = FastEmbedAdapter(MINILM)
        await adapter(["x"])
        init = fake_fastembed.calls["init"][0]
        assert init["cache_dir"] is None
        assert init["threads"] is None

    async def test_unusable_cache_dir_falls_back_with_warning(
        self, fake_fastembed, tmp_path, caplog
    ):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        with caplog.at_level("WARNING", logger="stash_mcp.embedders"):
            adapter = FastEmbedAdapter(MINILM, cache_dir=blocker / "sub")
        assert adapter.cache_dir is None
        assert any("cache" in rec.message.lower() for rec in caplog.records)
        await adapter(["x"])
        assert fake_fastembed.calls["init"][0]["cache_dir"] is None

    def test_unwritable_cache_dir_falls_back_with_warning(
        self, fake_fastembed, tmp_path, caplog, monkeypatch
    ):
        """A directory that exists but rejects writes must not defer the failure
        to the first embed, where nothing is left to fall back to."""
        import tempfile as tempfile_module

        cache = tmp_path / "models"

        def refuse(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(tempfile_module, "NamedTemporaryFile", refuse)
        with caplog.at_level("WARNING", logger="stash_mcp.embedders"):
            adapter = FastEmbedAdapter(MINILM, cache_dir=cache)
        assert adapter.cache_dir is None
        assert any("cache" in rec.message.lower() for rec in caplog.records)

    def test_unknown_model_fails_fast_at_construction(self, fake_fastembed):
        with pytest.raises(ValueError, match="nope/not-a-model"):
            FastEmbedAdapter("nope/not-a-model")
        assert fake_fastembed.calls["init"] == []

    def test_model_name_check_is_case_insensitive(self, fake_fastembed):
        FastEmbedAdapter(MINILM.lower())  # does not raise

    def test_missing_fastembed_raises_install_hint(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "fastembed", None)  # makes `import fastembed` fail
        with pytest.raises(RuntimeError, match=r"stash-mcp\[search\]"):
            FastEmbedAdapter(MINILM)

    async def test_document_prefix_is_applied_to_embedded_text(self, fake_fastembed):
        adapter = FastEmbedAdapter(MINILM, document_prefix="passage: ")
        await adapter(["hello"])
        assert fake_fastembed.calls["embed"] == [["passage: hello"]]

    async def test_query_prefix_is_applied_only_to_queries(self, fake_fastembed):
        adapter = FastEmbedAdapter(
            MINILM, query_prefix="query: ", document_prefix="passage: "
        )
        await adapter(["a document"])
        vector = await adapter.embed_query("a question")
        assert fake_fastembed.calls["embed"] == [
            ["passage: a document"],
            ["query: a question"],
        ]
        assert vector == [float(len("query: a question")), 1.0, 0.5]

    async def test_embed_query_without_prefixes_matches_document_path(
        self, fake_fastembed
    ):
        adapter = FastEmbedAdapter(MINILM)
        assert await adapter.embed_query("text") == (await adapter(["text"]))[0]

    async def test_prefixes_default_to_the_model_table(self, fake_fastembed):
        fake_fastembed.TextEmbedding.SUPPORTED.append("nomic-ai/nomic-embed-text-v1.5")
        adapter = FastEmbedAdapter("nomic-ai/nomic-embed-text-v1.5")
        assert adapter.query_prefix == "search_query: "
        assert adapter.document_prefix == "search_document: "
        await adapter(["doc"])
        await adapter.embed_query("q")
        assert fake_fastembed.calls["embed"] == [
            ["search_document: doc"],
            ["search_query: q"],
        ]

    async def test_explicit_prefix_overrides_the_table(self, fake_fastembed):
        fake_fastembed.TextEmbedding.SUPPORTED.append("nomic-ai/nomic-embed-text-v1.5")
        adapter = FastEmbedAdapter(
            "nomic-ai/nomic-embed-text-v1.5", query_prefix="", document_prefix=""
        )
        await adapter(["doc"])
        assert fake_fastembed.calls["embed"] == [["doc"]]

    async def test_visible_chars_reports_full_length_when_text_fits(
        self, fake_fastembed
    ):
        adapter = FastEmbedAdapter(BGE_SMALL)  # fake limit: 128 "words"
        text = "word " * 10
        assert await adapter.measure_visible_chars([text.strip()]) == [len(text.strip())]

    async def test_visible_chars_reports_the_truncation_point(self, fake_fastembed):
        adapter = FastEmbedAdapter(BGE_SMALL, max_tokens=3)
        text = "alpha beta gamma delta epsilon"
        # Only "alpha beta gamma" survives truncation
        assert await adapter.measure_visible_chars([text]) == [len("alpha beta gamma")]

    async def test_visible_chars_discounts_the_document_prefix(self, fake_fastembed):
        adapter = FastEmbedAdapter(
            BGE_SMALL, max_tokens=3, document_prefix="passage: "
        )
        text = "alpha beta gamma delta"
        # "passage:" eats one token, so only "alpha beta" of the text is read
        assert await adapter.measure_visible_chars([text]) == [len("alpha beta")]

    async def test_visible_chars_empty_input_does_not_load_the_model(
        self, fake_fastembed
    ):
        adapter = FastEmbedAdapter(BGE_SMALL)
        assert await adapter.measure_visible_chars([]) == []
        assert fake_fastembed.calls["init"] == []

    async def test_visible_chars_is_none_when_the_tokenizer_is_unavailable(
        self, fake_fastembed
    ):
        original_init = fake_fastembed.TextEmbedding.__init__

        def init_without_tokenizer(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self.model = object()

        fake_fastembed.TextEmbedding.__init__ = init_without_tokenizer
        adapter = FastEmbedAdapter(MINILM)
        assert await adapter.measure_visible_chars(["a b c"]) is None

    async def test_concurrent_first_use_loads_model_once(self, fake_fastembed):
        fake_fastembed.TextEmbedding.init_delay = 0.05
        adapter = FastEmbedAdapter(MINILM)
        results = await asyncio.gather(*(adapter([f"text {i}"]) for i in range(5)))
        assert len(fake_fastembed.calls["init"]) == 1
        assert [r[0][0] for r in results] == [6.0] * 5  # len("text 0") == 6

    async def test_minilm_truncation_restored_to_256_tokens(self, fake_fastembed):
        adapter = FastEmbedAdapter(MINILM)
        await adapter(["x"])
        tokenizer = adapter._model.model.tokenizer
        assert tokenizer.truncation["max_length"] == 256
        # The model's other truncation settings survive the override
        assert tokenizer.truncation["strategy"] == "only_second"
        # Fixed-length padding must become dynamic so batches stay rectangular,
        # while the model's pad token/id are kept (not reset to library defaults)
        assert tokenizer.padding["length"] is None
        assert tokenizer.padding["pad_id"] == 1
        assert tokenizer.padding["pad_token"] == "<pad>"

    async def test_other_models_keep_fastembed_truncation(self, fake_fastembed):
        adapter = FastEmbedAdapter(BGE_SMALL)
        await adapter(["x"])
        tokenizer = adapter._model.model.tokenizer
        assert tokenizer.truncation["max_length"] == 128
        assert tokenizer.padding["length"] == 128

    async def test_explicit_max_tokens_overrides_default(self, fake_fastembed):
        adapter = FastEmbedAdapter(BGE_SMALL, max_tokens=512)
        await adapter(["x"])
        assert adapter._model.model.tokenizer.truncation["max_length"] == 512

    async def test_truncation_override_failure_only_warns(self, fake_fastembed, caplog):
        # Simulate a fastembed release that no longer exposes `.model.tokenizer`
        original_init = fake_fastembed.TextEmbedding.__init__

        def init_without_tokenizer(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self.model = object()  # no `.tokenizer` attribute

        fake_fastembed.TextEmbedding.__init__ = init_without_tokenizer
        adapter = FastEmbedAdapter(MINILM)
        with caplog.at_level("WARNING", logger="stash_mcp.embedders"):
            vectors = await adapter(["x"])
        assert vectors == [[1.0, 1.0, 0.5]]
        assert any("truncation" in rec.message.lower() for rec in caplog.records)

    async def test_partial_override_failure_restores_original_truncation(
        self, fake_fastembed, caplog
    ):
        # Truncation succeeds but padding fails: leave the tokenizer as we found
        # it rather than truncating at 256 with fixed 128 padding (ragged batches).
        original_init = fake_fastembed.TextEmbedding.__init__

        def init_with_broken_padding(self, *args, **kwargs):
            original_init(self, *args, **kwargs)

            def broken(**kwargs):
                raise TypeError("unexpected keyword")

            self.model.tokenizer.enable_padding = broken

        fake_fastembed.TextEmbedding.__init__ = init_with_broken_padding
        adapter = FastEmbedAdapter(MINILM)
        with caplog.at_level("WARNING", logger="stash_mcp.embedders"):
            await adapter(["x"])
        tokenizer = adapter._model.model.tokenizer
        assert tokenizer.truncation["max_length"] == 128
        assert tokenizer.padding["length"] == 128
        assert any("truncation" in rec.message.lower() for rec in caplog.records)


# --- FastEmbedReranker ----------------------------------------------------


class TestFastEmbedReranker:

    def test_default_model_is_the_ms_marco_l12_cross_encoder(self):
        """L-12 measured best per megabyte of the small cross-encoders."""
        assert DEFAULT_RERANK_MODEL == "Xenova/ms-marco-MiniLM-L-12-v2"

    async def test_scores_each_document_against_the_query(self, fake_fastembed):
        reranker = FastEmbedReranker(RERANK_MODEL)
        scores = await reranker.rerank(
            "oauth redirect", ["oauth redirect flow", "unrelated text"]
        )
        assert scores == [-3.0, -5.0]  # fake: 2 query words vs 0, minus 5

    async def test_loads_lazily_and_only_once(self, fake_fastembed):
        reranker = FastEmbedReranker(RERANK_MODEL)
        assert fake_fastembed.calls["rerank_init"] == []
        assert reranker.loaded is False
        await reranker.rerank("q", ["a"])
        await reranker.rerank("q", ["b"])
        assert len(fake_fastembed.calls["rerank_init"]) == 1
        assert reranker.loaded is True

    async def test_runs_off_the_event_loop_thread(self, fake_fastembed):
        reranker = FastEmbedReranker(RERANK_MODEL)
        await reranker.rerank("q", ["a"])
        assert all(
            t is not threading.main_thread()
            for t in fake_fastembed.calls["rerank_threads"]
        )

    async def test_empty_documents_short_circuit(self, fake_fastembed):
        reranker = FastEmbedReranker(RERANK_MODEL)
        assert await reranker.rerank("q", []) == []
        assert fake_fastembed.calls["rerank_init"] == []

    async def test_passes_cache_dir_and_threads(self, fake_fastembed, tmp_path):
        cache = tmp_path / "models" / "fastembed"
        reranker = FastEmbedReranker(RERANK_MODEL, cache_dir=cache, threads=2)
        await reranker.rerank("q", ["a"])
        init = fake_fastembed.calls["rerank_init"][0]
        assert init["cache_dir"] == str(cache)
        assert init["threads"] == 2

    def test_unknown_model_fails_fast(self, fake_fastembed):
        with pytest.raises(ValueError, match="nope/not-a-reranker"):
            FastEmbedReranker("nope/not-a-reranker")

    def test_missing_fastembed_raises_install_hint(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", None)
        with pytest.raises(RuntimeError, match=r"stash-mcp\[search\]"):
            FastEmbedReranker(RERANK_MODEL)
