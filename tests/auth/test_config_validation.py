"""Tests for ``Config.validate_auth_config``."""

from __future__ import annotations

import pytest

from stash_mcp.config import Config


def _disable_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every required auth knob to None / empty so we know exactly
    what's missing when the validator runs."""
    monkeypatch.setattr(Config, "AUTH_TOKEN_HMAC_KEYS", [], raising=False)
    monkeypatch.setattr(Config, "OIDC_DISCOVERY_URL", None, raising=False)
    monkeypatch.setattr(Config, "OIDC_CLIENT_ID", None, raising=False)
    monkeypatch.setattr(Config, "OIDC_CLIENT_SECRET", None, raising=False)
    monkeypatch.setattr(Config, "SESSION_SECRET", None, raising=False)
    monkeypatch.setattr(Config, "OIDC_ADMIN_GROUP", None, raising=False)


def test_noop_when_auth_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", False, raising=False)
    _disable_auth_env(monkeypatch)
    Config.validate_auth_config()  # must not raise


def test_lists_every_missing_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    _disable_auth_env(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        Config.validate_auth_config()
    msg = str(excinfo.value)
    for var in (
        "STASH_AUTH_TOKEN_HMAC_KEYS",
        "STASH_OIDC_DISCOVERY_URL",
        "STASH_OIDC_CLIENT_ID",
        "STASH_OIDC_CLIENT_SECRET",
        "STASH_SESSION_SECRET",
        "STASH_OIDC_ADMIN_GROUP",
    ):
        assert var in msg


def test_passes_when_fully_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "AUTH_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "DATABASE_URL", "sqlite+aiosqlite:///:memory:", raising=False)
    monkeypatch.setattr(Config, "AUTH_TOKEN_HMAC_KEYS", ["k1"], raising=False)
    monkeypatch.setattr(Config, "OIDC_DISCOVERY_URL", "http://idp/.well-known", raising=False)
    monkeypatch.setattr(Config, "OIDC_CLIENT_ID", "stash-mcp", raising=False)
    monkeypatch.setattr(Config, "OIDC_CLIENT_SECRET", "shh", raising=False)
    monkeypatch.setattr(Config, "SESSION_SECRET", "cookie-secret", raising=False)
    monkeypatch.setattr(Config, "OIDC_ADMIN_GROUP", "stash-admins", raising=False)

    Config.validate_auth_config()  # must not raise
