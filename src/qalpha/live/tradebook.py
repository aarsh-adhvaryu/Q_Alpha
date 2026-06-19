"""Zerodha tradebook → dated FIFO ``Portfolio`` (the criterion-4 path; Q_alpha.md §14 crit 4).

``kite.holdings()`` gives only a blended average price with **no purchase dates**, so it can't drive
FIFO capital-gains tax (STCG vs LTCG, the ₹1.25L exemption, the 365-day line). The **tradebook** —
exported from Zerodha Console (Reports → Tradebook) — is the source of truth: every buy and sell with
its date and price. Replaying it through the *same* validated ``Portfolio`` engine reconstructs the
exact dated FIFO lots and the realized gains, which (a) makes the advisor's tax **exact** and (b) is
what we reconcile against the official Console **Tax P&L** to the rupee.

The Console export is a CSV (there is no API for it); this module parses a path **or any file-like
object**, so the dashboard can hand it the uploaded file directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import IO

import pandas as pd

from qalpha.accounting.capital_gains import RealizedGain
from qalpha.accounting.corporate_actions import CorporateAction
from qalpha.accounting.costs import Side
from qalpha.accounting.tax_lots import InsufficientSharesError
from qalpha.backtest.portfolio import Portfolio, to_decimal_price
from qalpha.config import Config
from qalpha.live.holdings import canonical_ticker

# A sentinel cash balance so replaying buys is never affordability-capped (the trades already
# happened; the tradebook does not encode the cash account). The caller sets real cash afterwards.
_UNCONSTRAINED_CASH = Decimal("1000000000000")

# Column aliases seen across Zerodha Console tradebook exports (headers normalized to snake_case).
_REQUIRED = ("symbol", "trade_date", "trade_type", "quantity", "price")


@dataclass(frozen=True)
class TradebookTrade:
    """One executed trade from the Console tradebook, normalized to our ticker convention."""

    trade_date: date
    ticker: str
    side: Side
    quantity: Decimal
    price: Decimal
    exec_time: str = ""  # order_execution_time, used only to order same-day trades


@dataclass(frozen=True)
class ReplayResult:
    """The reconstructed dated portfolio plus what the replay realized."""

    portfolio: Portfolio
    warnings: list[str]
    realized_tax: Decimal  # total FIFO capital-gains tax across all sells in the tradebook
    n_trades: int
    realized_gains: list[RealizedGain]  # per-lot realized gains from every sell (for crit-4 recon)


def parse_tradebook(source: str | IO[bytes] | IO[str]) -> list[TradebookTrade]:
    """Parse a Zerodha Console tradebook CSV (path or uploaded file) into normalized trades.

    Tolerant to header case/spacing. Any ``exchange`` column is ignored — every symbol resolves to
    its canonical NSE ticker (same ISIN/demat; NSE is our single price/universe source), so a BSE
    leg and its NSE counterpart reconcile to the same lot. Raises if the required columns (symbol,
    trade_date, trade_type, quantity, price) are absent.
    """
    df = pd.read_csv(source)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"tradebook is missing columns {missing}; got {list(df.columns)}")

    has_time = "order_execution_time" in df.columns
    trades: list[TradebookTrade] = []
    for _, row in df.iterrows():
        side = Side.BUY if "buy" in str(row["trade_type"]).strip().lower() else Side.SELL
        trades.append(
            TradebookTrade(
                trade_date=pd.to_datetime(row["trade_date"]).date(),
                ticker=canonical_ticker(str(row["symbol"]).strip()),
                side=side,
                quantity=Decimal(str(int(abs(float(row["quantity"]))))),
                price=to_decimal_price(float(row["price"])),
                exec_time=str(row["order_execution_time"]) if has_time else "",
            )
        )
    return trades


def replay_tradebook(
    trades: list[TradebookTrade],
    cfg: Config,
    *,
    cash: Decimal = Decimal("0"),
    corporate_actions: list[CorporateAction] | None = None,
) -> ReplayResult:
    """Replay ``trades`` chronologically through the engine → a dated FIFO portfolio + realized tax.

    Buys add dated lots; sells consume FIFO and realize gains (so the LTCG/STCG tally and tax are
    exact). A sell that can't be matched (the export started mid-history) is skipped with a warning
    rather than aborting. ``cash`` sets the resulting account balance (the tradebook doesn't encode
    it — pass the live available cash).

    ``corporate_actions`` (§14 criterion 5) are interleaved by date: on each date the action applies
    **first** (a split/bonus reshapes the lots held *into* the ex-date, which is what makes the replay
    reproduce the broker's post-action share count), then that day's buys, then its sells. Without
    this, a held name that split/bonused would fail :func:`reconcile_positions`.
    """
    pf = Portfolio(cfg.cost, cfg.tax, cash=_UNCONSTRAINED_CASH)
    warnings: list[str] = []
    realized_tax = Decimal("0")
    realized_gains: list[RealizedGain] = []
    matched = 0

    # Unified timeline. Phase orders same-date events: corporate action (0) → buy (1) → sell (2).
    events: list[tuple[date, int, str, TradebookTrade | CorporateAction]] = [
        (a.ex_date, 0, "", a) for a in (corporate_actions or [])
    ]
    events += [(t.trade_date, 1 if t.side is Side.BUY else 2, t.exec_time, t) for t in trades]
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    for _d, _phase, _t, payload in events:
        if isinstance(payload, CorporateAction):
            pf.apply_corporate_action(payload)
            continue
        try:
            if payload.side is Side.BUY:
                pf.buy(payload.trade_date, payload.ticker, payload.quantity, payload.price)
            else:
                # Capture the per-lot gains (preview is on the identical pre-sell state) before
                # the sell mutates the ledger, so the crit-4 reconciliation can break down by
                # STCG/LTCG and by symbol.
                gains, _ = pf.preview_sell(
                    payload.trade_date, payload.ticker, payload.quantity, payload.price
                )
                realized_gains.extend(gains)
                realized_tax += pf.sell(
                    payload.trade_date, payload.ticker, payload.quantity, payload.price
                ).tax
            matched += 1
        except InsufficientSharesError as exc:
            warnings.append(
                f"{payload.trade_date}: sell {payload.quantity} {payload.ticker} could not be "
                f"matched ({exc}) — tradebook history may be incomplete."
            )
    pf.cash = cash
    return ReplayResult(
        portfolio=pf,
        warnings=warnings,
        realized_tax=realized_tax,
        n_trades=matched,
        realized_gains=realized_gains,
    )


def reconcile_positions(portfolio: Portfolio, holdings_qty: dict[str, Decimal]) -> list[str]:
    """Compare replayed open positions against live ``holdings()`` quantities; return mismatches.

    An empty list means the tradebook replay reproduces the broker's current holdings exactly (the
    integrity check that the lot reconstruction is complete and correct).
    """
    replayed = portfolio.positions()
    issues: list[str] = []
    for ticker in sorted(set(replayed) | set(holdings_qty)):
        ours = replayed.get(ticker, Decimal("0"))
        theirs = holdings_qty.get(ticker, Decimal("0"))
        if ours != theirs:
            issues.append(f"{ticker}: tradebook {ours} vs broker {theirs}")
    return issues
