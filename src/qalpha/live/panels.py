"""The price files the live layer reads, named once.

Paths written out by hand in several modules once meant two different things by "the prices": the
refresh button updated one panel while the page read another. One definition, and
:func:`refresh_targets` pairs each panel with the universe it is built from.
"""

from __future__ import annotations

from pathlib import Path

#: The investor's world: the Nifty-100 watchlist (holdings and candidates), with raw close and volume.
WATCHLIST_PANEL = Path("data/historical/prices_watchlist.parquet")
WATCHLIST_UNIVERSE = Path("data/universes/nifty100_watchlist.csv")

#: NIFTYBEES — ``BASELINE``, and the benchmark series.
BENCHMARK_PANEL = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")
BENCHMARK_TICKER = "NIFTYBEES.NS"

#: Point-in-time Nifty-50 membership and prices — what ``BASELINE_EW``'s index is built from.
NIFTY50_PANEL = Path("data/historical/prices_pit_2026.parquet")
NIFTY50_UNIVERSE = Path("data/universes/nifty50_membership_2026.csv")


def refresh_targets() -> tuple[tuple[Path, Path], ...]:
    """``(panel, universe)`` for every stock panel a run must bring up to date. Watchlist first."""
    return ((WATCHLIST_PANEL, WATCHLIST_UNIVERSE), (NIFTY50_PANEL, NIFTY50_UNIVERSE))
