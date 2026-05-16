"""Tests for ``stash_mcp.auth.sessions`` cookie signing helpers."""

from __future__ import annotations

import time

import pytest

from stash_mcp.auth import sessions as session_mod
from stash_mcp.config import Config


@pytest.fixture(autouse=True)
def _session_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "SESSION_SECRET", "test-secret-do-not-use", raising=False)
    monkeypatch.setattr(Config, "SESSION_MAX_AGE_SECONDS", 60, raising=False)
    yield


def test_roundtrip_returns_same_payload():
    cookie = session_mod.issue_session("u-1", "oidc-sub-1")
    payload = session_mod.verify_session(cookie)
    assert payload == {"uid": "u-1", "sub": "oidc-sub-1"}


def test_tampered_cookie_returns_none():
    cookie = session_mod.issue_session("u-1", "oidc-sub-1")
    # Replace the signature with one that definitely doesn't match. Flipping
    # the last char of the cookie is not safe: itsdangerous URL-safe-
    # base64-encodes a 20-byte HMAC into 27 chars, leaving 2 slack bits in
    # the last char, so swapping (say) A↔B can decode to the same signature
    # bytes and make this test flake.
    payload_and_timestamp, sig = cookie.rsplit(".", 1)
    tampered = payload_and_timestamp + "." + "X" * len(sig)
    assert session_mod.verify_session(tampered) is None


def test_expired_cookie_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "SESSION_MAX_AGE_SECONDS", 1, raising=False)
    cookie = session_mod.issue_session("u-1", "oidc-sub-1")
    # itsdangerous compares integer seconds, so we need >max_age elapsed.
    time.sleep(2.1)
    assert session_mod.verify_session(cookie) is None


def test_rotating_secret_invalidates_existing_cookies(monkeypatch: pytest.MonkeyPatch):
    cookie = session_mod.issue_session("u-1", "oidc-sub-1")
    monkeypatch.setattr(Config, "SESSION_SECRET", "different-secret", raising=False)
    assert session_mod.verify_session(cookie) is None


def test_missing_secret_raises_on_issue(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(Config, "SESSION_SECRET", None, raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        session_mod.issue_session("u-1", "oidc-sub-1")
