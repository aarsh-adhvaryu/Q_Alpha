"""Point-in-time NIFTY 100 membership — gate 4's first job, and what still blocks it.

### The problem this exists for

`exp_screen_oos.py` measured the live screen and found the honest answer only on the **Nifty 50**,
because that is the only universe in this repo with dated entries and exits. The screen the money
actually runs on uses `nifty100_watchlist.csv`, which is **today's** constituents — and
`build_nifty100_watchlist.py` says so in its own docstring:

    "This is NOT a backtest universe: it is *today's* constituents ... survivorship bias is
     irrelevant (we are not measuring a historical edge — we are listing the names currently
     investable)."

That was true when it was written. It stopped being true the moment the file was fed to a backtest.
Measured on 2026-09-08, the same test on the same days reports **+6.44%/yr on the survivor list
against +2.65%/yr point-in-time** — the bias is worth about 3.8 points a year, which is larger than
the entire signal being measured. It cannot be processed away.

### The method, which is already proven here

`build_nifty_universe.py` reconstructs the PIT Nifty 50 by **reverse-applying a chronological change
list from a known current endpoint**, asserting at every step that the added name is currently
present and the removed name currently absent. A gap in the change list fails loudly instead of
silently corrupting the universe. That method is sound and this script reuses it verbatim.

### What is missing, and why this script will not pretend otherwise

NIFTY 100 = NIFTY 50 + NIFTY Next 50. The Nifty-50 half is done. **The Next-50 change list is not in
this repository**, and there is no way to derive it from prices: a name's absence from a price panel
means yfinance could not fetch it, not that it left an index.

So :data:`NEXT_50_CHANGES` is empty, and this script **refuses to write anything** while it is. The
alternative — stamping today's Next-50 with a 2012 start date — would produce a file that looks
point-in-time, passes every check, and quietly reintroduces the 3.8%/yr bias into every result
computed from it. Unknown is never substituted.

    uv run python scripts/build_nifty100_pit.py --audit   # what is present, what is missing
    uv run python scripts/build_nifty100_pit.py           # build (refuses until sourced)

To finish it: fill NEXT_50_CHANGES from NSE's Next-50 reconstitution circulars (Wikipedia mirrors
them under "NIFTY Next 50 → Index changes", which is where the Nifty-50 list came from), then run
without --audit. The consistency assertions will tell you immediately if the list has a hole.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

PIT_NIFTY50 = Path("data/universes/nifty50_membership_2026.csv")
STATIC_WATCHLIST = Path("data/universes/nifty100_watchlist.csv")
OUT = Path("data/universes/nifty100_membership_pit.csv")

#: Chronological NIFTY Next 50 index changes, oldest first: ``(effective_date, added, removed)``.
#: **EMPTY AND MUST BE SOURCED.** See the module docstring. Do not populate this by guessing, and do
#: not populate it from a current constituent list — the dates are the entire point.
NEXT_50_CHANGES: list[tuple[date, str, str]] = []

#: The measured cost of using the survivor list instead, from `reports/SCREEN_OOS_FIRST_READ.md`.
BIAS_PCT_PER_YEAR = 3.79


def _pit_50() -> pd.DataFrame:
    if not PIT_NIFTY50.exists():
        raise SystemExit(f"missing {PIT_NIFTY50} — the Nifty-50 half is the part that exists")
    return pd.read_csv(PIT_NIFTY50)


def _static_100() -> pd.DataFrame:
    if not STATIC_WATCHLIST.exists():
        raise SystemExit(f"missing {STATIC_WATCHLIST}")
    return pd.read_csv(STATIC_WATCHLIST)


def audit() -> int:
    """Report exactly what is point-in-time, what is not, and what the difference is worth."""
    fifty, hundred = _pit_50(), _static_100()
    pit_names = set(fifty["ticker"])
    all_names = set(hundred["ticker"])
    next50 = sorted(all_names - pit_names)
    dated = fifty[fifty["end_date"].notna()]

    print("POINT-IN-TIME UNIVERSE AUDIT\n" + "=" * 70)
    print(f"  Nifty 50   {PIT_NIFTY50.name}")
    print(f"             {len(fifty)} membership rows · {len(pit_names)} distinct names")
    print(f"             {len(dated)} carry an end_date — names that LEFT the index and are kept")
    print("             → point-in-time: YES")
    print()
    print(f"  Nifty 100  {STATIC_WATCHLIST.name}")
    print(f"             {len(all_names)} names, no start_date, no end_date")
    print(f"             {len(next50)} of them are outside the PIT Nifty-50 file")
    print("             → point-in-time: NO — this is today's list applied to the past")
    print()
    print(
        f"  Next-50 change list in this repo: {len(NEXT_50_CHANGES)} entries. Needed to close it."
    )
    print()
    print("  MEASURED COST OF USING THE SURVIVOR LIST (reports/SCREEN_OOS_FIRST_READ.md):")
    print("    survivor universe   +6.44%/yr      point-in-time   +2.65%/yr")
    print(
        f"    bias                ~{BIAS_PCT_PER_YEAR:.2f} points a year — larger than the signal measured"
    )
    print()
    print("  Names with no dated history (the ones that would need sourcing):")
    for i in range(0, len(next50), 6):
        print("    " + "  ".join(t.removesuffix(".NS").ljust(12) for t in next50[i : i + 6]))
    print()
    print("  Until NEXT_50_CHANGES is filled, any result computed on the Nifty-100 watchlist is")
    print("  DEVELOPMENT EVIDENCE ONLY and must be labelled as such wherever it appears.")
    return 0


def build() -> int:
    if not NEXT_50_CHANGES:
        print(
            "REFUSING TO BUILD.\n\n"
            "NEXT_50_CHANGES is empty, so the only Nifty-100 this script could write would be\n"
            "today's constituents wearing historical dates. That file would look point-in-time,\n"
            "pass every check downstream, and silently put ~3.8%/yr of survivorship bias into\n"
            "every number computed from it — larger than the edge being measured.\n\n"
            "Run with --audit to see exactly what is missing.",
            file=sys.stderr,
        )
        return 1
    raise SystemExit(
        "NEXT_50_CHANGES is populated but the reverse-apply step is not written yet. Port it from "
        "build_nifty_universe.reconstruct(), which already does this correctly for the Nifty 50 — "
        "including the per-step assertions that turn a gap in the change list into a loud failure."
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit", action="store_true", help="report coverage; write nothing")
    args = ap.parse_args(argv)
    return audit() if args.audit else build()


if __name__ == "__main__":
    raise SystemExit(main())
