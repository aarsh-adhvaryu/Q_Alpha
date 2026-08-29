"""Phase 4 — the whole system, backtested independently and together, with a noise floor.

    uv run python scripts/backtest_phase4.py            # full run (slow: the null is N simulations)
    uv run python scripts/backtest_phase4.py --null 30  # fewer null draws, for a quick look

**Pre-registered before the first run** (PLAN_REDESIGN §5/§6). One variant per question, thresholds
fixed in the plan, negatives published. The temptation to tune until it looks good is materially
stronger now that real money rides on the answer, which is exactly when the discipline matters.

**What is tested**

* each component **alone** — buy screen, exits, hedge — against the same do-nothing baseline;
* the **composite**, which is the only configuration that has ever been run with money;
* a **no-skill null**: the same machinery choosing at random, which sets the bar every live gap
  must clear (GO criterion 3).

**⚠️ The AI cannot be backtested, and this run does not pretend to.** Generating historical verdicts
means asking a model whose training data *contains the outcome* — a 2015 verdict from a 2025 model is
not a forecast, it is a memory. There is no honest historical AI test, only the forward one the twin
runs. Reported as a limitation, never as a result.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
import pandas as pd
from backtest_sip import Result, _month_starts, run_index, run_screen
from paper import _load_benchmark_series

from qalpha.backtest.significance import noise_floor, summarise_null
from qalpha.data.ingest import load_parquet
from qalpha.data.prices import PriceData

WATCHLIST_PANEL = "data/historical/prices_watchlist.parquet"
WATCHLIST_CSV = "data/universes/nifty100_watchlist.csv"
#: Point-in-time Nifty-50 membership — dead names included, so a name that left the index leaves the
#: universe on the date it actually left. The headline MUST run on this.
PIT_MEMBERSHIP = "data/universes/nifty50_membership.csv"
LUMP = Decimal("100000")
SIP = Decimal("50000")
MAX_NAMES = 15


def _load() -> tuple[PriceData, dict[str, str], pd.DataFrame, list[str], pd.Series]:
    """Panel, sectors, PIT membership, the (survivorship-biased) watchlist, and a REPAIRED benchmark.

    ⚠️ ``_load_benchmark_series`` rather than ``pd.read_parquet``. The committed benchmark carries two
    corrupt prints — 2019-12-19/20 read ₹13.02 and ₹13.03 against a true ₹129.25, a factor-of-ten
    feed error — and the loader repairs them. Reading the parquet directly produced an **-89.9%**
    drawdown on NIFTYBEES, which is impossible and would have poisoned every baseline in this file.
    """
    prices = load_parquet(WATCHLIST_PANEL)
    wl = pd.read_csv(WATCHLIST_CSV)
    sector_of = dict(zip(wl["ticker"], wl["sector"], strict=False))
    pit = pd.read_csv(PIT_MEMBERSHIP)
    sector_of.update(dict(zip(pit["ticker"], pit["sector"], strict=False)))
    biased = [t for t in wl["ticker"] if t in prices.adj_close.columns]
    return prices, sector_of, pit, biased, _load_benchmark_series()


def _pit_universe(pit: pd.DataFrame, available: set[str]):
    """``universe_on(d)`` → the names actually IN the index on ``d``, dead ones included.

    Survivorship is the largest single distortion available here: holding today's constituents fixed
    across fourteen years roughly **triples** the apparent result (BACKTEST_SIP.md), because every
    name in that list is one that survived. The headline runs point-in-time; the static watchlist is
    reported only to size the bias.
    """
    rows = [
        (
            str(r["ticker"]),
            date.fromisoformat(str(r["start_date"])),
            date.fromisoformat(str(r["end_date"])) if pd.notna(r["end_date"]) else date(2100, 1, 1),
        )
        for _, r in pit.iterrows()
        if str(r["ticker"]) in available
    ]

    def universe_on(d: date) -> list[str]:
        return [t for t, a, b in rows if a <= d <= b]

    return universe_on


def _random_universe_pit(universe_on, k: int, rng: np.random.Generator):
    """Offer the screen only ``k`` names drawn at random **from that day's real universe**.

    This is the null. Identical sizing, cadence, costs, taxes and whole-share granularity; identical
    point-in-time membership, so a dead name can still be drawn on a date it was alive. Only the
    *choosing* is destroyed — any gap it produces is luck, which is exactly the bar a live gap has
    to clear.
    """

    def pick(d: date) -> list[str]:
        pool = universe_on(d)
        if not pool:
            return []
        return list(rng.choice(np.array(pool), size=min(k, len(pool)), replace=False))

    return pick


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--null", type=int, default=60, help="no-skill draws (default 60)")
    ap.add_argument("--seed", type=int, default=20260829)
    ap.add_argument("--start", default="2013-07-01")
    ap.add_argument("--end", default="2026-06-30")
    args = ap.parse_args(argv)

    prices, sector_of, pit, biased, bench = _load()
    dates = [d.date() for d in prices.dates]
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    schedule = _month_starts(dates, start, end)
    index_close = bench.reindex(prices.adj_close.index).ffill()
    available = set(prices.adj_close.columns)
    universe_on = _pit_universe(pit, available)
    names = sorted({t for d in schedule for t in universe_on(d)})
    print(
        f"{len(schedule)} monthly deploys · {start} → {end}\n"
        f"point-in-time Nifty-50: {len(names)} names ever in the universe "
        f"({len(universe_on(schedule[0]))} on day one, {len(universe_on(schedule[-1]))} at the end)\n"
    )

    # ---- the do-nothing baseline ----------------------------------------------------------------
    base = run_index(bench, schedule, lump=LUMP, sip=SIP, label="NIFTYBEES (do nothing)")

    # ---- each component alone, then the composite -------------------------------------------------
    runs: list[Result] = [base]
    for label, maintain in [
        ("Screen only (buy & hold)", "none"),
        ("Screen + §4.7 exits", "prune"),
        ("Screen + annual trim", "annual"),
    ]:
        runs.append(
            run_screen(
                prices,
                sector_of,
                universe_on,
                index_close,
                schedule,
                lump=LUMP,
                sip=SIP,
                max_names=MAX_NAMES,
                label=label,
                maintain=maintain,
            )
        )

    # The survivorship sensitivity: the SAME screen on today's Nifty-100 held fixed for 14 years.
    # Reported only to size the bias — it must never be quoted as a result (BACKTEST_SIP.md).
    runs.append(
        run_screen(
            prices,
            sector_of,
            lambda _d: biased,
            index_close,
            schedule,
            lump=LUMP,
            sip=SIP,
            max_names=MAX_NAMES,
            label="⚠️ static Nifty-100 (BIASED)",
            maintain="none",
        )
    )

    print(f"{'plan':<30}{'final':>16}{'return':>10}{'worst fall':>13}{'tax':>12}{'trades':>8}")
    print("-" * 89)
    for r in runs:
        print(
            f"{r.label:<30}{r.final:>16,.0f}{r.total_return_pct:>9.1f}%"
            f"{r.max_drawdown_pct():>12.1f}%{float(r.tax_paid):>12,.0f}{r.trades:>8}"
        )

    # ---- the null: same machinery, no skill --------------------------------------------------------
    print(f"\nRunning {args.null} no-skill draws (random selection, identical everything else)…")
    rng = np.random.default_rng(args.seed)
    gaps: list[float] = []
    for i in range(args.null):
        r = run_screen(
            prices,
            sector_of,
            _random_universe_pit(universe_on, MAX_NAMES, rng),
            index_close,
            schedule,
            lump=LUMP,
            sip=SIP,
            max_names=MAX_NAMES,
            label=f"null-{i}",
            maintain="none",
        )
        gaps.append(r.final - base.final)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{args.null}…")

    floor = noise_floor([abs(g) for g in gaps])
    real_gap = runs[1].final - base.final
    print(f"\n{summarise_null([abs(g) for g in gaps])}")
    print(f"\nScreen − baseline: ₹{real_gap:,.0f}")
    print(f"Noise floor (p95): ₹{floor:,.0f}")
    verdict = (
        "CLEARS the floor" if abs(real_gap) > float(floor) else "INSIDE the floor — not a result"
    )
    print(f"Verdict: **{verdict}**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
