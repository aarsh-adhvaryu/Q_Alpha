"""options.py — a convex, defined-risk protective-put hedge (regime track, Sprint 2 P3).

The futures hedge (`regime/hedge.py`) is *linear*: it caps the downside but also the upside, so it
bleeds when the (coincident) gauge fires on a dip that then rebounds. A **protective put** is convex:
the most you lose is the premium, and you **keep the upside** — better suited to "reduce risk, keep
profit" when the signal is imperfect. The cost is the premium drag in calm periods.

We price rolling ~1-month Nifty puts with Black–Scholes, using **India VIX as the implied vol** and
marking the put to market daily. The equity book is never sold (no capital-gains tax); option P&L is
F&O business income (taxed on net gains). Same no-look-ahead discipline: the position is set from the
lagged gauge, and BS uses only the current spot/vol.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from qalpha.live.hedge import COST_EVENT, FNO_TAX


def bs_put(s: float, k: float, t_years: float, sigma: float, r: float = 0.06) -> float:
    """Black–Scholes European put price. ``sigma`` is annualised vol (e.g. India VIX/100)."""
    if t_years <= 0 or sigma <= 0 or s <= 0:
        return max(k - s, 0.0)
    sqrt_t = np.sqrt(t_years)
    d1 = (np.log(s / k) + (r + 0.5 * sigma**2) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return float(k * np.exp(-r * t_years) * norm.cdf(-d2) - s * norm.cdf(-d1))


@dataclass(frozen=True)
class PutHedgeResult:
    equity: pd.Series
    premium_paid: float  # cumulative premium spent (book-value units)
    tax: float  # F&O business-income tax on net option gains
    rolls: int  # number of puts bought (initial + rolls)


def apply_put_hedge(
    book_ret: pd.Series,
    index_level: pd.Series,
    vix: pd.Series,
    active: pd.Series,
    *,
    h: float,
    otm: float = 0.05,
    tenor_days: int = 30,
    r: float = 0.06,
    execution_lag: int = 1,
    apply_costs: bool = True,
) -> PutHedgeResult:
    """Overlay a rolling protective put (notional ``h``·book) while the gauge is active.

    The put is marked to market daily via Black–Scholes; rolled at expiry; closed when the gauge
    turns off. ``index_level``/``vix`` give the BS spot and implied vol on each day.
    """
    idx = pd.DatetimeIndex(book_ret.index)
    pos = active.reindex(idx).fillna(False).astype(bool)
    if execution_lag:
        pos = pos.shift(execution_lag).fillna(False).astype(bool)
    spot = index_level.reindex(idx).ffill()
    sig = (vix.reindex(idx).ffill() / 100.0).clip(lower=0.05)
    br = book_ret.fillna(0.0)

    pv = 1.0
    equity: list[float] = []
    premium_paid = total_tax = 0.0
    rolls = 0
    # current put: strike, expiry position, units, last MTM value, episode option P&L
    strike = units = prev_val = notional = 0.0
    expiry_pos = -1
    episode_pnl = 0.0
    has_put = False

    positions = list(range(len(idx)))
    for i, t in zip(positions, idx, strict=True):
        s = float(spot.loc[t])
        vol = float(sig.loc[t])
        pv *= 1.0 + float(br.loc[t])
        on = bool(pos.loc[t])

        if on:
            # roll at expiry: realise the expiring put at intrinsic, then re-open
            if has_put and i >= expiry_pos:
                intrinsic = max(strike - s, 0.0) * units
                pv += intrinsic - prev_val
                episode_pnl += intrinsic - prev_val
                if apply_costs:
                    pv -= COST_EVENT * notional
                has_put = False
            if not has_put:  # open a fresh put
                strike = (1.0 - otm) * s
                units = h * pv / s
                notional = h * pv
                prev_val = bs_put(s, strike, tenor_days / 365.0, vol, r) * units
                premium_paid += prev_val
                expiry_pos = i + tenor_days
                if apply_costs:
                    pv -= COST_EVENT * notional
                has_put = True
                rolls += 1
            else:  # mark to market
                t_rem = max((expiry_pos - i) / 365.0, 1.0 / 365.0)
                val = bs_put(s, strike, t_rem, vol, r) * units
                pv += val - prev_val
                episode_pnl += val - prev_val
                prev_val = val
        elif has_put:  # gauge turned off → close the put at its current value
            t_rem = max((expiry_pos - i) / 365.0, 1.0 / 365.0)
            val = bs_put(s, strike, t_rem, vol, r) * units
            pv += val - prev_val
            episode_pnl += val - prev_val
            if apply_costs:
                pv -= COST_EVENT * notional
            has_put = False
            tax = FNO_TAX * max(0.0, episode_pnl) if apply_costs else 0.0
            pv -= tax
            total_tax += tax
            episode_pnl = 0.0

        equity.append(pv)

    return PutHedgeResult(
        equity=pd.Series(equity, index=idx, name="put_hedged"),
        premium_paid=premium_paid,
        tax=total_tax,
        rolls=rolls,
    )
