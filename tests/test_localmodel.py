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
    assert usage == {"input": 11, "output": 3}
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


def test_probe_asks_the_models_route_not_the_chat_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Probing must cost nothing and must not look like work."""
    asked: list[str] = []

    class _Resp:
        status = 200

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def _urlopen(url: Any, timeout: float = 0.0) -> _Resp:
        asked.append(url)
        return _Resp()

    monkeypatch.setattr(localmodel.urllib.request, "urlopen", _urlopen)
    assert localmodel.probe("http://127.0.0.1:11434/v1/chat/completions") == ""
    assert asked == ["http://127.0.0.1:11434/v1/models"]


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
