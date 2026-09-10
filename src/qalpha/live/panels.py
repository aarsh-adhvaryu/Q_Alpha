"""The price files the live layer reads, named once.

### Why a module for four paths

The **Refresh market data** button could not fix the staleness it exists to fix. It re-pulled
``prices_pit_2026.parquet`` — the *paper book's* panel, built from the Nifty-50 membership list —
while the screen reads ``prices_watchlist.parquet``, built from the 96-name watchlist. Pressing it
moved one file to today and left the other on 2026-08-28, so the gate went on refusing to deploy
with *"prices are 13 days old"* however many times it was pressed.

Nothing was wrong with either file. The paths were written out by hand in nine places across seven
modules, and two of them meant different things by "the prices".

An earlier fix in this repo made the freshness check follow the panel the decision is actually made
from. This is the other half: **the refresh must follow the same panel the freshness check does.**
They are one fact, so they get one definition, and :func:`refresh_targets` pairs each panel with the
universe it is built from — because a panel refreshed from the wrong ticker list is the same defect
one level down.
"""

from __future__ import annotations

from pathlib import Path

#: What the buy screen ranks from, and therefore the ONLY panel whose age may gate a decision.
#: `local_run._price_as_of` and `local_run._panel_sha` both follow this.
SCREEN_PANEL = Path("data/historical/prices_watchlist.parquet")
#: The ticker list that panel is built from. 96 names; not the paper book's 85.
SCREEN_UNIVERSE = Path("data/universes/nifty100_watchlist.csv")

#: The Nifty TRI proxy the deploy tranche is paced against. Required alongside the screen panel:
#: a current price list against a stale benchmark still paces off a stale market.
BENCHMARK_PANEL = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")
#: The instrument that panel holds — an ETF used as a Nifty total-return proxy.
BENCHMARK_TICKER = "NIFTYBEES.NS"

#: The paper/model book's own panel, and its own universe. A different question, kept separate on
#: purpose — but it must not be mistaken for the screen's, which is what happened.
BOOK_PANEL = Path("data/historical/prices_pit_2026.parquet")
BOOK_UNIVERSE = Path("data/universes/nifty50_membership_2026.csv")


def refresh_targets() -> tuple[tuple[Path, Path], ...]:
    """``(panel, universe)`` for every panel a run must bring up to date.

    The screen's panel is first because it is the one that gates buying. If a refresh has to stop
    early, the file a decision rests on is the one already done.
    """
    return ((SCREEN_PANEL, SCREEN_UNIVERSE), (BOOK_PANEL, BOOK_UNIVERSE))
