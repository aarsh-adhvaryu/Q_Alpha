"""Tests for the local model path (:mod:`qalpha.live.localmodel`).

The property under test throughout is **which model reads the filings, and whether the run says so
truthfully**. The one that matters most is :func:`test_unreachable_local_does_not_become_a_cloud_call`:
a fallback there would put filing text on the network on the evening the user believed nothing was.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qalpha.live import localmodel
from qalpha.live.announcements import MAX_DOCUMENT_CHARS
from qalpha.live.extraction import PROMPT_CHAR_BUDGET


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate from BOTH the shell and the developer's own ``.env``.

    Clearing the variables stopped being enough once ``configured()`` learned to hydrate ``.env``
    itself — which it had to, because the app is launched from a shortcut whose shell exports
    nothing. Without this, every assertion here would depend on whatever the author happens to have
    configured locally, and the suite would pass or fail by machine.
    """
    from qalpha.live import credentials

    for var in (localmodel.URL_VAR, localmodel.MODEL_VAR, localmodel.CONTEXT_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(credentials, "_ENV_LOADED", False)


def test_no_model_and_no_key_is_a_named_absence() -> None:
    backend = localmodel.choose_backend()
    assert not backend.available
    assert backend.kind == "none"
    assert "unread is not clean" in backend.note.lower()


def test_key_alone_uses_the_cloud_and_says_the_text_left(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    backend = localmodel.choose_backend()
    assert backend.kind == "anthropic"
    assert backend.available
    assert "left this machine" in backend.note
    assert backend.batch_chars == PROMPT_CHAR_BUDGET


def test_configured_local_model_is_preferred_over_a_present_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key in the environment must not override an explicit local choice."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv(localmodel.MODEL_VAR, "qwen2.5:7b")
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "")
    backend = localmodel.choose_backend()
    assert backend.kind == "local"
    assert backend.model == "qwen2.5:7b"
    assert "Nothing left this machine" in backend.note


def test_unreachable_local_does_not_become_a_cloud_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE LOAD-BEARING ONE. Local asked for, local down, key present — and still no network call.

    Falling back here would be a silent substitution of one privacy posture for its opposite, on
    the run where the user was least likely to look.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv(localmodel.MODEL_VAR, "qwen2.5:7b")
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "nothing answered at …")
    backend = localmodel.choose_backend()
    assert backend.kind == "none"
    assert backend.generate is None
    assert "did NOT fall back" in backend.note


def test_local_url_without_a_model_name_refuses_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(localmodel.URL_VAR, "http://127.0.0.1:8080/v1/chat/completions")
    backend = localmodel.choose_backend(prefer_local=True)
    assert backend.kind == "none"
    assert localmodel.MODEL_VAR in backend.note


def test_a_context_too_small_for_one_chunk_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 4k window truncates the tail of a filing while coverage counts it read."""
    monkeypatch.setenv(localmodel.MODEL_VAR, "tiny")
    monkeypatch.setenv(localmodel.CONTEXT_VAR, "4096")
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "")
    backend = localmodel.choose_backend()
    assert backend.kind == "none"
    assert "less than one" in backend.note


def test_a_generous_context_still_never_exceeds_the_prompt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(localmodel.MODEL_VAR, "big")
    monkeypatch.setenv(localmodel.CONTEXT_VAR, "131072")
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "")
    assert localmodel.choose_backend().batch_chars == PROMPT_CHAR_BUDGET


def test_a_modest_context_shrinks_the_batch_but_still_fits_a_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(localmodel.MODEL_VAR, "eight-k")
    monkeypatch.setenv(localmodel.CONTEXT_VAR, "8192")
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "")
    backend = localmodel.choose_backend()
    assert backend.kind == "local"
    assert MAX_DOCUMENT_CHARS <= backend.batch_chars < PROMPT_CHAR_BUDGET


def test_budget_for_never_returns_less_than_a_floor() -> None:
    assert localmodel.budget_for(1) >= 2_000


def test_generate_posts_the_openai_shape_and_reads_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wire format, without a server: what we send and what we make of what comes back."""
    sent: dict[str, Any] = {}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [{"message": {"content": "EVENT: something"}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 3},
                }
            ).encode()

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def _urlopen(request: Any, timeout: float = 0.0) -> _Resp:
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data.decode())
        return _Resp()

    monkeypatch.setattr(localmodel.urllib.request, "urlopen", _urlopen)
    text, usage = localmodel.local_generate("http://127.0.0.1:11434/v1/chat/completions")(
        "qwen2.5:7b", "read this"
    )
    assert text == "EVENT: something"
    assert usage["input"] == 11 and usage["output"] == 3
    assert usage["truncated"] == 0, "a reply that finished is not a reply that was cut off"
    assert sent["body"]["model"] == "qwen2.5:7b"
    assert sent["body"]["messages"] == [{"role": "user", "content": "read this"}]
    # Extraction must be reproducible: the same filing, the same events, on a re-run.
    assert sent["body"]["temperature"] == 0
    assert sent["body"]["stream"] is False


