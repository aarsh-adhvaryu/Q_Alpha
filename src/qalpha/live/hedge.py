"""hedge.py — the tax-free short-futures downside-protection overlay (promoted from research).

The one thing the research arc found that actually *minimises loss* in a crash: hold every share
(so **no capital-gains tax**, and you don't miss the recovery) and overlay a short index-futures
position, sized at ratio ``h`` of book value, while the systemic-stress gauge is elevated. It cut the
COVID drawdown ≈−25%→−10% on the validated book with ~no return given up. The only cost is futures
transaction + monthly roll + **F&O business-income tax** on hedge gains (the honest India treatment).

*Why this and not "sell to go defensive":* selling appreciated equity to dodge a drawdown was tested
(the research HMM sell-overlay) and **lost** — the capital-gains tax outweighed the avoided loss,
because drawdowns mostly recover. The tax is always the killer; hedge, don't sell.

**No look-ahead (load-bearing):** ``hedge_active`` is a causal state machine over the gauge; the
position is lagged by ``execution_lag`` inside ``apply_futures_hedge`` (the gauge at t sets the
position carried into t+1). This is the validated research module, brought into the product so the
auto-pilot can forward-test the protection on fake money. **It never places a real F&O trade.**
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Conservative Zerodha F&O cost model (fraction of hedge notional).
COST_EVENT = 0.0003  # entry or exit (brokerage + STT-on-sell + exchange/GST/stamp), per side
COST_ROLL = 0.0005  # monthly roll (close near + open next)
FNO_TAX = 0.30  # F&O = non-speculative business income → slab; 30% high-bracket proxy on net gains


@dataclass(frozen=True)
class HedgeResult:
    equity: pd.Series  # hedged book equity (normalised to 1.0 at start)
    cost: float  # cumulative transaction + roll cost (book-value units)
    tax: float  # cumulative F&O business-income tax on hedge gains
    episodes: int  # number of distinct hedge episodes


def stress_gauge(index_close: pd.Series, *, full_stress_drawdown: float = 0.15) -> pd.Series:
    """A product-native systemic-stress gauge in [0, 1] from the index's drawdown vs its rolling
    1-year high — 0 at a fresh high, 1.0 once it is ``full_stress_drawdown`` (15%) or more below it.

    This is the same drawdown signal the product's 'Systemic risk' tab already uses (the richer
    cross-asset fragility gauge stays in research as the upgrade path). Causal — only past/present.
    """
    high = index_close.rolling(252, min_periods=20).max()
    drawdown = (high - index_close) / high  # ≥ 0; deeper = more stress
    return (drawdown / full_stress_drawdown).clip(lower=0.0, upper=1.0).fillna(0.0)


def hedge_active(gauge: pd.Series, tau: float, persist: int) -> pd.Series:
    """Causal hedge-state: ON after the gauge holds ≥ τ for ``persist`` days; OFF once it drops < τ.

    Uses only past/present gauge values; the persistence filter suppresses whipsaw. The execution lag
    (so the position is set from *yesterday's* gauge) is applied later by ``apply_futures_hedge``.
    """
    above = (gauge >= tau).fillna(False)
    streak = above.rolling(persist, min_periods=persist).sum() == persist
    state = False
    out: list[bool] = []
    for ab, stk in zip(above.to_numpy(), streak.to_numpy(), strict=True):
        if not ab:
            state = False
        elif stk:
            state = True
        out.append(state)
    return pd.Series(out, index=gauge.index, name="hedge_active")


def apply_futures_hedge(
    book_ret: pd.Series,
    index_ret: pd.Series,
    active: pd.Series,
    *,
    h: float,
    execution_lag: int = 1,
    apply_costs: bool = True,
    cost_event: float = COST_EVENT,
    cost_roll: float = COST_ROLL,
    fno_tax: float = FNO_TAX,
) -> HedgeResult:
    """Overlay a short index-futures hedge on a book given its and the index's daily returns.

    ``book_ret`` — the book's daily returns (a passive index, or the qalpha strategy book).
    ``index_ret`` — the hedging index's daily returns (Nifty futures underlying).
    ``active`` — causal hedge state from ``hedge_active``; lagged by ``execution_lag`` here so the
    position carried into day t was decided on data ≤ t-lag (no look-ahead).
    """
    idx = pd.DatetimeIndex(book_ret.index)
    pos = active.reindex(idx).fillna(False).astype(bool)
    if execution_lag:
        pos = pos.shift(execution_lag).fillna(False).astype(bool)
    ir = index_ret.reindex(idx).fillna(0.0)
    br = book_ret.fillna(0.0)
    month_end = idx.to_series() == idx.to_series().groupby(idx.to_period("M")).transform("max")

    pv = 1.0
    equity: list[float] = []
    total_cost = total_tax = 0.0
    episodes = 0
    prev = False
    episode_pnl = 0.0
    for t in idx:
        on = bool(pos.loc[t])
        hedge_r = -h * float(ir.loc[t]) if on else 0.0
        pv_before = pv
        pv *= 1.0 + float(br.loc[t]) + hedge_r
        episode_pnl += hedge_r * pv_before
        notional = h * pv
        if on != prev:
            c = cost_event * notional if apply_costs else 0.0
            pv -= c
            total_cost += c
            if on:
                episodes += 1
        if on and bool(month_end.loc[t]):
            c = cost_roll * notional if apply_costs else 0.0
            pv -= c
            total_cost += c
        if prev and not on:  # episode closed → tax the net hedge GAIN as business income
            tax = fno_tax * max(0.0, episode_pnl) if apply_costs else 0.0
            pv -= tax
            total_tax += tax
            episode_pnl = 0.0
        prev = on
        equity.append(pv)

    # An episode still ON at the final bar never reached the close branch — tax its gain too, else a
    # run that ends mid-hedge silently over-states the hedged return (untaxed trailing gain).
    if prev and apply_costs and episode_pnl > 0.0:
        tax = fno_tax * episode_pnl
        pv -= tax
        total_tax += tax
        equity[-1] = pv

    return HedgeResult(
        equity=pd.Series(equity, index=idx, name="hedged"),
        cost=total_cost,
        tax=total_tax,
        episodes=episodes,
    )
