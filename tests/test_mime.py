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
        ("clip.mp3", "audio/mpeg"),      # already worked
        ("clip.opus", "audio/opus"),     # already worked
        ("doc.pdf", "application/pdf"),
    ],
)
def test_guess_mime_type(name, want):
    assert server._guess_mime_type(Path(name)) == want


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
