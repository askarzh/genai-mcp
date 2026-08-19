"""The container has no /etc/mime.types (python:3.12-slim ships none), so Python
falls back to its built-in table — which knows .mp3 and .opus but NOT .ogg,
.oga or .m4a. google-genai calls mimetypes.guess_type() and refuses the upload
with "Unknown mime type" when it comes back None, which is what WhatsApp voice
notes (.ogg) hit.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

# Depending on the fastmcp version, @mcp.tool() either returns the plain
# function or wraps it in a FunctionTool exposing the original as .fn.
upload_file = getattr(server.upload_file, "fn", server.upload_file)


@pytest.mark.parametrize(
    "name,want",
    [
        ("voice.ogg", "audio/ogg"),      # WhatsApp voice notes
        ("voice.oga", "audio/ogg"),
        ("memo.m4a", "audio/mp4"),       # iOS voice memos
        ("track.aac", "audio/aac"),
        ("track.flac", "audio/flac"),
    ],
)
def test_registered_types_are_exact(name, want):
    """Types we register ourselves must not vary by host.

    add_type() overrides whatever the platform thinks, so these hold both in
    the slim image (no /etc/mime.types) and on a CI runner that has one.
    """
    assert server._guess_mime_type(Path(name)) == want


@pytest.mark.parametrize(
    "name,family",
    [
        ("clip.mp3", "audio/"),
        ("clip.opus", "audio/"),         # audio/opus bare, audio/ogg with system mime.types
        ("doc.pdf", "application/"),
    ],
)
def test_platform_types_still_resolve(name, family):
    """Types we leave to the platform must still resolve to something sane.

    The exact string is environment-dependent — .opus is audio/opus from
    Python's built-in table but audio/ogg from a system /etc/mime.types — and
    Gemini accepts either. What matters is that it is never None, which is the
    condition google-genai refuses on.
    """
    got = server._guess_mime_type(Path(name))
    assert got is not None and got.startswith(family), got


def test_guess_mime_type_unknown_returns_none():
    assert server._guess_mime_type(Path("mystery.zzz")) is None


def test_upload_file_accepts_explicit_mime_type(tmp_path, monkeypatch):
    """An explicit mime_type must win over anything guessed."""
    f = tmp_path / "voice.ogg"
    f.write_bytes(b"OggS")

    captured = {}

    class FakeFiles:
        def upload(self, file, config=None):
            captured["config"] = config

            class R:
                name, uri, mime_type, size_bytes, state = "files/x", "u", "audio/ogg", 4, "ACTIVE"

            return R()

    monkeypatch.setattr(server, "client", SimpleNamespace(files=FakeFiles()))

    upload_file(str(f), mime_type="audio/vorbis")
    assert captured["config"].mime_type == "audio/vorbis"


def test_upload_file_fills_in_mime_type_for_ogg(tmp_path, monkeypatch):
    """No mime_type given: .ogg must still upload rather than raising."""
    f = tmp_path / "whatsapp_audio.ogg"
    f.write_bytes(b"OggS")

    captured = {}

    class FakeFiles:
        def upload(self, file, config=None):
            captured["config"] = config

            class R:
                name, uri, mime_type, size_bytes, state = "files/x", "u", "audio/ogg", 4, "ACTIVE"

            return R()

    monkeypatch.setattr(server, "client", SimpleNamespace(files=FakeFiles()))

    out = upload_file(str(f))
    assert captured["config"] is not None, "no config passed — the SDK would guess and fail"
    assert captured["config"].mime_type == "audio/ogg"
    assert out["name"] == "files/x"
