"""Tests for the Nifty-100 watchlist's sector taxonomy (scripts/build_nifty100_watchlist.py).

The watchlist CSV is the advisor's fresh-capital opportunity set, and ``deploy.deploy_target`` caps
each *sector* at 30% of a deploy — so the sector column is load-bearing for diversification, not just
a label. These lock the FIN 3-way split (BANK / NBFC / INSURANCE) and that the committed CSV matches
the builder. **Watchlist-only** — the backtest engine's sector map is a different file and untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:  # the builder imports its Nifty-50 half as a sibling module
    sys.path.insert(0, str(_SCRIPTS))

from build_nifty100_watchlist import WATCHLIST_SECTOR_OVERRIDES, build  # noqa: E402

_CSV = Path("data/universes/nifty100_watchlist.csv")


def test_financials_are_split_three_ways() -> None:
    members = build()
    sectors = set(members.values())
    assert {"BANK", "NBFC", "INSURANCE"} <= sectors
    # The coarse catch-all is fully retired — nothing may fall back into one shared 30% budget.
    assert "FIN" not in sectors


def test_overrides_apply_to_both_halves_of_the_index() -> None:
    members = build()
    # HDFCBANK comes from the Nifty-50 half, BANKBARODA from the Next-50 half: both get retagged.
    assert members["HDFCBANK"] == "BANK"
    assert members["BANKBARODA"] == "BANK"
    assert members["BAJFINANCE"] == "NBFC"
    assert members["HDFCLIFE"] == "INSURANCE"


def test_overrides_only_retag_never_add_names() -> None:
    """An override for a name that left the index must not resurrect it into the watchlist."""
    members = build()
    assert set(WATCHLIST_SECTOR_OVERRIDES) >= {"SBIN", "PFC"}
    assert all(sym in members for sym in WATCHLIST_SECTOR_OVERRIDES)


def test_committed_csv_matches_the_builder() -> None:
    """The CSV the dashboard actually loads must be a regenerated artifact, not hand-edited drift."""
    if not _CSV.exists():  # gitignored/absent in a bare checkout — nothing to check
        return
    wl = pd.read_csv(_CSV)
    expected = {f"{sym}.NS": sec for sym, sec in build().items()}
    assert dict(zip(wl["ticker"], wl["sector"], strict=True)) == expected
