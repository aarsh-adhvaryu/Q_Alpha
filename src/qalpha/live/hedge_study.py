"""hedge_paper.py — the tax-free futures hedge run FORWARD as a live paper overlay.

Sprint 2 proved the gauge-triggered short-futures hedge clears the bar *in backtest*. This runs the
**same** validated machinery (`fragility.compute_fragility` → `hedge.hedge_active` →
`hedge.apply_futures_hedge`) **forward in real time** on a passive Nifty book, accumulating a live
paper track record — the hedge's analogue of the product's criterion-6 paper run. No real derivatives
are traded: it tracks what the hedge *would* do (modelled F&O cost + 30% business-income tax), so if
it holds up live over months it is ready to integrate alongside the product's GO.

**Stateless by design:** the cross-asset panel IS the state. Each daily run recomputes the forward
curve from a fixed :data:`FORWARD_START` to today off the (refreshed) panel — there are no lots to
persist (a passive overlay), so recomputation can't drift. The gauge uses the panel's full history for
its *causal* percentile ranks (no look-ahead); only the equity curve is restricted to the forward
window.

**Honest caveat (unchanged):** the gauge is *coincident* and severe crashes are rare, so a forward
window may contain no stress event — the hedge then just sits OFF and you get "not disproven", not
"proven in live fire". Its GO legitimately waits on a real event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from qalpha.live.fragility import compute_fragility
from qalpha.live.hedge import apply_futures_hedge, hedge_active

# The forward paper run begins here (the validated operating point: τ≥0.7, persist 5, h=0.5).
FORWARD_START = date(2026, 6, 19)
DEFAULT_TAU = 0.7
DEFAULT_PERSIST = 5
DEFAULT_H = 0.5
_GAUGE_HISTORY_DAYS = 504  # ~2 trading years of gauge to chart as context (real cross-asset data)

# The validated backtest evidence this forward run is re-testing (from reports/hedge_book_findings.md
# + hedge_findings.md). Shown as context so a calm forward day still conveys the real-world proof.
BACKTEST_CONTEXT: dict[str, str] = {
    "window": "qalpha book 2012–26 (incl. COVID); index 1997–2026 (incl. 2008 GFC + COVID)",
    "full_book": "Sharpe 1.08→1.13, maxDD −25.2→−22.5, CAGR ~flat, still beats 1/N",
    "covid_2020": "drawdown −25.2→−9.7, Sharpe 1.55→2.47",
    "index_2008_covid": "2008 GFC DD −60.9→−52.1 · COVID −38.1→−22.8 (OOS, untuned)",
    "robustness": "survives 2–3d execution lag, ≫10× cost + 40% tax bracket; operate at τ≥0.7",
}


@dataclass(frozen=True)
class HedgePaperResult:
    """A snapshot of the forward hedge paper run: state now + the forward hedged/unhedged curves."""

    forward_start: date
    as_of: date
    base: str
    tau: float
    persist: int
    h: float
    gauge_now: float
    hedge_on: bool
    gauge_history: pd.Series  # trailing ~2y of the systemic-stress gauge (real data, charts daily)
    hedged: pd.Series  # forward paper equity of the hedged book (starts at 1.0 on forward_start)
    unhedged: pd.Series  # forward paper equity of the unhedged book (starts at 1.0)
    episodes: int
    cost: float  # cumulative hedge transaction + roll cost (book-value units)
    tax: float  # cumulative F&O business-income tax on hedge gains

    @property
    def days(self) -> int:
        return len(self.unhedged)

    @property
    def hedged_return(self) -> float:
        return float(self.hedged.iloc[-1] - 1.0) if self.days else 0.0

    @property
    def unhedged_return(self) -> float:
        return float(self.unhedged.iloc[-1] - 1.0) if self.days else 0.0

    @property
    def level(self) -> str:
        """A traffic-light reading of the current gauge (display only)."""
        if self.gauge_now >= self.tau:
            return "elevated"
        if self.gauge_now >= self.tau - 0.15:
            return "watch"
        return "calm"


def forward_hedge_track(
    panel: pd.DataFrame,
    *,
    forward_start: date = FORWARD_START,
    base: str = "nifty",
    tau: float = DEFAULT_TAU,
    persist: int = DEFAULT_PERSIST,
    h: float = DEFAULT_H,
) -> HedgePaperResult:
    """Compute the forward hedge paper run from ``forward_start`` to the panel's last date.

    ``panel`` is the cross-asset fragility panel (``data/fragility_panel.csv``). The gauge and the
    hedge state machine run over the panel's *full* causal history; the hedged/unhedged equity curves
    are then accumulated only over the forward window (normalised to 1.0 at the start).
    """
    gauge = compute_fragility(panel).composite
    base_ret = panel[base].dropna().pct_change().dropna()
    g = gauge.reindex(base_ret.index, method="ffill")
    active = hedge_active(
        g, tau, persist
    )  # full-history state (correct persistence at the boundary)

    fwd_ret = base_ret[base_ret.index >= pd.Timestamp(forward_start)]
    active_fwd = active.reindex(fwd_ret.index).fillna(False).astype(bool)
    res = apply_futures_hedge(fwd_ret, fwd_ret, active_fwd, h=h, apply_costs=True)
    unhedged = (1.0 + fwd_ret).cumprod()

    as_of = base_ret.index[-1].date() if len(base_ret) else forward_start
    gauge_clean = g.dropna()
    gauge_now = float(gauge_clean.iloc[-1]) if len(gauge_clean) else 0.0
    hedge_on = bool(active.iloc[-1]) if len(active) else False
    return HedgePaperResult(
        forward_start=forward_start,
        as_of=as_of,
        base=base,
        tau=tau,
        persist=persist,
        h=h,
        gauge_now=gauge_now,
        hedge_on=hedge_on,
        gauge_history=gauge_clean.tail(_GAUGE_HISTORY_DAYS),
        hedged=res.equity,
        unhedged=unhedged,
        episodes=res.episodes,
        cost=res.cost,
        tax=res.tax,
    )


def track_record_csv(result: HedgePaperResult) -> str:
    """The forward paper curves as committable CSV: date, hedged, unhedged (both indexed to 1.0)."""
    rows = ["date,hedged,unhedged"]
    unhedged = result.unhedged
    hedged = result.hedged.reindex(unhedged.index)
    dates = pd.DatetimeIndex(unhedged.index).strftime("%Y-%m-%d")
    for d, h, u in zip(dates, hedged.to_numpy(), unhedged.to_numpy(), strict=True):
        rows.append(f"{d},{float(h):.6f},{float(u):.6f}")
    return "\n".join(rows) + "\n"


def study_status(result: HedgePaperResult, today: date, *, max_weekdays: int = 2) -> str:
    """The study's liveness and evidence, stated on its face — never inferred from a chart.

    **Why this exists.** The research forward run died on 2026-07-21 and nobody noticed for 38 days,
    because a hedge that never fires and a hedge that is not running produce *the same picture*: two
    overlapping lines. Its 23 marks contained **zero** hedge episodes, so the chart looked exactly as
    it would have looked had the cron been healthy. The failure mode and the success mode were
    visually identical — the same shape as the seven label defects of 2026-08-28, a surface that
    could not report bad news.

    So the panel leads with the two facts a chart cannot show: **is it still running**, and **has the
    gauge ever fired**. "No episodes" is a legitimate, reportable state — the market simply has not
    obliged — but it must be *said*, and it must be distinguishable from silence.
    """
    stale_days = max(0, _weekdays_between(result.as_of, today) - 1)
    lines: list[str] = []
    if stale_days >= max_weekdays:
        lines.append(
            f"🔴 **The hedge study is not running.** Last mark **{result.as_of}** — "
            f"{stale_days} weekday(s) missed. Nothing below has been updated since; check the cron. "
            "This is the failure the 2026-07-21 outage hid for 38 days."
        )
    else:
        lines.append(f"✓ Running — last mark {result.as_of}.")

    if result.episodes == 0:
        lines.append(
            f"⚪ **The gauge has fired 0 times in {result.days} marks.** The hedged and unhedged "
            "curves are therefore identical *by construction*, not by measurement — this run has "
            "produced **no evidence** about whether hedging works, and cannot until a drawdown "
            "arrives (GO criterion 2)."
        )
    else:
        lines.append(
            f"🟠 **{result.episodes} hedge episode(s) over {result.days} marks.** Cost "
            f"{result.cost:.4f} + F&O tax {result.tax:.4f} of book value — the curves diverge, so "
            "the comparison below is measuring something."
        )
    return "\n\n".join(lines)


def _weekdays_between(start: date, end: date) -> int:
    """Weekdays strictly after ``start`` up to and including ``end`` (0 when end <= start)."""
    n, d = 0, start + timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n
