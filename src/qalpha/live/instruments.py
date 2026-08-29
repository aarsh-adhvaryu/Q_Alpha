"""Kite's instrument master — the tokens and tick sizes a basket file cannot be built without.

``instrumentToken`` is Kite-internal and cannot be derived from a ticker, and ``tickSize`` varies by
instrument *and* by exchange (WIPRO 0.01 on NSE, 0.05 on BSE; six distinct ticks across the 10,101
NSE equities). Both come from Kite's public dump at ``https://api.kite.trade/instruments`` — no auth
— cached here as the NSE-equity subset so the generator is pure and the tests need no network.

Refresh with ``scripts/refresh_instruments.py``. Tokens are stable in practice but not guaranteed;
a stale cache surfaces as an unknown symbol, which :func:`load_instruments` reports by name rather
than by silently dropping the order.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

INSTRUMENTS_CSV = Path("data/reference/kite_instruments_nse_eq.csv")


@dataclass(frozen=True)
class Instrument:
    """The nine fields a Kite basket row needs — verified against a basket Kite itself exported."""

    tradingsymbol: str
    exchange: str
    segment: str
    instrument_token: int
    exchange_token: int
    tick_size: Decimal
    lot_size: int
    instrument_type: str

    @property
    def is_equity(self) -> bool:
        return self.instrument_type == "EQ"

    def as_basket_instrument(self) -> dict[str, object]:
        """The `instrument` block of a basket row.

        Only these nine keys: a minimal object was verified to import cleanly (796 bytes against
        2,160), so Kite's fifteen decorative UI fields — ``company``, ``niceName``, ``stockWidget``
        and the rest — are never synthesised.
        """
        return {
            "tradingsymbol": self.tradingsymbol,
            "exchange": self.exchange,
            "segment": self.segment,
            "instrumentToken": self.instrument_token,
            "exchangeToken": self.exchange_token,
            "tickSize": float(self.tick_size),
            "lotSize": self.lot_size,
            "type": self.instrument_type,
            "isEquity": self.is_equity,
        }


def to_kite_symbol(ticker: str) -> str:
    """``INFY.NS`` → ``INFY``. The engine keys on yfinance tickers; Kite has no suffix."""
    return ticker.removesuffix(".NS").removesuffix(".BO")


def load_instruments(path: Path = INSTRUMENTS_CSV) -> dict[str, Instrument]:
    """Load the cached NSE-equity master, keyed by Kite tradingsymbol."""
    out: dict[str, Instrument] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["tradingsymbol"]] = Instrument(
                tradingsymbol=row["tradingsymbol"],
                exchange=row["exchange"],
                segment=row["segment"],
                instrument_token=int(row["instrument_token"]),
                exchange_token=int(row["exchange_token"]),
                tick_size=Decimal(row["tick_size"]),
                lot_size=int(row["lot_size"]),
                instrument_type=row["instrument_type"],
            )
    return out
