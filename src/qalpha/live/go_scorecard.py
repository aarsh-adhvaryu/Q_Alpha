"""Deterministic GO scorecard — the autonomous "is the forward paper run ready?" verdict (§14 crit 6).

The real-money GO can't be a fixed countdown. This module evaluates the *actual* criteria against the
live paper track record and returns a 🟢/🟡/🔴 verdict that flips to **GO the moment the evidence
genuinely clears** — earlier than 6 months if it does, later (or NO-GO) if it doesn't. Pure arithmetic
over the committed equity curve + benchmark; **no LLM, no judgement call** — so the dashboard can show
it unattended and the user never has to ask anyone whether the run has passed.

Criteria (all must be 🟢 for GO):

1. **Track length (power floor)** — enough trading days for the forward estimate to mean anything. A
   floor, *not* a fixed date.
2. **Volatility event withstood (hard gate)** — the run must have lived through ≥1 genuine market
   stress event (a Nifty pullback ≥ :data:`VOL_EVENT_DRAWDOWN`). A calm-market curve, however pretty,
   cannot earn a GO — this is the spec's intent and the main reason "before 6 months" is possible only
   if a real event happens early. Absence is *pending* (🟡), never failure.
3. **Forward vs benchmark (net)** — the strategy's forward return must not materially trail the
   benchmark over the same window. A material lag is a NO-GO (🔴) — but **only once the track is long
   enough to mean anything**; below the power floor a lag is "keep waiting" (🟡), never a noise-driven
   NO-GO (a defensive book can briefly lag a sharp rally over a short window).
4. **Drawdown behaviour (market-relative)** — judged against the benchmark over the same window, NOT a
   flat absolute floor (mirrors the engine's §0 dynamic rule, drawdown.py): a deep drawdown that merely
   tracks a market crash is beta (🟢); only an *idiosyncratic* drawdown materially worse than the index
   means behaviour diverged from the validated profile (🔴 → NO-GO).
5. **Data integrity** — the track record must be dense and ordered (no missed marks / feed gaps).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise

import pandas as pd

# --- thresholds (documented, deterministic) ------------------------------------------------------
MIN_TRADING_DAYS = (
    63  # ~3 months: the statistical-power floor (NOT the 6-month target — earlier ok)
)
VOL_EVENT_DRAWDOWN = 0.10  # a ≥10% Nifty pullback in-window = a genuine volatility event to survive
LAG_TOLERANCE = (
    0.03  # forward return may trail the benchmark by ≤3 pts (short-sample noise) before 🔴
)
# "Behaviour broke" is judged MARKET-RELATIVE, not by a flat absolute floor — mirroring the engine's
# §0 dynamic drawdown rule (drawdown.py). A deep drawdown that merely tracks a market crash is beta,
# not failure; only an *idiosyncratic* drawdown materially worse than the index means behaviour
# diverged. (A flat floor would both false-pass a -34% book in a -10% market and false-fail a -36%
# book in a -45% market — the exact mistake §0 was rewritten to avoid.)
EXCESS_DD_TOLERANCE = 0.10  # the book may draw down up to 10pt MORE than Nifty before 🔴
MAX_MARK_GAP_DAYS = 7  # a >7-calendar-day gap between marks = missed runs / feed outage


@dataclass(frozen=True)
class Criterion:
    """One GO criterion. ``status`` ∈ {green, yellow, red}; ``blocking`` ones must be green for GO.

    ``awaitable`` marks a criterion you can only *wait* on, never force or hurry — the volatility
    event. When the only thing left is an awaitable criterion, the run is **READY**, not merely
    NOT YET (you're done but for the market).
    """

    name: str
    status: str
    detail: str
    blocking: bool = True
    awaitable: bool = False

    @property
    def icon(self) -> str:
        return {"green": "🟢", "yellow": "🟡", "red": "🔴"}[self.status]


@dataclass(frozen=True)
class GoScorecard:
    """The combined GO verdict over the forward paper run."""

    as_of: date
    criteria: list[Criterion]

    @property
    def verdict(self) -> str:
        """``GO`` (all green) · ``NO-GO`` (a blocking criterion red) · ``READY`` (only an *awaitable*
        criterion — the volatility event — is left) · ``NOT YET`` (still accumulating other evidence).
        """
        if any(c.status == "red" and c.blocking for c in self.criteria):
            return "NO-GO"
        if all(c.status == "green" for c in self.criteria):
            return "GO"
        non_green = [c for c in self.criteria if c.status != "green"]
        if non_green and all(c.awaitable for c in non_green):
            return "READY"
        return "NOT YET"

    def render(self) -> str:
        head = {
            "GO": "🟢 **GO** — the forward paper run has cleared every criterion.",
            "NO-GO": "🔴 **NO-GO** — a blocking criterion is failing (see below); the strategy is not "
            "behaving as validated.",
            "READY": "🟢 **READY — awaiting a stress event** — every criterion you can earn is green; "
            "the only thing left is a real market event to prove the strategy through stress (it can't "
            "be scheduled). You're done but for the market.",
            "NOT YET": "🟡 **NOT YET** — accumulating evidence; the run has not yet cleared every "
            "criterion (this is the expected state until it does).",
        }[self.verdict]
        lines = [head, ""]
        lines += [f"- {c.icon} **{c.name}** — {c.detail}" for c in self.criteria]
        return "\n".join(lines)


def _to_series(equity_curve: list[dict[str, str]]) -> pd.Series:
    """The marked-equity track record as a float Series indexed by date (sorted, deduped)."""
    if not equity_curve:
        return pd.Series(dtype=float)
    idx = [date.fromisoformat(str(p["date"])) for p in equity_curve]
    vals = [float(p["equity"]) for p in equity_curve]
    s = pd.Series(vals, index=pd.DatetimeIndex(idx), name="equity")
    return s[~s.index.duplicated(keep="last")].sort_index()


def _max_drawdown(s: pd.Series) -> float:
    """Worst peak-to-trough fractional drawdown of a value series (≤ 0; 0.0 if empty/flat)."""
    if s.empty:
        return 0.0
    running_max = s.cummax()
    return float((s / running_max - 1.0).min())


def _track_length(s: pd.Series) -> Criterion:
    n = len(s)
    if n >= MIN_TRADING_DAYS:
        return Criterion(
            "Track length", "green", f"{n} trading days marked (≥ {MIN_TRADING_DAYS})."
        )
    return Criterion(
        "Track length",
        "yellow",
        f"{n}/{MIN_TRADING_DAYS} trading days — building the minimum sample for a meaningful estimate.",
    )


def _vol_event(benchmark: pd.Series, start: date, end: date) -> Criterion:
    """Did the market throw a genuine stress event (≥VOL_EVENT_DRAWDOWN pullback) within the window?"""
    win = benchmark.loc[pd.Timestamp(start) : pd.Timestamp(end)].dropna()
    worst = _max_drawdown(win)
    if worst <= -VOL_EVENT_DRAWDOWN:
        return Criterion(
            "Volatility event withstood",
            "green",
            f"survived a {worst:.1%} Nifty pullback in-window — tested through real stress.",
            awaitable=True,
        )
    return Criterion(
        "Volatility event withstood",
        "yellow",
        f"no market stress event yet (worst Nifty pullback in-window {worst:.1%}, needs "
        f"≤ {-VOL_EVENT_DRAWDOWN:.0%}). A calm run can't earn a GO — waiting on a real event.",
        awaitable=True,
    )


def _forward_vs_benchmark(strat: pd.Series, benchmark: pd.Series, *, mature: bool) -> Criterion:
    """Strategy forward return vs the benchmark over the *same* window (total return, no annualising).

    A material lag only becomes a blocking 🔴 once the track is ``mature`` (≥ the power floor) — over a
    short window the comparison is statistical noise (a defensive book can briefly lag a sharp rally),
    so a lag there is 🟡 "keep waiting", never a NO-GO. This stops a transient short-sample NO-GO.
    """
    start, end = strat.index[0].date(), strat.index[-1].date()
    bench_win = benchmark.loc[pd.Timestamp(start) : pd.Timestamp(end)].dropna()
    strat_ret = float(strat.iloc[-1] / strat.iloc[0] - 1.0)
    if bench_win.empty:
        return Criterion(
            "Forward vs benchmark", "yellow", "no overlapping benchmark history to compare yet."
        )
    bench_ret = float(bench_win.iloc[-1] / bench_win.iloc[0] - 1.0)
    gap = strat_ret - bench_ret
    detail = f"strategy {strat_ret:+.1%} vs Nifty {bench_ret:+.1%} (Δ {gap:+.1%})."
    if gap >= 0:
        return Criterion("Forward vs benchmark", "green", "ahead of the benchmark net — " + detail)
    if gap >= -LAG_TOLERANCE:
        return Criterion(
            "Forward vs benchmark",
            "yellow",
            f"within noise of the benchmark (≤ {LAG_TOLERANCE:.0%} behind) — " + detail,
        )
    if not mature:
        return Criterion(
            "Forward vs benchmark",
            "yellow",
            f"trailing, but the {MIN_TRADING_DAYS}-day power floor isn't met yet — too short to be a "
            "NO-GO (short-sample noise) — " + detail,
        )
    return Criterion("Forward vs benchmark", "red", "trailing the benchmark materially — " + detail)


def _drawdown_behaviour(strat: pd.Series, benchmark: pd.Series) -> Criterion:
    """Market-relative drawdown check (mirrors the engine's §0 rule): a deep drawdown is only 🔴 when it
    is *idiosyncratic* — materially worse than the benchmark's over the same window. A drawdown that
    tracks (or beats) a market crash is beta, not a behaviour break."""
    dd = _max_drawdown(strat)
    start, end = strat.index[0].date(), strat.index[-1].date()
    bench_win = benchmark.loc[pd.Timestamp(start) : pd.Timestamp(end)].dropna()
    bench_dd = _max_drawdown(bench_win) if not bench_win.empty else 0.0
    excess = dd - bench_dd  # < 0 ⇒ the book fell MORE than the market (idiosyncratic)
    detail = f"worst live drawdown {dd:.1%} vs Nifty {bench_dd:.1%} (excess {excess:+.1%})."
    if excess >= -EXCESS_DD_TOLERANCE:
        return Criterion(
            "Drawdown behaviour", "green", "market-driven, within tolerance — " + detail
        )
    return Criterion(
        "Drawdown behaviour",
        "red",
        f"fell {-excess:.1%} more than the market — idiosyncratic, behaviour diverged from the "
        "validated profile. " + detail,
    )


def _integrity(s: pd.Series) -> Criterion:
    if len(s) < 2:
        return Criterion("Data integrity", "yellow", "too few marks to assess feed continuity yet.")
    dates = [t.date() for t in s.index]
    gaps = [(b - a).days for a, b in pairwise(dates)]
    worst_gap = max(gaps)
    if worst_gap > MAX_MARK_GAP_DAYS:
        return Criterion(
            "Data integrity",
            "red",
            f"a {worst_gap}-day gap between marks (> {MAX_MARK_GAP_DAYS}) — the daily pipeline missed "
            "runs; the track record has a hole.",
        )
    return Criterion(
        "Data integrity", "green", f"dense track record (largest gap {worst_gap} days)."
    )


def build_scorecard(
    equity_curve: list[dict[str, str]], benchmark: pd.Series, as_of: date
) -> GoScorecard:
    """Evaluate every GO criterion against the live paper track record + benchmark.

    ``equity_curve`` is :attr:`PaperBook.equity_curve` (``[{date, equity, cash}, ...]``); ``benchmark``
    is the Nifty 50 TRI proxy series. Deterministic — the same inputs always give the same verdict.
    """
    s = _to_series(equity_curve)
    if s.empty:
        return GoScorecard(as_of, [Criterion("Track length", "yellow", "no marks recorded yet.")])
    start, end = s.index[0].date(), s.index[-1].date()
    criteria = [
        _track_length(s),
        _vol_event(benchmark, start, end),
        _forward_vs_benchmark(s, benchmark, mature=len(s) >= MIN_TRADING_DAYS),
        _drawdown_behaviour(s, benchmark),
        _integrity(s),
    ]
    return GoScorecard(as_of, criteria)


def trading_days_remaining(equity_curve: list[dict[str, str]]) -> int:
    """How many more trading-day marks until the power floor is met (0 once cleared)."""
    return max(0, MIN_TRADING_DAYS - len(_to_series(equity_curve)))