def test_an_empty_reply_is_no_events_rather_than_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Resp:
        status = 200

        def read(self) -> bytes:
            return json.dumps({"choices": []}).encode()

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(localmodel.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert localmodel.local_generate("http://x/v1/chat/completions")("m", "p") == ("", {})


def _listing(*ids: str, body: bytes | None = None, status: int = 200) -> Any:
    """A stand-in for the models route, in the shape Ollama actually answers in."""
    payload = body
    if payload is None:
        payload = json.dumps(
            {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]}
        ).encode()

    class _Resp:
        def __init__(self) -> None:
            self.status = status

        def read(self) -> bytes:
            return payload  # type: ignore[return-value]

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    return _Resp


def test_probe_asks_the_models_route_not_the_chat_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probing must cost nothing and must not look like work."""
    asked: list[str] = []
    resp = _listing("qwen3-8b-32k:latest")

    def _urlopen(url: Any, timeout: float = 0.0) -> Any:
        asked.append(url)
        return resp()

    monkeypatch.setattr(localmodel.urllib.request, "urlopen", _urlopen)
    assert localmodel.probe("http://127.0.0.1:11434/v1/chat/completions") == ""
    assert asked == ["http://127.0.0.1:11434/v1/models"]


# --- the probe has to read the list, not merely reach it -------------------------------------------
#
# `.env` on the machine this was found on named `qwen2.5:7b`; Ollama had `qwen3-8b-32k` and
# `qwen3:8b`. The probe passed, the page said "Filings read locally by qwen2.5:7b", and every
# extraction call came back 404. Everything underneath degraded correctly — no events, no receipt,
# "Filings NOT read" on the buy screen — while the surface said reading was happening.
def _served(monkeypatch: pytest.MonkeyPatch, *ids: str, body: bytes | None = None) -> None:
    resp = _listing(*ids, body=body)
    monkeypatch.setattr(localmodel.urllib.request, "urlopen", lambda url, timeout=0.0: resp())


def test_probe_refuses_a_tag_the_server_does_not_have(monkeypatch: pytest.MonkeyPatch) -> None:
    _served(monkeypatch, "qwen3-8b-32k:latest", "qwen3:8b")
    why = localmodel.probe("http://127.0.0.1:11434/v1/chat/completions", model="qwen2.5:7b")
    assert "does not have qwen2.5:7b" in why
    assert "qwen3-8b-32k:latest" in why and "qwen3:8b" in why, "say what IS there"


def test_probe_accepts_the_short_form_of_an_implicit_latest_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ollama create name -f Modelfile` lists `name:latest`; people write `name` in .env."""
    _served(monkeypatch, "qwen3-8b-32k:latest")
    assert localmodel.probe("http://x/v1/chat/completions", model="qwen3-8b-32k") == ""
    assert localmodel.probe("http://x/v1/chat/completions", model="qwen3-8b-32k:latest") == ""


