"""The local app — buttons, live progress, the Kite link, and where the tokens go.

### Why a server and not the static file

The static page answers "what did the last run find". It cannot answer "run it now", "log me in",
"which tokens are missing", or "what is it doing at this moment" — a file opened over ``file://``
can run nothing, and that is the browser working correctly.

This is the smallest thing that can: **Python's own http.server, bound to 127.0.0.1 only.** No
framework, no dependency, no cloud, nothing listening on the network. Same `ui.py` rendering as the
file, so there is one visual language and one set of number-formatting rules rather than two.

### What it will not do

**It cannot place an order and there is no code path here that could.** The buttons run analysis,
refresh data and mint a broker session; every one of them ends in a page you read. Orders are yours,
in Kite.

It binds to loopback and prints the URL rather than opening a port on the LAN, because this page
shows an account. And it runs **one job at a time** — two concurrent runs would interleave their
narration into nonsense and race each other on the same ledgers.
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from qalpha.live import ui
from qalpha.live.progress import IST, LOG

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
PAGE_PATH = Path("data/session/qalpha.html")

#: Secrets the system uses, and what each one unlocks. **Names only — a value is never rendered.**
TOKENS: tuple[tuple[str, str], ...] = (
    ("KITE_API_KEY", "your holdings, cash and live prices"),
    ("KITE_API_SECRET", "exchanging a login for a day's session"),
    ("ANTHROPIC_API_KEY", "reading filings (the AI layer)"),
    ("GIST_TOKEN", "the private tradebook store, if you use it"),
)


class Jobs:
    """One job at a time, on a worker thread, with its narration in :data:`LOG`."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, name: str, work: Callable[[], None]) -> bool:
        """``False`` when something is already running — refused, never queued.

        Queueing would let two runs disagree about the same ledgers minutes apart, and the second
        one would look like it had simply taken a long time.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False

            def runner() -> None:
                LOG.begin()
                LOG.say(name, "step")
                try:
                    work()
                except Exception as exc:
                    LOG.end(f"{type(exc).__name__}: {exc}")
                else:
                    LOG.end()

            self._thread = threading.Thread(target=runner, name=name, daemon=True)
            self._thread.start()
            return True


JOBS = Jobs()


def _token_rows() -> list[ui.Row]:
    rows = []
    for name, unlocks in TOKENS:
        present = bool(os.environ.get(name, "").strip())
        rows.append(
            ui.Row(
                cells=[
                    ui.Cell(name, strong=True),
                    ui.Cell("set" if present else "missing", tone="good" if present else "warn"),
                    ui.Cell(unlocks),
                ]
            )
        )
    return rows


def _shell(body: str, *, refresh: bool) -> bytes:
    """The page frame. Auto-refresh only while a job runs — a page that reloads under your cursor
    when nothing is happening is worse than one you refresh yourself."""
    now = datetime.now(IST)
    poll = (
        "<script>setInterval(async()=>{const r=await fetch('/status.json');const s=await r.json();"
        "document.getElementById('feed').innerHTML=s.lines.map(l=>"
        "`<div class=\"qa-line qa-${l.level}\"><span>${l.at}</span> ${l.text}</div>`).join('');"
        "if(!s.running&&document.getElementById('feed').dataset.was==='1'){location.reload();}"
        "document.getElementById('feed').dataset.was=s.running?'1':'0';},900);</script>"
        if refresh
        else ""
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Q-Alpha</title>{ui.stylesheet()}
<style>
 body{{margin:0;padding:18px 22px 60px;background:var(--qa-plane)}}
 .qa-wrap{{max-width:1180px;margin:0 auto}}
 form{{display:inline}}
 .qa-btn{{font:inherit;font-size:.78rem;font-weight:600;padding:.4rem .8rem;border-radius:2px;
   border:1px solid var(--qa-line-2);background:var(--qa-surface);color:var(--qa-ink);cursor:pointer}}
 .qa-btn.primary{{background:var(--qa-accent);border-color:var(--qa-accent);color:#fff}}
 .qa-btn:disabled{{opacity:.5;cursor:not-allowed}}
 .qa-feed{{border:1px solid var(--qa-line);border-radius:3px;background:var(--qa-surface);
   padding:.5rem .7rem;max-height:19rem;overflow:auto;font-family:var(--qa-num);font-size:.74rem}}
 .qa-line{{padding:.1rem 0;color:var(--qa-ink-2)}}
 .qa-line span{{color:var(--qa-muted);margin-right:.5rem}}
 .qa-line.qa-step{{color:var(--qa-ink);font-weight:650}}
 .qa-line.qa-warn{{color:var(--qa-warn-ink)}}
 .qa-line.qa-error{{color:var(--qa-bad-ink)}}
 .qa-line.qa-done{{color:var(--qa-good-ink);font-weight:650}}
 input[type=text]{{font:inherit;font-size:.78rem;padding:.4rem .6rem;border:1px solid var(--qa-line-2);
   border-radius:2px;width:min(560px,100%);background:var(--qa-surface);color:var(--qa-ink)}}
 p{{font-size:.82rem;color:var(--qa-ink-2);line-height:1.5}}
</style></head><body><div class="qa-wrap">
{
        ui.app_bar(
            product="Q-Alpha",
            tagline="local · nothing here places an order",
            chips=[
                ui.Chip(f"{now:%d %b %H:%M} IST", dot=False),
                ui.Chip(
                    "running" if LOG.running else "idle", tone="info" if LOG.running else "neutral"
                ),
                ui.Chip(
                    "read-only",
                    tone="info",
                    title="No code path in this server can place an order.",
                ),
            ],
        )
    }
{body}
</div>{poll}</body></html>"""
    return html.encode("utf-8")


