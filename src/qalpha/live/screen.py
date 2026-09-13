"""Which non-held names the investor is shown as candidates: the furthest below their 1-year high.

A pullback is **not** a valuation. It is how the candidate list is narrowed to a handful the model
can read about in one review, and the prompt says so. Widening or changing this list changes what
the investor can choose from, which is a new version of the investor.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date

import pandas as pd

from qalpha.data.prices import PriceData

_HIGH_WINDOW = 252  # ~1 trading year for the rolling high


def cheapness_scores(
    prices: PriceData,
    tickers: list[str],
    as_of: date,
    *,
    window: int = _HIGH_WINDOW,
    rebase_from: Mapping[str, date] | None = None,
    no_tilt: Collection[str] | None = None,
) -> dict[str, float]:
    """Per-name 'out of favour' score in [0,1): fractional pullback below its own 1y high.

    0 = at/above its rolling high; 0.30 = 30% below it. A *technical* cheapness proxy (pulled back),
    not fundamental valuation. Names without enough history get 0 (no tilt rather than a guess).

    **Price-continuity inputs (PR-2).** ``adj_close`` corrects splits and dividends and nothing else,
    so a demerger leaves a step-down that this rule would read as a discount for a full year — the
    defect that put two price artifacts at the top of a real ₹100,000 recommendation. Callers pass
    :func:`~qalpha.live.price_integrity.rebase_starts` as ``rebase_from`` to measure a flagged name's
    high only over the window that starts at its gap (the first comparable price), and
    :func:`~qalpha.live.price_integrity.excluded_from_tilt` as ``no_tilt`` for flagged names with too
    little post-gap history to read — those score 0. Both default to off, leaving the original
    behaviour exactly intact for every caller that does not opt in.
    """
    adj = prices.adj_close
    cutoff = pd.Timestamp(as_of)
    rebase = rebase_from or {}
    untilted = set(no_tilt or ())
    out: dict[str, float] = {}
    for t in tickers:
        if t not in adj.columns or t in untilted:
            out[t] = 0.0
            continue
        series = adj[t].loc[:cutoff].dropna()
        if len(series) < 20:
            out[t] = 0.0
            continue
        cur = float(series.iloc[-1])
        start = rebase.get(t)
        if start is not None:  # discontinuous series — the pre-gap high is a different instrument
            series = series[series.index >= pd.Timestamp(start)]
            if series.empty:
                out[t] = 0.0
                continue
        high = float(series.tail(window).max())
        out[t] = max(0.0, 1.0 - cur / high) if high > 0 else 0.0
    return out


#: Non-held names shown to the investor per review, and read about each evening.
CANDIDATES = 8


def candidates(
    panel: PriceData,
    watchlist: list[str],
    as_of: date,
    *,
    held: Collection[str],
    rebase_from: Mapping[str, date] | None = None,
    no_tilt: Collection[str] | None = None,
    n: int = CANDIDATES,
) -> list[tuple[str, float]]:
    """The ``n`` non-held names furthest below their 1-year high, with the pullback. Ties by ticker."""
    scores = cheapness_scores(panel, watchlist, as_of, rebase_from=rebase_from, no_tilt=no_tilt)
    ranked = sorted(
        ((t, s) for t, s in scores.items() if t not in held and s > 0),
        key=lambda ts: (-ts[1], ts[0]),
    )
    return ranked[:n]


def research_scope(as_of: date, *, n: int = CANDIDATES) -> list[str]:
    """Every name the evening reads about: what SYSTEM holds, then its candidates.

    **One definition.** Filings, headlines and the investor's review all use :func:`candidates`, so
    what is read is exactly what the investor can be shown. Held names always come first and are
    never dropped; without the watchlist panel the scope is the held names alone, and says so.
    """
    from qalpha.config import Config
    from qalpha.data.ingest import load_parquet
    from qalpha.live.panels import WATCHLIST_PANEL, WATCHLIST_UNIVERSE
    from qalpha.live.price_integrity import excluded_from_tilt, rebase_starts, unexplained_gaps
    from qalpha.live.twin import SYSTEM, load_books

    held: list[str] = []
    book = load_books(Config()).get(SYSTEM)
    if book is not None:
        held = sorted(t for t, q in book.portfolio.positions().items() if q > 0)
    if not (WATCHLIST_PANEL.exists() and WATCHLIST_UNIVERSE.exists()):
        print(f"[scope] no watchlist panel ({WATCHLIST_PANEL}) — held names only, no candidates")
        return held
    panel = load_parquet(str(WATCHLIST_PANEL))
    listed = pd.read_csv(WATCHLIST_UNIVERSE)["ticker"].astype(str).tolist()
    watchlist = [t for t in listed if t in panel.adj_close.columns]
    on = min(as_of, pd.Timestamp(panel.adj_close.index.max()).date())
    gaps = unexplained_gaps(panel.adj_close, watchlist, on)
    picked = candidates(
        panel,
        watchlist,
        on,
        held=held,
        rebase_from=rebase_starts(gaps),
        no_tilt=excluded_from_tilt(gaps),
        n=n,
    )
    return held + [t for t, _score in picked]
