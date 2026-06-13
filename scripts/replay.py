"""Replay the production decision over history — the credential-free half of the live build.

Drives the *exact same* ``decide_rebalance`` the live runner will call across the full point-in-time
history (via the validated Phase-0 config), and prints the per-rebalance decision feed a
human-in-the-loop would have approved, plus a determinism check. This is how we de-risk the live
path before a single rupee or a single live tick (STRATEGY.md Stage 1; Q_alpha.md §13).

    uv run python scripts/replay.py                 # validated window (2012 → 2024-12-31)
    uv run python scripts/replay.py --end 2026-06-30 --universe-csv data/universes/nifty50_membership_2026.csv

Exits non-zero if the decision stream is non-deterministic.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_phase0 import (
    PIT_PRICES_PARQUET,
    _load_universe_csv,
)

from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe
from qalpha.live.replay import replay, verify_determinism


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2012-01-01")
    parser.add_argument("--end", default="2024-12-31", help="window end (validated default)")
    parser.add_argument(
        "--universe-csv",
        default="data/universes/nifty50_membership.csv",
        help="point-in-time membership CSV (survivorship-free Nifty 50)",
    )
    parser.add_argument("--band", type=float, default=0.10, help="no-trade band")
    parser.add_argument("--rebalance", default="Y", choices=["M", "Q", "Y"])
    parser.add_argument(
        "--weighting", default="shrink", choices=["minvar", "equal", "score", "shrink"]
    )
    parser.add_argument(
        "--full", action="store_true", help="print every rebalance (not just trades)"
    )
    args = parser.parse_args()

    cfg = Config()
    _tickers, sector_of = _load_universe_csv(Path(args.universe_csv))
    prices = load_parquet(PIT_PRICES_PARQUET)
    universe = Universe.from_csv(args.universe_csv)

    run_kwargs = {
        "start": args.start,
        "end": args.end,
        "tax_aware": True,
        "min_trade_fraction": args.band,
        "rebalance_freq": args.rebalance,
        "weighting": args.weighting,
        "force_refresh": True,
    }

    rep = replay(prices, sector_of, universe, cfg, **run_kwargs)

    print(f"\n=== Replay decision feed (validated config, {args.start} → {args.end}) ===\n")
    for r in rep.rebalances:
        if args.full or r.orders:
            print(r.render())

    final_equity = float(rep.result.equity.iloc[-1])
    print("\n=== Summary ===")
    print(f"rebalance dates evaluated : {rep.n_decisions}")
    print(f"rebalances that traded    : {rep.n_executed}")
    print(f"trades                    : {len(rep.result.trades)}")
    print(f"total capital-gains tax   : ₹{rep.result.total_tax:,.2f}")
    print(f"final equity              : ₹{final_equity:,.0f}")

    print("\n=== Determinism check (run twice → identical trade stream) ===")
    deterministic = verify_determinism(prices, sector_of, universe, cfg, **run_kwargs)
    print("PASS — identical" if deterministic else "FAIL — trade stream differs between runs!")
    return 0 if deterministic else 1


if __name__ == "__main__":
    raise SystemExit(main())