def _controls() -> str:
    busy = JOBS.busy()
    dis = " disabled" if busy else ""
    return (
        ui.section("Do something", note="each of these ends in a page you read")
        + f"""<p>
<form method="post" action="/run"><button class="qa-btn primary"{dis}>▶ Run the analysis</button></form>
&nbsp;<form method="post" action="/refresh"><button class="qa-btn"{dis}>⭯ Refresh market data</button></form>
&nbsp;<form method="post" action="/evidence"><button class="qa-btn"{dis}>📄 Read new filings</button></form>
&nbsp;<form method="post" action="/login"><button class="qa-btn"{dis}>🔑 Log in to Zerodha</button></form>
</p>"""
        + (
            "<p><b>A job is running.</b> This page follows it below and reloads when it finishes.</p>"
            if busy
            else ""
        )
    )


def _kite_panel(message: str = "") -> str:
    """The login flow, in the two steps it actually has."""
    note = f"<p>{message}</p>" if message else ""
    return (
        ui.section("Zerodha session", note="expires ~6am IST, so most days it will ask")
        + note
        + """<p>Press <b>Log in to Zerodha</b> above. Your browser opens Kite; after you approve it,
Kite redirects to a URL containing <code>request_token=…</code>. If the redirect lands somewhere
that cannot catch it, copy the whole address bar and paste it here.</p>
<form method="post" action="/token">
  <input type="text" name="redirect" placeholder="paste the redirect URL, or just the request_token"
         autocomplete="off">
  <button class="qa-btn">Use this token</button>
</form>
<p>The session is minted locally and written to your <code>.env</code>. It is never sent anywhere
except to Kite, and this page never displays it.</p>"""
    )


def _tokens_panel() -> str:
    return (
        ui.section("Credentials", note="names and presence only — a value is never shown here")
        + ui.table(
            [ui.Column("Variable"), ui.Column("State"), ui.Column("What it unlocks")],
            _token_rows(),
        )
        + """<p>These live in <code>.env</code> at the repo root — copy <code>.env.example</code>
and fill it in. A missing one is not an error: the run degrades to a named absence and says which
figures it therefore cannot confirm. Restart this app after editing <code>.env</code>.</p>"""
    )


def _feed_panel() -> str:
    snap = LOG.snapshot()
    raw = snap.get("lines")
    entries: list[dict[str, str]] = raw if isinstance(raw, list) else []
    lines = "".join(
        f'<div class="qa-line qa-{escape_level(line.get("level"))}">'
        f"<span>{_escape(line.get('at'))}</span> {_escape(line.get('text'))}</div>"
        for line in entries
    )
    elapsed = snap.get("elapsed_seconds")
    note = f"{elapsed}s" if isinstance(elapsed, int) else "nothing has run yet this session"
    return (
        ui.section("What it is doing", note=str(note))
        + f'<div class="qa-feed" id="feed" data-was="{"1" if LOG.running else "0"}">{lines}</div>'
    )


