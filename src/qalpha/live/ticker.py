"""Session-scoped realtime tick streaming (Kite ``KiteTicker`` WebSocket).

True *pushed* ticks while the dashboard tab is open, torn down when it closes. Streamlit Community
Cloud sleeps when idle, which would kill a 24/7 socket — but realtime is only needed while the user
is **looking** at the page, so the socket's lifetime is tied to the browser session, not to an
always-on server: on login a background thread opens ``KiteTicker``, subscribes to the held
instruments, and pushes ticks into a thread-safe :class:`TickStore` the UI fragment reads; when the
session goes away the thread is stopped. The 30 s ``ltp()`` polling stays as the fallback for the
brief window before the socket connects (and whenever it isn't running).

``KiteTicker`` is imported lazily inside :meth:`RealtimeTicker.start`, so this module (and the pure,
unit-tested :class:`TickStore`) import fine without a live broker. The socket itself can only be
verified against a real Kite session on the deployed box.
"""

from __future__ import annotations

import contextlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class TickStore:
    """Thread-safe latest-price store written by the socket thread, read by the UI thread."""

    _prices: dict[int, float] = field(default_factory=dict)
    _updated: dict[int, datetime] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    connected: bool = False
    error: str | None = None

    def update(self, ticks: list[dict[str, Any]]) -> None:
        """Apply a batch of KiteTicker ticks (each has ``instrument_token`` + ``last_price``)."""
        now = datetime.now(UTC)
        with self._lock:
            for t in ticks:
                token = t.get("instrument_token")
                price = t.get("last_price")
                if token is None or price is None:
                    continue
                self._prices[int(token)] = float(price)
                self._updated[int(token)] = now

    def last(self, token: int) -> float | None:
        with self._lock:
            return self._prices.get(int(token))

    def snapshot(self) -> dict[int, float]:
        """A copy of the current token→price map (safe to read from the UI thread)."""
        with self._lock:
            return dict(self._prices)

    def last_update(self) -> datetime | None:
        with self._lock:
            return max(self._updated.values()) if self._updated else None


class RealtimeTicker:
    """Manages one ``KiteTicker`` socket + background thread, pushing ticks into a :class:`TickStore`.

    Lifecycle: :meth:`start` (idempotent) opens the socket in threaded mode and subscribes to
    ``tokens``; :meth:`stop` closes it. Designed to be parked in ``st.session_state`` so it lives
    exactly as long as the browser session.
    """

    def __init__(self, api_key: str, access_token: str, tokens: list[int]) -> None:
        self.api_key = api_key
        self.access_token = access_token
        self.tokens = [int(t) for t in tokens]
        self.store = TickStore()
        self._kws: Any | None = None

    def start(self) -> TickStore:
        """Open the socket (no-op if already started). Returns the live store."""
        if self._kws is not None or not self.tokens:
            return self.store
        from kiteconnect import KiteTicker  # lazy: only needed when actually streaming

        kws = KiteTicker(self.api_key, self.access_token)

        def on_ticks(_ws: Any, ticks: list[dict[str, Any]]) -> None:
            self.store.update(ticks)

        def on_connect(ws: Any, _response: Any) -> None:
            self.store.connected = True
            ws.subscribe(self.tokens)
            ws.set_mode(ws.MODE_LTP, self.tokens)  # LTP-only = lightest payload

        def on_close(_ws: Any, code: Any, reason: Any) -> None:
            self.store.connected = False
            self.store.error = f"socket closed ({code}: {reason})"

        def on_error(_ws: Any, code: Any, reason: Any) -> None:
            self.store.error = f"socket error ({code}: {reason})"

        kws.on_ticks = on_ticks
        kws.on_connect = on_connect
        kws.on_close = on_close
        kws.on_error = on_error
        kws.connect(threaded=True)  # background thread; returns immediately
        self._kws = kws
        return self.store

    def stop(self) -> None:
        if self._kws is not None:
            # best-effort teardown — never let a dying socket break the UI
            with contextlib.suppress(Exception):
                self._kws.close()
            self._kws = None
            self.store.connected = False


def resolve_tokens(kite: Any, symbols: list[str], *, exchange: str = "NSE") -> dict[str, int]:
    """Map tradable symbols (e.g. ``"INFY"``) to their instrument tokens via ``kite.ltp``.

    ``kite.ltp(["NSE:INFY", ...])`` returns each quote's ``instrument_token`` — enough to subscribe,
    without downloading the full instruments dump. Symbols that don't resolve are skipped.
    """
    if not symbols:
        return {}
    keys = [f"{exchange}:{s}" for s in symbols]
    quotes = kite.ltp(keys)
    out: dict[str, int] = {}
    for sym, key in zip(symbols, keys, strict=True):
        q = quotes.get(key)
        if q and "instrument_token" in q:
            out[sym] = int(q["instrument_token"])
    return out
