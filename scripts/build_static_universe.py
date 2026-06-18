"""Build a *static* current-constituents universe CSV for a breadth screen (Stage 1 only).

⚠️ SURVIVORSHIP-BIASED BY CONSTRUCTION. This treats **today's** index constituents as members for the
whole historical window. It is the Stage-1 screening universe from `reports/PREREGISTRATION_universe.md`
— NOT a survivorship-free universe, and a result on it is directional, never a GO. The Nifty-50 half is
reused from `build_nifty_universe.CURRENT_2025` (single source of truth); the Next-50 half is the
current (2026) NIFTY Next 50 with coarse sector tags matching the engine taxonomy.

Output: ``data/universes/<index>_current_static.csv`` (ticker,start_date,end_date,sector), every name a
member for the full window so the engine just skips a name on dates it has no price (mid-window IPOs).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from build_nifty_universe import CURRENT_2025, NAME_TO_SYMBOL, WINDOW_END, WINDOW_START

# Current (2026) NIFTY Next 50 → (yfinance .NS base symbol, coarse sector). Two Wikipedia rows are
# dropped on purpose: "LTM" (ambiguous/unresolvable) and "TMCV" (post-2025 Tata Motors CV demerger
# entity — no historical NSE listing under that symbol; the Tata Motors listing is already covered).
NEXT_50: dict[str, str] = {
    "ABB": "INFRA",
    "ADANIENSOL": "POWER",
    "ADANIGREEN": "POWER",
    "ADANIPOWER": "POWER",
    "AMBUJACEM": "CEMENT",
    "BAJAJHLDNG": "FIN",
    "BANKBARODA": "FIN",
    "BPCL": "ENERGY",
    "BRITANNIA": "FMCG",
    "BOSCHLTD": "AUTO",
    "CANBK": "FIN",
    "CGPOWER": "INFRA",
    "CHOLAFIN": "FIN",
    "CUMMINSIND": "INFRA",
    "DIVISLAB": "PHARMA",
    "DLF": "REALTY",
    "DMART": "CONSUMER",
    "GAIL": "ENERGY",
    "GODREJCP": "FMCG",
    "HDFCAMC": "FIN",
    "HAL": "INFRA",
    "HINDZINC": "METAL",
    "HYUNDAI": "AUTO",
    "INDHOTEL": "CONSUMER",
    "IOC": "ENERGY",
    "IRFC": "FIN",
    "JINDALSTEL": "METAL",
    "LODHA": "REALTY",
    "MAZDOCK": "INFRA",
    "MUTHOOTFIN": "FIN",
    "PIDILITIND": "CHEMICALS",
    "PFC": "FIN",
    "PNB": "FIN",
    "RECLTD": "FIN",
    "MOTHERSON": "AUTO",
    "SHREECEM": "CEMENT",
    "SIEMENS": "INFRA",
    "ENRIN": "INFRA",
    "SOLARINDS": "CHEMICALS",
    "TATACAP": "FIN",
    "TATAPOWER": "POWER",
    "TORNTPHARM": "PHARMA",
    "TVSMOTOR": "AUTO",
    "UNIONBANK": "FIN",
    "UNITDSPR": "FMCG",
    "VBL": "FMCG",
    "VEDL": "METAL",
    "ZYDUSLIFE": "PHARMA",
}


def nifty50_current() -> dict[str, str]:
    """Current NIFTY 50 as {symbol: sector}, reused from the PIT builder's anchor set."""
    return {NAME_TO_SYMBOL[name][0]: NAME_TO_SYMBOL[name][1] for name in CURRENT_2025}


def build(index: str) -> dict[str, str]:
    """{symbol: sector} for the requested static index (deduped; Nifty-50 sector wins on overlap)."""
    members = dict(NEXT_50)
    if index != "nifty100":
        raise SystemExit(
            f"only 'nifty100' is built here; got {index!r} (200 needs the Next-100 list)"
        )
    members.update(nifty50_current())  # Nifty-50 entries override any Next-50 overlap
    return members


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="nifty100", choices=["nifty100"])
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    members = build(args.index)
    rows = [
        {
            "ticker": f"{sym}.NS",
            "start_date": WINDOW_START.isoformat(),
            "end_date": "",  # open interval: member for the whole window (static / biased)
            "sector": sector,
        }
        for sym, sector in sorted(members.items())
    ]
    out = Path(args.out or f"data/universes/{args.index}_current_static.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    by_sector = pd.Series([r["sector"] for r in rows]).value_counts()
    print(f"Wrote {len(rows)} static members → {out}  (window {WINDOW_START}..{WINDOW_END})")
    print("Sector spread:", dict(by_sector))


if __name__ == "__main__":
    main()
