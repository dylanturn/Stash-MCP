"""Smoke coverage for the Problem Details exception handler + each
standard :class:`StashError` subclass."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from stash_mcp.errors import (
    PROBLEM_MEDIA_TYPE,
    ConfirmationRequired,
    ContentNotFound,
    ETagMismatch,
    Forbidden,
    ScopeRequired,
    StoreAlreadyExists,
    StoreNotFound,
    StoreNotProvisioned,
    TenantAlreadyExists,
    TenantHasStores,
    TenantNotFound,
    TokenNotFound,
    Unauthenticated,
    UserNotFound,
    ValidationError,
    install_problem_handlers,
)


def _build_app(err_factory):
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/boom")
    async def boom():
        raise err_factory()

    return TestClient(app)


@pytest.mark.parametrize(
    "factory, status, type_id, title",
    [
        (lambda: Unauthenticated("login required"), 401,
         "/problems/auth/unauthenticated", "Authentication required"),
        (lambda: Forbidden(), 403,
         "/problems/auth/forbidden", "Forbidden"),
        (lambda: ScopeRequired(required_scope="write"), 403,
         "/problems/auth/scope-required", "Insufficient scope"),
        (lambda: ContentNotFound("missing"), 404,
         "/problems/content/not-found", "Content not found"),
        (lambda: ETagMismatch(current_etag='"abc"'), 412,
         "/problems/content/etag-mismatch",
         "ETag mismatch on conditional write"),
        (lambda: StoreNotFound(), 404,
         "/problems/store/not-found", "Store not found"),
        (lambda: StoreAlreadyExists(), 409,
         "/problems/store/already-exists", "Store already exists"),
        (lambda: StoreNotProvisioned("on-disk gone"), 500,
         "/problems/store/not-provisioned",
         "Store has DB row but no on-disk repo"),
        (lambda: TenantNotFound(), 404,
         "/problems/tenant/not-found", "Tenant not found"),
        (lambda: TenantAlreadyExists(), 409,
         "/problems/tenant/already-exists", "Tenant already exists"),
        (lambda: TenantHasStores(), 409,
         "/problems/tenant/has-stores",
         "Tenant cannot be deleted while it owns stores"),
        (lambda: UserNotFound(), 404,
         "/problems/user/not-found", "User not found"),
        (lambda: TokenNotFound(), 404,
         "/problems/token/not-found", "Token not found"),
        (lambda: ValidationError(errors=["bad"]), 400,
         "/problems/validation", "Validation failed"),
        (lambda: ConfirmationRequired(), 400,
         "/problems/confirmation-required",
         "Destructive operation requires confirm=true"),
    ],
)
def test_problem_renders_standard_fields(factory, status, type_id, title):
    client = _build_app(factory)
    resp = client.get("/boom")
    assert resp.status_code == status
    assert resp.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = resp.json()
    assert body["type"] == type_id
    assert body["title"] == title
    assert body["status"] == status
    assert body["instance"] == "/boom"


def test_extras_flow_into_response_body():
    client = _build_app(
        lambda: ETagMismatch(detail="stale write", current_etag='"deadbeef"')
    )
    resp = client.get("/boom")
    body = resp.json()
    assert body["detail"] == "stale write"
    assert body["current_etag"] == '"deadbeef"'


def test_401_sets_www_authenticate():
    client = _build_app(lambda: Unauthenticated())
    resp = client.get("/boom")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate", "").startswith("Bearer")
