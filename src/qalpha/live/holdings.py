"""Live Zerodha holdings reader → a ``Portfolio`` the advisor/dashboard can consume (plan item #3).

The advisor and dashboard are source-agnostic: they operate on a :class:`Portfolio`. The paper book
provides one today; this module provides the **same shape from the real account** once it is funded —
``kite.holdings()`` for positions + average cost, ``kite.ltp()`` for live prices. Swapping the source
is then a one-line change at the call site (e.g. the dashboard's ``_load``).

**Important tax caveat (why the tradebook still matters):** ``holdings()`` reports only a *blended
average price* and total quantity per scrip — it carries **no per-lot acquisition dates**. FIFO
capital-gains tax (STCG vs LTCG, the ₹1.25L exemption, the 365-day line) needs those dates. So
:func:`portfolio_from_holdings` builds **one undated lot per holding** at the average price unless it
is given real dated lots (reconstructed from a Console tradebook export — that is the criterion-4
work). Without dated lots the holding period is unknown; callers must treat the tax as approximate and
say so. This module flags that via :attr:`LiveHoldings.lots_dated`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kiteconnect import KiteConnect

from qalpha.accounting.tax_lots import TaxLot
from qalpha.backtest.portfolio import Portfolio, to_decimal_price
from qalpha.config import Config

# Zerodha exchange → our yfinance-style suffix (the price panel / universe convention).
_EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


@dataclass(frozen=True)
class Holding:
    """One holding from ``kite.holdings()``, normalized to our ticker convention."""

    ticker: str  # e.g. "RELIANCE.NS" (our convention)
    tradingsymbol: str  # e.g. "RELIANCE" (Zerodha)
    exchange: str  # e.g. "NSE"
    quantity: Decimal
    average_price: Decimal
    last_price: Decimal


def to_ticker(tradingsymbol: str, exchange: str) -> str:
    """Map a Zerodha (tradingsymbol, exchange) to our yfinance-style ticker (RELIANCE → RELIANCE.NS)."""
    return f"{tradingsymbol}{_EXCHANGE_SUFFIX.get(exchange, '.NS')}"


def fetch_holdings(kite: KiteConnect) -> list[Holding]:
    """Read the account's delivery holdings (settled + T1), normalized. Empty list if none.

    ``quantity`` includes T1 (bought, not yet settled) shares so the view matches what the user sees;
    zero-quantity rows (fully sold, awaiting settlement) are dropped.
    """
    out: list[Holding] = []
    for h in kite.holdings():
        qty = Decimal(str(h.get("quantity", 0))) + Decimal(str(h.get("t1_quantity", 0)))
        if qty <= 0:
            continue
        exchange = str(h.get("exchange", "NSE"))
        out.append(
            Holding(
                ticker=to_ticker(str(h["tradingsymbol"]), exchange),
                tradingsymbol=str(h["tradingsymbol"]),
                exchange=exchange,
                quantity=qty,
                average_price=to_decimal_price(float(h.get("average_price", 0.0))),
                last_price=to_decimal_price(float(h.get("last_price", 0.0))),
            )
        )
    return out


def fetch_prices(kite: KiteConnect, holdings: list[Holding]) -> dict[str, Decimal]:
    """Live last-traded prices for ``holdings`` via ``kite.ltp()``, keyed by our ticker."""
    if not holdings:
        return {}
    instruments = [f"{h.exchange}:{h.tradingsymbol}" for h in holdings]
    quotes = kite.ltp(instruments)
    by_ticker: dict[str, Decimal] = {}
    for h in holdings:
        key = f"{h.exchange}:{h.tradingsymbol}"
        q = quotes.get(key)
        if q is not None and q.get("last_price"):
            by_ticker[h.ticker] = to_decimal_price(float(q["last_price"]))
        else:
            by_ticker[h.ticker] = h.last_price  # fall back to the holdings snapshot
    return by_ticker


def fetch_available_cash(kite: KiteConnect) -> Decimal:
    """Available equity cash (``margins('equity')['net']``) — the deployable balance."""
    margins = kite.margins("equity")
    net = margins.get("net", 0.0) if isinstance(margins, dict) else 0.0
    return to_decimal_price(float(net))


def prices_from_holdings(holdings: list[Holding]) -> dict[str, Decimal]:
    """Marking prices straight from the holdings snapshot (no extra ``ltp()`` call)."""
    return {h.ticker: h.last_price for h in holdings if h.last_price > 0}


@dataclass(frozen=True)
class LiveHoldings:
    """A live account snapshot as a :class:`Portfolio` plus marking prices and a tax-accuracy flag."""

    portfolio: Portfolio
    prices: dict[str, Decimal]
    lots_dated: bool  # False when lots are undated averages → holding-period (LTCG/STCG) is unknown

    @property
    def tax_caveat(self) -> str | None:
        if self.lots_dated:
            return None
        return (
            "Holding periods are unknown — positions were read from the broker's blended average "
            "price, which carries no purchase dates. Tax figures assume short-term (the conservative "
            "case); import your Zerodha tradebook for exact LTCG/STCG and exemption handling."
        )


def portfolio_from_holdings(
    holdings: list[Holding],
    cfg: Config,
    *,
    as_of: date,
    cash: Decimal = Decimal("0"),
    dated_lots: dict[str, list[TaxLot]] | None = None,
) -> LiveHoldings:
    """Build a :class:`Portfolio` from live holdings (and optional dated lots from a tradebook).

    When ``dated_lots`` is given (real FIFO lots reconstructed from a Console tradebook export, the
    criterion-4 path) it is used verbatim and the result is tax-accurate (``lots_dated=True``).
    Otherwise one lot per holding is created at the average price dated ``as_of`` — quantities and
    market value are exact, but the holding period is not, so ``lots_dated=False``.
    """
    pf = Portfolio(cfg.cost, cfg.tax, cash=cash)
    dated = dated_lots or {}
    all_dated = bool(holdings) and all(h.ticker in dated for h in holdings)
    for h in holdings:
        lots = dated.get(h.ticker)
        if lots:
            for lot in lots:
                pf.ledger.add_lot(lot)
        else:
            pf.ledger.add_lot(
                TaxLot(
                    ticker=h.ticker,
                    acquisition_date=as_of,
                    quantity_original=h.quantity,
                    buy_price=h.average_price,
                )
            )
    return LiveHoldings(
        portfolio=pf,
        prices=prices_from_holdings(holdings),
        lots_dated=all_dated,
    )
