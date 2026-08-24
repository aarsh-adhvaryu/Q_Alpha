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
from dataclasses import dataclass
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
    """Which holdings to sell to raise ``amount`` at the least tax, vs a naive pro-rata sell."""

    as_of: date
    amount: Decimal
    smart_orders: list[TradeRecord]
    smart_tax: Decimal
    smart_raised: Decimal
    naive_tax: Decimal
    tax_saved: Decimal

    def render(self) -> str:
        lines = [
            f"### Raise {_rupees(self.amount)} cash  (as of {self.as_of})",
            "",
            "**Tax-smart source order** (long-term lots and losers first, gains kept in the "
            "exemption):",
            "",
            "| Sell | Qty | Price | Tax |",
            "|---|---|---|---|",
        ]
        for o in self.smart_orders:
            lines.append(f"| {o.ticker} | {o.quantity} | {_rupees(o.price)} | {_rupees(o.tax)} |")
        lines += [
            "",
            f"- Raises {_rupees(self.smart_raised)} for **{_rupees(self.smart_tax)} tax**.",
            f"- A naive pro-rata sell across all holdings would cost {_rupees(self.naive_tax)}.",
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
    portfolio: Portfolio, prices: Mapping[str, Decimal], as_of: date
) -> list[_Liquidation]:
    """Per-holding full-liquidation cost, ranked by tax per rupee raised (cheapest first)."""
    rows: list[_Liquidation] = []
    for ticker, qty in portfolio.positions().items():
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        realized, cb = portfolio.preview_sell(as_of, ticker, qty, price)
        tax = sum((g.tax for g in realized), _ZERO)
        proceeds = qty * price - cb.total - tax
        per_rupee = float(tax / proceeds) if proceeds > 0 else 0.0
        rows.append(_Liquidation(ticker, qty, price, proceeds, tax, per_rupee))
    rows.sort(key=lambda r: (r.tax_per_rupee, r.ticker))
    return rows


def advise_raise_cash(
    portfolio: Portfolio,
    amount: Decimal,
    prices: Mapping[str, Decimal],
    as_of: date,
) -> RaiseCashAdvice:
    """Plan the least-tax way to raise ``amount`` in cash, vs a naive pro-rata liquidation.

    The smart plan is costed exactly by replaying the chosen sells on a clone in order (the FY LTCG
    exemption depletes across sequential sells, so order matters). Share counts are sized off the
    gross price, so the cash actually raised can be a touch below ``amount`` once tax is netted —
    the figures are advisory, the tax numbers are exact.
    """
    ranked = _liquidation_efficiency(portfolio, prices, as_of)

    smart = portfolio.clone()
    orders: list[TradeRecord] = []
    raised = _ZERO
    for row in ranked:
        if raised >= amount:
            break
        need = amount - raised
        # Size off a slightly discounted price so the net (post cost+tax) clears ``need`` in one
        # source instead of spilling a stray share into the next — usually more taxable — holding.
        buffered = row.price * Decimal("0.995")
        shares = min(row.quantity, (need / buffered).to_integral_value(rounding=ROUND_CEILING))
        if shares <= 0:
            continue
        rec = smart.sell(as_of, row.ticker, shares, row.price)
        orders.append(rec)
        raised += shares * row.price - rec.cost - rec.tax
    cess_rate = portfolio.tax_cfg.cess_rate  # real ITR figures include the 4% cess
    smart_tax = _add_cess(sum((o.tax for o in orders), _ZERO), cess_rate)

    # Naive baseline: sell the same fraction of every holding to raise ``amount``.
    naive = portfolio.clone()
    holdings_value = portfolio.holdings_value(prices)
    frac = min(Decimal("1"), amount / holdings_value) if holdings_value > 0 else _ZERO
    naive_tax = _ZERO
    for ticker, qty in portfolio.positions().items():
        price = prices.get(ticker)
        if price is None or price <= 0:
            continue
        shares = (qty * frac).to_integral_value(rounding=ROUND_DOWN)
        if shares > 0:
            naive_tax += naive.sell(as_of, ticker, shares, price).tax
    naive_tax = _add_cess(naive_tax, cess_rate)

    return RaiseCashAdvice(
        as_of=as_of,
        amount=amount,
        smart_orders=orders,
        smart_tax=smart_tax,
        smart_raised=raised,
        naive_tax=naive_tax,
        tax_saved=naive_tax - smart_tax,
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
