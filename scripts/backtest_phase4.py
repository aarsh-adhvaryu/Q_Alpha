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

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.runstore import RunRecord, save_run
from qalpha.backtest.significance import noise_floor, summarise_null
from qalpha.data.ingest import load_parquet
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.twin import EW_FUND_FEE

WATCHLIST_PANEL = "data/historical/prices_watchlist.parquet"
WATCHLIST_CSV = "data/universes/nifty100_watchlist.csv"
#: Point-in-time Nifty-50 membership — dead names included, so a name that left the index leaves the
#: universe on the date it actually left. The headline MUST run on this.
PIT_MEMBERSHIP = "data/universes/nifty50_membership.csv"
LUMP = Decimal("100000")
SIP = Decimal("50000")
MAX_NAMES = 15


def _max_drawdown(series: pd.Series) -> float:
    """Worst peak-to-trough fall of a normalised equity series."""
    return float((series / series.cummax() - 1).min())


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

    # ---- the two baselines ------------------------------------------------------------------------
    # NIFTYBEES is the floor: doing literally nothing. The equal-weight FUND is the bar that decides
    # whether to bother, because 76% of the screen's gap over the cap-weighted index is the
    # equal-weight premium — and that premium is purchasable for ~0.41%/yr.
    base = run_index(bench, schedule, lump=LUMP, sip=SIP, label="NIFTYBEES (do nothing)")
    ew_level = equal_weight_pit(
        prices, Universe.from_csv(PIT_MEMBERSHIP), prices.adj_close.index, Decimal("100")
    )
    ew = run_index(ew_level, schedule, lump=LUMP, sip=SIP, label="Equal-weight index (no fee)")
    years = Decimal(str((end - schedule[0]).days / 365.25))
    ew_fund_final = float(Decimal(str(ew.final)) * (Decimal("1") - EW_FUND_FEE) ** years)

    # ---- each component alone, then the composite -------------------------------------------------
    runs: list[Result] = [base, ew]
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
    screen = runs[2]
    real_gap = screen.final - base.final
    # ---- the hedge overlay, on the composite's own equity curve ----------------------------------
    # The docstring promised this component and the first version of this file did not deliver it.
    # Measured the honest way: the same book, hedged and unhedged, so the difference is the overlay
    # and nothing else — including its transaction cost, monthly roll, and the 30% F&O
    # business-income tax on hedge gains that makes it cheaper than selling but not free.
    from qalpha.live.hedge import apply_futures_hedge, hedge_active, stress_gauge

    curve = screen.equity_curve
    book_ret = curve.pct_change().fillna(0.0)
    idx = index_close.reindex(curve.index).ffill()
    gauge = stress_gauge(idx)
    active = hedge_active(gauge, 0.7, 3)
    hedged = apply_futures_hedge(book_ret, idx.pct_change().fillna(0.0), active, h=0.5)
    unhedged_final = float((1.0 + book_ret).cumprod().iloc[-1])
    print("\n--- the hedge overlay (τ=0.7, persist=3, h=0.5) ---")
    print(f"episodes fired: {hedged.episodes}")
    if hedged.episodes == 0:
        print("  ⚪ the gauge never cleared τ on this window — NO evidence either way.")
    else:
        hedged_final = float(hedged.equity.iloc[-1])
        unhedged_curve = (1.0 + book_ret).cumprod()
        dd_un = _max_drawdown(unhedged_curve)
        dd_hg = _max_drawdown(hedged.equity)
        print(
            f"  unhedged ×{unhedged_final:.3f}  ·  hedged ×{hedged_final:.3f}"
            f"  ·  cost {hedged.cost:.4f} + F&O tax {hedged.tax:.4f} of book value"
        )
        print(f"  worst drawdown: unhedged {dd_un:.1%}  ·  hedged {dd_hg:.1%}")
        print(
            f"  → cost {(1 - hedged_final / unhedged_final):.1%} of terminal wealth to cut the "
            f"worst fall by {abs(dd_hg - dd_un):.1%}"
        )

    print(f"\n{summarise_null([abs(g) for g in gaps])}")
    print(f"\nScreen − baseline: ₹{real_gap:,.0f}")
    print(f"Noise floor (p95): ₹{floor:,.0f}")
    verdict = (
        "CLEARS the floor" if abs(real_gap) > float(floor) else "INSIDE the floor — not a result"
    )
    print(f"Verdict: **{verdict}**")

    vs_fund = screen.final - ew_fund_final
    print("\n--- against the baseline that decides whether to bother ---")
    print(
        f"Equal-weight index FUND (net {float(EW_FUND_FEE) * 100:.2f}%/yr fee): ₹{ew_fund_final:,.0f}"
    )
    print(
        f"Screen − EW fund: ₹{vs_fund:,.0f}  "
        f"({vs_fund / ew_fund_final * 100:+.1f}% more terminal wealth)"
    )

    path = save_run(
        RunRecord(
            label="phase4",
            params={
                "universe": "point_in_time_nifty50",
                "start": str(start),
                "end": str(end),
                "deploys": len(schedule),
                "lump": str(LUMP),
                "sip": str(SIP),
                "max_names": MAX_NAMES,
                "null_draws": args.null,
                "seed": args.seed,
                "ew_fund_fee": str(EW_FUND_FEE),
            },
            results={
                "baseline_niftybees": base.final,
                "baseline_ew_index_nofee": ew.final,
                "baseline_ew_fund_netfee": ew_fund_final,
                "screen_buyhold": screen.final,
                "screen_with_exits": runs[3].final,
                "screen_annual_trim": runs[4].final,
                "hedge_episodes": float(hedged.episodes),
                "hedge_cost_frac": float(hedged.cost),
                "hedge_fno_tax_frac": float(hedged.tax),
                "static_universe_BIASED": runs[5].final,
                "noise_floor_p95": float(floor),
                "null_median": float(np.median([abs(g) for g in gaps])),
                "screen_minus_niftybees": real_gap,
                "screen_minus_ew_fund": vs_fund,
            },
            caveats=[
                "One window, one universe, one parameterisation — no walk-forward on the composite.",
                "The screen was developed with this data visible: the selection edge is NOT out of sample.",
                f"{args.null} null draws supports p < {1 / (args.null + 1):.3f} and nothing stronger.",
                "The static-universe row is survivorship-biased ~2.5x and must never be quoted.",
                "The AI is absent by necessity: historical verdicts leak the outcome.",
                "Costs use the Zerodha model at default impact; no slippage sensitivity was run.",
            ],
        )
    )
    print(f"\n✓ run recorded → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
