"""Daily Kite Connect login → access-token flow (Q_alpha.md §6: live data feed).

Kite access tokens are minted via an interactive login and expire ~06:00 IST the next day, so this
must be re-run each trading day. Two capture modes for the post-login redirect, both single-user:

* **auto** — a localhost listener on the app's Redirect URL (``http://127.0.0.1:5000/redirect``)
  grabs the ``request_token`` automatically; you just click the login link.
* **manual** — paste the ``request_token`` from the browser address bar. Use when the redirect can't
  reach this machine (e.g. logging in from a laptop while the code runs on a remote box).

Run::

    uv run python -m qalpha.live.auth            # auto listener on 127.0.0.1:5000
    uv run python -m qalpha.live.auth --manual   # paste the token yourself

The minted token is cached to ``<repo>/.kite_session.json`` (gitignored). Downstream code gets an
authenticated client via :func:`qalpha.live.client.authenticated_kite`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

from qalpha.live.credentials import REPO_ROOT, KiteCredentials, load_credentials

IST = ZoneInfo("Asia/Kolkata")
SESSION_FILE = REPO_ROOT / ".kite_session.json"
LOGIN_BASE = "https://kite.zerodha.com/connect/login"
DEFAULT_PORT = 5000
DEFAULT_PATH = "/redirect"


@dataclass(frozen=True)
class KiteSession:
    access_token: str
    user_id: str
    login_date: str  # ISO date (IST) the token was minted; used for staleness checks

    @property
    def is_fresh(self) -> bool:
        """Kite tokens die ~06:00 IST the next day; 'minted today (IST)' is a safe usable window."""
        return self.login_date == dt.datetime.now(IST).date().isoformat()


def login_url(api_key: str) -> str:
    return f"{LOGIN_BASE}?v=3&api_key={api_key}"


def parse_request_token(raw: str) -> str:
    """Extract the ``request_token`` from a full redirect URL, a bare query string, or a bare token.

    Pure and testable — accepts everything the user might paste in manual mode.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("empty input; expected a request_token or the redirect URL")
    if "request_token" not in raw:
        return raw  # assume a bare token was pasted
    parsed = urlparse(raw)
    query = parsed.query or raw
    tokens = parse_qs(query).get("request_token")
    if not tokens:
        raise ValueError(f"no request_token found in: {raw!r}")
    return tokens[0]


def capture_request_token(
    port: int = DEFAULT_PORT, path: str = DEFAULT_PATH, timeout: int = 300
) -> str:
    """Run a one-shot localhost listener and return the ``request_token`` Kite redirects with."""
    captured: dict[str, str] = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # stdlib-mandated handler name (BaseHTTPRequestHandler)
            parsed = urlparse(self.path)
            if parsed.path != path:
                self.send_response(404)
                self.end_headers()
                return
            tokens = parse_qs(parsed.query).get("request_token")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if tokens:
                captured["request_token"] = tokens[0]
                self.wfile.write(b"<h2>Q-Alpha: login captured.</h2><p>You can close this tab.</p>")
            else:
                self.wfile.write(b"<h2>No request_token in the redirect.</h2>")

        def log_message(self, *_: object) -> None:  # silence default stderr request logging
            return

    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.timeout = 5
    deadline = time.monotonic() + timeout
    try:
        while "request_token" not in captured and time.monotonic() < deadline:
            server.handle_request()  # blocks up to 5s; loops past favicon/other hits
    finally:
        server.server_close()
    if "request_token" not in captured:
        raise TimeoutError(f"no redirect received on 127.0.0.1:{port}{path} within {timeout}s")
    return captured["request_token"]


def exchange(creds: KiteCredentials, request_token: str) -> KiteSession:
    """Trade a ``request_token`` + api_secret for a day's access token (a Kite network call)."""
    kite = KiteConnect(api_key=creds.api_key)
    data = kite.generate_session(request_token, api_secret=creds.api_secret)
    return KiteSession(
        access_token=str(data["access_token"]),
        user_id=str(data.get("user_id", "")),
        login_date=dt.datetime.now(IST).date().isoformat(),
    )


def persist_session(session: KiteSession) -> None:
    SESSION_FILE.write_text(json.dumps(asdict(session), indent=2) + "\n")


def load_cached_session() -> KiteSession | None:
    if not SESSION_FILE.exists():
        return None
    return KiteSession(**json.loads(SESSION_FILE.read_text()))


def get_access_token(*, allow_stale: bool = False) -> str:
    """Return a cached, same-day access token, or raise telling the caller to re-login."""
    session = load_cached_session()
    if session is None:
        raise RuntimeError("No Kite session cached. Run:  uv run python -m qalpha.live.auth")
    if not session.is_fresh and not allow_stale:
        raise RuntimeError(
            f"Kite session is stale (minted {session.login_date}; tokens expire ~06:00 IST). "
            "Re-run:  uv run python -m qalpha.live.auth"
        )
    return session.access_token


def interactive_login(*, manual: bool, port: int = DEFAULT_PORT) -> KiteSession:
    creds = load_credentials()
    url = login_url(creds.api_key)
    print(f"\n1. Open this URL and log in to Zerodha:\n\n   {url}\n")
    if manual:
        request_token = parse_request_token(
            input("2. Paste the request_token (or the full redirect URL): ")
        )
    else:
        print(f"2. Waiting for the redirect on http://127.0.0.1:{port}{DEFAULT_PATH} ...")
        request_token = capture_request_token(port=port)
    session = exchange(creds, request_token)
    persist_session(session)
    print(f"\n✓ Logged in as {session.user_id}. Token cached to {SESSION_FILE.name} (valid today).")
    return session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kite Connect daily login → access token.")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="paste the request_token instead of running the localhost listener",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="listener port (auto mode)")
    args = parser.parse_args(argv)
    try:
        interactive_login(manual=args.manual, port=args.port)
    except (RuntimeError, ValueError, TimeoutError) as exc:
        print(f"login failed: {exc}", file=sys.stderr)
        return 1
    except KiteException as exc:
        print(f"Kite rejected the login: {exc}", file=sys.stderr)
        if "not enabled" in str(exc).lower():
            print(
                "  → 'user not enabled for the app': log in with the SAME Zerodha account whose "
                "Client ID is registered on the app. Check the app's 'Zerodha Client ID' field at "
                "https://developers.kite.trade/apps and confirm the Connect subscription is active.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
