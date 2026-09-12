"""Generate the matched null for the forward experiments (pre-registration §2 / CORE_V1 §4).

    uv run python scripts/exp_null.py --draws 1000

**What a null is for.** The gate compares one number — $G=\\ln(\\mathrm{NAV}_{\\text{strategy}} /
\\mathrm{NAV}_{\\text{fund}})$ — against a bar. Without a bar, *any* positive $G$ looks like skill,
including the amount a coin-flipping basket would produce by luck over the same twelve months, in
the same market, paying the same costs. `NULL_P95_LOG_REL_WEALTH` is that bar: the 95th percentile
of $|G|$ when **selection is random and everything else is identical**.

**Why generate it before the window opens rather than after.** The specification was frozen in
August so that computing it later could not be tuned to the result. Computing it *now* is stronger
still: `CORE_V1`'s window has not opened, so there is no observation to tune toward. The threshold
exists before the thing it will judge.

**What is randomised, and what is not.** Only the *selection*. The window, the deposit schedule, the
point-in-time membership, the whole-share rounding, the Zerodha cost model and the benchmark
construction are the ones the live book uses. A null that skipped costs would be easier to beat than
reality and would understate the bar.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe
from qalpha.live.nav import unitized_nav
from qalpha.live.twin import EW_FUND_FEE

PANEL = "data/historical/prices_pit_2026.parquet"
MEMBERSHIP = "data/universes/nifty50_membership_2026.csv"
OUT = Path("reports/NULL_MATCHED.json")

#: The live cash profile, from the pre-registration: ₹3,00,000 opening, then ₹50,000 a month.
OPENING = Decimal("300000")
MONTHLY = Decimal("50000")
MONTHS = 12

#: Names per deployment. Not pinned by the original text, so it is pinned **here, before any
#: observation exists**: it is the live ``deploy_policy.max_names_default``, so the null carries the
#: same breadth as the book it is a bar for. A narrower null would be noisier and the bar higher.
NAMES_PER_DEPLOY = 15

#: No sells inside a twelve-month window — the live cadence is annual — so realised tax is ₹0 on
#: **both** legs. The tax engine is still wired in; it simply has nothing to charge. That is the
#: same arithmetic the real book runs, not a shortcut past it.
SELLS_IN_WINDOW = 0


@dataclass(frozen=True)
class Draw:
    """One simulated twelve-month life of a randomly-selected book."""

    start: date
    end: date
    g: float
    strategy_nav: float
    benchmark_nav: float


def _flow_dates(sessions: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """The opening deposit plus one on the first session of each later month, capped at 12."""
    out = [sessions[0]]
    seen = {(sessions[0].year, sessions[0].month)}
    for ts in sessions:
        key = (ts.year, ts.month)
        if key not in seen:
            seen.add(key)
            out.append(ts)
        if len(out) == MONTHS:
            break
    return out


def _deploy(
    portfolio: Portfolio,
    on: date,
    picks: Sequence[str],
    prices: pd.DataFrame,
    cash: Decimal,
) -> None:
    """Spend ``cash`` equally across ``picks``, whole shares, real costs. Never fractional."""
    if not picks:
        return
    per_name = cash / Decimal(len(picks))
    row = prices.loc[pd.Timestamp(on)]
    for ticker in picks:
        price = row.get(ticker)
        if price is None or not np.isfinite(price) or price <= 0:
            continue
        # Checked finite and positive on the line above; the stub still types it as a Series.
        px = float(cast(float, price))
        qty = int(per_name / Decimal(str(px)))
        if qty > 0:
            portfolio.buy(on, ticker, Decimal(qty), Decimal(str(px)))


def one_draw(
    rng: np.random.Generator,
    prices: pd.DataFrame,
    universe: Universe,
    ew_level: pd.Series,
    cfg: Config,
    starts: pd.DatetimeIndex,
) -> Draw | None:
    """Simulate one window. ``None`` when the window cannot be built honestly."""
    start = starts[int(rng.integers(0, len(starts)))]
    window = prices.loc[start : start + pd.Timedelta(days=365)]
    if len(window) < 200:  # a 12-month window has ~250 sessions; a short one is not one
        return None
    flow_days = _flow_dates(pd.DatetimeIndex(window.index))
    if len(flow_days) < MONTHS:
        return None

    portfolio = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    flows: list[tuple[date, float]] = []
    bench_units = 0.0
    bench_units_by_day: dict[pd.Timestamp, float] = {}
    # Positions and cash are snapshotted AFTER each deployment and forward-filled across the window.
    # **The first version valued the FINAL basket across every session, including before it was
    # bought.** The book then looked flat while eleven deposits kept arriving, so the unitized NAV
    # divided by an ever-growing unit count and every one of 20 draws lost 49% to the fund. A null
    # where nothing ever beats the benchmark is not a null; it is a bug reporting itself.
    qty_snapshots: dict[pd.Timestamp, dict[str, float]] = {}
    cash_snapshots: dict[pd.Timestamp, float] = {}

    for i, day in enumerate(flow_days):
        amount = OPENING if i == 0 else MONTHLY
        portfolio.cash += amount
        flows.append((day.date(), float(amount)))

        members = [t for t in universe.members_on(day.date()) if t in window.columns]
        row = window.loc[day]
        eligible = [t for t in members if np.isfinite(row.get(t, np.nan)) and row.get(t, 0) > 0]
        if len(eligible) < NAMES_PER_DEPLOY:
            return None
        picks = list(rng.choice(np.array(eligible), size=NAMES_PER_DEPLOY, replace=False))
        _deploy(portfolio, day.date(), picks, window, portfolio.cash)

        qty_snapshots[day] = {t: float(q) for t, q in portfolio.positions().items() if q > 0}
        cash_snapshots[day] = float(portfolio.cash)

        level = float(cast(float, ew_level.asof(day)))
        if not np.isfinite(level) or level <= 0:
            return None
        bench_units += float(amount) / level
        bench_units_by_day[day] = bench_units

    everything = sorted({t for snap in qty_snapshots.values() for t in snap})
    if not everything:
        return None
    quantities = (
        pd.DataFrame(
            [[snap.get(t, 0.0) for t in everything] for snap in qty_snapshots.values()],
            index=pd.DatetimeIndex(list(qty_snapshots)),
            columns=everything,
        )
        .reindex(window.index)
        .ffill()
        .fillna(0.0)
    )
    cash_series = pd.Series(cash_snapshots).reindex(window.index).ffill().fillna(0.0)
    marks = np.nan_to_num(window[everything].to_numpy(dtype=float), nan=0.0)
    strat_values = pd.Series(
        (marks * quantities.to_numpy(dtype=float)).sum(axis=1) + cash_series.to_numpy(dtype=float),
        index=window.index,
    )

    # THE FUND'S FEE, charged continuously, exactly as ``ew_fund_mark`` charges it live. The
    # pre-registration says "the equal-weight fund **net of its fee**", and a frictionless benchmark
    # is not one anybody can hold — it would be *easier* to beat, which biases the null's G
    # distribution downward and sets the bar too low. Caught by re-reading the spec, not the code.
    units = pd.Series(bench_units_by_day).reindex(window.index).ffill().fillna(0.0)
    elapsed_years = (window.index - window.index[0]).days / 365.25
    drag = pd.Series(
        float(Decimal("1") - EW_FUND_FEE) ** np.asarray(elapsed_years, dtype=float),
        index=window.index,
    )
    bench_values = units * ew_level.reindex(window.index).ffill() * drag
    if not np.isfinite(bench_values.iloc[-1]) or bench_values.iloc[-1] <= 0:
        return None

    strat_nav = unitized_nav(strat_values, flows)
    bench_nav = unitized_nav(bench_values, flows)
    a, b = float(strat_nav.iloc[-1]), float(bench_nav.iloc[-1])
    if not (np.isfinite(a) and np.isfinite(b)) or a <= 0 or b <= 0:
        return None
    return Draw(
        start=window.index[0].date(),
        end=window.index[-1].date(),
        g=float(np.log(a / b)),
        strategy_nav=a,
        benchmark_nav=b,
    )


def generate(draws: int, seed: int) -> dict[str, object]:
    cfg = Config()
    panel = load_parquet(PANEL)
    universe = Universe.from_csv(MEMBERSHIP)
    prices = panel.adj_close
    index = pd.DatetimeIndex(panel.dates)
    ew_level = equal_weight_pit(panel, universe, index, Decimal("100"))

    latest_start = index[-1] - pd.Timedelta(days=366)
    starts = index[index <= latest_start]
    print(
        f"[null] {len(starts)} candidate window starts, {index[0].date()} → {latest_start.date()}"
    )

    rng = np.random.default_rng(seed)
    kept: list[Draw] = []
    attempts = 0
    while len(kept) < draws and attempts < draws * 20:
        attempts += 1
        drawn = one_draw(rng, prices, universe, ew_level, cfg, starts)
        if drawn is not None:
            kept.append(drawn)
        if len(kept) and len(kept) % 200 == 0 and attempts % 5 == 0:
            print(f"[null]   {len(kept)}/{draws} draws")

    gs = np.array([d.g for d in kept], dtype=float)
    abs_gs = np.abs(gs)
    p95 = float(np.percentile(abs_gs, 95))
    return {
        "specification": "PREREGISTRATION_TWIN_RUN2.md §2 / PREREGISTRATION_CORE_V1.md §4",
        "generated_on": date.today().isoformat(),
        "draws": len(kept),
        "attempts": attempts,
        "seed": seed,
        "names_per_deploy": NAMES_PER_DEPLOY,
        "opening": str(OPENING),
        "monthly": str(MONTHLY),
        "months": MONTHS,
        "panel": PANEL,
        "membership": MEMBERSHIP,
        "window_starts": [str(starts[0].date()), str(starts[-1].date())],
        "p95_abs_log_rel_wealth": p95,
        "mean_log_rel_wealth": float(gs.mean()),
        "median_log_rel_wealth": float(np.median(gs)),
        "p05_log_rel_wealth": float(np.percentile(gs, 5)),
        "p95_log_rel_wealth": float(np.percentile(gs, 95)),
        "std_log_rel_wealth": float(gs.std(ddof=1)),
        "fraction_beating_the_fund": float((gs > 0).mean()),
        **_power(float(np.percentile(abs_gs, 95)), float(gs.std(ddof=1))),
    }


#: The backtest's own headline, over the **gating** benchmark. 18.2% vs 17.7% CAGR — not the +3.7%
#: over the cap-weighted index, because the index is not what the gate compares against and 76% of
#: that wider gap is the equal-weight premium, which is purchasable.
BACKTEST_CAGR = 0.182
BENCHMARK_CAGR = 0.177


def _power(p95: float, sd: float) -> dict[str, float]:
    """How likely is criterion 3 to fire **if the backtested edge is entirely real?**

    A bar without a power calculation is half a test. It tells you the false-positive rate and says
    nothing about whether the true positive can ever happen — and if the answer is "less often than
    the false positive", the criterion is not measuring the strategy, it is measuring noise.
    """
    from statistics import NormalDist

    edge = float(np.log((1 + BACKTEST_CAGR) / (1 + BENCHMARK_CAGR)))
    detect = 1.0 - NormalDist(edge, sd).cdf(p95)
    z = NormalDist().inv_cdf(0.95)
    return {
        "expected_edge_log_per_year": edge,
        "bar_as_multiple_of_edge": p95 / edge,
        "power_in_one_12m_window": detect,
        "false_positive_rate": 0.05,
        "years_to_detect_at_95pc": (z * sd / edge) ** 2,
        "one_year_outperformance_needed": float(np.exp(p95) - 1),
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260906)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    result = generate(args.draws, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"  draws                     {result['draws']}")
    print(f"  mean G                    {result['mean_log_rel_wealth']:+.5f}")
    print(f"  median G                  {result['median_log_rel_wealth']:+.5f}")
    print(
        f"  5th–95th percentile of G  {result['p05_log_rel_wealth']:+.5f} … {result['p95_log_rel_wealth']:+.5f}"
    )
    print(f"  fraction beating the fund {result['fraction_beating_the_fund']:.1%}")
    print()
    print(f"  NULL_P95_LOG_REL_WEALTH = {result['p95_abs_log_rel_wealth']:.6f}")
    print()
    print("  ── power, if the backtested edge is entirely real ──")
    print(f"  expected edge over the fund   {result['expected_edge_log_per_year']:+.5f}/yr")
    print(f"  the bar is                    {result['bar_as_multiple_of_edge']:.1f}x that edge")
    print(f"  P(criterion 3 fires in 12m)   {result['power_in_one_12m_window']:.1%}")
    print(f"  P(false positive)             {result['false_positive_rate']:.1%}")
    print(f"  years to detect at 95%        {result['years_to_detect_at_95pc']:,.0f}")
    print(f"  1-year gap that would clear   {result['one_year_outperformance_needed']:.1%}")
    print(f"  → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