def escape_level(level: object) -> str:
    return str(level) if str(level) in ("step", "detail", "warn", "error", "done") else "detail"


def _escape(text: object) -> str:
    from html import escape

    return escape(str(text))


def _last_report() -> str:
    """The most recent run's page, inlined. Absent is a sentence, not a blank."""
    if not PAGE_PATH.exists():
        return (
            ui.section("The account")
            + '<div class="qa-empty">No run yet this install. Press <b>Run the analysis</b>.</div>'
        )
    html = PAGE_PATH.read_text(encoding="utf-8")
    body = html.split("<body>", 1)[-1].split("</body>", 1)[0] if "<body>" in html else ""
    # The report brings its own <style>; the shell already carries the same stylesheet, so the
    # duplicate is dropped rather than shipped twice.
    return body.replace("</div>", "</div>", 1)


class Handler(BaseHTTPRequestHandler):
    server_version = "QAlpha/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return  # the page narrates itself; an access log on top of it is noise

    def _send(self, payload: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # This page shows an account. Nothing about it should be cached or embedded elsewhere.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, to: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/status.json":
            self._send(json.dumps(LOG.snapshot()).encode(), "application/json")
            return
        if route != "/":
            self.send_error(404)
            return
        message = parse_qs(urlparse(self.path).query).get("m", [""])[0]
        body = (
            _controls()
            + _feed_panel()
            + _last_report()
            + _kite_panel(_escape(message) if message else "")
            + _tokens_panel()
        )
        self._send(_shell(body, refresh=True))

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        actions = _ACTIONS
        if route == "/token":
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = parse_qs(self.rfile.read(length).decode()).get("redirect", [""])[0]
            self._redirect("/?m=" + _use_token(raw))
            return
        action = actions.get(route)
        if action is None:
            self.send_error(404)
            return
        name, work = action
        started = JOBS.start(name, work)
        self._redirect("/" if started else "/?m=Something+is+already+running.")


def _use_token(raw: str) -> str:
    """Exchange a pasted redirect for a day's session. Returns a message for the page."""
    from urllib.parse import quote

    if not raw.strip():
        return quote("Nothing pasted.")
    try:
        from qalpha.live.auth import exchange, parse_request_token
        from qalpha.live.credentials import load_credentials

        exchange(load_credentials(), parse_request_token(raw))
    except Exception as exc:
        return quote(f"That token was not accepted: {type(exc).__name__}: {exc}")
    return quote("Logged in. Run the analysis to use the fresh session.")


def _job_run() -> None:
    import local_run

    LOG.say("Reconciling the account and screening.", "step")
    local_run.main(["--no-open"])
    LOG.say(f"Wrote {PAGE_PATH}", "done")


def _job_refresh() -> None:
    LOG.say("Refreshing prices and the benchmark from yfinance.", "step")
    import paper

    paper._refresh_prices()
    LOG.say("Prices refreshed.", "done")


def _job_evidence() -> None:
    LOG.say("Reading new filings. This is the slow one — it downloads and extracts.", "step")
    import evidence

    evidence.main(["daily"])


def _job_login() -> None:
    from qalpha.live.auth import capture_request_token, exchange, login_url
    from qalpha.live.credentials import load_credentials

    creds = load_credentials()
    url = login_url(creds.api_key)
    LOG.say("Opening Kite in your browser…", "step")
    LOG.say(url, "detail")
    webbrowser.open(url)
    LOG.say("Waiting for the redirect (paste it on the page if it does not arrive).", "detail")
    exchange(creds, capture_request_token())
    LOG.say("Session minted and written to .env.", "done")


_ACTIONS: dict[str, tuple[str, Callable[[], None]]] = {
    "/run": ("Run the analysis", _job_run),
    "/refresh": ("Refresh market data", _job_refresh),
    "/evidence": ("Read new filings", _job_evidence),
    "/login": ("Log in to Zerodha", _job_login),
}


def serve(port: int = DEFAULT_PORT, *, open_browser: bool = True) -> None:
    """Run until interrupted. Loopback only — this page shows an account."""
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    print(f"Q-Alpha is at {url}")
    print("Nothing here places an order. Ctrl-C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
