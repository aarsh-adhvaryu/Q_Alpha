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
    assert "Run the analysis" in body and "Log in to Zerodha" in body


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
