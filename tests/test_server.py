"""The local app — the page, the run button, and live progress.

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
    assert "Nothing on this page places an order" in body
    assert "Run the evening" in body
    assert "Zerodha" not in body, "no broker login exists any more; the page must not offer one"


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
    """A secret on the page ends up in a browser cache, a screenshot and any screen-share."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    _, body, _ = _get(app, "/")
    assert "sk-ant-secret-value" not in body


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


def test_the_page_never_prints_a_credential_value(
    app: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-do-not-render-me")
    _status, body, _ = _get(app, "/")
    assert "sk-ant-do-not-render-me" not in body


# --- the buttons -----------------------------------------------------------------------------------
def test_every_button_is_a_distinct_job() -> None:
    assert set(server._ACTIONS) == {"/run", "/refresh", "/redraw"}
    assert len({work for _name, work in server._ACTIONS.values()}) == 3


@pytest.mark.parametrize(
    ("job", "argv"),
    [
        ("_job_run", ["--no-open"]),
        ("_job_refresh", ["--no-open", "--prices-only"]),
        ("_job_redraw", ["--no-open", "--no-pipeline"]),
    ],
)
def test_each_button_passes_the_flag_that_is_its_meaning(
    monkeypatch: pytest.MonkeyPatch, job: str, argv: list[str]
) -> None:
    """Assert the flag, not the label. The full evening must NOT skip the research."""
    import sys
    import types

    seen: list[list[str]] = []
    stub = types.ModuleType("local_run")
    stub.main = lambda a: seen.append(list(a)) or 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "local_run", stub)
    getattr(server, job)()
    assert seen == [argv]


def test_the_trail_panel_reports_an_empty_history_rather_than_nothing(app: int) -> None:
    _status, body, _ = _get(app, "/")
    assert "What has run" in body


# --- the login button, when there is no browser ---------------------------------------------------
#
# The bug was not that opening failed — inside WSL there is no desktop handler and it always would.
# It was that the app claimed to have opened Kite anyway, so the user sat waiting for a redirect
# that was never coming, next to a terminal error naming a program they had never heard of.
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


class _StubServer:
    def __init__(self, addr: object, handler: object) -> None:
        self.addr = addr

    def serve_forever(self) -> None:
        return None

    def server_close(self) -> None:
        return None


def test_autorun_starts_the_evening_and_only_after_the_socket_is_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bound first: the browser must land on a page that is already narrating, and a second
    double-click must meet the launcher's 'already running' branch rather than a second server."""
    from qalpha.live import browser

    order: list[str] = []

    class _Bound(_StubServer):
        def __init__(self, addr: object, handler: object) -> None:
            order.append("bound")
            super().__init__(addr, handler)

    started: list[str] = []
    monkeypatch.setattr(server, "ThreadingHTTPServer", _Bound)
    monkeypatch.setattr(browser, "open_url", lambda url: True)
    monkeypatch.setattr(
        server.JOBS,
        "start",
        lambda name, work: (order.append("started"), started.append(name), True)[-1],
    )

    server.serve(9998, open_browser=False, autorun=True)
    assert started == ["Run the evening"], "the click runs the evening, not a bare server"
    assert order == ["bound", "started"]


def test_without_autorun_the_app_waits_to_be_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(server, "ThreadingHTTPServer", _StubServer)
    monkeypatch.setattr(server.JOBS, "start", lambda name, work: started.append(name) or True)
    server.serve(9998, open_browser=False)
    assert started == []


def test_the_empty_state_names_a_button_that_exists(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """It said "Press Run the analysis". There is no such button, and the one there is says a
    different thing — an instruction that cannot be followed reads as a broken page."""
    monkeypatch.setattr(server, "LAST_RUN", tmp_path / "never-written.json")
    body = server._last_run()
    assert "Run the evening" in body and "Run the analysis" not in body
