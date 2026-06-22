"""CLI to manage the discretionary (satellite / IPO) sleeve registry.

A satellite holding is a position the optimizer cannot model yet (a fresh listing with no price
history). Registering one tells the system to **track, tax, and watch** it but never optimize or sell
it — the model treats its capital as withdrawn (see ``qalpha.live.satellite``). The dashboard surfaces
the full per-holding tax/exit advice + graduation countdown; this CLI just maintains membership.

    uv run python scripts/satellite.py add JIOFIN.NS 2026-06-20   # mark a holding as discretionary
    uv run python scripts/satellite.py list                       # show the registry
    uv run python scripts/satellite.py remove JIOFIN.NS           # graduate / drop it
"""

from __future__ import annotations

import argparse
from datetime import date

from qalpha.live.satellite import REGISTRY_PATH, SatelliteRegistry, register_ipo


def _cmd_add(args: argparse.Namespace) -> None:
    listed = date.fromisoformat(args.listed_date)
    register_ipo(args.ticker, listed, path=REGISTRY_PATH)
    print(f"Registered {args.ticker} (listed {listed}) as a discretionary satellite holding.")
    print("The optimizer will now exclude it; it is still tracked, taxed, and watched.")


def _cmd_remove(args: argparse.Namespace) -> None:
    registry = SatelliteRegistry.load(REGISTRY_PATH)
    if not registry.is_satellite(args.ticker):
        print(f"{args.ticker} is not in the satellite registry — nothing to remove.")
        return
    registry.remove(args.ticker)
    registry.save(REGISTRY_PATH)
    print(
        f"Removed {args.ticker}. (To graduate it: also add it to the universe + ingest its prices.)"
    )


def _cmd_list(_args: argparse.Namespace) -> None:
    registry = SatelliteRegistry.load(REGISTRY_PATH)
    if not registry.listed_on:
        print("No discretionary (satellite/IPO) holdings registered.")
        return
    print("Discretionary (satellite/IPO) holdings — excluded from the optimizer:")
    for ticker, listed in sorted(registry.listed_on.items()):
        print(f"  {ticker:<16} listed {listed}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="register a holding as discretionary/satellite")
    p_add.add_argument("ticker", help="canonical ticker, e.g. JIOFIN.NS")
    p_add.add_argument("listed_date", help="listing date, ISO YYYY-MM-DD")
    p_add.set_defaults(func=_cmd_add)

    p_rm = sub.add_parser("remove", help="remove a holding from the registry (e.g. on graduation)")
    p_rm.add_argument("ticker")
    p_rm.set_defaults(func=_cmd_remove)

    p_ls = sub.add_parser("list", help="show the registered satellite holdings")
    p_ls.set_defaults(func=_cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
