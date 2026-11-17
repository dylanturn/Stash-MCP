"""Tests for the upload_content MCP tool and byte-level filesystem helpers."""

import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock

import pytest

from stash_mcp.config import Config
from stash_mcp.filesystem import FileSystem, InvalidPathError
from stash_mcp.mcp_server import _decode_upload, _upload_mime_type, create_mcp_server

# Not valid UTF-8, contains CRLF and NUL — any text round-trip would corrupt it.
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\x00\x80"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _data(result) -> dict:
    return json.loads(str(result.content[0].text))


@pytest.fixture
def temp_fs():
    with TemporaryDirectory() as tmpdir:
        yield FileSystem(Path(tmpdir))


@pytest.fixture
def mock_context():
    from fastmcp.server.context import Context, _current_context

    ctx = MagicMock(spec=Context)
    ctx.session = AsyncMock()
    ctx.send_resource_list_changed = AsyncMock()
    token = _current_context.set(ctx)
    yield ctx
    _current_context.reset(token)


async def _upload(fs, args):
    tool = await create_mcp_server(fs).get_tool("upload_content")
    return await tool.run(args)


# --- filesystem ---


def test_write_and_read_bytes_round_trip(temp_fs):
    temp_fs.write_bytes("a/b/img.png", PNG_BYTES)
    assert temp_fs.read_bytes("a/b/img.png") == PNG_BYTES


def test_write_bytes_rejects_escape(temp_fs):
    with pytest.raises(InvalidPathError):
        temp_fs.write_bytes("../escape.bin", b"x")


def test_write_bytes_rejects_directory(temp_fs):
    temp_fs.write_bytes("dir/file.bin", b"x")
    with pytest.raises(InvalidPathError):
        temp_fs.write_bytes("dir", b"x")


# --- decoding ---


def test_decode_accepts_data_url_whitespace_and_urlsafe():
    raw = bytes(range(256))
    std = _b64(raw)
    assert _decode_upload(f"data:image/png;base64,{std}", 1000) == raw
    assert _decode_upload("\n".join(std[i:i + 60] for i in range(0, len(std), 60)), 1000) == raw
    urlsafe = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert _decode_upload(urlsafe, 1000) == raw


def test_decode_rejects_invalid():
    with pytest.raises(ValueError, match="not valid base64"):
        _decode_upload("not*base64!", 1000)


def test_decode_enforces_limit():
    assert _decode_upload(_b64(b"x" * 10), 10) == b"x" * 10
    with pytest.raises(ValueError, match="limit"):
        _decode_upload(_b64(b"x" * 11), 10)
    with pytest.raises(ValueError, match="limit"):
        _decode_upload(_b64(b"x" * 1000), 10)


# --- tool ---


async def test_tool_registered(temp_fs):
    tools = await create_mcp_server(temp_fs).get_tools()
    assert "upload_content" in tools


async def test_upload_creates_binary_file_byte_for_byte(temp_fs, mock_context):
    args = {"path": "assets/logo.png", "data_base64": _b64(PNG_BYTES)}
    result = _data(await _upload(temp_fs, args))
    assert result == {
        "path": "assets/logo.png",
        "created": True,
        "size_bytes": len(PNG_BYTES),
        "mime_type": "image/png",
        "sha": _sha(PNG_BYTES),
    }
    assert (temp_fs.content_dir / "assets/logo.png").read_bytes() == PNG_BYTES


