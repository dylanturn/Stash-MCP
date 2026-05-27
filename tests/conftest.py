"""Shared pytest fixtures for the test suite."""

import pytest

import stash_mcp.config as _config_module


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
    for name, value in snapshot.items():
        setattr(original_class, name, value)
