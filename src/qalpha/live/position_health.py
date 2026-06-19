"""Mid-cycle position-health watch — flags a holding breaking down *between* rebalances (read-only).

The core strategy rebalances slowly (annual), which is the validated tax edge — but a consumer's real
fear is "a holding falls apart in month 3 and the model just holds it for a year." This watch closes
that gap **without** touching the cadence: every day it checks each holding for a *sustained,
idiosyncratic* breakdown (the §3.6/§4.7 rule — actually bleeding over ~6 months AND badly lagging the
cross-sectional 'market', so a name-specific problem, not a market-wide dip) and surfaces it as an
**advisory alert**. It never sells — the human decides (and the Sell tab prices the exact tax).

Mirrors :func:`qalpha.backtest.defensive.idiosyncratic_exit_flags` but returns per-holding *detail*
(how far down, how much it lags, a watch tier before breaking) for the dashboard. Read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from qalpha.config import DefensiveConfig


@dataclass(frozen=True)
class HoldingHealth:
    """One holding's mid-cycle health reading."""

    ticker: str
    trailing_return: float  # return over the lookback window
    excess_vs_market: float  # trailing_return − cross-sectional median (the idiosyncratic part)
    drawdown_from_high: float  # from its own trailing high (≤ 0)
    level: str  # "breaking" | "watch" | "healthy"
    note: str

    @property
    def icon(self) -> str:
        return {"breaking": "🔴", "watch": "🟠", "healthy": "🟢"}[self.level]


@dataclass(frozen=True)
class PositionHealthReport:
    """The mid-cycle health of every current holding (advisory; never trades)."""

    as_of: date
    holdings: list[HoldingHealth]

    @property
    def breaking(self) -> list[HoldingHealth]:
        return [h for h in self.holdings if h.level == "breaking"]

    @property
    def watch(self) -> list[HoldingHealth]:
        return [h for h in self.holdings if h.level == "watch"]

    def render(self) -> str:
        if not self.holdings:
            return "No holdings to watch."
        lines: list[str] = []
        if self.breaking:
            lines.append(
                "🔴 **Breaking down — consider reviewing for exit** (idiosyncratic, not a market dip):"
            )
            lines += [f"- {h.note}" for h in self.breaking]
        if self.watch:
            lines.append("🟠 **On watch** (weak, not yet a confirmed breakdown):")
            lines += [f"- {h.note}" for h in self.watch]
        if not self.breaking and not self.watch:
            lines.append("🟢 All holdings healthy — no idiosyncratic breakdown between rebalances.")
        lines.append("")
        lines.append(
            "_Advisory only — this never sells. The Sell tab prices the exact tax if you act._"
        )
        return "\n".join(lines)


def position_health(
    adj_close: pd.DataFrame,
    held: list[str],
    as_of: date,
    cfg: DefensiveConfig | None = None,
) -> PositionHealthReport:
    """Assess each held name for a sustained, idiosyncratic breakdown as of ``as_of`` (no look-ahead).

    ``adj_close`` is a wide TR-adjusted price frame (dates × tickers). A name is **breaking** iff it is
    BOTH down more than ``abs_drawdown_exit`` over ``lookback_days`` AND lagging the cross-sectional
    median trailing return by more than ``rel_underperf_exit`` (the §4.7 'this company has a problem,
    it's not just the market' test). **watch** is the early tier (half the drawdown AND below median).
    """
    cfg = cfg or DefensiveConfig()
    frame = adj_close.loc[: pd.Timestamp(as_of)].dropna(how="all")
    if len(frame) <= cfg.lookback_days:
        return PositionHealthReport(as_of, [])

    last = frame.iloc[-1]
    prior = frame.iloc[-1 - cfg.lookback_days]
    trailing = (last / prior - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    if trailing.empty:
        return PositionHealthReport(as_of, [])
    market = float(trailing.median())  # the systemic baseline (how the whole cross-section moved)

    out: list[HoldingHealth] = []
    for t in held:
        if t not in trailing.index:
            out.append(
                HoldingHealth(t, 0.0, 0.0, 0.0, "healthy", f"{t}: no recent price — skipped.")
            )
            continue
        ret = float(trailing[t])
        excess = ret - market
        window_high = float(frame[t].tail(cfg.lookback_days).max())
        dd = float(last[t] / window_high - 1.0) if window_high > 0 else 0.0

        if ret < -cfg.abs_drawdown_exit and excess < -cfg.rel_underperf_exit:
            level = "breaking"
            note = (
                f"**{t}**: {ret:+.0%} over ~6mo, lagging the market ({market:+.0%}) by "
                f"{excess:+.0%} — a name-specific breakdown, not a market move."
            )
        elif ret < -cfg.abs_drawdown_exit / 2 and excess < 0:
            level = "watch"
            note = f"{t}: {ret:+.0%} over ~6mo, {excess:+.0%} vs market — weak, watching."
        else:
            level = "healthy"
            note = f"{t}: {ret:+.0%} over ~6mo ({excess:+.0%} vs market) — healthy."
        out.append(HoldingHealth(t, ret, excess, dd, level, note))
    return PositionHealthReport(as_of, out)