def test_probe_rejects_a_web_page_that_answers_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open WebUI serves its own HTML at /v1/models on :8080 and 405s the chat route."""
    _served(monkeypatch, body=b"<!doctype html><html><body>Open WebUI</body></html>")
    why = localmodel.probe("http://127.0.0.1:8080/v1/chat/completions", model="qwen3:8b")
    assert "not with a model list" in why and "Open WebUI" in why
    assert localmodel.URL_VAR in why


def test_probe_rejects_a_server_holding_no_models(monkeypatch: pytest.MonkeyPatch) -> None:
    _served(monkeypatch)
    assert "no models loaded" in localmodel.probe("http://x/v1/chat/completions", model="m")


def test_a_tag_the_server_lacks_does_not_become_a_cloud_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same promise as an unreachable server: local was asked for, so local it stays."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv(localmodel.MODEL_VAR, "qwen2.5:7b")
    _served(monkeypatch, "qwen3-8b-32k:latest")
    backend = localmodel.choose_backend()
    assert backend.kind == "none" and backend.generate is None
    assert "did NOT fall back" in backend.note


def test_choose_backend_asks_about_the_model_it_would_actually_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}
    monkeypatch.setenv(localmodel.MODEL_VAR, "qwen3-8b-32k")
    monkeypatch.setattr(
        localmodel, "probe", lambda url, **kw: seen.update(model=kw.get("model", "")) or ""
    )
    localmodel.choose_backend()
    assert seen == {"model": "qwen3-8b-32k"}, "probing a different model than we call is no probe"


# --- thinking, and running out of room ---------------------------------------------------------
def test_the_request_asks_the_model_not_to_think(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qwen3 thinks by default and it is charged to the same cap as the events — 150-220 tokens on
    a one-line answer, out of the 3,000 a whole batch has to fit in."""
    sent = _capture(monkeypatch, {"choices": [{"message": {"content": "ok"}}]})
    localmodel.local_generate("http://x/v1/chat/completions")("m", "p")
    assert sent["body"]["reasoning_effort"] == "none"


def test_a_reply_cut_off_at_the_cap_is_reported_as_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The input fitting the window says nothing about the OUTPUT fitting max_tokens."""
    _capture(
        monkeypatch,
        {"choices": [{"message": {"content": "EVENT: one"}, "finish_reason": "length"}]},
    )
    _text, usage = localmodel.local_generate("http://x/v1/chat/completions")("m", "p")
    assert usage["truncated"] == 1


def test_a_model_that_thought_anyway_is_recorded_rather_than_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture(
        monkeypatch,
        {
            "choices": [
                {
                    "message": {"content": "EVENT: one", "reasoning": "Okay, the user wants…"},
                    "finish_reason": "stop",
                }
            ]
        },
    )
    _text, usage = localmodel.local_generate("http://x/v1/chat/completions")("m", "p")
    assert usage["thought"] == 1 and usage["truncated"] == 0


def test_the_per_call_ceiling_is_shorter_than_the_evening_s_whole_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It was 900 seconds, which is exactly the evidence run's own budget: one wedged call could
    spend the entire evening and cover nothing."""
    monkeypatch.delenv(localmodel.TIMEOUT_VAR, raising=False)
    assert localmodel.timeout_seconds() < 900
    monkeypatch.setenv(localmodel.TIMEOUT_VAR, "45")
    assert localmodel.timeout_seconds() == 45.0
    monkeypatch.setenv(localmodel.TIMEOUT_VAR, "not a number")
    assert localmodel.timeout_seconds() == localmodel.TIMEOUT_SECONDS


