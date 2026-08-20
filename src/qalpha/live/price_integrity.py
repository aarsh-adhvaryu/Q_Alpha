"""Price-continuity guard — stop corporate actions from reading as discounts (PLAN_TRUST_REPAIR PR-2).

The deploy advisor scores "cheap" as the fractional pullback below each name's 1-year high
(:func:`~qalpha.live.deploy.cheapness_scores`), computed over yfinance **Adj Close**. That series is
corrected for splits and for dividends — and for **nothing else**. A demerger or spinoff moves value
out of the listed entity, so the price steps down by the value that left, and *no adjustment is
applied*. To a 1-year-high rule that step is indistinguishable from a 65% crash, and the phantom
discount persists for a full trading year.

This is not hypothetical. Exactly two of the 95 Nifty-100 watchlist names carried such a step
(VEDL −64.9% on 2026-04-30, TRENT −33.0% on 2026-01-01); both ranked **#1 and #2** on cheapness and
together took 44.4% of a ₹100,000 recommendation. That is the defect this module exists to close.

**The fix is a re-base, not a veto.** A flagged name's 1-year high is recomputed over the window that
starts at the gap — the first price on the new, comparable basis — so the name keeps a *correct*
cheapness reading rather than being silently dropped. Only when too little post-gap history exists to
mean anything does the name fall back to a zero (untilted) score.

**Why the corporate-actions feed is consulted at all.** Since ``adj_close`` already handles splits and
dividends, a residual gap is unexplained by construction — so the default (no feed) flags every gap,
which is the conservative direction. The optional cross-check exists because yfinance's adjustment can
lag the ex-date: a panel downloaded in that window shows an *unadjusted* split as a gap, and matching
it against :func:`~qalpha.live.corporate_actions_feed.corporate_actions_from_series` keeps a real,
already-understood action from being reported as a data defect. That function is reused, never
reimplemented — split-vs-bonus nuance lives there and stays there.

Pure over already-loaded data (the feed is injected, never fetched here), so the whole guard is
unit-testable offline and adds no network call to a dashboard render.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction

#: A one-day move at or beyond this magnitude is a candidate discontinuity. Chosen well above the
#: worst genuine single-session moves in the Nifty 100 (circuit limits aside, a real name rarely
#: gives up a quarter of its value in one session) and far below the artifacts we must catch
#: (−33.0% and −64.9%). Both directions count: an unexplained *spike* corrupts the 1-year high just
#: as an unexplained *step-down* does.
DEFAULT_GAP_THRESHOLD = 0.25

#: How close a known corporate action must sit to the gap to explain it. yfinance's ex-date and the
#: session the adjustment lands on need not be the same day (weekends, holidays, feed lag).
_MATCH_TOLERANCE_DAYS = 3

#: Below this many post-gap observations there is not enough of a re-based window to read a pullback
#: from, so the name scores 0 (no tilt) rather than a number computed on almost nothing.
MIN_POST_GAP_OBSERVATIONS = 20


@dataclass(frozen=True)
class PriceGap:
    """One discontinuity in a price series — a day the name stopped being comparable to itself."""

    ticker: str
    on: date  # the session the gap lands on; the first price on the new basis
    ret: float  # the one-day return, e.g. -0.649
    explained_by: str | None  # a matched corporate action, or None if unexplained
    post_gap_observations: int  # marks available from ``on`` through ``as_of``

    @property
    def unexplained(self) -> bool:
        return self.explained_by is None

    @property
    def rebasable(self) -> bool:
        """Is there enough post-gap history to read a re-based 1-year high from?"""
        return self.post_gap_observations >= MIN_POST_GAP_OBSERVATIONS

    def describe(self) -> str:
        pct = self.ret * 100
        if self.explained_by is not None:
            return f"{self.ticker}: {pct:+.1f}% on {self.on} — explained ({self.explained_by})."
        tail = (
            f"1y high re-based to {self.on} ({self.post_gap_observations} marks since)"
            if self.rebasable
            else f"only {self.post_gap_observations} marks since — cheapness set to 0 (no tilt)"
        )
        return (
            f"{self.ticker}: unexplained {pct:+.1f}% step on {self.on} — not a split or dividend "
            f"(Adj Close corrects those), so most likely a demerger/spinoff. {tail}."
        )


def _matching_action(
    gap_on: date, actions: Sequence[CorporateAction], *, tolerance_days: int = _MATCH_TOLERANCE_DAYS
) -> str | None:
    """The first known corporate action within ``tolerance_days`` of ``gap_on``, described, else None."""
    window = timedelta(days=tolerance_days)
    for action in actions:
        if abs(action.ex_date - gap_on) <= window:
            return f"{action.action_type.value.lower()} on {action.ex_date}"
    return None


def unexplained_gaps(
    prices: pd.DataFrame,
    tickers: Sequence[str],
    as_of: date,
    *,
    threshold: float = DEFAULT_GAP_THRESHOLD,
    lookback: int = 365,
    actions: Mapping[str, Sequence[CorporateAction]] | None = None,
) -> dict[str, PriceGap]:
    """Find each name's most recent unexplained price discontinuity in the trailing ``lookback`` days.

    ``prices`` is a wide adjusted-close panel (dates × tickers) — pass ``PriceData.adj_close``.
    ``actions`` optionally supplies known splits/dividends per ticker (from
    :func:`~qalpha.live.corporate_actions_feed.corporate_actions_from_series`); a gap matching one is
    reported as *explained* and never re-bases anything.

    Returns only the **latest** unexplained gap per affected ticker — that is the one that poisons
    the 1-year high, and re-basing to it subsumes every earlier gap in the window. Names with a clean
    series are absent from the result entirely.
    """
    cutoff = pd.Timestamp(as_of)
    start = cutoff - pd.Timedelta(days=lookback)
    out: dict[str, PriceGap] = {}
    for ticker in tickers:
        if ticker not in prices.columns:
            continue
        series = prices[ticker].loc[:cutoff].dropna()
        window = series[series.index >= start]
        if len(window) < 2:
            continue
        moves = window.pct_change()
        breaches = moves[moves.abs() >= threshold]
        if breaches.empty:
            continue
        known = list(actions.get(ticker, ())) if actions is not None else []
        for stamp, ret in reversed(list(breaches.items())):
            on = pd.Timestamp(str(stamp)).date()
            explained_by = _matching_action(on, known)
            if explained_by is not None:
                continue  # a real, understood action — keep looking further back
            out[ticker] = PriceGap(
                ticker=ticker,
                on=on,
                ret=float(ret),
                explained_by=None,
                post_gap_observations=int((series.index >= pd.Timestamp(on)).sum()),
            )
            break
    return out


def repair_price_spikes(
    series: pd.Series, *, threshold: float = DEFAULT_GAP_THRESHOLD, window: int = 5
) -> tuple[pd.Series, list[date]]:
    """Repair round-trip data artifacts in a single price series. Returns ``(clean, repaired_dates)``.

    A *round trip* is a move past ``threshold`` that reverses within ``window`` sessions — the
    signature of a bad print rather than a real event. Prices do not fall 90% and fully recover three
    days later; index levels especially do not. Found in the NIFTYBEES benchmark, which carried two
    days at ₹13.02 against a true level near ₹129 (2019-12-19/20) before snapping back.

    That series is not decorative: it drives :func:`~qalpha.live.deploy.market_weakness`, which sizes
    every deploy. On those two days the index would have read as ~90% below its 1-year high — "deep"
    weakness — and the rule would have deployed the entire wallet on a typo.

    Deliberately narrow. Only a move that **reverses** is repaired; a genuine crash that persists is
    left completely alone, because that is exactly the signal the system must not be blind to. The
    repaired points are forward-filled from the last good price (causal — never interpolated from the
    future), and every repair is returned so the caller can disclose rather than silently clean.
    """
    clean = series.copy()
    repaired: list[date] = []
    values = series.to_numpy(dtype=float).copy()  # to_numpy may return a read-only view
    n = len(values)
    i = 1
    while i < n:
        prev = values[i - 1]
        if prev > 0 and abs(values[i] / prev - 1.0) >= threshold:
            # Does it come back to the pre-move level within `window` sessions?
            end = min(i + window + 1, n)
            back = next(
                (j for j in range(i + 1, end) if abs(values[j] / prev - 1.0) < threshold), None
            )
            if back is not None:
                for j in range(i, back):
                    clean.iloc[j] = prev
                    repaired.append(pd.Timestamp(str(series.index[j])).date())
                    values[j] = prev
                i = back
                continue
        i += 1
    return clean, repaired


def rebase_starts(gaps: Mapping[str, PriceGap]) -> dict[str, date]:
    """Per-ticker date the 1-year high must be measured from — the gap day itself.

    The gap day carries the **first price on the new basis**, so it belongs in the re-based window;
    everything before it is a different instrument in all but name. Names whose post-gap history is
    too short to read are omitted: the caller scores them 0 rather than re-basing onto noise.
    """
    return {t: g.on for t, g in gaps.items() if g.unexplained and g.rebasable}


def excluded_from_tilt(gaps: Mapping[str, PriceGap]) -> set[str]:
    """Names whose cheapness must be forced to 0 — flagged, but with too little post-gap history."""
    return {t for t, g in gaps.items() if g.unexplained and not g.rebasable}


def gaps_note(gaps: Mapping[str, PriceGap]) -> str:
    """The user-facing explanation of what the guard did, or '' when every series was continuous."""
    flagged = [g for g in gaps.values() if g.unexplained]
    if not flagged:
        return ""
    lines = [
        f"⚠️ **Price-continuity guard: {len(flagged)} name"
        f"{'s' if len(flagged) != 1 else ''} adjusted.** A one-day step this large that is *not* a "
        "split or dividend is almost always a demerger — Adj Close never corrects those, so the "
        "old price is not comparable and the 'discount' is an artifact:",
    ]
    lines += [f"  - {g.describe()}" for g in sorted(flagged, key=lambda g: g.on, reverse=True)]
    return "\n".join(lines)
