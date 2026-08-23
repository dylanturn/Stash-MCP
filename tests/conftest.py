"""Shared pytest fixtures for the test suite."""

import sys
import threading
import types

import pytest

import stash_mcp.config as _config_module

FAKE_MINILM = "sentence-transformers/all-MiniLM-L6-v2"
FAKE_BGE_SMALL = "BAAI/bge-small-en-v1.5"
FAKE_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


@pytest.fixture
def fake_fastembed(monkeypatch):
    """Install a fake ``fastembed`` module with a scripted ``TextEmbedding``.

    Lets the ONNX embedding backend be exercised without a model download
    or network access. Records constructor kwargs and embed calls, and mimics
    the tokenizer layout (``TextEmbedding.model.tokenizer``) the adapter
    adjusts after loading. Vectors are 3-dim: ``[len(text), 1.0, 0.5]``.
    """
    import numpy as np

    calls = {
        "init": [], "embed": [], "embed_threads": [],
        "rerank_init": [], "rerank": [], "rerank_threads": [],
    }

    class FakeTokenizer:
        """Mimics ``tokenizers.Tokenizer``: enable_* replace the whole config
        (unspecified kwargs fall back to library defaults, like the real thing).

        Deliberately non-default pad_id/pad_token/strategy so tests can prove
        the adapter carries the model's values over rather than the defaults.
        """

        def __init__(self):
            self.truncation = {
                "max_length": 128, "stride": 0,
                "strategy": "only_second", "direction": "right",
            }
            self.padding = {
                "length": 128, "pad_to_multiple_of": None, "pad_id": 1,
                "pad_token": "<pad>", "pad_type_id": 0, "direction": "right",
            }

        def enable_truncation(
            self, max_length, stride=0, strategy="longest_first", direction="right"
        ):
            self.truncation = {
                "max_length": max_length, "stride": stride,
                "strategy": strategy, "direction": direction,
            }

        def enable_padding(
            self, direction="right", pad_id=0, pad_type_id=0, pad_token="[PAD]",
            length=None, pad_to_multiple_of=None,
        ):
            self.padding = {
                "length": length, "pad_to_multiple_of": pad_to_multiple_of,
                "pad_id": pad_id, "pad_token": pad_token, "pad_type_id": pad_type_id,
                "direction": direction,
            }

        def encode_batch(self, texts):
            """Stand-in for real tokenization: one token per whitespace word,
            truncated to the configured limit and padded to the configured
            length — both of which the real tokenizer also apply here.

            Encodings expose ``offsets`` (character spans, (0, 0) for padding)
            like ``tokenizers.Encoding`` does.
            """
            limit = self.truncation["max_length"]
            pad_to = self.padding.get("length")
            out = []
            for text in texts:
                offsets = []
                position = 0
                for word in text.split():
                    start = text.index(word, position)
                    offsets.append((start, start + len(word)))
                    position = start + len(word)
                offsets = offsets[:limit]
                ids = list(range(len(offsets)))
                if pad_to:
                    pad = max(0, pad_to - len(ids))
                    ids += [0] * pad
                    offsets += [(0, 0)] * pad
                out.append(types.SimpleNamespace(ids=ids, offsets=offsets))
            return out

    class FakeInnerModel:
        def __init__(self):
            self.tokenizer = FakeTokenizer()

    class FakeTextEmbedding:
        SUPPORTED = [FAKE_MINILM, FAKE_BGE_SMALL]
        init_delay = 0.0  # tests can set this to simulate a slow download/load

        def __init__(self, model_name=FAKE_BGE_SMALL, cache_dir=None, threads=None, **kwargs):
            if model_name.lower() not in [m.lower() for m in self.SUPPORTED]:
                raise ValueError(f"Model {model_name} is not supported in TextEmbedding.")
            if self.init_delay:
                import time

                time.sleep(self.init_delay)
            calls["init"].append(
                {"model_name": model_name, "cache_dir": cache_dir, "threads": threads, **kwargs}
            )
            self.model_name = model_name
            self.model = FakeInnerModel()

        @classmethod
        def list_supported_models(cls):
            return [{"model": m, "dim": 3} for m in cls.SUPPORTED]

        def embed(self, documents, batch_size=256, **kwargs):
            docs = list(documents)
            calls["embed"].append(docs)
            calls["embed_threads"].append(threading.current_thread())
            for doc in docs:
                # float64 like the real library, and a generator (not a list)
                yield np.array([float(len(doc)), 1.0, 0.5], dtype=np.float64)

    class FakeTextCrossEncoder:
        """Scores a pair by how many query words the document contains."""

        SUPPORTED = [FAKE_RERANK_MODEL]

        def __init__(self, model_name, cache_dir=None, threads=None, **kwargs):
            if model_name.lower() not in [m.lower() for m in self.SUPPORTED]:
                raise ValueError(f"Model {model_name} is not supported in TextCrossEncoder.")
            calls["rerank_init"].append(
                {"model_name": model_name, "cache_dir": cache_dir, "threads": threads}
            )
            self.model_name = model_name

        @classmethod
        def list_supported_models(cls):
            return [{"model": m, "size_in_GB": 0.08} for m in cls.SUPPORTED]

        def rerank(self, query, documents, batch_size=64, **kwargs):
            docs = list(documents)
            calls["rerank"].append((query, docs))
            calls["rerank_threads"].append(threading.current_thread())
            terms = set(query.lower().split())
            for doc in docs:
                words = doc.lower().split()
                # Logit-like unbounded score, as real cross-encoders return
                yield float(sum(w in terms for w in words)) - 5.0

    module = types.ModuleType("fastembed")
    module.TextEmbedding = FakeTextEmbedding
    rerank_module = types.ModuleType("fastembed.rerank")
    cross_module = types.ModuleType("fastembed.rerank.cross_encoder")
    cross_module.TextCrossEncoder = FakeTextCrossEncoder
    rerank_module.cross_encoder = cross_module
    module.rerank = rerank_module
    monkeypatch.setitem(sys.modules, "fastembed", module)
    monkeypatch.setitem(sys.modules, "fastembed.rerank", rerank_module)
    monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", cross_module)
    return types.SimpleNamespace(
        module=module,
        TextEmbedding=FakeTextEmbedding,
        TextCrossEncoder=FakeTextCrossEncoder,
        calls=calls,
    )


@pytest.fixture(autouse=True)
def _isolate_config_state():
    """Snapshot Config state per test and restore on teardown.

    Two known sources of cross-test pollution this guards against:

    1. Several call paths in stash_mcp.main and stash_mcp.server assign
       directly to Config (e.g. `Config.GIT_TRACKING = True` inside
       `_maybe_clone_repo`), bypassing the monkeypatch protocol.
    2. A couple of tests do `importlib.reload(stash_mcp.config)`, which
       creates a NEW Config class object. Other modules (`main`,
       `server`, `mcp_server`, ...) hold the OLD class reference via
       `from stash_mcp.config import Config`, so the two diverge —
       monkeypatches on the new class don't affect the importers.
       We restore the class identity AND attributes on teardown.
    """
    original_class = _config_module.Config
    snapshot = {
        name: getattr(original_class, name)
        for name in vars(original_class)
        if name.isupper()
    }
    yield
    if _config_module.Config is not original_class:
        _config_module.Config = original_class
    # Delete any uppercase attrs a test added (not in snapshot) before
    # restoring the originals, so the class never carries extra state.
    current_upper = {
        name for name in vars(original_class) if name.isupper()
    }
    for name in current_upper - snapshot.keys():
        delattr(original_class, name)
    for name, value in snapshot.items():
        setattr(original_class, name, value)
