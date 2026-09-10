"""The local app — buttons, live progress, the Kite link, and where the tokens go.

A static page cannot run anything: `file://` blocks it, correctly. This is the smallest thing that
can — Python's own http.server on loopback — and these pin the properties that make it safe to point
at an account rather than the HTML it happens to emit.
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from qalpha.live import server
from qalpha.live.progress import Progress


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def app():
    from http.server import ThreadingHTTPServer

    port = _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(port: int, path: str) -> tuple[int, str, dict[str, str]]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    r = conn.getresponse()
    body = r.read().decode()
    headers = {k.lower(): v for k, v in r.getheaders()}
    conn.close()
    return r.status, body, headers


def test_the_page_serves_and_says_it_cannot_trade(app: int) -> None:
    """The claim has to be on the surface, because this is the page with the buttons on it."""
    status, body, _ = _get(app, "/")
    assert status == 200
    assert "nothing here places an order" in body
    assert "Run the evening" in body and "Log in to Zerodha" in body


def test_the_account_page_is_never_cached_or_framed(app: int) -> None:
    """It shows holdings and cash. A cached copy outlives the session that earned it, and a framed
    one can be read by whatever framed it."""
    _, _, headers = _get(app, "/")
    assert headers.get("cache-control") == "no-store"
    assert headers.get("x-frame-options") == "DENY"


def test_status_is_json_and_starts_idle(app: int) -> None:
    status, body, headers = _get(app, "/status.json")
    assert status == 200 and headers["content-type"].startswith("application/json")
    snap = json.loads(body)
    assert set(snap) == {"running", "elapsed_seconds", "failure", "lines"}


def test_an_unknown_route_is_a_404_not_a_page(app: int) -> None:
    assert _get(app, "/../../etc/passwd")[0] == 404
    assert _get(app, "/anything")[0] == 404


def test_no_token_value_can_reach_the_page(app: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """The credentials panel exists to say which are MISSING. Printing one would put a broker secret
    into a browser cache, a screenshot and any screen-share — the panel shows names and presence."""
    monkeypatch.setenv("KITE_API_KEY", "sk-do-not-render-me")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    _, body, _ = _get(app, "/")
    assert "sk-do-not-render-me" not in body
    assert "sk-ant-secret-value" not in body
    assert "KITE_API_KEY" in body and "set" in body


def test_a_missing_token_is_reported_as_missing(app: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIST_TOKEN", raising=False)
    _, body, _ = _get(app, "/")
    assert "GIST_TOKEN" in body and "missing" in body


# --- the job runner -----------------------------------------------------------------------------
def test_one_job_at_a_time_and_the_second_is_refused_not_queued() -> None:
    """Two runs would interleave their narration into nonsense and race on the same ledgers. A
    queued second run is worse than a refused one: it looks like the first simply took a while."""
    jobs = server.Jobs()
    gate = threading.Event()
    assert jobs.start("first", gate.wait)
    assert not jobs.start("second", lambda: None), "the second must be refused"
    assert jobs.busy()
    gate.set()


def test_a_failing_job_is_recorded_and_does_not_kill_the_server() -> None:
    jobs = server.Jobs()
    done = threading.Event()

    def boom() -> None:
        done.set()
        raise RuntimeError("the feed was unreachable")

    assert jobs.start("boom", boom)
    done.wait(timeout=5)
    for _ in range(50):
        if not jobs.busy():
            break
        threading.Event().wait(0.05)
    from qalpha.live.progress import LOG

    assert "the feed was unreachable" in json.dumps(LOG.snapshot())


# --- the narration itself ------------------------------------------------------------------------
def test_the_progress_log_is_bounded_and_never_raises() -> None:
    """A run that emits ten thousand lines must not grow without limit, and a narrator that can
    throw is a narrator that can take down the thing it is describing."""
    from qalpha.live.progress import MAX_LINES

    log = Progress()
    log.begin()
    for i in range(MAX_LINES + 250):
        log.say(f"line {i}")
    snap = log.snapshot()
    lines = snap["lines"]
    assert isinstance(lines, list) and len(lines) == MAX_LINES
    assert lines[-1]["text"] == f"line {MAX_LINES + 249}", "the NEWEST lines survive"


def test_a_step_records_its_own_failure_and_re_raises() -> None:
    """The caller still decides what a failure means; the log only makes sure it was seen."""
    log = Progress()
    log.begin()
    with pytest.raises(ValueError), log.step("fetching filings"):
        raise ValueError("nse said no")
    text = json.dumps(log.snapshot())
    assert "fetching filings" in text and "nse said no" in text


def test_the_log_reports_elapsed_time_while_still_running() -> None:
    """ "Is it stuck or is it working" is only answerable while it is still going."""
    log = Progress()
    log.begin()
    assert log.running and isinstance(log.snapshot()["elapsed_seconds"], int)
    log.end()
    assert not log.running


def test_the_server_binds_loopback_only() -> None:
    """This page shows an account. It must not be reachable from the network."""
    assert server.HOST == "127.0.0.1"
    src = __import__("inspect").getsource(server.serve)
    assert "0.0.0.0" not in src


# --- what the app says about the reader -----------------------------------------------------------
#
# The page must never claim a privacy posture the next run will not honour. It resolves the backend
# live for that reason: a remembered answer would say "local" for as long as it took someone to
# notice their Ollama had stopped.
def test_the_page_says_who_will_read_the_filings(app: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QALPHA_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _status, body, _ = _get(app, "/")
    assert "Who reads the filings" in body
    assert "unread is not clean" in body.lower()


def test_the_page_offers_the_local_route_when_there_is_none_configured(app: int) -> None:
    _status, body, _ = _get(app, "/")
    assert "ollama pull" in body.lower()
    assert "QALPHA_LOCAL_MODEL" in body


def test_the_page_never_prints_a_credential_value(
    app: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Names and presence only — the rule the token panel exists to keep."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-do-not-render-me")
    _status, body, _ = _get(app, "/")
    assert "ANTHROPIC_API_KEY" in body
    assert "sk-ant-do-not-render-me" not in body


def test_the_local_model_variables_are_listed_as_credentials(app: int) -> None:
    _status, body, _ = _get(app, "/")
    assert "QALPHA_LOCAL_MODEL_URL" in body


# --- the two run buttons --------------------------------------------------------------------------
def test_both_run_routes_exist_and_are_distinct() -> None:
    assert "/run" in server._ACTIONS
    assert "/decide" in server._ACTIONS
    assert server._ACTIONS["/run"][1] is not server._ACTIONS["/decide"][1]


def test_decide_only_asks_the_runner_to_skip_the_research(monkeypatch: pytest.MonkeyPatch) -> None:
    """The button's whole meaning is the flag it passes. Assert the flag, not the label."""
    import sys
    import types

    seen: list[list[str]] = []
    stub = types.ModuleType("local_run")
    stub.main = lambda argv: seen.append(list(argv)) or 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "local_run", stub)

    server._job_decide()
    assert seen == [["--no-open", "--no-pipeline"]]

    seen.clear()
    server._job_run()
    assert seen == [["--no-open"]], "the full evening must NOT skip the research"


