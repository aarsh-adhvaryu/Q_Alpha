"""Build the product **Nifty-100 watchlist** — the forward-looking opportunity set the advisor
deploys fresh capital into (Q_alpha.md §2.9 fresh-capital routing).

This is NOT a backtest universe: it is *today's* constituents, used only to decide where to deploy
**new** money now, so survivorship bias is irrelevant (we are not measuring a historical edge — we are
listing the names currently investable). The validated *backtested strategy* default stays Nifty 50;
this wider watchlist only widens the manual investor's diversification + entry opportunity set.

Nifty-50 half reused from `build_nifty_universe.CURRENT_2025` (single source of truth on `main`);
Nifty Next-50 half embedded below (current constituents, coarse sector tags matching the engine).

Output: ``data/universes/nifty100_watchlist.csv`` (ticker,sector).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from build_nifty_universe import CURRENT_2025, NAME_TO_SYMBOL

# Current NIFTY Next 50 → coarse sector (engine taxonomy). "LTM"/"TMCV" Wikipedia artifacts dropped.
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
    "SOLARINDS": "CHEMICALS",
    "TATAPOWER": "POWER",
    "TORNTPHARM": "PHARMA",
    "TVSMOTOR": "AUTO",
    "UNIONBANK": "FIN",
    "UNITDSPR": "FMCG",
    "VBL": "FMCG",
    "VEDL": "METAL",
    "ZYDUSLIFE": "PHARMA",
}


# The engine's coarse taxonomy lumps every financial into one "FIN" tag — 22 of the 96 watchlist
# names. Since ``deploy_target`` caps each *sector* at 30% of a deploy, banks end up competing with
# NBFCs and insurers for one shared budget, so a deploy can never lean into banks specifically.
# Splitting the bucket three ways gives each its own cap. **Watchlist-only** (this file's CSV is the
# advisor's fresh-capital opportunity set) — the backtest engine reads its sector map from
# ``build_nifty_universe``/``nifty50_membership.csv``, which are untouched, so rule (a) holds and the
# validated headline cannot move. Honest side-effect: combined financials may now exceed 30% in an
# extreme tilt (base weights ≈ 9/9/4% make that unlikely).
WATCHLIST_SECTOR_OVERRIDES: dict[str, str] = {
    # Deposit-taking banks (public + private)
    "AXISBANK": "BANK",
    "BANKBARODA": "BANK",
    "CANBK": "BANK",
    "HDFCBANK": "BANK",
    "ICICIBANK": "BANK",
    "KOTAKBANK": "BANK",
    "PNB": "BANK",
    "SBIN": "BANK",
    "UNIONBANK": "BANK",
    # Non-bank lenders / holding companies
    "BAJAJHLDNG": "NBFC",
    "BAJFINANCE": "NBFC",
    "CHOLAFIN": "NBFC",
    "IRFC": "NBFC",
    "JIOFIN": "NBFC",
    "MUTHOOTFIN": "NBFC",
    "PFC": "NBFC",
    "RECLTD": "NBFC",
    "SHRIRAMFIN": "NBFC",
    # Insurance + asset management
    "BAJAJFINSV": "INSURANCE",
    "HDFCAMC": "INSURANCE",
    "HDFCLIFE": "INSURANCE",
    "SBILIFE": "INSURANCE",
}


def build() -> dict[str, str]:
    """{symbol: sector} for the current Nifty 100 (Nifty-50 sector wins on any overlap).

    ``WATCHLIST_SECTOR_OVERRIDES`` is applied last, so the FIN split wins over both halves.
    """
    members = dict(NEXT_50)
    members.update({NAME_TO_SYMBOL[n][0]: NAME_TO_SYMBOL[n][1] for n in CURRENT_2025})
    members.update({s: sec for s, sec in WATCHLIST_SECTOR_OVERRIDES.items() if s in members})
    return members


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/universes/nifty100_watchlist.csv")
    ap.add_argument(
        "--prices",
        action="store_true",
        help="also download the watchlist's price history → the watchlist panel, so the advisor's "
        "deploy-weakness can actually see all the names (esp. the Next-50 midcaps).",
    )
    ap.add_argument("--prices-out", default="data/historical/prices_watchlist.parquet")
    ap.add_argument("--start", default="2012-01-01")
    args = ap.parse_args()
    members = build()
    rows = [{"ticker": f"{s}.NS", "sector": sec} for s, sec in sorted(members.items())]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    spread = pd.Series([r["sector"] for r in rows]).value_counts().to_dict()
    print(f"Wrote {len(rows)} Nifty-100 watchlist names → {out}")
    print("Sector spread:", spread)

    if args.prices:
        from qalpha.data.ingest import download_prices, save_parquet
        from qalpha.data.prices import PriceData

        tickers = [r["ticker"] for r in rows]
        print(f"\nDownloading price history for {len(tickers)} watchlist names (yfinance)...")
        panel = download_prices(tickers, args.start, None)
        save_parquet(panel, args.prices_out)
        priced = set(PriceData.from_long(panel).tickers)
        missing = sorted(set(tickers) - priced)
        print(f"✓ Priced {len(priced)}/{len(tickers)} → {args.prices_out}")
        if missing:
            print(f"  Unpriceable (delisted/just-listed; advisor skips them): {missing}")


if __name__ == "__main__":
    main()