async def test_upload_existing_without_sha_fails(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    with pytest.raises(Exception, match="already exists"):
        await _upload(temp_fs, {"path": "logo.png", "data_base64": _b64(b"new")})
    assert temp_fs.read_bytes("logo.png") == PNG_BYTES


async def test_upload_replaces_with_matching_sha(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    result = _data(await _upload(
        temp_fs, {"path": "logo.png", "data_base64": _b64(b"v2"), "sha": _sha(PNG_BYTES)}
    ))
    assert result["created"] is False
    assert result["sha"] == _sha(b"v2")
    assert temp_fs.read_bytes("logo.png") == b"v2"


async def test_upload_replace_with_stale_sha_fails(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    with pytest.raises(Exception, match="SHA mismatch"):
        await _upload(temp_fs, {"path": "logo.png", "data_base64": _b64(b"v2"), "sha": "0" * 64})
    assert temp_fs.read_bytes("logo.png") == PNG_BYTES


async def test_upload_sha_for_missing_file_fails(temp_fs, mock_context):
    with pytest.raises(Exception, match="does not exist"):
        await _upload(temp_fs, {"path": "new.png", "data_base64": _b64(b"x"), "sha": "0" * 64})
    assert not temp_fs.file_exists("new.png")


async def test_upload_over_limit_writes_nothing(temp_fs, mock_context, monkeypatch):
    monkeypatch.setattr(Config, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(Exception, match="limit"):
        await _upload(temp_fs, {"path": "big.bin", "data_base64": _b64(b"12345")})
    assert not temp_fs.file_exists("big.bin")


async def test_upload_path_escape_rejected(temp_fs, mock_context):
    with pytest.raises(Exception):
        await _upload(temp_fs, {"path": "../escape.bin", "data_base64": _b64(b"x")})
    assert not (temp_fs.content_dir.parent / "escape.bin").exists()


async def test_upload_readme_registers_resource(temp_fs, mock_context):
    await _upload(temp_fs, {"path": "docs/README.md", "data_base64": _b64(b"# Hi\n")})
    mock_context.send_resource_list_changed.assert_awaited_once()
    assert temp_fs.read_file("docs/README.md") == "# Hi\n"


async def test_upload_not_registered_when_read_only(temp_fs, monkeypatch):
    monkeypatch.setattr(Config, "READ_ONLY", True)
    tools = await create_mcp_server(temp_fs).get_tools()
    assert "upload_content" not in tools


async def test_upload_inside_transaction(mock_context):
    """Under a TransactionManager the write gate re-arms an asyncio timeout,
    so the write must run on the event loop rather than a worker thread."""
    from tests.test_transactions import _make_tm

    with TemporaryDirectory() as tmpdir:
        tm, fs = _make_tm(Path(tmpdir))
        session_id = str(id(mock_context.session))
        await tm.start_transaction(session_id, timeout=30, lock_wait=5)
        try:
            args = {"path": "img.png", "data_base64": _b64(PNG_BYTES)}
            result = _data(await _upload(tm, args))
            assert result["created"] is True
            assert fs.read_bytes("img.png") == PNG_BYTES
        finally:
            await tm.abort_transaction(session_id)


def test_upload_mime_type():
    assert _upload_mime_type("a/logo.png") == "image/png"
    assert _upload_mime_type("doc.md") == "text/markdown"
    assert _upload_mime_type("report.pdf") == "application/pdf"
    assert _upload_mime_type("blob.unknownext") == "application/octet-stream"
    assert _upload_mime_type("noext") == "application/octet-stream"


async def test_concurrent_replacements_with_same_sha_cannot_both_succeed(
    temp_fs, mock_context, monkeypatch
):
    """The sha check and the write must not be split by an await, or two
    replacements validated against the same bytes both win (lost update)."""
    import asyncio
    import time

    temp_fs.write_bytes("logo.png", PNG_BYTES)
    real_read_bytes = temp_fs.read_bytes

    def slow_read_bytes(path):
        # Read, then linger: if the read is awaited off the event loop, the
        # second call is guaranteed to read the old bytes too.
        data = real_read_bytes(path)
        time.sleep(0.05)
        return data

    monkeypatch.setattr(temp_fs, "read_bytes", slow_read_bytes)
    tool = await create_mcp_server(temp_fs).get_tool("upload_content")
    old_sha = _sha(PNG_BYTES)

    async def replace(payload: bytes):
        args = {"path": "logo.png", "data_base64": _b64(payload), "sha": old_sha}
        return await tool.run(args)

    results = await asyncio.gather(replace(b"A"), replace(b"B"), return_exceptions=True)
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 1
    assert "SHA mismatch" in str(failures[0])
