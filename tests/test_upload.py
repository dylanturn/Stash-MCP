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
from stash_mcp.mcp_server import (
    _binary_mime_type,
    _check_upload_allowed,
    _decode_upload,
    create_mcp_server,
)

# Not valid UTF-8, contains CRLF and NUL — any text round-trip would corrupt it.
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\x00\x80"
PNG_V2 = PNG_BYTES + b"\x00v2"


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


async def _call(fs, name, args):
    tool = await create_mcp_server(fs).get_tool(name)
    return await tool.run(args)


async def _upload(fs, args):
    return await _call(fs, "upload_content", args)


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
        await _upload(temp_fs, {"path": "logo.png", "data_base64": _b64(PNG_V2)})
    assert temp_fs.read_bytes("logo.png") == PNG_BYTES


async def test_upload_replaces_with_matching_sha(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    result = _data(await _upload(
        temp_fs, {"path": "logo.png", "data_base64": _b64(PNG_V2), "sha": _sha(PNG_BYTES)}
    ))
    assert result["created"] is False
    assert result["sha"] == _sha(PNG_V2)
    assert temp_fs.read_bytes("logo.png") == PNG_V2


async def test_upload_replace_with_stale_sha_fails(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    with pytest.raises(Exception, match="SHA mismatch"):
        await _upload(temp_fs, {"path": "logo.png", "data_base64": _b64(PNG_V2), "sha": "0" * 64})
    assert temp_fs.read_bytes("logo.png") == PNG_BYTES


async def test_upload_sha_for_missing_file_fails(temp_fs, mock_context):
    with pytest.raises(Exception, match="does not exist"):
        await _upload(temp_fs, {"path": "new.png", "data_base64": _b64(PNG_BYTES), "sha": "0" * 64})
    assert not temp_fs.file_exists("new.png")


async def test_upload_over_limit_writes_nothing(temp_fs, mock_context, monkeypatch):
    monkeypatch.setattr(Config, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(Exception, match="limit"):
        await _upload(temp_fs, {"path": "big.txt", "data_base64": _b64(b"12345")})
    assert not temp_fs.file_exists("big.txt")


async def test_upload_path_escape_rejected(temp_fs, mock_context):
    with pytest.raises(Exception):
        await _upload(temp_fs, {"path": "../escape.png", "data_base64": _b64(PNG_BYTES)})
    assert not (temp_fs.content_dir.parent / "escape.png").exists()


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


def test_binary_mime_type():
    assert _binary_mime_type("a/logo.png") == "image/png"
    assert _binary_mime_type("doc.md") == "text/markdown"
    assert _binary_mime_type("blob.unknownext") == "application/octet-stream"
    assert _binary_mime_type("noext") == "application/octet-stream"


# --- upload allowlist ---

ELF_BYTES = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8
ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 26
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
GIF_BYTES = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"
WEBP_BYTES = b"RIFF\x1a\x00\x00\x00WEBPVP8 "


@pytest.mark.parametrize(
    "path,data",
    [
        ("doc.md", "# Héllo\r\n".encode()),
        ("page.html", b"<html></html>"),
        ("data.json", b"{}"),
        ("icon.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ("img.png", PNG_BYTES),
        ("photo.JPG", JPEG_BYTES),
        ("anim.gif", GIF_BYTES),
        ("pic.webp", WEBP_BYTES),
    ],
)
def test_allowlist_accepts_documents_and_images(path, data):
    _check_upload_allowed(path, data)


@pytest.mark.parametrize(
    "path,data",
    [
        ("tool.exe", b"MZ\x90\x00"),
        ("lib.so", ELF_BYTES),
        ("run", ELF_BYTES),
        ("bundle.zip", ZIP_BYTES),
        ("app.jar", ZIP_BYTES),
        ("pkg.tar.gz", b"\x1f\x8b\x08\x00"),
        ("mod.pyc", b"\x6f\x0d\x0d\x0a" + b"\x00" * 12),
        ("Main.class", b"\xca\xfe\xba\xbe"),
        ("script.sh", b"#!/bin/sh\necho hi\n"),
        ("report.pdf", b"%PDF-1.7\n"),
    ],
)
def test_allowlist_rejects_disallowed_extensions(path, data):
    with pytest.raises(ValueError, match="does not accept"):
        _check_upload_allowed(path, data)


@pytest.mark.parametrize(
    "path,data,match",
    [
        ("evil.png", ELF_BYTES, "valid PNG"),
        ("evil.jpg", ZIP_BYTES, "valid JPG"),
        ("evil.gif", b"MZ\x90\x00", "valid GIF"),
        ("evil.webp", b"RIFF\x00\x00\x00\x00AVI ", "valid WEBP"),
        ("evil.md", ELF_BYTES, "UTF-8|NUL"),
        ("evil.html", b"\xff\xfe<\x00h\x00", "UTF-8"),
        ("evil.txt", b"abc\x00def", "NUL"),
    ],
)
def test_allowlist_rejects_content_not_matching_extension(path, data, match):
    with pytest.raises(ValueError, match=match):
        _check_upload_allowed(path, data)


async def test_upload_disallowed_type_writes_nothing(temp_fs, mock_context):
    with pytest.raises(Exception, match="does not accept"):
        await _upload(temp_fs, {"path": "tool.exe", "data_base64": _b64(b"MZ\x90\x00")})
    assert not temp_fs.file_exists("tool.exe")


async def test_upload_disguised_binary_writes_nothing(temp_fs, mock_context):
    with pytest.raises(Exception, match="valid PNG"):
        await _upload(temp_fs, {"path": "logo.png", "data_base64": _b64(ELF_BYTES)})
    assert not temp_fs.file_exists("logo.png")


async def test_replace_with_disallowed_content_keeps_original(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    with pytest.raises(Exception, match="valid PNG"):
        await _upload(temp_fs, {
            "path": "logo.png", "data_base64": _b64(ZIP_BYTES), "sha": _sha(PNG_BYTES),
        })
    assert temp_fs.read_bytes("logo.png") == PNG_BYTES


# --- reading binaries ---


async def test_read_content_on_binary_explains_raw_sha(temp_fs):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    with pytest.raises(Exception, match="not UTF-8 text.*raw-bytes sha"):
        await _call(temp_fs, "read_content", {"path": "logo.png"})


# --- delete_content on binary and text files ---


async def test_delete_binary_with_raw_sha(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    await _call(temp_fs, "delete_content", {"path": "logo.png", "sha": _sha(PNG_BYTES)})
    assert not temp_fs.file_exists("logo.png")


async def test_delete_binary_with_stale_sha_reports_raw_sha(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    with pytest.raises(Exception, match=f"expected {_sha(PNG_BYTES)}"):
        await _call(temp_fs, "delete_content", {"path": "logo.png", "sha": "0" * 64})
    assert temp_fs.file_exists("logo.png")


async def test_delete_crlf_text_accepts_text_or_raw_sha(temp_fs, mock_context):
    raw = b"line one\r\nline two\r\n"
    text_sha = _sha(b"line one\nline two\n")  # what read_content returns
    assert text_sha != _sha(raw)
    for sha in (text_sha, _sha(raw)):
        temp_fs.write_bytes("notes.md", raw)
        read = _data(await _call(temp_fs, "read_content", {"path": "notes.md"}))
        assert read["sha"] == text_sha
        await _call(temp_fs, "delete_content", {"path": "notes.md", "sha": sha})
        assert not temp_fs.file_exists("notes.md")


async def test_delete_text_stale_sha_reports_text_sha(temp_fs, mock_context):
    temp_fs.write_bytes("notes.md", b"a\r\nb\r\n")
    text_sha = _sha(b"a\nb\n")
    with pytest.raises(Exception, match=f"expected {text_sha}"):
        await _call(temp_fs, "delete_content", {"path": "notes.md", "sha": "0" * 64})
    assert temp_fs.file_exists("notes.md")


# --- end-to-end through MCP tools only ---


async def test_binary_lifecycle_through_tools(temp_fs, mock_context):
    """Upload, replace and delete an image using only MCP tools."""
    up = _data(await _upload(temp_fs, {"path": "img/logo.png", "data_base64": _b64(PNG_BYTES)}))
    assert up["created"] is True
    assert temp_fs.read_bytes("img/logo.png") == PNG_BYTES

    rep = _data(await _upload(temp_fs, {
        "path": "img/logo.png", "data_base64": _b64(PNG_V2), "sha": up["sha"],
    }))
    assert rep["created"] is False
    assert temp_fs.read_bytes("img/logo.png") == PNG_V2

    # The pre-replace sha is stale now.
    with pytest.raises(Exception, match="SHA mismatch"):
        await _call(temp_fs, "delete_content", {"path": "img/logo.png", "sha": up["sha"]})

    await _call(temp_fs, "delete_content", {"path": "img/logo.png", "sha": rep["sha"]})
    assert not temp_fs.file_exists("img/logo.png")


async def test_text_upload_readable_and_deletable(temp_fs, mock_context):
    """A text document uploaded byte-for-byte works with the text tools."""
    raw = b"# Notes\r\nbody\r\n"
    up = _data(await _upload(temp_fs, {"path": "notes.md", "data_base64": _b64(raw)}))
    read = _data(await _call(temp_fs, "read_content", {"path": "notes.md"}))
    assert read["content"] == "# Notes\nbody\n"
    # Both the upload sha and the read_content sha identify the same file.
    assert read["sha"] != up["sha"]
    await _call(temp_fs, "delete_content", {"path": "notes.md", "sha": up["sha"]})
    assert not temp_fs.file_exists("notes.md")


# --- sha check and write must not interleave with other writes ---


async def _race(fs, first, second):
    """Start two tool calls concurrently, first one first; return outcomes."""
    import asyncio

    server = create_mcp_server(fs)

    async def run(name, args):
        tool = await server.get_tool(name)
        try:
            await tool.run(args)
            return "ok"
        except Exception as e:  # noqa: BLE001
            return e

    return await asyncio.gather(run(*first), run(*second))


async def test_delete_does_not_remove_concurrent_overwrite(temp_fs, mock_context):
    temp_fs.write_file("doc.md", "v1\n")
    sha = _sha(b"v1\n")
    deleted, overwritten = await _race(
        temp_fs,
        ("delete_content", {"path": "doc.md", "sha": sha}),
        ("overwrite_content", {"path": "doc.md", "sha": sha, "content": "v2\n"}),
    )
    # Exactly one of the two writes holding the same sha may win.
    assert deleted == "ok"
    assert overwritten != "ok"
    assert not temp_fs.file_exists("doc.md")


async def test_replace_upload_does_not_clobber_concurrent_replace(temp_fs, mock_context):
    temp_fs.write_bytes("logo.png", PNG_BYTES)
    sha = _sha(PNG_BYTES)
    a, b = await _race(
        temp_fs,
        ("upload_content", {"path": "logo.png", "data_base64": _b64(PNG_V2), "sha": sha}),
        ("delete_content", {"path": "logo.png", "sha": sha}),
    )
    assert a == "ok"
    assert b != "ok"
    assert temp_fs.read_bytes("logo.png") == PNG_V2


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

    results = await asyncio.gather(
        replace(PNG_V2), replace(PNG_BYTES + b"\x00"), return_exceptions=True
    )
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 1
    assert "SHA mismatch" in str(failures[0])
