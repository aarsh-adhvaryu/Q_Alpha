"""Deterministic tax-smart advisor (Q_alpha.md §14 criterion 10 — the recommendation layer).

The user trades **manually** — every decision is his. This module does not decide *what* to own
(that is the validated funnel in ``decide_rebalance``); it answers the tax question a manual trader
actually asks at the moment of a trade:

* **"I want to sell N shares of TICKER"** → ``advise_sell``: which FIFO lots it consumes, the STCG
  vs LTCG split, the exact tax, how much the ₹1.25L FY LTCG exemption shelters, the largest quantity
  sellable for ₹0 tax, and whether waiting out the 365-day line converts STCG to cheaper LTCG.
* **"I need ₹Y in cash"** → ``advise_raise_cash``: which holdings to sell to raise it at the least
  tax (long-term lots and losers first, gains kept inside the exemption) vs a naive pro-rata sell.
* **"I'm adding ₹Y of new money"** → ``advise_deploy``: route it into the underweight names as buys
  only (₹0 capital-gains tax — §2.9 fresh-capital routing) instead of a full rebalance that sells.

Every number comes from the **same** FIFO/cost/tax engine the backtest was validated on
(``Portfolio.preview_sell`` / ``estimate_rebalance`` dry-runs) — there is **no LLM and no separate
tax formula here**; the output is a template filled with engine figures, fully auditable. The advisor
takes a ``Portfolio``, so it works on the notional paper book today and on a live Zerodha holdings
snapshot later with no change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

import pandas as pd

from qalpha.accounting.capital_gains import (
    RealizedGain,
    apply_grandfathering,
    apply_long_term_boundary,
    financial_year,
    is_long_term_holding,
    net_capital_gains_tax,
    twelve_months_after,
)
from qalpha.accounting.costs import Side, compute_costs
from qalpha.backtest.portfolio import Portfolio, TradeRecord
from qalpha.config import Config

_ZERO = Decimal("0")
# How close to the 365-day line a short-term lot must be before "just wait" is worth surfacing.
_BOUNDARY_WINDOW_DAYS = 60
# Safety cap on the greedy whole-share deploy loop (huge ₹ ÷ a penny-stock price); never hit in
# practice — it deploys idle cash + new money one share at a time toward the most underweight name.
_MAX_DEPLOY_SHARES = 1_000_000


def _rupees(value: Decimal) -> str:
    return f"₹{value:,.2f}"


def _add_cess(tax: Decimal, cess_rate: Decimal) -> Decimal:
    """Gross a base capital-gains tax up by the 4% Health & Education Cess (the real ITR figure)."""
    return (tax * (Decimal("1") + cess_rate)).quantize(Decimal("0.01"))


def exemption_remaining(portfolio: Portfolio, cfg: Config, as_of: date) -> Decimal:
    """Unused ₹1.25L LTCG exemption for the financial year containing ``as_of``."""
    used = portfolio.gains.ltcg_realized(financial_year(as_of))
    return max(_ZERO, cfg.tax.ltcg_annual_exemption - used)


# ---- "sell N shares of TICKER" ------------------------------------------------------------------


@dataclass(frozen=True)
class BoundaryWait:
    """A short-term lot close enough to the 365-day line that waiting converts STCG → LTCG."""

    quantity: Decimal
    holding_days: int
    days_to_long_term: int
    long_term_date: date
    gain: Decimal
    estimated_saving: Decimal  # gain × (STCG − LTCG) rate spread; exemption can make it larger


@dataclass(frozen=True)
class SellAdvice:
    """The tax breakdown + smart alternatives for selling ``quantity`` shares of ``ticker``."""

    ticker: str
    as_of: date
    price: Decimal
    quantity: Decimal
    realized: list[RealizedGain]
    cost: Decimal
    stcg_gain: Decimal
    ltcg_gain: Decimal
    total_tax: Decimal  # real ITR figure: §70 set-off + §112A grandfathering + 4% cess
    cess: Decimal  # the 4% Health & Education Cess component included in total_tax
    setoff_saving: Decimal  # tax saved because loss lots in this sell offset the gain lots (§70)
    grandfather_saving: Decimal  # tax saved by the §112A pre-2018 FMV step-up
    grandfather_unpriced: list[str]  # pre-2018 tickers missing a 31-Jan-2018 FMV (tax over-stated)
    ltcg_sheltered: Decimal
    exemption_remaining: Decimal
    net_proceeds: Decimal
    tax_free_quantity: Decimal
    boundary_waits: list[BoundaryWait]
    # Lots past 365 days but NOT past the 12-calendar-month line — still short-term (§2(42A)).
    boundary_demoted: tuple[RealizedGain, ...] = ()

    def render(self) -> str:
        lines = [
            f"### Sell {self.quantity} {self.ticker} @ {_rupees(self.price)}  (as of {self.as_of})",
            "",
            f"- Gross proceeds: {_rupees(self.quantity * self.price)}",
            f"- Realized gain: short-term {_rupees(self.stcg_gain)} · "
            f"long-term {_rupees(self.ltcg_gain)}",
            f"- Transaction cost: {_rupees(self.cost)}",
            f"- **Capital-gains tax: {_rupees(self.total_tax)}** "
            f"(incl. {_rupees(self.cess)} @ 4% Health & Education Cess)",
            f"- **Net you receive: {_rupees(self.net_proceeds)}**",
            "",
            "**Tax-smart notes**",
        ]
        if self.boundary_demoted:
            qty = sum((g.quantity for g in self.boundary_demoted), _ZERO)
            lt_date = max(
                twelve_months_after(g.acquisition_date) + timedelta(days=1)
                for g in self.boundary_demoted
            )
            lines.append(
                f"- ⚠️ **{qty} share(s) are NOT long-term yet**, despite being held 365+ days: the "
                f"law needs *more than* 12 calendar months, so these are taxed at **20%**, not "
                f"12.5%. Sell on or after **{lt_date:%d %b %Y}** for the lower rate."
            )
        if self.grandfather_saving > 0:
            lines.append(
                f"- {_rupees(self.grandfather_saving)} of tax is saved by §112A grandfathering — "
                f"pre-2018 lots are re-costed to their 31-Jan-2018 value."
            )
        if self.grandfather_unpriced:
            lines.append(
                f"- ⚠️ Lots in **{', '.join(self.grandfather_unpriced)}** were acquired before "
                f"1-Feb-2018 but have no 31-Jan-2018 FMV provided — the tax above uses actual cost "
                f"and may be **over-stated**. Provide each name's 31-Jan-2018 FMV for the exact figure."
            )
        if self.ltcg_sheltered > 0:
            lines.append(
                f"- {_rupees(self.ltcg_sheltered)} of long-term gain is shielded by your remaining "
                f"{_rupees(self.exemption_remaining)} FY exemption."
            )
        else:
            lines.append(f"- Remaining FY LTCG exemption: {_rupees(self.exemption_remaining)}.")
        if self.setoff_saving > 0:
            lines.append(
                f"- {_rupees(self.setoff_saving)} of tax is saved here because loss lots in this "
                f"sell set off against the gains (§70 loss set-off)."
            )
        if self.tax_free_quantity <= 0:
            lines.append("- No part of this position can be sold tax-free right now.")
        elif self.tax_free_quantity < self.quantity:
            lines.append(
                f"- You could sell **{self.tax_free_quantity} shares for ₹0 tax** today; the rest is "
                f"what triggers the {_rupees(self.total_tax)} above."
            )
        else:
            lines.append("- This entire sale is tax-free (within the exemption / long-term lots).")
        for b in self.boundary_waits:
            lines.append(
                f"- ⏳ {b.quantity} shares turn long-term in **{b.days_to_long_term} days** "
                f"(on {b.long_term_date}); waiting cuts the tax rate 20%→12.5%, saving about "
                f"{_rupees(b.estimated_saving)} (more if the exemption covers it)."
            )
        return "\n".join(lines)


def _tax_free_quantity(
    portfolio: Portfolio, ticker: str, price: Decimal, as_of: date, headroom: Decimal
) -> Decimal:
    """Largest whole-share quantity sellable for ₹0 capital-gains tax, walking the lots FIFO.

    A loss/break-even lot is always tax-free; a long-term lot is free while its gain fits the
    remaining ₹1.25L exemption; a *short-term* lot with a gain taxes immediately, so FIFO (which
    must consume oldest first) cannot reach past it tax-free.
    """
    remaining = headroom
    free = _ZERO
    for lot in portfolio.ledger.open_lots(ticker):
        gain_per_share = price - lot.cost_basis_per_share
        is_long_term = is_long_term_holding(lot.acquisition_date, as_of)
        if gain_per_share <= 0:
            free += lot.quantity_remaining  # loss/flat: no tax on any of it
            continue
        if not is_long_term:
            break  # a taxable short-term lot blocks everything behind it under FIFO
        if remaining <= 0:
            break
        shares_within = (remaining / gain_per_share).to_integral_value(rounding=ROUND_DOWN)
        take = min(lot.quantity_remaining, shares_within)
        free += take
        remaining -= take * gain_per_share
        if take < lot.quantity_remaining:
            break
    return free


def _boundary_waits(realized: list[RealizedGain], cfg: Config) -> list[BoundaryWait]:
    """Short-term consumed lots within ``_BOUNDARY_WINDOW_DAYS`` of becoming long-term."""
    spread = cfg.tax.stcg_rate - cfg.tax.ltcg_rate
    out: list[BoundaryWait] = []
    for g in realized:
        if g.gain_type != "STCG" or g.gain <= 0:
            continue
        # First date the lot is genuinely long-term: the day AFTER the 12-month anniversary
        # (§2(42A) needs *more than* 12 months — selling on the anniversary is still short-term).
        lt_date = twelve_months_after(g.acquisition_date) + timedelta(days=1)
        days_to_lt = (lt_date - g.sell_date).days
        if 0 < days_to_lt <= _BOUNDARY_WINDOW_DAYS:
            out.append(
                BoundaryWait(
                    quantity=g.quantity,
                    holding_days=g.holding_days,
                    days_to_long_term=days_to_lt,
                    long_term_date=lt_date,
                    gain=g.gain,
                    estimated_saving=(g.gain * spread).quantize(Decimal("0.01")),
                )
            )
    return out


def advise_sell(
    portfolio: Portfolio,
    ticker: str,
    price: Decimal,
    as_of: date,
    cfg: Config,
    *,
    quantity: Decimal | None = None,
    grandfather_fmv: Mapping[str, Decimal] | None = None,
) -> SellAdvice:
    """Tax breakdown + smart alternatives for selling ``quantity`` (default: all) of ``ticker``.

    The quoted tax is the **real ITR figure**: §70 intra-year loss set-off, §112A grandfathering for
    any pre-2018 lot whose 31-Jan-2018 FMV is supplied via ``grandfather_fmv`` (ticker → FMV/share),
    and the 4% Health & Education Cess. (The frozen backtest engine stays cess-free and on actual
    cost — this real-life layer never feeds the validated headline.)
    """
    held = portfolio.ledger.quantity_held(ticker)
    if held <= 0:
        raise ValueError(f"no open position in {ticker}")
    qty = held if quantity is None else min(quantity, held)
    if qty <= 0:
        raise ValueError("sell quantity must be positive")

    realized_raw, cb = portfolio.preview_sell(as_of, ticker, qty, price)
    # §2(42A): the engine's `holding_days >= 365` fast path calls a lot long-term a day early (and up
    # to two days early across a leap year). Re-classify against the exact 12-calendar-month test
    # BEFORE anything else, so the quoted rate, the exemption and §112A all key off the true type.
    realized_raw, boundary_demoted = apply_long_term_boundary(realized_raw, cfg.tax)
    # §112A: re-cost pre-2018 long-term lots to their 31-Jan-2018 FMV (when supplied); flag any that
    # are pre-2018 but unpriced (kept on actual cost → conservative, tax possibly over-stated).
    realized, gf_unpriced = apply_grandfathering(realized_raw, price, grandfather_fmv or {})
    stcg = [g for g in realized if g.gain_type == "STCG"]
    ltcg = [g for g in realized if g.gain_type == "LTCG"]

    fy = financial_year(as_of)
    used = {fy: portfolio.gains.ltcg_realized(fy)}
    # The legally-correct figure nets losses against gains within the FY (§70) and adds cess; the
    # FY rows carry the exemption actually applied to the (grandfathered) LTCG.
    rows = net_capital_gains_tax(realized, cfg.tax, exemption_used_by_fy=used)
    total_tax = sum((r.total_tax for r in rows), _ZERO)
    cess = sum((r.cess for r in rows), _ZERO)
    ltcg_sheltered = sum((r.ltcg_exempted for r in rows), _ZERO)

    # Attribution, all on the same (cess-inclusive) basis so each saving is isolated:
    #  · setoff  = per-lot-in-isolation tax  −  net tax, both on actual cost;
    #  · grandfather = net tax on actual cost  −  net tax after the FMV step-up.
    tax_actualcost = sum(
        (
            r.total_tax
            for r in net_capital_gains_tax(realized_raw, cfg.tax, exemption_used_by_fy=used)
        ),
        _ZERO,
    )
    gross_no_setoff = (
        sum((g.tax for g in realized_raw), _ZERO) * (Decimal("1") + cfg.tax.cess_rate)
    ).quantize(Decimal("0.01"))
    headroom = exemption_remaining(portfolio, cfg, as_of)
    return SellAdvice(
        ticker=ticker,
        as_of=as_of,
        price=price,
        quantity=qty,
        realized=realized,
        cost=cb.total,
        stcg_gain=sum((g.gain for g in stcg), _ZERO),
        ltcg_gain=sum((g.gain for g in ltcg), _ZERO),
        total_tax=total_tax,
        cess=cess,
        setoff_saving=max(_ZERO, gross_no_setoff - tax_actualcost),
        grandfather_saving=max(_ZERO, tax_actualcost - total_tax),
        grandfather_unpriced=sorted({g.ticker for g in gf_unpriced}),
        ltcg_sheltered=ltcg_sheltered,
        exemption_remaining=headroom,
        net_proceeds=qty * price - cb.total - total_tax,
        tax_free_quantity=_tax_free_quantity(portfolio, ticker, price, as_of, headroom),
        boundary_waits=_boundary_waits(realized, cfg),
        boundary_demoted=tuple(boundary_demoted),
    )


# ---- "I need ₹Y in cash" ------------------------------------------------------------------------


@dataclass(frozen=True)
class RaiseCashAdvice:
    """Which holdings to sell to raise ``amount`` at the least tax, vs a naive pro-rata sell.

    ``smart_tax`` is the **real ITR figure**, on the identical basis as :class:`SellAdvice` — §70
    set-off, the §2(42A) 12-calendar-month boundary, the FY exemption and the 4% cess. It used to be
    a sum of per-lot ``Portfolio.sell`` taxes: the frozen backtest engine, which by its own docstring
    defers loss set-off and calls a lot long-term at 365 days when the law needs *more than* twelve
    calendar months. On a lot held exactly 365 days that quoted ₹620 against a true ₹9,570, while the
    Sell tab priced the same shares at ₹32,754 and warned they were not long-term yet. Two surfaces,
    one book, one day, two answers — so both now run the same engine.
    """

    as_of: date
    amount: Decimal
    smart_orders: list[TradeRecord]
    smart_tax: Decimal
    smart_raised: Decimal
    naive_tax: Decimal
    tax_saved: Decimal
    charges: Decimal = _ZERO  # brokerage/STT/stamp on the smart plan
    realized: list[RealizedGain] = field(default_factory=list)  # every lot the plan consumes
    boundary_demoted: tuple[RealizedGain, ...] = ()  # 365+ days but not 12 calendar months
    shortfall: Decimal = _ZERO  # requested minus actually raised, when the book cannot cover it
    ltcg_sheltered: Decimal = _ZERO  # long-term gain absorbed by the FY exemption

    @property
    def gross_proceeds(self) -> Decimal:
        return sum((o.quantity * o.price for o in self.smart_orders), _ZERO)

    def render(self) -> str:
        lines = [
            f"### Raise {_rupees(self.amount)} cash  (as of {self.as_of})",
            "",
            "**Tax-smart source order** (long-term lots and losers first, gains kept in the "
            "exemption):",
            "",
            "| Sell | Qty | Price | Gross |",
            "|---|---|---|---|",
        ]
        for o in self.smart_orders:
            lines.append(
                f"| {o.ticker} | {o.quantity} | {_rupees(o.price)} | "
                f"{_rupees(o.quantity * o.price)} |"
            )
        # Every line below must reconcile to the one above it. The old panel netted the cash against
        # a pre-cess tax while reporting the post-cess figure, so "Raises ₹392,610.50 for ₹24,300.19
        # tax" was ₹934.62 out on its own face, and the per-order tax column did not sum to the
        # headline. Tax is a property of the *plan* (§70 nets across names), not of one order, so it
        # is stated once, here, where it is subtracted.
        lines += [
            "",
            f"- Gross proceeds: {_rupees(self.gross_proceeds)}",
            f"- Less charges: {_rupees(self.charges)}",
            f"- Less capital-gains tax: **{_rupees(self.smart_tax)}** "
            "(§70 set-off + FY exemption + 4% cess — the ITR figure)",
            f"- **Cash you receive: {_rupees(self.smart_raised)}**",
        ]
        if self.shortfall > 0:
            lines.append(
                f"- ⚠️ **{_rupees(self.shortfall)} short of the {_rupees(self.amount)} you asked "
                "for** — selling everything sellable does not raise it. Nothing here is wrong; the "
                "book cannot cover the request."
            )
        if self.boundary_demoted:
            qty = sum((g.quantity for g in self.boundary_demoted), _ZERO)
            names = ", ".join(sorted({g.ticker for g in self.boundary_demoted}))
            lines.append(
                f"- ⚠️ **{qty} share(s) in {names} are NOT long-term yet**, despite being held 365+ "
                "days: the law needs *more than* 12 calendar months, so they are taxed at **20%**, "
                "not 12.5%. Waiting a few days is the cheapest change you can make to this plan."
            )
        lines += [
            f"- A naive pro-rata sell across all holdings would cost {_rupees(self.naive_tax)} on "
            "the same basis.",
            f"- **Tax saved: {_rupees(self.tax_saved)}.**",
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class _Liquidation:
    ticker: str
    quantity: Decimal
    price: Decimal
    proceeds: Decimal
    tax: Decimal
    tax_per_rupee: float


def _liquidation_efficiency(
    portfolio: Portfolio, prices: Mapping[str, Decimal], as_of: date, cfg: Config
) -> list[_Liquidation]:
    """Per-holding full-liquidation cost, ranked by tax per rupee raised (cheapest first).

    Ranked on the **boundary-corrected** tax: a lot held exactly 365 days is long-term to the engine
    and short-term to the law, so the raw figure ranked such a holding as the cheapest source when it
    is among the dearest. This is a ranking heuristic — each holding is costed in isolation against
    the full remaining FY exemption, which several holdings cannot all use — so the *order* is
    advisory. The plan's quoted tax is not: it is computed on the executed plan as a whole.
    """
    rows: list[_Liquidation] = []
    for ticker, qty in portfolio.positions().items():
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        realized, cb = portfolio.preview_sell(as_of, ticker, qty, price)
        realized, _demoted = apply_long_term_boundary(realized, cfg.tax)
        tax = sum((g.tax for g in realized), _ZERO)
        proceeds = qty * price - cb.total - tax
        per_rupee = float(tax / proceeds) if proceeds > 0 else 0.0
        rows.append(_Liquidation(ticker, qty, price, proceeds, tax, per_rupee))
    rows.sort(key=lambda r: (r.tax_per_rupee, r.ticker))
    return rows


def _itr_tax(
    realized: list[RealizedGain], cfg: Config, exemption_used: Mapping[int, Decimal]
) -> Decimal:
    """The plan's tax as the ITR computes it — §70 set-off, FY exemption, 4% cess. One number.

    Tax cannot be attributed per order: a loss in one name sets off a gain in another, so the plan's
    liability is a property of the whole plan. Summing per-order taxes (the old behaviour) could only
    ever over-state the set-off case and under-state the boundary case, and never reconciled to the
    cash line beneath it.
    """
    rows = net_capital_gains_tax(realized, cfg.tax, exemption_used_by_fy=dict(exemption_used))
    return sum((r.total_tax for r in rows), _ZERO)


def advise_raise_cash(
    portfolio: Portfolio,
    amount: Decimal,
    prices: Mapping[str, Decimal],
    as_of: date,
    cfg: Config | None = None,
) -> RaiseCashAdvice:
    """Plan the least-tax way to raise ``amount`` in cash, vs a naive pro-rata liquidation.

    The plan is built by drawing from the cheapest source until it is exhausted, then the next, and
    is **re-costed on the ITR basis after every sale** — so the loop stops on the cash actually
    received, not on an estimate. Three defects this closes, all found on one panel:

    * the quoted tax came from the frozen backtest engine (no §70 set-off, no §2(42A) boundary) while
      the Sell tab quoted the ITR figure for the same shares — ₹620 against ₹32,754;
    * ``smart_raised`` netted the pre-cess tax while ``smart_tax`` reported the post-cess one, so
      "Raises ₹X for ₹Y tax" was out by the cess on its own face;
    * the sizing loop made a single pass over holdings, so when tax exceeded the 0.5% price buffer it
      silently under-raised — ₹4,00,000 asked, ₹3,92,610 raised, 466 shares still held, no mention.
      It now keeps drawing, and says so plainly when the book genuinely cannot cover the request.
    """
    cfg = cfg or Config()
    fy = financial_year(as_of)
    used = {fy: portfolio.gains.ltcg_realized(fy)}
    ranked = _liquidation_efficiency(portfolio, prices, as_of, cfg)

    smart = portfolio.clone()
    orders: list[TradeRecord] = []
    realized_all: list[RealizedGain] = []
    demoted_all: list[RealizedGain] = []
    charges = _ZERO
    gross = _ZERO
    raised = _ZERO
    remaining = {r.ticker: r.quantity for r in ranked}

    for row in ranked:
        # Draw from this source until it is exhausted or the target is met, re-costing each time.
        while raised < amount and remaining[row.ticker] > 0:
            need = amount - raised
            # Size off a slightly discounted price so the net (post cost+tax) clears ``need`` in one
            # go rather than spilling a stray share into the next — usually dearer — holding.
            buffered = row.price * Decimal("0.995")
            shares = min(
                remaining[row.ticker], (need / buffered).to_integral_value(rounding=ROUND_CEILING)
            )
            if shares <= 0:
                break
            # Capture the per-lot gains on the identical pre-sell state (the same preview-then-sell
            # pairing ``replay_tradebook`` uses), boundary-correct them, then execute.
            lots, _cb = smart.preview_sell(as_of, row.ticker, shares, row.price)
            lots, demoted = apply_long_term_boundary(lots, cfg.tax)
            rec = smart.sell(as_of, row.ticker, shares, row.price)
            realized_all.extend(lots)
            demoted_all.extend(demoted)
            orders.append(rec)
            remaining[row.ticker] -= shares
            gross += shares * row.price
            charges += rec.cost
            raised = gross - charges - _itr_tax(realized_all, cfg, used)
        if raised >= amount:
            break
    # The loop above sizes the plan; it can draw from one source several times, but the user places
    # ONE order per name. Charges and per-lot gains both depend on trade size, so the plan is now
    # **re-costed from scratch as the orders he will actually place** — quoting a merged order while
    # costing three split ones would reintroduce the very thing this audit is about: a number that
    # does not describe the thing beside it.
    quantities: dict[str, Decimal] = {}
    for o in orders:
        quantities[o.ticker] = quantities.get(o.ticker, _ZERO) + o.quantity
    final = portfolio.clone()
    orders, realized_all, demoted_all = [], [], []
    gross = charges = _ZERO
    for ticker in [r.ticker for r in ranked if r.ticker in quantities]:
        qty, price = quantities[ticker], next(r.price for r in ranked if r.ticker == ticker)
        lots, _cb = final.preview_sell(as_of, ticker, qty, price)
        lots, demoted = apply_long_term_boundary(lots, cfg.tax)
        rec = final.sell(as_of, ticker, qty, price)
        realized_all.extend(lots)
        demoted_all.extend(demoted)
        orders.append(rec)
        gross += qty * price
        charges += rec.cost
    smart_tax = _itr_tax(realized_all, cfg, used)
    raised = gross - charges - smart_tax

    # Naive baseline: sell the same fraction of every holding to raise ``amount`` — costed on the
    # SAME basis, or "tax saved" would be a difference between two different tax engines.
    naive = portfolio.clone()
    naive_realized: list[RealizedGain] = []
    holdings_value = portfolio.holdings_value(prices)
    frac = min(Decimal("1"), amount / holdings_value) if holdings_value > 0 else _ZERO
    for ticker, qty in portfolio.positions().items():
        mark = prices.get(ticker)
        if mark is None or mark <= 0:
            continue
        shares = (qty * frac).to_integral_value(rounding=ROUND_DOWN)
        if shares > 0:
            lots, _cb = naive.preview_sell(as_of, ticker, shares, mark)
            lots, _demoted = apply_long_term_boundary(lots, cfg.tax)
            naive_realized.extend(lots)
            naive.sell(as_of, ticker, shares, mark)
    naive_tax = _itr_tax(naive_realized, cfg, used)

    return RaiseCashAdvice(
        as_of=as_of,
        amount=amount,
        smart_orders=orders,
        smart_tax=smart_tax,
        smart_raised=raised,
        naive_tax=naive_tax,
        tax_saved=naive_tax - smart_tax,
        charges=charges,
        realized=realized_all,
        boundary_demoted=tuple(demoted_all),
        shortfall=max(_ZERO, amount - raised),
        ltcg_sheltered=sum(
            (
                r.ltcg_exempted
                for r in net_capital_gains_tax(
                    realized_all, cfg.tax, exemption_used_by_fy=dict(used)
                )
            ),
            _ZERO,
        ),
    )


# ---- "I'm adding ₹Y of new money" ---------------------------------------------------------------


@dataclass(frozen=True)
class DeployAdvice:
    """Route new money into underweights as buys only (₹0 tax) vs a full taxable rebalance."""

    as_of: date
    amount: Decimal
    buy_orders: list[TradeRecord]
    buy_cost: Decimal
    leftover_cash: Decimal
    naive_tax: Decimal
    naive_cost: Decimal
    tax_saved: Decimal
    #: Idle cash already sitting in the account that this basket **also** spends. The advisor has
    #: always deployed ``portfolio.cash + amount`` (see ``advise_deploy`` — putting idle cash to work
    #: is the point), but the heading named only ``amount``. Recorded so the heading can state the
    #: number the orders actually add up to.
    idle_cash: Decimal = Decimal("0")
    #: Idle cash deliberately left alone because ``amount`` was treated as a hard budget.
    held_back: Decimal = Decimal("0")

    @property
    def total_deployed(self) -> Decimal:
        """What the listed orders actually cost — new money **plus** idle cash already in the account."""
        return sum((o.quantity * o.price for o in self.buy_orders), Decimal("0"))

    def render(self) -> str:
        # The heading must name what the orders below add up to, not just the amount typed in.
        # Found live on 2026-08-24, on the real-money buy surface, with real money in the account:
        # a ₹5,00,000 broker balance and ₹1,00,000 typed in produced a ₹5,97,418 basket under a
        # heading that read "Deploy ₹100,000.00 of new money", and the user was seconds from placing
        # a 64-share order that should have been 11. The arithmetic was right and documented; the
        # label was wrong, which on this surface is the same thing as being wrong.
        if self.held_back > 0:
            head = (
                f"### Deploy {_rupees(self.total_deployed)}  (as of {self.as_of})\n\n"
                f"✅ **{_rupees(self.held_back)} of your broker balance is left untouched.** This "
                "basket spends the amount you asked for and nothing else — the rest stays as cash in "
                "your account for whenever you want it."
            )
        elif self.idle_cash > 0:
            head = (
                f"### Deploy {_rupees(self.total_deployed)}  (as of {self.as_of})\n\n"
                f"⚠️ **This spends {_rupees(self.amount)} of new money plus "
                f"{_rupees(self.idle_cash)} of idle cash already in your account.** If some of that "
                "balance is earmarked for later — a future SIP instalment, money you want held back "
                "— untick *deploy idle cash too* and only the amount you typed will be spent."
            )
        else:
            head = f"### Deploy {_rupees(self.amount)} of new money  (as of {self.as_of})"
        lines = [
            head,
            "",
            "**Tax-smart: buy the underweight names only — no sells, so ₹0 capital-gains tax.**",
            "",
            "| Buy | Qty | Price |",
            "|---|---|---|",
        ]
        for o in self.buy_orders:
            lines.append(f"| {o.ticker} | {o.quantity} | {_rupees(o.price)} |")
        lines += [
            "",
            f"- Orders total {_rupees(self.total_deployed)} · transaction cost: "
            f"{_rupees(self.buy_cost)} · leftover cash: "
            f"{_rupees(self.leftover_cash)}.",
            f"- A full rebalance to target would instead realize {_rupees(self.naive_tax)} tax "
            f"(cost {_rupees(self.naive_cost)}).",
            f"- **Tax saved by routing new money to underweights: {_rupees(self.tax_saved)}.**",
        ]
        return "\n".join(lines)


def _spent(orders: list[TradeRecord]) -> Decimal:
    """Rupees of stock the listed orders buy, excluding charges."""
    return sum((o.quantity * o.price for o in orders), _ZERO)


def advise_deploy(
    portfolio: Portfolio,
    amount: Decimal,
    target: pd.Series,
    prices: Mapping[str, Decimal],
    as_of: date,
    *,
    spend_idle_cash: bool = True,
) -> DeployAdvice:
    """Advise deploying ``amount`` of fresh capital toward ``target`` weights with zero tax.

    ``spend_idle_cash`` decides what the budget is. Default ``True`` keeps the original contract —
    idle cash is a drag and the advisor's job is to put it to work. Pass ``False`` to make ``amount``
    a **hard budget**, leaving whatever else sits in the account untouched.

    That switch exists because a broker balance is not self-describing. Cash parked for next month's
    SIP instalment and cash waiting to be deployed look identical from here; only the person who put
    it there knows which is which. Deploying all of it by default turned a ₹1,00,000 opening position
    into a ₹5,97,418 basket on a live account (2026-08-24) — and the alternative advice, "keep the
    other ₹4,00,000 in your bank and transfer monthly", is a chore the software should absorb rather
    than hand back to the user.

    Smart path: spend the budget buying whole shares toward ``target``, always topping
    up the **most underweight** name that is still affordable, until no further share fits — pure
    buys, so no capital-gains tax is realized (§2.9 fresh-capital routing). Buying whole shares one at
    a time toward the largest shortfall both tracks target weights and drives idle cash down to less
    than one share of the cheapest name (a single bulk floor would strand a share's worth per name).
    Naive path: a full rebalance to ``target`` on the same post-injection book, which sells the
    overweights and realizes capital-gains tax. ``tax_saved`` is that avoided tax.
    """
    # The target book: everything already held, plus the money actually being put to work. When idle
    # cash is held back it is deliberately NOT part of the book being sized — counting it would size
    # every name against capital the user has ruled out spending.
    budget = portfolio.cash + amount if spend_idle_cash else amount
    total_after = portfolio.holdings_value(prices) + budget
    desired_value = {
        str(t): Decimal(str(w)) * total_after
        for t, w in target.items()
        if float(w) > 0 and str(t) in prices
    }

    # Allocate whole-share buys greedily against the budget, leaving a small
    # buffer for the ~0.3% buy cost so the executed orders below don't get affordability-capped.
    held = portfolio.positions()
    buffered = {t: prices[t] * Decimal("1.004") for t in desired_value}
    shares: dict[str, Decimal] = dict.fromkeys(desired_value, _ZERO)
    available = budget
    for _ in range(_MAX_DEPLOY_SHARES):
        best, best_shortfall = None, _ZERO
        for t in desired_value:
            if buffered[t] > available:
                continue
            shortfall = desired_value[t] - (held.get(t, _ZERO) + shares[t]) * prices[t]
            if shortfall > best_shortfall:
                best, best_shortfall = t, shortfall
        if best is None:
            break  # nothing left that is both underweight and affordable
        shares[best] += 1
        available -= buffered[best]

    # Execute one buy per name (no sells → ₹0 capital-gains tax by construction).
    smart = portfolio.clone()
    smart.cash += amount
    buy_orders: list[TradeRecord] = []
    for ticker in sorted(shares, key=lambda k: shares[k] * prices[k], reverse=True):
        if shares[ticker] > 0:
            order = smart.buy(as_of, ticker, shares[ticker], prices[ticker])
            if order is not None:
                buy_orders.append(order)

    naive = portfolio.clone()
    naive.cash += amount
    naive_cost, naive_tax_base, _ = naive.estimate_rebalance(
        as_of, target, prices, min_trade_fraction=0.0
    )
    naive_tax = _add_cess(naive_tax_base, portfolio.tax_cfg.cess_rate)  # real ITR figure

    return DeployAdvice(
        as_of=as_of,
        amount=amount,
        buy_orders=buy_orders,
        buy_cost=sum((o.cost for o in buy_orders), _ZERO),
        leftover_cash=budget - _spent(buy_orders) - sum((o.cost for o in buy_orders), _ZERO),
        held_back=portfolio.cash if not spend_idle_cash else _ZERO,
        naive_tax=naive_tax,
        naive_cost=naive_cost,
        tax_saved=naive_tax,
        idle_cash=portfolio.cash,
    )


# ---- "which losses can I bank before 31 March?" --------------------------------------------------


@dataclass(frozen=True)
class HarvestCandidate:
    """One name's best reachable loss, and what it costs to reach it."""

    ticker: str
    quantity: Decimal  # whole shares to sell — a FIFO **prefix**, not a chosen lot
    price: Decimal
    net_gain: Decimal  # negative = the loss banked; includes any gain crossed to reach it
    gain_crossed: Decimal  # gain realised on lots sold *only* to reach the loss behind them
    lots_consumed: int
    charges: Decimal  # round-trip: this sale plus buying the position back
    resets_long_term: bool  # rebuying restarts the 12-month clock on these shares

    @property
    def worthwhile(self) -> bool:
        """Does the banked loss exceed what it costs to bank it?

        A loss is only worth realising if it survives the gain crossed to reach it *and* the
        round trip. ``net_gain`` is already net of the crossing; charges are the remaining hurdle.
        """
        return self.net_gain < 0 and abs(self.net_gain) > self.charges


@dataclass(frozen=True)
class HarvestAdvice:
    """Losses that can be banked before the financial year closes, and what each is worth."""

    as_of: date
    financial_year: int
    candidates: list[HarvestCandidate]
    realized_gains_this_fy: Decimal  # what a banked loss can offset *now*
    days_to_fy_end: int

    @property
    def actionable(self) -> list[HarvestCandidate]:
        return [c for c in self.candidates if c.worthwhile]

    @property
    def total_loss(self) -> Decimal:
        return sum((c.net_gain for c in self.actionable), _ZERO)

    def render(self) -> str:
        if not self.actionable:
            return (
                "### Tax-loss harvest\n\nNo position is far enough underwater for banking the loss "
                "to beat the cost of the round trip. Nothing to do."
            )
        lines = [
            f"### Tax-loss harvest — {self.days_to_fy_end} days to 31 March",
            "",
            "Selling a position that is **down** converts a paper loss into a **realised** one, which "
            "sets off against gains under §70 and carries forward **eight years** under §74. India "
            "has no wash-sale rule, so the position can be bought straight back.",
            "",
            "| Sell | Qty | Price | Loss banked | Round trip |",
            "|---|---|---|---|---|",
        ]
        for c in self.actionable:
            lines.append(
                f"| {c.ticker} | {c.quantity} | {_rupees(c.price)} | "
                f"**{_rupees(-c.net_gain)}** | {_rupees(c.charges)} |"
            )
        lines += ["", f"- **Total loss banked: {_rupees(-self.total_loss)}**"]
        if self.realized_gains_this_fy > 0:
            lines.append(
                f"- Offsets the {_rupees(self.realized_gains_this_fy)} of gains you have already "
                "realised this financial year; any excess carries forward eight years."
            )
        else:
            lines.append(
                "- ⚠️ You have **no realised gains this financial year**, so this does not cut a "
                "bill now — it banks a loss that carries forward **eight years** against gains you "
                "have not made yet. Real value, but not cash back."
            )
        crossed = [c for c in self.actionable if c.gain_crossed > 0]
        if crossed:
            names = ", ".join(c.ticker for c in crossed)
            lines.append(
                f"- ⚠️ **{names}**: FIFO sells oldest first, so reaching the loss also realises "
                f"{_rupees(sum((c.gain_crossed for c in crossed), _ZERO))} of gain on the lots in "
                "front of it. That is already netted off the figures above."
            )
        if any(c.resets_long_term for c in self.actionable):
            lines.append(
                "- ⚠️ Buying back **restarts the 12-month clock** on those shares. Close to the "
                "long-term line, the delayed 12.5% rate can cost more than the loss is worth."
            )
        lines.append(
            "- To carry a loss forward you must **file your ITR by the due date** — an unfiled "
            "return forfeits the carry-forward entirely."
        )
        return "\n".join(lines)


def _best_harvest_prefix(
    portfolio: Portfolio, ticker: str, price: Decimal, as_of: date, cfg: Config
) -> tuple[Decimal, Decimal, Decimal, int] | None:
    """The FIFO prefix that banks the largest net loss: (quantity, net_gain, gain_crossed, n_lots).

    **Why a prefix and not a lot.** Lots cannot be chosen — a sale consumes the oldest first, so a
    gain lot sitting in front of a loss lot blocks it, and reaching the loss means realising that
    gain too. Selecting "the losers" by eye can therefore realise a gain *larger* than the loss it
    was chasing. This walks the cumulative gain lot by lot and returns the cut with the most
    negative total, which is the most loss the ledger actually permits.
    """
    lots = portfolio.ledger.open_lots(ticker)
    if not lots:
        return None
    running_qty = _ZERO
    running_gain = _ZERO
    best: tuple[Decimal, Decimal, Decimal, int] | None = None
    positive_seen = _ZERO
    for n, lot in enumerate(lots, start=1):
        qty = lot.quantity_remaining
        lot_gain = (price - lot.cost_basis_per_share) * qty
        running_qty += qty
        running_gain += lot_gain
        if lot_gain > 0:
            positive_seen += lot_gain
        if running_gain < 0 and (best is None or running_gain < best[1]):
            best = (running_qty, running_gain, positive_seen, n)
    return best


def advise_harvest(
    portfolio: Portfolio,
    prices: Mapping[str, Decimal],
    as_of: date,
    cfg: Config | None = None,
) -> HarvestAdvice:
    """Which losses can be banked before 31 March, FIFO-aware, net of the round trip.

    The tax *computation* has always been here — §70 set-off and the §74 eight-year carry-forward
    live in ``net_capital_gains_tax``. What has never existed is a surface that says *"these
    positions are at a loss; realising them before 31 March banks a loss you can carry forward eight
    years"*; ``capital_gains.py`` calls harvesting itself "deferred past Phase 0" in a comment.

    This is the one selling behaviour that earns its turnover: the sale is a loss, so it costs no
    capital-gains tax, and the loss is an asset. It needs no crash and no minimum book size — only a
    position underwater and a date on the calendar — which is why it is the first component expected
    to graduate onto the real-money surface (PLAN_REDESIGN §2a).
    """
    cfg = cfg or Config()
    fy = financial_year(as_of)
    fy_end = date(as_of.year + 1 if as_of.month > 3 else as_of.year, 3, 31)
    candidates: list[HarvestCandidate] = []
    for ticker in sorted(portfolio.positions()):
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        best = _best_harvest_prefix(portfolio, ticker, price, as_of, cfg)
        if best is None:
            continue
        qty, net_gain, crossed, n_lots = best
        sell_cb = compute_costs(Side.SELL, qty, price, cfg.cost)
        buy_cb = compute_costs(Side.BUY, qty, price, cfg.cost)
        lots = portfolio.ledger.open_lots(ticker)[:n_lots]
        near_boundary = any(
            0 < (twelve_months_after(lot.acquisition_date) - as_of).days <= _BOUNDARY_WINDOW_DAYS
            for lot in lots
        )
        candidates.append(
            HarvestCandidate(
                ticker=ticker,
                quantity=qty,
                price=price,
                net_gain=net_gain,
                gain_crossed=crossed,
                lots_consumed=n_lots,
                charges=sell_cb.total + buy_cb.total,
                resets_long_term=near_boundary,
            )
        )
    return HarvestAdvice(
        as_of=as_of,
        financial_year=fy,
        candidates=candidates,
        realized_gains_this_fy=portfolio.gains.ltcg_realized(fy),
        days_to_fy_end=(fy_end - as_of).days,
    )
