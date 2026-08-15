"""Shared pytest fixtures for the test suite."""

import sys
import threading
import types

import pytest

import stash_mcp.config as _config_module

FAKE_MINILM = "sentence-transformers/all-MiniLM-L6-v2"
FAKE_BGE_SMALL = "BAAI/bge-small-en-v1.5"


@pytest.fixture
def fake_fastembed(monkeypatch):
    """Install a fake ``fastembed`` module with a scripted ``TextEmbedding``.

    Lets the ONNX embedding backend be exercised without a model download
    or network access. Records constructor kwargs and embed calls, and mimics
    the tokenizer layout (``TextEmbedding.model.tokenizer``) the adapter
    adjusts after loading. Vectors are 3-dim: ``[len(text), 1.0, 0.5]``.
    """
    import numpy as np

    calls = {"init": [], "embed": [], "embed_threads": []}

    class FakeTokenizer:
        def __init__(self):
            self.truncation = {
                "max_length": 128, "stride": 0,
                "strategy": "longest_first", "direction": "right",
            }
            self.padding = {
                "length": 128, "pad_to_multiple_of": None, "pad_id": 0,
                "pad_token": "[PAD]", "pad_type_id": 0, "direction": "right",
            }

        def enable_truncation(self, max_length, **kwargs):
            self.truncation = {**self.truncation, "max_length": max_length, **kwargs}

        def enable_padding(self, **kwargs):
            self.padding = {**self.padding, **kwargs}

    class FakeInnerModel:
        def __init__(self):
            self.tokenizer = FakeTokenizer()

    class FakeTextEmbedding:
        SUPPORTED = [FAKE_MINILM, FAKE_BGE_SMALL]

        def __init__(self, model_name=FAKE_BGE_SMALL, cache_dir=None, threads=None, **kwargs):
            if model_name.lower() not in [m.lower() for m in self.SUPPORTED]:
                raise ValueError(f"Model {model_name} is not supported in TextEmbedding.")
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

    module = types.ModuleType("fastembed")
    module.TextEmbedding = FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", module)
    return types.SimpleNamespace(module=module, TextEmbedding=FakeTextEmbedding, calls=calls)


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
