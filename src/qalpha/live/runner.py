"""One day of an autonomous twin book — the step that turns a policy into decisions.

Phase 2 gave five books identical cash flows; Phase 3's :mod:`qalpha.live.policy` gave four of them a
configuration. This is what makes them *act*, once per day, and record why.

**Order matters and is deliberate.** Harvest → exits → hedge → deploy:

1. **Harvest** first, because its opportunity is a *date* (31 March) and a later exit could consume
   the very lots that carried the reachable loss.
2. **Exits** next, so cash freed by an exit is available to the deploy step in the same pass rather
   than idling a day.
3. **Hedge** before deploying, since the hedge decision reads the book's exposure and must not be
   computed against a position the same step is about to change.
4. **Deploy** last, spending whatever cash the earlier steps left.

**Every branch emits a Decision, including doing nothing.** A book that holds must say it held —
silence and a dead runner are otherwise indistinguishable, which is exactly how a forward run died
unnoticed for 38 days.

**Nothing here touches Zerodha.** These are fake-money books; the user places every real order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.config import Config
from qalpha.live.advisor import advise_harvest
from qalpha.live.hedge import hedge_active, hedge_availability, stress_gauge
from qalpha.live.policy import (
    DEPLOY,
    EXIT,
    HARVEST,
    HEDGE_OFF,
    HEDGE_ON,
    HOLD,
    Decision,
    Policy,
)
from qalpha.live.position_health import position_health
from qalpha.live.twin import TwinBook

#: Gauge threshold and persistence for the overlay — the validated research parameters.
HEDGE_TAU = 0.7
HEDGE_PERSIST = 3


@dataclass(frozen=True)
class Market:
    """Everything a step needs to know about the world on one day, gathered by the caller.

    Passed in rather than fetched so a step is pure: same market, same book, same decisions. That is
    what makes an autonomous book replayable — and a book whose past decisions cannot be reproduced
    cannot be audited when it turns out to have been wrong.
    """

    as_of: date
    prices: dict[str, Decimal]
    #: The benchmark **price series** — in practice NIFTYBEES, an ETF trading near ₹276, not the
    #: Nifty index level near 27,574. Correct for :func:`stress_gauge`, which reads a drawdown
    #: *ratio* and is therefore scale-invariant. **Never a substitute for the index level.**
    index_close: pd.Series
    adj_close: pd.DataFrame
    #: The actual Nifty index level, for anything that multiplies by a futures lot size. ``None``
    #: when nothing supplies it, which must produce CANNOT ASSESS rather than a number.
    index_level: float | None = None
    rebase_from: dict[str, date] | None = None
    exclude: set[str] | None = None
    #: Watchlist inputs for the deploy step. Absent → the book cannot deploy and says so.
    watchlist: list[str] | None = None
    sector_of: dict[str, str] | None = None
    wl_prices: object | None = None  # PriceData for the watchlist panel
    #: Per-name AI keep/drop, gathered by the caller. Injected rather than fetched so a step stays
    #: pure and replayable — and so an AI outage degrades TWIN_FULL to TWIN_NO_AI, never to nothing.
    ai_verdicts: dict[str, str] | None = None


def step(
    book: TwinBook, policy: Policy, market: Market, cfg: Config | None = None
) -> list[Decision]:
    """Run one day for one book, **execute** what it decided, and return the decisions with reasons.

    Execution is not optional. The first live run produced 60 decisions and left every book at ₹0
    gain with zero lots, because ``step`` computed a plan and never touched the portfolio — a
    decision log wearing a book's clothes. The comparison only means something if the books actually
    hold what they chose.
    """
    cfg = cfg or Config()
    out: list[Decision] = []
    out += _harvest(book, policy, market, cfg)
    out += _exits(book, policy, market)
    out += _hedge(book, policy, market)
    out += _deploy(book, policy, market, cfg)
    _execute(book, out, market)
    if not out:
        out.append(
            Decision(
                on=market.as_of,
                book=book.name,
                action=HOLD,
                reason="no harvest worth its round trip, no breakdown, hedge unchanged",
            )
        )
    return out


def _execute(book: TwinBook, decisions: list[Decision], market: Market) -> None:
    """Apply the day's decisions to the book, through the validated FIFO/cost/tax engine.

    Sells before buys, so cash freed by a harvest or an exit is spendable the same day rather than
    idling until tomorrow. ``HEDGE_ON``/``HEDGE_OFF`` move no shares — the overlay is a futures
    position outside the equity book — so they are recorded and not executed here.
    """
    for d in decisions:
        if d.ticker is None or d.quantity is None or d.quantity <= 0:
            continue
        price = market.prices.get(d.ticker)
        if price is None or price <= 0:
            continue
        if d.action in (HARVEST, EXIT):
            held = book.portfolio.ledger.quantity_held(d.ticker)
            qty = min(d.quantity, held)
            if qty > 0:
                book.portfolio.sell(market.as_of, d.ticker, qty, price)
    for d in decisions:
        if d.action != DEPLOY or d.ticker is None or d.quantity is None or d.quantity <= 0:
            continue
        price = market.prices.get(d.ticker)
        if price is not None and price > 0:
            book.portfolio.buy(market.as_of, d.ticker, d.quantity, price)


def _harvest(book: TwinBook, policy: Policy, market: Market, cfg: Config) -> list[Decision]:
    """Bank reachable losses. Never ablated — it is not a strategy bet (see `policy.Policy`)."""
    advice = advise_harvest(book.portfolio, market.prices, market.as_of, cfg)
    return [
        Decision(
            on=market.as_of,
            book=book.name,
            action=HARVEST,
            ticker=c.ticker,
            quantity=c.quantity,
            reason=(
                f"banks ₹{-c.net_gain:,.0f} of loss against ₹{c.charges:,.0f} round trip; "
                f"{c.lots_consumed} FIFO lot(s), ₹{c.gain_crossed:,.0f} of gain crossed; "
                f"{advice.days_to_fy_end}d to 31 March"
            ),
        )
        for c in advice.actionable
    ]


def _exits(book: TwinBook, policy: Policy, market: Market) -> list[Decision]:
    """§4.7 idiosyncratic breakdown. Removed entirely in TWIN_NO_EXITS — the ablation."""
    if not policy.use_exits:
        return []
    held = sorted(book.portfolio.positions())
    if not held:
        return []
    report = position_health(
        market.adj_close,
        held,
        market.as_of,
        rebase_from=market.rebase_from,
        exclude=market.exclude,
    )
    return [
        Decision(
            on=market.as_of,
            book=book.name,
            action=EXIT,
            ticker=h.ticker,
            quantity=book.portfolio.ledger.quantity_held(h.ticker),
            reason=(
                f"§4.7 breakdown: {h.trailing_return:+.0%} vs market {h.excess_vs_market:+.0%} — "
                "name-specific, not a market move"
            ),
        )
        for h in report.breaking
    ]


def _hedge(book: TwinBook, policy: Policy, market: Market) -> list[Decision]:
    """Short-index overlay while stress is elevated. Removed in TWIN_NO_HEDGE — the ablation.

    ⚠️ **This moves no money, and now says so.** The overlay needs a whole Nifty futures contract; a
    ₹3L book cannot hold one, so ``TWIN_FULL − TWIN_NO_HEDGE`` is ₹0 **by construction**. That is the
    same defect that left the AI ablation starved, and it must never be reported as a measured hedge
    effect. Rather than silently emitting HEDGE_ON for a position nobody can take, the decision now
    carries :func:`hedge_availability` — so the ₹0 is *explained*, and the reader is told the book
    size at which hedging first becomes purchasable.
    """
    if not policy.use_hedge:
        return []
    gauge = stress_gauge(market.index_close)
    active = hedge_active(gauge, HEDGE_TAU, HEDGE_PERSIST)
    window = active.loc[: pd.Timestamp(market.as_of)]
    if len(window) < 2:
        return []
    now, before = bool(window.iloc[-1]), bool(window.iloc[-2])
    if now == before:
        return []
    level = float(gauge.loc[: pd.Timestamp(market.as_of)].iloc[-1])
    holdings = {t: q for t, q in book.portfolio.positions().items() if q > 0}
    book_value = float(book.portfolio.holdings_value(market.prices)) if holdings else 0.0
    # THE DEFECT THIS FIXES. Until 2026-09-05 this line read the last value of ``index_close`` and
    # called it the index level. ``index_close`` is the NIFTYBEES ETF series, ~₹276 against a Nifty
    # near 27,574 — a hundredfold error, straight into a lot-size multiplication. On a ₹3L book the
    # runtime reported "hedge available: 8 lot(s) — one lot ₹17,923" when one lot is ₹17.9 *lakh*
    # and the book can hold none. Worse, CLAUDE.md cited that very function as the thing which
    # *explained* why TWIN_FULL − TWIN_NO_HEDGE is ₹0.
    #
    # An unknown index level is not a reason to invent one. Missing input → CANNOT ASSESS.
    if market.index_level is None:
        tail = (
            " — hedge availability CANNOT BE ASSESSED: no Nifty index level supplied "
            "(the benchmark series is an ETF price, not the index)"
        )
    else:
        avail = hedge_availability(book_value, market.index_level)
        tail = "" if avail.available else f" — but {avail.render()}"
    return [
        Decision(
            on=market.as_of,
            book=book.name,
            action=HEDGE_ON if now else HEDGE_OFF,
            reason=(
                f"stress gauge {level:.2f} {'≥' if now else '<'} τ={HEDGE_TAU} "
                f"held {HEDGE_PERSIST} scans{tail}"
            ),
        )
    ]


def _deploy(book: TwinBook, policy: Policy, market: Market, cfg: Config) -> list[Decision]:
    """Spend idle cash through the deploy-into-weakness screen — the buy rule the user actually runs.

    ``use_ai`` is the ablation. The AI acts as a **filter over the deterministic candidate set**, so
    it can drop a name but never invent one, and never sizes anything: survivors keep the quantities
    the deterministic screen computed. Those guards are structural, not prompted. A missing verdict
    map means the AI said nothing — the name is **kept**, so an outage degrades ``TWIN_FULL`` to
    exactly ``TWIN_NO_AI`` rather than to an empty basket.
    """
    from qalpha.data.prices import PriceData
    from qalpha.live.deploy import advise_deploy_into_weakness

    cash = book.portfolio.cash
    floor = cfg.deploy_policy.idle_cash_floor
    if cash < floor:
        # Below the pre-committed floor, a deploy is charges wearing a strategy costume.
        return []
    if not market.watchlist or not isinstance(market.wl_prices, PriceData):
        return [
            Decision(
                on=market.as_of,
                book=book.name,
                action=HOLD,
                reason=f"₹{cash:,.0f} idle but no watchlist panel — cannot size a basket today",
            )
        ]
    advice = advise_deploy_into_weakness(
        book.portfolio,
        cash,
        market.watchlist,
        market.sector_of or {},
        market.wl_prices,
        market.index_close,
        market.as_of,
        max_names=cfg.deploy_policy.max_names_default,
        spend_idle_cash=False,
    )
    orders = list(advice.deploy.buy_orders)
    dropped: list[str] = []
    if policy.use_ai and market.ai_verdicts:
        kept = [o for o in orders if market.ai_verdicts.get(o.ticker, "keep").lower() != "drop"]
        dropped = [o.ticker for o in orders if o not in kept]
        orders = kept
    if not orders:
        return [
            Decision(
                on=market.as_of,
                book=book.name,
                action=HOLD,
                reason=f"₹{cash:,.0f} idle; screen produced no affordable basket",
            )
        ]
    reason_tail = f"; AI dropped {', '.join(dropped)}" if dropped else ""
    return [
        Decision(
            on=market.as_of,
            book=book.name,
            action=DEPLOY,
            ticker=o.ticker,
            quantity=o.quantity,
            reason=(
                f"market {advice.weakness.level}; deploy-into-weakness from ₹{cash:,.0f} idle"
                f"{reason_tail}"
            ),
        )
        for o in orders
    ]


__all__ = ["HEDGE_PERSIST", "HEDGE_TAU", "Market", "step"]
