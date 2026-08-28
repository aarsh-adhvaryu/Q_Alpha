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

from collections.abc import Collection, Mapping
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
    *,
    rebase_from: Mapping[str, date] | None = None,
    exclude: Collection[str] | None = None,
) -> PositionHealthReport:
    """Assess each held name for a sustained, idiosyncratic breakdown as of ``as_of`` (no look-ahead).

    ``adj_close`` is a wide TR-adjusted price frame (dates × tickers). A name is **breaking** iff it is
    BOTH down more than ``abs_drawdown_exit`` over ``lookback_days`` AND lagging the cross-sectional
    median trailing return by more than ``rel_underperf_exit`` (the §4.7 'this company has a problem,
    it's not just the market' test). **watch** is the early tier (half the drawdown AND below median).

    **Price-continuity inputs.** ``adj_close`` corrects splits and dividends and nothing else, so a
    demerger leaves a step-down that this rule reads as a company falling apart. PR-2 taught
    :func:`~qalpha.live.deploy.cheapness_scores` to re-base; this detector was left on the raw series,
    and the two then contradicted each other on one screen — the guard scored VEDL 22.1% off its high
    (a normal pullback) while this function called the same name ``-59% over ~6mo, a name-specific
    breakdown``. Callers pass :func:`~qalpha.live.price_integrity.rebase_starts` as ``rebase_from`` to
    measure a flagged name only over the window that starts at its gap (the first comparable price),
    and :func:`~qalpha.live.price_integrity.excluded_from_tilt` as ``exclude`` for flagged names with
    too little post-gap history to read at all — those are reported unreadable rather than guessed at,
    which for this detector means *not* flagged, since an artifact is not evidence of a breakdown.

    Both default to off, leaving the original behaviour exactly intact for every caller that does not
    opt in — the validated SIP backtest among them.
    """
    cfg = cfg or DefensiveConfig()
    rebase = rebase_from or {}
    skip = set(exclude or ())
    frame = adj_close.loc[: pd.Timestamp(as_of)].dropna(how="all")
    if len(frame) <= cfg.lookback_days:
        return PositionHealthReport(as_of, [])

    last = frame.iloc[-1]
    prior = frame.iloc[-1 - cfg.lookback_days]
    trailing = (last / prior - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    # Re-based names are measured from their gap day instead of from ``lookback_days`` ago — a
    # shorter window, but the only one whose two endpoints price the same instrument.
    for ticker, start in rebase.items():
        if ticker not in frame.columns:
            continue
        window = frame[ticker].loc[pd.Timestamp(start) :].dropna()
        if len(window) < 2 or float(window.iloc[0]) <= 0:
            skip.add(ticker)
            continue
        trailing[ticker] = float(last[ticker] / window.iloc[0] - 1.0)
    if trailing.empty:
        return PositionHealthReport(as_of, [])
    # Median AFTER re-basing: the systemic baseline must not be set by artifacts either.
    market = float(trailing.median())  # the systemic baseline (how the whole cross-section moved)

    out: list[HoldingHealth] = []
    for t in held:
        if t in skip:
            out.append(
                HoldingHealth(
                    t,
                    0.0,
                    0.0,
                    0.0,
                    "healthy",
                    f"{t}: price series breaks at a corporate action with too little history since "
                    "— not readable, so not flagged.",
                )
            )
            continue
        if t not in trailing.index:
            out.append(
                HoldingHealth(t, 0.0, 0.0, 0.0, "healthy", f"{t}: no recent price — skipped.")
            )
            continue
        ret = float(trailing[t])
        excess = ret - market
        window = frame[t]
        if t in rebase:
            window = window.loc[pd.Timestamp(rebase[t]) :]
        window_high = float(window.tail(cfg.lookback_days).max())
        dd = float(last[t] / window_high - 1.0) if window_high > 0 else 0.0
        # A re-based name is measured over a SHORTER window than the others, so it must not be
        # labelled "~6mo" — that is the same mislabelling this whole guard exists to undo.
        span = f"since its {rebase[t]:%b %Y} corporate action" if t in rebase else "over ~6mo"

        if ret < -cfg.abs_drawdown_exit and excess < -cfg.rel_underperf_exit:
            level = "breaking"
            note = (
                f"**{t}**: {ret:+.0%} {span}, lagging the market ({market:+.0%}) by "
                f"{excess:+.0%} — a name-specific breakdown, not a market move."
            )
        elif ret < -cfg.abs_drawdown_exit / 2 and excess < 0:
            level = "watch"
            note = f"{t}: {ret:+.0%} {span}, {excess:+.0%} vs market — weak, watching."
        else:
            level = "healthy"
            note = f"{t}: {ret:+.0%} {span} ({excess:+.0%} vs market) — healthy."
        out.append(HoldingHealth(t, ret, excess, dd, level, note))
    return PositionHealthReport(as_of, out)
