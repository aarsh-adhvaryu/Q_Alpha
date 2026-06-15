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

from qalpha.accounting.capital_gains import RealizedGain, financial_year
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
    total_tax: Decimal
    ltcg_sheltered: Decimal
    exemption_remaining: Decimal
    net_proceeds: Decimal
    tax_free_quantity: Decimal
    boundary_waits: list[BoundaryWait]

    def render(self) -> str:
        lines = [
            f"### Sell {self.quantity} {self.ticker} @ {_rupees(self.price)}  (as of {self.as_of})",
            "",
            f"- Gross proceeds: {_rupees(self.quantity * self.price)}",
            f"- Realized gain: short-term {_rupees(self.stcg_gain)} · "
            f"long-term {_rupees(self.ltcg_gain)}",
            f"- Transaction cost: {_rupees(self.cost)}",
            f"- **Capital-gains tax: {_rupees(self.total_tax)}**",
            f"- **Net you receive: {_rupees(self.net_proceeds)}**",
            "",
            "**Tax-smart notes**",
        ]
        if self.ltcg_sheltered > 0:
            lines.append(
                f"- {_rupees(self.ltcg_sheltered)} of long-term gain is shielded by your remaining "
                f"{_rupees(self.exemption_remaining)} FY exemption."
            )
        else:
            lines.append(f"- Remaining FY LTCG exemption: {_rupees(self.exemption_remaining)}.")
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
        is_long_term = (as_of - lot.acquisition_date).days >= portfolio.tax_cfg.ltcg_holding_days
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
        days_to_lt = cfg.tax.ltcg_holding_days - g.holding_days
        if 0 < days_to_lt <= _BOUNDARY_WINDOW_DAYS:
            out.append(
                BoundaryWait(
                    quantity=g.quantity,
                    holding_days=g.holding_days,
                    days_to_long_term=days_to_lt,
                    long_term_date=g.acquisition_date + timedelta(days=cfg.tax.ltcg_holding_days),
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
) -> SellAdvice:
    """Tax breakdown + smart alternatives for selling ``quantity`` (default: all) of ``ticker``."""
    held = portfolio.ledger.quantity_held(ticker)
    if held <= 0:
        raise ValueError(f"no open position in {ticker}")
    qty = held if quantity is None else min(quantity, held)
    if qty <= 0:
        raise ValueError("sell quantity must be positive")

    realized, cb = portfolio.preview_sell(as_of, ticker, qty, price)
    stcg = [g for g in realized if g.gain_type == "STCG"]
    ltcg = [g for g in realized if g.gain_type == "LTCG"]
    total_tax = sum((g.tax for g in realized), _ZERO)
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
        ltcg_sheltered=sum((g.gain - g.taxable_gain for g in ltcg if g.gain > 0), _ZERO),
        exemption_remaining=headroom,
        net_proceeds=qty * price - cb.total - total_tax,
        tax_free_quantity=_tax_free_quantity(portfolio, ticker, price, as_of, headroom),
        boundary_waits=_boundary_waits(realized, cfg),
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
    smart_tax = sum((o.tax for o in orders), _ZERO)

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

    def render(self) -> str:
        lines = [
            f"### Deploy {_rupees(self.amount)} of new money  (as of {self.as_of})",
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
            f"- Transaction cost: {_rupees(self.buy_cost)} · leftover cash: "
            f"{_rupees(self.leftover_cash)}.",
            f"- A full rebalance to target would instead realize {_rupees(self.naive_tax)} tax "
            f"(cost {_rupees(self.naive_cost)}).",
            f"- **Tax saved by routing new money to underweights: {_rupees(self.tax_saved)}.**",
        ]
        return "\n".join(lines)


def advise_deploy(
    portfolio: Portfolio,
    amount: Decimal,
    target: pd.Series,
    prices: Mapping[str, Decimal],
    as_of: date,
) -> DeployAdvice:
    """Advise deploying ``amount`` of fresh capital toward ``target`` weights with zero tax.

    Smart path: spend the idle cash + new money buying whole shares toward ``target``, always topping
    up the **most underweight** name that is still affordable, until no further share fits — pure
    buys, so no capital-gains tax is realized (§2.9 fresh-capital routing). Buying whole shares one at
    a time toward the largest shortfall both tracks target weights and drives idle cash down to less
    than one share of the cheapest name (a single bulk floor would strand a share's worth per name).
    Naive path: a full rebalance to ``target`` on the same post-injection book, which sells the
    overweights and realizes capital-gains tax. ``tax_saved`` is that avoided tax.
    """
    total_after = portfolio.market_value(prices) + amount
    desired_value = {
        str(t): Decimal(str(w)) * total_after
        for t, w in target.items()
        if float(w) > 0 and str(t) in prices
    }

    # Allocate whole-share buys greedily against the available cash (idle + new), leaving a small
    # buffer for the ~0.3% buy cost so the executed orders below don't get affordability-capped.
    held = portfolio.positions()
    buffered = {t: prices[t] * Decimal("1.004") for t in desired_value}
    shares: dict[str, Decimal] = dict.fromkeys(desired_value, _ZERO)
    available = portfolio.cash + amount
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
    naive_cost, naive_tax, _ = naive.estimate_rebalance(
        as_of, target, prices, min_trade_fraction=0.0
    )

    return DeployAdvice(
        as_of=as_of,
        amount=amount,
        buy_orders=buy_orders,
        buy_cost=sum((o.cost for o in buy_orders), _ZERO),
        leftover_cash=smart.cash,
        naive_tax=naive_tax,
        naive_cost=naive_cost,
        tax_saved=naive_tax,
    )
