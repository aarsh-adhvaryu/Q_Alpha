"""Reconstruct a point-in-time NIFTY 50 membership table (Q_alpha.md §5.4 survivorship fix).

The static survivor watchlist in ``run_phase0.py`` is the classic survivorship bias: dead/dropped
names are simply absent. This script builds a genuine point-in-time membership — including names
that later delisted or were dropped from the index — so the backtest sees, on each historical
date, exactly the stocks investable on *that* date.

**Method (reverse-apply from a known endpoint, with validation).** We know the current NIFTY 50
constituents exactly. We also have the authoritative chronological list of index changes
(NSE reconstitutions, mirrored on Wikipedia's "Index changes" section). Starting from the current
set and walking the changes *backward* reconstructs the membership at any past date. Each reverse
step asserts consistency — the added name must currently be present (so we can remove it) and the
removed name must currently be absent (so we can add it). A failed assertion would reveal a gap in
the change list rather than letting it silently corrupt the universe (the exact failure mode the
README warns about).

**Provenance:** change list from Wikipedia "NIFTY 50 → Index changes" (NSE reconstitution circulars),
fetched 2026-06. Sector tags are coarse (matching the existing engine taxonomy). yfinance NSE
symbols (``.NS``). Names yfinance can no longer price (merged/delisted away) are written to the CSV
anyway — the membership is *true* — and listed in ``UNPRICEABLE`` so the report can bound the
residual bias honestly. The backtest engine naturally skips a member with no price column.

Output: ``data/universes/nifty50_membership.csv`` (ticker,start_date,end_date,sector).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

WINDOW_START = date(2012, 1, 1)
WINDOW_END = date(2024, 12, 31)

# Company -> (yfinance base symbol, coarse sector). One row per distinct name in the change list
# or the current set. Sectors use the engine's coarse taxonomy, extended where needed.
NAME_TO_SYMBOL: dict[str, tuple[str, str]] = {
    # --- IT ---
    "TCS": ("TCS", "IT"),
    "Infosys": ("INFY", "IT"),
    "Wipro": ("WIPRO", "IT"),
    "HCLTech": ("HCLTECH", "IT"),
    "Tech Mahindra": ("TECHM", "IT"),
    "LTIMindtree": ("LTIM", "IT"),
    # --- Financials (banks + NBFC + insurance) ---
    "HDFC Bank": ("HDFCBANK", "FIN"),
    "ICICI Bank": ("ICICIBANK", "FIN"),
    "State Bank of India": ("SBIN", "FIN"),
    "Kotak Mahindra Bank": ("KOTAKBANK", "FIN"),
    "Axis Bank": ("AXISBANK", "FIN"),
    "IndusInd Bank": ("INDUSINDBK", "FIN"),
    "Bank of Baroda": ("BANKBARODA", "FIN"),
    "Bajaj Finance": ("BAJFINANCE", "FIN"),
    "Bajaj Finserv": ("BAJAJFINSV", "FIN"),
    "HDFC Life": ("HDFCLIFE", "FIN"),
    "SBI Life Insurance Company": ("SBILIFE", "FIN"),
    "Shriram Finance": ("SHRIRAMFIN", "FIN"),
    "Yes Bank": ("YESBANK", "FIN"),
    "Indiabulls Housing Finance": ("SAMMAANCAP", "FIN"),  # renamed; SAMMAANCAP carries the listing
    "IDFC": ("IDFC", "FIN"),  # UNPRICEABLE (merged into IDFC First Bank 2024)
    "HDFC": ("HDFC", "FIN"),  # UNPRICEABLE (merged into HDFC Bank Jul 2023)
    # --- Energy / oil & gas ---
    "Reliance Industries": ("RELIANCE", "ENERGY"),
    "Oil and Natural Gas Corporation": ("ONGC", "ENERGY"),
    "Hindustan Petroleum": ("HINDPETRO", "ENERGY"),
    "Indian Oil Corporation": ("IOC", "ENERGY"),
    "GAIL": ("GAIL", "ENERGY"),
    "Bharat Petroleum": ("BPCL", "ENERGY"),
    "Cairn India": ("CAIRN", "ENERGY"),  # UNPRICEABLE (merged into Vedanta 2017)
    # --- Power / utilities ---
    "NTPC": ("NTPC", "POWER"),
    "Power Grid": ("POWERGRID", "POWER"),
    "Tata Power": ("TATAPOWER", "POWER"),
    "Reliance Power": ("RPOWER", "POWER"),
    "Reliance Infrastructure": ("RELINFRA", "POWER"),
    # --- FMCG / consumer staples ---
    "Hindustan Unilever": ("HINDUNILVR", "FMCG"),
    "ITC": ("ITC", "FMCG"),
    "Nestlé India": ("NESTLEIND", "FMCG"),
    "Britannia Industries": ("BRITANNIA", "FMCG"),
    "Tata Consumer Products": ("TATACONSUM", "FMCG"),
    "United Spirits": ("UNITDSPR", "FMCG"),
    # --- Autos ---
    "Maruti Suzuki": ("MARUTI", "AUTO"),
    "Mahindra & Mahindra": ("M&M", "AUTO"),
    "Bajaj Auto": ("BAJAJ-AUTO", "AUTO"),
    "Hero MotoCorp": ("HEROMOTOCO", "AUTO"),
    "Eicher Motors": ("EICHERMOT", "AUTO"),
    "Bosch India": ("BOSCHLTD", "AUTO"),
    "Tata Motors": ("TATAMOTORS", "AUTO"),  # UNPRICEABLE (NSE symbol retired post-2025 demerger)
    # --- Pharma / healthcare ---
    "Sun Pharma": ("SUNPHARMA", "PHARMA"),
    "Cipla": ("CIPLA", "PHARMA"),
    "Dr. Reddy's Laboratories": ("DRREDDY", "PHARMA"),
    "Lupin": ("LUPIN", "PHARMA"),
    "Aurobindo Pharma": ("AUROPHARMA", "PHARMA"),
    "Divi's Laboratories": ("DIVISLAB", "PHARMA"),
    "Apollo Hospitals": ("APOLLOHOSP", "PHARMA"),
    # --- Metals & mining ---
    "Tata Steel": ("TATASTEEL", "METAL"),
    "Hindalco Industries": ("HINDALCO", "METAL"),
    "JSW Steel": ("JSWSTEEL", "METAL"),
    "Steel Authority of India": ("SAIL", "METAL"),
    "NMDC": ("NMDC", "METAL"),
    "Vedanta": ("VEDL", "METAL"),
    "Coal India": ("COALINDIA", "METAL"),
    "Adani Enterprises": ("ADANIENT", "METAL"),
    "Sterlite Industries": ("STER", "METAL"),  # UNPRICEABLE (became Vedanta 2013)
    # --- Cement / construction materials ---
    "UltraTech Cement": ("ULTRACEMCO", "CEMENT"),
    "Grasim Industries": ("GRASIM", "CEMENT"),
    "ACC": ("ACC", "CEMENT"),
    "Ambuja Cements": ("AMBUJACEM", "CEMENT"),
    "Shree Cement": ("SHREECEM", "CEMENT"),
    # --- Infra / capital goods / construction ---
    "Larsen & Toubro": ("LT", "INFRA"),
    "Siemens India": ("SIEMENS", "INFRA"),
    "BHEL": ("BHEL", "INFRA"),
    "JP Associates": ("JPASSOCIAT", "INFRA"),
    "Bharat Electronics": ("BEL", "INFRA"),
    "Adani Ports & SEZ": ("ADANIPORTS", "INFRA"),
    # --- Telecom ---
    "Bharti Airtel": ("BHARTIARTL", "TELECOM"),
    "Idea Cellular": ("IDEA", "TELECOM"),
    # --- Consumer discretionary / retail / paints / media ---
    "Asian Paints": ("ASIANPAINT", "CONSUMER"),
    "Titan Company": ("TITAN", "CONSUMER"),
    "Trent": ("TRENT", "CONSUMER"),
    "Zee Entertainment Enterprises": ("ZEEL", "CONSUMER"),
    # --- Realty ---
    "DLF": ("DLF", "REALTY"),
    # --- Chemicals ---
    "UPL": ("UPL", "CHEMICALS"),
    # --- Post-window-only current names (reverse-applied through; never produce a window interval) ---
    "Eternal": ("ETERNAL", "CONSUMER"),
    "IndiGo": ("INDIGO", "INFRA"),
    "Jio Financial Services": ("JIOFIN", "FIN"),
    "Max Healthcare": ("MAXHEALTH", "PHARMA"),
}

# Current NIFTY 50 constituents (post 30 Sep 2025 reconstitution) — the reverse-apply anchor.
# Names that only exist post-window (JIOFIN, ETERNAL, INDIGO, MAXHEALTH) are tracked through the
# reverse-apply but never produce a window interval. TMPV is the post-demerger Tata Motors entity;
# during the 2012-2024 window the listing is "Tata Motors".
CURRENT_2025: list[str] = [
    "Adani Enterprises",
    "Adani Ports & SEZ",
    "Apollo Hospitals",
    "Asian Paints",
    "Axis Bank",
    "Bajaj Auto",
    "Bajaj Finance",
    "Bajaj Finserv",
    "Bharat Electronics",
    "Bharti Airtel",
    "Cipla",
    "Coal India",
    "Dr. Reddy's Laboratories",
    "Eicher Motors",
    "Eternal",
    "Grasim Industries",
    "HCLTech",
    "HDFC Bank",
    "HDFC Life",
    "Hindalco Industries",
    "Hindustan Unilever",
    "ICICI Bank",
    "IndiGo",
    "Infosys",
    "ITC",
    "Jio Financial Services",
    "JSW Steel",
    "Kotak Mahindra Bank",
    "Larsen & Toubro",
    "Mahindra & Mahindra",
    "Maruti Suzuki",
    "Max Healthcare",
    "Nestlé India",
    "NTPC",
    "Oil and Natural Gas Corporation",
    "Power Grid",
    "Reliance Industries",
    "SBI Life Insurance Company",
    "Shriram Finance",
    "State Bank of India",
    "Sun Pharma",
    "TCS",
    "Tata Consumer Products",
    "Tata Motors",
    "Tata Steel",
    "Tech Mahindra",
    "Titan Company",
    "Trent",
    "UltraTech Cement",
    "Wipro",
]
# Post-window-only names present in CURRENT_2025 (added after 2024-12-31). They must NOT appear in
# the window's reconstructed set; the reverse-apply removes them as we walk back through 2025.
POST_WINDOW_ADDS = {"Eternal", "IndiGo", "Jio Financial Services", "Max Healthcare"}

# Chronological NIFTY 50 index changes (effective date, ADDED, REMOVED).
# Source: Wikipedia "NIFTY 50 → Index changes" (NSE reconstitution circulars), 2012-2025.
CHANGES: list[tuple[date, str, str]] = [
    (date(2012, 9, 28), "UltraTech Cement", "Sterlite Industries"),
    (date(2012, 9, 28), "Lupin", "Steel Authority of India"),
    (date(2012, 9, 28), "Bank of Baroda", "Reliance Power"),
    (date(2013, 4, 1), "IndusInd Bank", "Siemens India"),
    (date(2013, 9, 27), "Wipro", "Reliance Infrastructure"),
    (date(2014, 3, 28), "Tech Mahindra", "JP Associates"),
    (date(2014, 9, 19), "Zee Entertainment Enterprises", "United Spirits"),
    (date(2015, 3, 27), "Idea Cellular", "DLF"),
    (date(2015, 5, 29), "Bosch India", "IDFC"),
    (date(2015, 9, 28), "Adani Ports & SEZ", "NMDC"),
    (date(2016, 4, 1), "Aurobindo Pharma", "Cairn India"),
    (date(2016, 4, 1), "Eicher Motors", "Vedanta"),
    (date(2017, 5, 26), "Vedanta", "Grasim Industries"),
    (date(2017, 9, 29), "Bajaj Finance", "ACC"),
    # April 2018: Wikipedia mis-tags two of these three removals (it lists Tata Power and HPCL,
    # which were Nifty-100 actions). NSE's actual Nifty-50 removals were Ambuja, Aurobindo, Bosch
    # (added: Bajaj Finserv, Grasim, Titan) — Business Standard 2018-02-21; HPCL's real Nifty-50
    # exit was March 2019 (Britannia). Pairing within a date is arbitrary (simultaneous).
    (date(2018, 4, 2), "Bajaj Finserv", "Aurobindo Pharma"),
    (date(2018, 4, 2), "Grasim Industries", "Bosch India"),
    (date(2018, 4, 2), "Titan Company", "Ambuja Cements"),
    # March 2018: Wikipedia dates the Indiabulls/BHEL swap to 2017 and omits Idea Cellular's exit.
    # News sources (Moneylife, DNA, 2018) confirm BHEL *and* Idea Cellular were excluded effective
    # the March 2018 review, replaced by Indiabulls Housing Finance and Indian Oil — encoded here.
    (date(2018, 3, 31), "Indiabulls Housing Finance", "BHEL"),
    (date(2018, 3, 31), "Indian Oil Corporation", "Idea Cellular"),
    (date(2018, 9, 28), "JSW Steel", "Lupin"),
    (date(2019, 3, 29), "Britannia Industries", "Hindustan Petroleum"),
    (date(2019, 9, 27), "Nestlé India", "Indiabulls Housing Finance"),
    (date(2020, 3, 19), "Shree Cement", "Yes Bank"),
    (date(2020, 7, 31), "HDFC Life", "Vedanta"),
    (date(2020, 9, 25), "SBI Life Insurance Company", "Zee Entertainment Enterprises"),
    (date(2021, 3, 31), "Tata Consumer Products", "GAIL"),
    (date(2022, 3, 31), "Apollo Hospitals", "Indian Oil Corporation"),
    (date(2022, 9, 30), "Adani Enterprises", "Shree Cement"),
    (date(2023, 7, 13), "LTIMindtree", "HDFC"),
    (date(2024, 3, 28), "Shriram Finance", "UPL"),
    (date(2024, 9, 30), "Bharat Electronics", "Divi's Laboratories"),
    (date(2024, 9, 30), "Trent", "LTIMindtree"),
    (date(2025, 3, 28), "Jio Financial Services", "Bharat Petroleum"),
    (date(2025, 3, 28), "Eternal", "Britannia Industries"),
    (date(2025, 9, 30), "IndiGo", "Hero MotoCorp"),
    (date(2025, 9, 30), "Max Healthcare", "IndusInd Bank"),
]

# yfinance can no longer price these (merged/delisted/renamed away). Kept in the membership for
# correctness; the engine skips a member that has no price column. Listed so the report can bound
# the residual survivorship gap explicitly rather than hide it.
UNPRICEABLE = {"HDFC", "TATAMOTORS", "CAIRN", "IDFC", "STER"}


@dataclass
class Interval:
    symbol: str
    sector: str
    start: date
    end: date | None


def _sym(name: str) -> str:
    return NAME_TO_SYMBOL[name][0]


def reconstruct(
    window_end: date = WINDOW_END,
) -> tuple[dict[str, date], list[tuple[date, str, str]], list[str]]:
    """Reverse-apply changes from the current set to get the set as of WINDOW_START.

    Returns ``(start_set, window_changes, orphan_adds)``. ``start_set`` maps each ticker live at
    WINDOW_START to that date; ``window_changes`` are the (date, added, removed) events inside the
    window in forward order; ``orphan_adds`` are tickers added in-window that are absent from the
    current set with no recorded exit (Wikipedia systematically omits these). Orphans are kept as
    members from their add-date through window-end — we do **not** fabricate an exit date — and are
    returned so the report can document them. A genuine contradiction (trying to re-add a name that
    is already present → a wrong source row) stays a hard error so it can't silently corrupt data.
    """
    unknown = {n for _, a, r in CHANGES for n in (a, r)} | set(CURRENT_2025)
    missing = sorted(n for n in unknown if n not in NAME_TO_SYMBOL)
    if missing:
        raise SystemExit(f"NAME_TO_SYMBOL missing entries: {missing}")

    state = {_sym(n) for n in CURRENT_2025}
    orphan_adds: list[str] = []
    for d, added, removed in reversed(CHANGES):
        a, r = _sym(added), _sym(removed)
        # Before date d: the added name was NOT yet in, the removed name WAS still in.
        if a not in state:
            # Added in-window but absent now with no recorded exit → orphan (missing-exit gap).
            orphan_adds.append(a)
        if r in state:
            raise SystemExit(
                f"reverse-apply contradiction at {d}: '{removed}' ({r}) already present "
                "(a wrong source row — resolve before trusting the universe)"
            )
        state.discard(a)
        state.add(r)
    # `state` is now the membership just before the earliest change (28 Sep 2012) ≈ WINDOW_START.
    start_set = dict.fromkeys(state, WINDOW_START)

    window_changes = [
        (d, _sym(a), _sym(r)) for d, a, r in CHANGES if WINDOW_START <= d <= window_end
    ]
    return start_set, window_changes, sorted(set(orphan_adds))


def build_intervals(window_end: date = WINDOW_END) -> tuple[list[Interval], list[str]]:
    start_set, window_changes, orphan_adds = reconstruct(window_end)
    sector_of = dict(NAME_TO_SYMBOL.values())

    open_start: dict[str, date] = dict(start_set)  # symbol -> current interval start
    intervals: list[Interval] = []

    for d, added, removed in window_changes:
        if removed in open_start:
            intervals.append(
                Interval(
                    removed, sector_of[removed], open_start.pop(removed), d - timedelta(days=1)
                )
            )
        # A name can re-enter (e.g. Vedanta, Grasim): open a fresh interval.
        open_start[added] = d
    # Close all still-open intervals at window end (still a member through 2024-12-31).
    for sym, start in open_start.items():
        intervals.append(Interval(sym, sector_of[sym], start, None))

    intervals.sort(key=lambda iv: (iv.symbol, iv.start))
    return intervals, orphan_adds


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/universes/nifty50_membership.csv")
    parser.add_argument(
        "--end",
        default=WINDOW_END.isoformat(),
        help="window end (ISO). Extend past 2024-12-31 to include the 2025 reconstitutions for "
        "an out-of-sample holdout (the 2025 changes are already in the change list).",
    )
    args = parser.parse_args()

    intervals, orphan_adds = build_intervals(pd.Timestamp(args.end).date())
    rows = [
        {
            "ticker": f"{iv.symbol}.NS",
            "start_date": iv.start.isoformat(),
            "end_date": "" if iv.end is None else iv.end.isoformat(),
            "sector": iv.sector,
        }
        for iv in intervals
    ]
    df = pd.DataFrame(rows).sort_values(["ticker", "start_date"]).reset_index(drop=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    distinct = sorted({iv.symbol for iv in intervals})
    priceable = [s for s in distinct if s not in UNPRICEABLE]
    unpriceable_present = sorted(set(distinct) & UNPRICEABLE)
    print(f"Wrote {len(df)} membership intervals for {len(distinct)} distinct names → {out}")
    print(f"  priceable (yfinance .NS): {len(priceable)}")
    print(f"  UNPRICEABLE (merged/delisted away, documented): {unpriceable_present}")
    if orphan_adds:
        print(
            f"  ORPHAN adds (entered in-window, exit not in source → kept to window-end): {orphan_adds}"
        )
    # Sanity: membership count on a few probe dates should sit at ~50.
    from qalpha.data.universe import Universe

    uni = Universe.from_csv(out)
    for probe in ["2012-06-30", "2015-06-30", "2018-06-30", "2021-06-30", "2024-06-30"]:
        n = len(uni.members_on(pd.Timestamp(probe).date()))
        print(f"  members on {probe}: {n}")


if __name__ == "__main__":
    main()
