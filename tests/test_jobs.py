"""generate_with_files on a long document took longer than the ~30 s a Claude
connector waits, so every call surfaced as a bare "MCP tool call failed"
(2026-10-29, Tuum x BCC MSA). And when Gemini declined (RECITATION) the tool
returned text=null with no reason."""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

gwf = getattr(server.generate_with_files, "fn", server.generate_with_files)
get_result = getattr(server.get_result, "fn", server.get_result)


def _response(text=None, finish="STOP"):
    cand = SimpleNamespace(finish_reason=SimpleNamespace(name=finish), content=None)
    return SimpleNamespace(text=text, candidates=[cand], prompt_feedback=None,
                           usage_metadata=None)


class FakeClient:
    def __init__(self, delay=0.0, response=None, raises=None):
        self.delay, self.response, self.raises, self.calls = delay, response, raises, 0
        self.files = SimpleNamespace(
            get=lambda name: SimpleNamespace(uri=f"https://x/{name}", mime_type="application/pdf"))
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        self.calls += 1
        time.sleep(self.delay)
        if self.raises:
            raise self.raises
        return self.response


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        client = FakeClient(**kw)
        monkeypatch.setattr(server, "client", client)
        monkeypatch.setattr(server, "JOB_WAIT_SECONDS", 0.05)
        return client
    return install


def test_a_quick_answer_comes_back_directly(fake):
    fake(response=_response("Summary of the MSA"))
    res = gwf(prompt="summarise", file_uris=["files/a"])
    assert res["text"] == "Summary of the MSA" and "status" not in res


def test_a_slow_answer_returns_a_job_id_then_the_result(fake):
    client = fake(delay=0.3, response=_response("Late answer"))
    first = gwf(prompt="analyse", file_uris=["files/a"])
    assert first["status"] == "processing" and first["job_id"]
    assert "get_result" in first["message"]
    time.sleep(0.4)
    done = get_result(first["job_id"])
    assert done["text"] == "Late answer" and client.calls == 1


def test_get_result_while_still_running_says_so(fake):
    fake(delay=0.5, response=_response("x"))
    job = gwf(prompt="p", file_uris=["files/a"])["job_id"]
    assert get_result(job)["status"] == "processing"


def test_recitation_is_reported_not_returned_as_null_text(fake):
    fake(response=_response(None, finish="RECITATION"))
    res = gwf(prompt="transcribe verbatim", file_uris=["files/a"])
    assert res["finish_reason"] == "RECITATION"
    assert "verbatim" in res["error"] and "text" not in res


def test_an_api_error_is_returned_with_its_message(fake):
    fake(raises=RuntimeError("400 INVALID_ARGUMENT: file too large"))
    res = gwf(prompt="p", file_uris=["files/a"])
    assert "INVALID_ARGUMENT" in res["error"]


def test_an_unknown_job_id_is_a_clear_error(fake):
    fake(response=_response("x"))
    assert "unknown" in get_result("nope")["error"]