def test_the_trail_panel_reports_an_empty_history_rather_than_nothing(app: int) -> None:
    _status, body, _ = _get(app, "/")
    assert "What has run" in body


# --- the login button, when there is no browser ---------------------------------------------------
#
# The bug was not that opening failed — inside WSL there is no desktop handler and it always would.
# It was that the app claimed to have opened Kite anyway, so the user sat waiting for a redirect
# that was never coming, next to a terminal error naming a program they had never heard of.
def test_the_login_job_says_so_when_no_browser_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    from qalpha.live import browser, server
    from qalpha.live.progress import LOG

    monkeypatch.setattr(browser, "open_url", lambda url: False)
    monkeypatch.setattr(
        server, "load_credentials", lambda: None, raising=False
    )  # not reached before the open

    class _Creds:
        api_key = "testkey"

    monkeypatch.setattr("qalpha.live.credentials.load_credentials", lambda: _Creds())
    monkeypatch.setattr(
        "qalpha.live.auth.login_url", lambda k: f"https://kite.test/?v=3&api_key={k}"
    )
    monkeypatch.setattr(
        "qalpha.live.auth.capture_request_token",
        lambda: (_ for _ in ()).throw(RuntimeError("stop")),
    )

    LOG.begin()
    with pytest.raises(RuntimeError, match="stop"):
        server._job_login()
    text = " ".join(str(line.get("text", "")) for line in LOG.snapshot()["lines"])  # type: ignore[union-attr]
    assert "Could not open a browser" in text
    assert "paste the address" in text.lower()
    assert "api_key=testkey" in text, "the link itself must be in the feed to copy"


def test_the_login_job_stays_quiet_when_the_browser_does_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warning printed on the happy path teaches people to ignore warnings."""
    from qalpha.live import browser, server
    from qalpha.live.progress import LOG

    class _Creds:
        api_key = "testkey"

    monkeypatch.setattr(browser, "open_url", lambda url: True)
    monkeypatch.setattr("qalpha.live.credentials.load_credentials", lambda: _Creds())
    monkeypatch.setattr("qalpha.live.auth.login_url", lambda k: "https://kite.test/")
    monkeypatch.setattr(
        "qalpha.live.auth.capture_request_token",
        lambda: (_ for _ in ()).throw(RuntimeError("stop")),
    )

    LOG.begin()
    with pytest.raises(RuntimeError, match="stop"):
        server._job_login()
    text = " ".join(str(line.get("text", "")) for line in LOG.snapshot()["lines"])  # type: ignore[union-attr]
    assert "Could not open a browser" not in text


def test_serve_prints_the_url_when_it_cannot_open_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--app` on a headless box must still tell you where the app is."""
    from qalpha.live import browser, server

    monkeypatch.setattr(browser, "open_url", lambda url: False)

    class _StopError(Exception):
        pass

    def _server(addr: object, handler: object) -> object:
        raise _StopError()

    monkeypatch.setattr(server, "ThreadingHTTPServer", _server)
    with pytest.raises(_StopError):
        server.serve(9999, open_browser=True)
