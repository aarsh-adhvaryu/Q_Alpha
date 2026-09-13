"""The local app: the page, a button to run the evening, and a feed that narrates it.

**Python's own http.server, bound to 127.0.0.1 only.** No framework, no cloud, nothing listening on
the network. It runs **one job at a time** — two concurrent runs would interleave their narration
and race each other on the same ledgers.

**It cannot place an order and there is no code path here that could.** Every button runs analysis
or refreshes data and ends in the page.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from qalpha.live import browser
from qalpha.live import build as build_info
from qalpha.live.progress import IST, LOG

HOST = "127.0.0.1"
DEFAULT_PORT = 8787
#: What the last evening said about itself — failures, skips, what moved. Written by ``local_run``.
LAST_RUN = Path("data/session/last_run.json")

APP_CSS = """<style>
form{display:inline}
.btn{font:inherit;font-size:13px;font-weight:600;padding:7px 12px;border-radius:8px;cursor:pointer;
 border:1px solid var(--line);background:var(--card);color:var(--ink)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn:disabled{opacity:.5;cursor:not-allowed}
.feed{max-height:16rem;overflow:auto;font:12px/1.5 ui-monospace,Consolas,monospace}
.feed div{color:var(--dim)} .feed .step{color:var(--ink);font-weight:600}
.feed .warn{color:var(--warn)} .feed .error{color:var(--down)} .feed .done{color:var(--up)}
.feed span{margin-right:8px}
.notes li{margin:2px 0}
</style>"""


class Jobs:
    """One job at a time, on a worker thread, with its narration in :data:`LOG`."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, name: str, work: Callable[[], None]) -> bool:
        """``False`` when something is already running — refused, never queued."""
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


def _level(level: object) -> str:
    return str(level) if str(level) in ("step", "detail", "warn", "error", "done") else "detail"


def _top(message: str = "") -> str:
    """Controls, the live feed, and what the last evening said about itself."""
    build = build_info.current()
    dis = " disabled" if JOBS.busy() else ""
    stale = (
        f'<div class="banner"><b class="down">This app is running old code.</b> '
        f"{escape(build.sentence())}</div>"
        if build.stale
        else ""
    )
    snap = LOG.snapshot()
    raw = snap.get("lines")
    lines = raw if isinstance(raw, list) else []
    feed = "".join(
        f'<div class="{_level(line.get("level"))}"><span>{escape(str(line.get("at")))}</span>'
        f"{escape(str(line.get('text')))}</div>"
        for line in lines
    )
    elapsed = snap.get("elapsed_seconds")
    status = "running" if LOG.running else (f"{elapsed}s" if isinstance(elapsed, int) else "idle")
    return f"""{APP_CSS}{stale}
<div class="card wide" style="margin-bottom:16px">
  <h2>Run</h2>
  <p class="note">{escape(build.chip_text())} · {escape(status)}
   {("· " + escape(message)) if message else ""}</p>
  <p>
  <form method="post" action="/run"><button class="btn primary"{dis}>▶ Run the evening</button></form>
  <form method="post" action="/refresh"><button class="btn"{dis}>⭯ Refresh prices</button></form>
  <form method="post" action="/redraw"><button class="btn"{dis}>↻ Redraw the page</button></form>
  </p>
  <p class="note"><b>Run the evening</b> pulls prices, reads filings and headlines for what SYSTEM
   holds and its candidates, then marks the books. A step already finished against these exact
   inputs is not redone, so an interrupted evening resumes where it stopped.</p>
  <div class="feed" id="feed" data-was="{"1" if LOG.running else "0"}">{feed}</div>
</div>
{_last_run()}"""


def _last_run() -> str:
    """The last evening's own notes. Absent is a sentence, not a blank."""
    if not LAST_RUN.exists():
        return (
            '<div class="banner">No evening has run on this install yet. '
            "Press <b>Run the evening</b>.</div>"
        )
    try:
        data = json.loads(LAST_RUN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return '<div class="banner warn">The last run&rsquo;s notes are unreadable.</div>'
    notes = data.get("notes") if isinstance(data, dict) else None
    when = escape(str(data.get("finished_at", "?"))) if isinstance(data, dict) else "?"
    if not notes:
        return f'<div class="banner">Last evening finished {when} with nothing to report.</div>'
    items = "".join(f"<li>{escape(str(n))}</li>" for n in notes)
    return f'<div class="banner"><b>Last evening ({when})</b><ul class="notes">{items}</ul></div>'


def _bottom() -> str:
    """Who reads the filings, and what the pipeline has actually done — failures included."""
    from qalpha.live.localmodel import choose_backend
    from qalpha.live.session import history

    backend = choose_backend()
    where = {"local": "on this machine", "anthropic": "in the cloud", "none": "not at all"}
    rows = history(limit=12)
    trail = (
        "".join(
            f"<tr><td>{r.at.astimezone(IST):%d %b %H:%M}</td><td>{escape(r.task)}</td>"
            f'<td class="{"up" if r.state == "done" else "down"}">{escape(r.state)}</td>'
            f"<td>{escape(r.detail)}</td></tr>"
            for r in reversed(rows)
        )
        or '<tr><td colspan="4" class="dim">Nothing recorded yet.</td></tr>'
    )
    return f"""<div class="grid" style="margin-top:16px">
  <div class="card wide"><h2>What has run</h2>
    <p class="note">Newest first. A failure stays on file after its later success.</p>
    <div class="scroll"><table><thead><tr><th>When</th><th>Step</th><th>Result</th><th>Detail</th>
    </tr></thead><tbody>{trail}</tbody></table></div></div>
  <div class="card wide"><h2>Who reads the filings: {escape(where[backend.kind])}</h2>
    <p class="note">{escape(backend.note)}</p></div>
</div>
<script>const esc=t=>String(t).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));
setInterval(async()=>{{const r=await fetch('/status.json');const s=await r.json();
const f=document.getElementById('feed');f.innerHTML=s.lines.map(l=>
`<div class="${{esc(l.level)}}"><span>${{esc(l.at)}}</span>${{esc(l.text)}}</div>`).join('');
if(!s.running&&f.dataset.was==='1'){{location.reload();}}f.dataset.was=s.running?'1':'0';}},900);
</script>"""


def page(message: str = "") -> str:
    from qalpha.live.record import dashboard_html

    return dashboard_html(top=_top(message), bottom=_bottom())


class Handler(BaseHTTPRequestHandler):
    server_version = "QAlpha/2.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return  # the page narrates itself

    def _send(self, payload: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
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
        if route == "/record.json":
            from qalpha.live.record import dashboard_data

            self._send(json.dumps(dashboard_data()).encode(), "application/json")
            return
        if route == "/record":
            self._redirect("/")
            return
        if route != "/":
            self.send_error(404)
            return
        message = parse_qs(urlparse(self.path).query).get("m", [""])[0]
        self._send(page(message).encode("utf-8"))

    def do_POST(self) -> None:
        action = _ACTIONS.get(urlparse(self.path).path)
        if action is None:
            self.send_error(404)
            return
        name, work = action
        started = JOBS.start(name, work)
        self._redirect("/" if started else "/?m=Something+is+already+running.")


def _job_run() -> None:
    import local_run

    local_run.main(["--no-open"])


def _job_refresh() -> None:
    import local_run

    local_run.main(["--no-open", "--prices-only"])


def _job_redraw() -> None:
    import local_run

    local_run.main(["--no-open", "--no-pipeline"])


_ACTIONS: dict[str, tuple[str, Callable[[], None]]] = {
    "/run": ("Run the evening", _job_run),
    "/refresh": ("Refresh prices", _job_refresh),
    "/redraw": ("Redraw the page", _job_redraw),
}


def serve(port: int = DEFAULT_PORT, *, open_browser: bool = True, autorun: bool = False) -> None:
    """Run until interrupted. ``autorun`` starts *Run the evening* first — what the desktop click asks.

    **Bound before started**, so the browser lands on a page that is already narrating, and a second
    double-click meets the launcher's "already running" branch instead of a second server.
    """
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    print(f"Q-Alpha is at {url}")
    print("Nothing here places an order. Ctrl-C to stop.")
    if autorun:
        name, work = _ACTIONS["/run"]
        JOBS.start(name, work)
    if open_browser and not browser.open_url(url):
        print(browser.describe_failure(url))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