def test_the_note_says_the_context_and_that_thinking_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whichever backend is chosen, the page says so in words — including what it was sized to."""
    monkeypatch.setenv(localmodel.MODEL_VAR, "qwen3-8b-32k")
    monkeypatch.setenv(localmodel.CONTEXT_VAR, "32768")
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "")
    backend = localmodel.choose_backend()
    assert backend.context_tokens == 32768
    assert "32,768-token context" in backend.note and "thinking off" in backend.note


def _capture(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> dict[str, Any]:
    """Record the request body and answer with ``payload``. No server, no network."""
    sent: dict[str, Any] = {}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return json.dumps(payload).encode()

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def _urlopen(request: Any, timeout: float = 0.0) -> _Resp:
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data.decode())
        return _Resp()

    monkeypatch.setattr(localmodel.urllib.request, "urlopen", _urlopen)
    return sent


# --- the server is on Windows and this is not ----------------------------------------------------
#
# Ollama on Windows binds the WINDOWS side's 127.0.0.1. WSL2 has its own network namespace, so that
# address is a different machine's loopback: nothing answers, and "nothing answered at
# http://127.0.0.1:11434" is an accurate and useless description of a server running two feet away.
def test_a_wsl_user_is_told_why_their_windows_ollama_is_invisible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qalpha.live import browser

    monkeypatch.setenv(localmodel.MODEL_VAR, "qwen2.5:7b")
    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "nothing answered")
    note = localmodel.choose_backend().note
    assert "WSL" in note
    assert "networkingMode=mirrored" in note
    assert "OLLAMA_HOST=0.0.0.0" in note


def test_the_wsl_advice_is_absent_off_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Linux desktop user with Ollama down does not need Windows instructions."""
    from qalpha.live import browser

    monkeypatch.setenv(localmodel.MODEL_VAR, "qwen2.5:7b")
    monkeypatch.setattr(browser, "is_wsl", lambda: False)
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "nothing answered")
    note = localmodel.choose_backend().note
    assert "WSL" not in note and "wslconfig" not in note


def test_the_no_fallback_promise_survives_the_extra_advice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adding help must not dilute the thing that matters: it did not go to the cloud."""
    from qalpha.live import browser

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv(localmodel.MODEL_VAR, "qwen2.5:7b")
    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setattr(localmodel, "probe", lambda url, **kw: "nothing answered")
    backend = localmodel.choose_backend()
    assert backend.kind == "none"
    assert "did NOT fall back" in backend.note


# --- .env has to be loaded by whoever reads it ----------------------------------------------------
#
# `choose_backend` reads os.environ. Nothing on the app's page path had loaded `.env`, so a freshly
# started server reported "QALPHA_LOCAL_MODEL is unset" while it was set in the file — and told the
# user to go and set a variable they had already set. A run moments later read it correctly, because
# a run touches the broker and the broker loads credentials. Two surfaces, one fact, two answers,
# depending on what else had happened to run first.
#
# Found on Windows on a cold start. It was invisible in WSL because a run had always happened first.
def test_configured_hydrates_dotenv_itself(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from qalpha.live import credentials

    env = tmp_path / ".env"
    env.write_text("QALPHA_LOCAL_MODEL=from-the-file\n", encoding="utf-8")
    monkeypatch.setattr(credentials, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(credentials, "_ENV_LOADED", False)
    monkeypatch.delenv("QALPHA_LOCAL_MODEL", raising=False)

    _url, model, _context = localmodel.configured()
    assert model == "from-the-file", (
        "a reader that trusts someone else to have loaded .env reports absences that are not real"
    )


def test_a_real_shell_variable_still_wins_over_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """load_dotenv does not override, and it must not start: an export is a deliberate act."""
    from qalpha.live import credentials

    (tmp_path / ".env").write_text("QALPHA_LOCAL_MODEL=from-the-file\n", encoding="utf-8")
    monkeypatch.setattr(credentials, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(credentials, "_ENV_LOADED", False)
    monkeypatch.setenv("QALPHA_LOCAL_MODEL", "from-the-shell")

    assert localmodel.configured()[1] == "from-the-shell"
