"""Tests for stash_mcp.auth.tokens."""

import time

import pytest

from stash_mcp.auth.tokens import (
    TOKEN_PREFIX,
    generate_token,
    hash_token,
    hash_with_active_key,
    looks_like_stash_token,
    verify_token,
)


def test_round_trip_with_active_key():
    keys = ["k1-active"]
    token = generate_token()
    digest, version = hash_with_active_key(token, keys=keys)
    assert version == 0
    assert verify_token(token, digest, keys=keys, key_version=version) is True


def test_verify_fails_when_recorded_key_rotated_out():
    """Row recorded key_version=0 under old keys list. Operator rotates the
    active key in place (single-entry list rolled over without prepend).
    Verification must fail closed because the original key is gone."""
    old_keys = ["k1"]
    token = generate_token()
    digest, version = hash_with_active_key(token, keys=old_keys)

    new_keys = ["k2"]
    assert verify_token(token, digest, keys=new_keys, key_version=version) is False


def test_rotation_old_key_still_in_list_verifies():
    """Hash with [K1], rotate to [K2, K1]. Existing row at key_version=0 in the
    old world is at key_version=1 after rotation."""
    token = generate_token()
    digest = hash_token(token, key="K1")
    rotated_keys = ["K2", "K1"]
    assert verify_token(token, digest, keys=rotated_keys, key_version=1) is True


def test_out_of_range_key_version_returns_false():
    keys = ["only-key"]
    token = generate_token()
    digest, _ = hash_with_active_key(token, keys=keys)
    assert verify_token(token, digest, keys=keys, key_version=5) is False
    assert verify_token(token, digest, keys=keys, key_version=-1) is False


def test_tampered_token_fails():
    keys = ["k"]
    token = generate_token()
    digest, version = hash_with_active_key(token, keys=keys)
    tampered = token + "x"
    assert verify_token(tampered, digest, keys=keys, key_version=version) is False


def test_hash_with_active_key_empty_list_raises():
    with pytest.raises(ValueError):
        hash_with_active_key(generate_token(), keys=[])


def test_constant_time_comparison_smoke():
    """Smoke check: verify_token times should be similar for matching prefixes
    of different lengths. Not a real timing-attack test — just confirms we
    aren't using ==."""
    keys = ["k"]
    token = generate_token()
    digest, version = hash_with_active_key(token, keys=keys)
    wrong_short = "0" * 64
    wrong_long_matching_prefix = digest[:32] + "0" * 32

    iters = 500
    start = time.perf_counter()
    for _ in range(iters):
        verify_token(token, wrong_short, keys=keys, key_version=version)
    short_elapsed = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(iters):
        verify_token(token, wrong_long_matching_prefix, keys=keys, key_version=version)
    long_elapsed = time.perf_counter() - start

    ratio = max(short_elapsed, long_elapsed) / max(
        min(short_elapsed, long_elapsed), 1e-9
    )
    assert ratio < 5.0, f"timing ratio {ratio:.2f} too large for HMAC compare"


def test_generated_token_has_prefix():
    assert generate_token().startswith(TOKEN_PREFIX)


def test_looks_like_stash_token():
    assert looks_like_stash_token(generate_token()) is True
    assert looks_like_stash_token("stash_pat_abc") is True
    assert looks_like_stash_token("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.sig") is False
    assert looks_like_stash_token("") is False
    assert looks_like_stash_token("Bearer something") is False
