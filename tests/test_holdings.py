"""Live Zerodha holdings reader → Portfolio (plan item #3).

Uses a stub Kite client (the live API is not type-checked or called here) to cover the parsing,
normalization, and Portfolio construction. The tax caveat for undated lots is the key honesty check.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from qalpha.accounting.tax_lots import TaxLot
from qalpha.config import Config
from qalpha.live.holdings import (
    Holding,
    fetch_available_cash,
    fetch_holdings,
    fetch_prices,
    portfolio_from_holdings,
    to_ticker,
)


class _StubKite:
    def __init__(self, holdings=None, ltp=None, margins=None):  # type: ignore[no-untyped-def]
        self._holdings = holdings or []
        self._ltp = ltp or {}
        self._margins = margins or {}

    def holdings(self):  # type: ignore[no-untyped-def]
        return self._holdings

    def ltp(self, instruments):  # type: ignore[no-untyped-def]
        return self._ltp

    def margins(self, segment):  # type: ignore[no-untyped-def]
        return self._margins


def test_to_ticker() -> None:
    assert to_ticker("RELIANCE", "NSE") == "RELIANCE.NS"
    assert to_ticker("RELIANCE", "BSE") == "RELIANCE.BO"
    assert to_ticker("FOO", "MCX") == "FOO.NS"  # unknown exchange defaults to NSE


def test_fetch_holdings_includes_t1_and_drops_zero() -> None:
    kite = _StubKite(
        holdings=[
            {
                "tradingsymbol": "RELIANCE",
                "exchange": "NSE",
                "quantity": 10,
                "t1_quantity": 2,
                "average_price": 2500.0,
                "last_price": 2600.0,
            },
            {"tradingsymbol": "SOLD", "exchange": "NSE", "quantity": 0, "t1_quantity": 0},
        ]
    )
    holdings = fetch_holdings(kite)
    assert len(holdings) == 1
    h = holdings[0]
    assert h.ticker == "RELIANCE.NS"
    assert h.quantity == Decimal("12")  # settled + T1
    assert h.average_price == Decimal("2500.00")


def test_fetch_prices_uses_ltp_then_falls_back() -> None:
    h = Holding("RELIANCE.NS", "RELIANCE", "NSE", Decimal("12"), Decimal("2500"), Decimal("2600"))
    live = fetch_prices(_StubKite(ltp={"NSE:RELIANCE": {"last_price": 2650.0}}), [h])
    assert live["RELIANCE.NS"] == Decimal("2650.00")
    fallback = fetch_prices(_StubKite(ltp={}), [h])
    assert fallback["RELIANCE.NS"] == Decimal("2600.00")  # the holdings snapshot price


def test_fetch_available_cash() -> None:
    assert fetch_available_cash(_StubKite(margins={"net": 54321.0})) == Decimal("54321.00")


def test_portfolio_from_undated_holdings_flags_tax_caveat() -> None:
    h = Holding("RELIANCE.NS", "RELIANCE", "NSE", Decimal("12"), Decimal("2500"), Decimal("2600"))
    live = portfolio_from_holdings([h], Config(), as_of=date(2026, 6, 13), cash=Decimal("1000"))
    assert live.lots_dated is False
    assert live.tax_caveat is not None  # holding period unknown → must warn
    assert live.portfolio.positions() == {"RELIANCE.NS": Decimal("12")}
    assert live.portfolio.cash == Decimal("1000")
    assert live.portfolio.market_value({"RELIANCE.NS": Decimal("2600")}) == Decimal("32200")


def test_portfolio_from_dated_lots_is_accurate() -> None:
    h = Holding("RELIANCE.NS", "RELIANCE", "NSE", Decimal("12"), Decimal("2500"), Decimal("2600"))
    lots = {
        "RELIANCE.NS": [
            TaxLot(
                ticker="RELIANCE.NS",
                acquisition_date=date(2023, 1, 1),
                quantity_original=Decimal("12"),
                buy_price=Decimal("2400"),
            )
        ]
    }
    live = portfolio_from_holdings([h], Config(), as_of=date(2026, 6, 13), dated_lots=lots)
    assert live.lots_dated is True
    assert live.tax_caveat is None
    assert live.portfolio.ledger.open_lots("RELIANCE.NS")[0].acquisition_date == date(2023, 1, 1)
