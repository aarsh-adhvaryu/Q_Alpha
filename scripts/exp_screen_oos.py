"""Does the screen the real money runs have any predictive signal? — a first, cheap read.

**This is development evidence, not out-of-sample evidence, and it must never be quoted as the
latter.** It exists to answer one question cheaply before months of engineering are spent on the
system around it: *does ranking names by how far they sit below their own 1-year high separate
future winners from future losers at all?*

WHAT IT TESTS

`live/deploy.py`'s two functions, called directly rather than reimplemented — testing a copy of the
rule would prove nothing about the rule that runs:

    cheapness_scores(prices, tickers, as_of)   per-name pullback below its own 1y high
    market_weakness(index_close, as_of)        the regime the deploy size is paced by

At each month end it ranks the eligible universe by cheapness, takes the top K, and measures the
next month's equal-weighted return against **the equal-weighted return of the whole eligible set** —
1/N, the benchmark the gate actually compares against, not the cap-weighted index. Phase 4 found 76%
of the apparent edge over the cap-weighted index *is* the equal-weight premium, which is purchasable,
so measuring against it would flatter the screen for something anyone can buy.

WHAT IT DOES NOT DO, AND WHY THE NUMBER IS AN UPPER BOUND

  - **No costs, no tax, no slippage.** Monthly re-ranking implies turnover the real book never pays;
    Phase 4 measured tax alone at ₹74.8 lakh over 13 years. A positive spread here is necessary and
    nowhere near sufficient.
  - **Monthly rebalancing is not the live policy.** The real book buys with new cash and holds. This
    measures the *signal*, not the strategy.
  - **The live universe cannot be tested cleanly.** The screen runs on `nifty100_watchlist.csv`,
    which is a static list of today's members — survivorship bias, and it cannot be undone by
    processing. This runs on `nifty50_membership.csv`, which carries dated entries and exits, so the
    headline is point-in-time honest on a universe that is *not* the live one. Both are printed and
    labelled; the biased one is never the headline.
  - **Overlapping windows are avoided** by using non-overlapping monthly holding periods, so the
    t-statistic is not inflated by reusing the same months.

Run:  uv run python scripts/exp_screen_oos.py
      uv run python scripts/exp_screen_oos.py --k 8 --k 15 --k 30 --biased-universe-too
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.deploy import cheapness_scores, market_weakness

# The panels the DAILY RUN actually loads (scripts/paper.py), not the 2012-2024 stubs beside them.
# The first version of this script read `prices.parquet`, which holds 24 tickers and stops in 2024,
# and reported a result on a 23-name "universe" — a top-8 of 23 is a third of the market, not a
# screen. Auditing input coverage before quoting a number is the whole of gate 4's first line.
PANEL = Path("data/historical/prices_pit_2026.parquet")
PIT_UNIVERSE = Path("data/universes/nifty50_membership_2026.csv")
STATIC_PANEL = Path("data/historical/prices_watchlist.parquet")
STATIC_UNIVERSE = Path("data/universes/nifty100_watchlist.csv")
BENCHMARK = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")

#: A name needs a full year of history before its 1-year high means anything.
MIN_HISTORY_DAYS = 260


@dataclass(frozen=True)
class Period:
    """One month: what was picked, and what it did next."""

    as_of: date
    n_eligible: int
    picked: tuple[str, ...]
    picked_return: float
    universe_return: float
    weakness: str

    @property
    def spread(self) -> float:
        return self.picked_return - self.universe_return


def _load_prices(path: Path) -> PriceData:
    if not path.exists():
        raise SystemExit(f"no price panel at {path} — run the data refresh first")
    return PriceData.from_long(pd.read_parquet(path))


def _load_benchmark() -> pd.Series:
    if not BENCHMARK.exists():
        return pd.Series(dtype=float)
    raw = pd.read_parquet(BENCHMARK)
    col = "adj_close" if "adj_close" in raw.columns else "close"
    if "date" in raw.columns:
        return pd.Series(raw[col].to_numpy(), index=pd.to_datetime(raw["date"])).sort_index()
    return pd.Series(raw[col].to_numpy(), index=pd.to_datetime(raw.index)).sort_index()


def _month_ends(index: pd.DatetimeIndex, *, start: pd.Timestamp) -> list[pd.Timestamp]:
    """The last trading day of each month, from ``start``. Rebalance dates, point-in-time."""
    idx = index[index >= start]
    return [g.max() for _, g in pd.Series(idx, index=idx).groupby([idx.year, idx.month])]


def _eligible(prices: PriceData, universe: Universe, on: pd.Timestamp) -> list[str]:
    """Universe members on that date that also have a year of price history by then."""
    adj = prices.adj_close
    members = [t for t in universe.members_on(on.date()) if t in adj.columns]
    out = []
    for t in members:
        series = adj[t].loc[:on].dropna()
        if len(series) >= MIN_HISTORY_DAYS and series.iloc[-1] > 0:
            out.append(t)
    return out


def _forward_return(
    prices: PriceData, tickers: list[str], a: pd.Timestamp, b: pd.Timestamp
) -> float:
    """Equal-weighted total return between two dates. Names unpriced at either end are dropped —
    never carried at zero, which would read a missing quote as a wipeout."""
    adj = prices.adj_close
    rets = []
    for t in tickers:
        try:
            p0, p1 = adj[t].loc[:a].dropna(), adj[t].loc[:b].dropna()
        except KeyError:
            continue
        if p0.empty or p1.empty or p0.iloc[-1] <= 0:
            continue
        rets.append(float(p1.iloc[-1] / p0.iloc[-1] - 1.0))
    return float(np.mean(rets)) if rets else 0.0


def run(prices: PriceData, universe: Universe, benchmark: pd.Series, *, k: int) -> list[Period]:
    dates = pd.DatetimeIndex(prices.adj_close.index)
    start = dates[0] + pd.Timedelta(days=MIN_HISTORY_DAYS + 10)
    ends = _month_ends(dates, start=start)
    out: list[Period] = []
    for a, b in pairwise(ends):
        eligible = _eligible(prices, universe, a)
        if len(eligible) < k + 5:  # need a universe meaningfully larger than the basket
            continue
        scores = cheapness_scores(prices, eligible, a.date())
        picked = [t for t, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:k]]
        weak = "unknown"
        if not benchmark.empty:
            try:
                weak = market_weakness(benchmark, a.date()).level
            except Exception:
                weak = "unknown"
        out.append(
            Period(
                as_of=a.date(),
                n_eligible=len(eligible),
                picked=tuple(picked),
                picked_return=_forward_return(prices, picked, a, b),
                universe_return=_forward_return(prices, eligible, a, b),
                weakness=weak,
            )
        )
    return out


def _block_bootstrap(
    spreads: np.ndarray, *, block: int = 6, draws: int = 5000, seed: int = 20260908
) -> tuple[float, float]:
    """95% CI on the mean monthly spread, resampling in blocks so serial dependence survives.

    An i.i.d. bootstrap on monthly equity spreads understates the interval, because market shocks
    hit consecutive months together — the same clustering that makes the cross-section far less
    informative than its row count suggests.
    """
    rng = np.random.default_rng(seed)
    n = len(spreads)
    if n < block * 2:
        return float("nan"), float("nan")
    starts = n - block + 1
    means = np.empty(draws)
    for i in range(draws):
        picks = rng.integers(0, starts, size=int(np.ceil(n / block)))
        sample = np.concatenate([spreads[s : s + block] for s in picks])[:n]
        means[i] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def report(periods: list[Period], *, k: int, label: str) -> None:
    if not periods:
        print(f"\n{label} · top {k}: no periods — not enough history or universe")
        return
    spreads = np.array([p.spread for p in periods])
    mean = spreads.mean()
    se = spreads.std(ddof=1) / np.sqrt(len(spreads))
    t = mean / se if se > 0 else float("nan")
    lo, hi = _block_bootstrap(spreads)
    ann = (1 + mean) ** 12 - 1
    print(f"\n{'=' * 78}\n{label} · top {k} by cheapness, held one month, vs the 1/N eligible set")
    print(f"{'=' * 78}")
    print(
        f"  months                     {len(periods)}  ({periods[0].as_of} → {periods[-1].as_of})"
    )
    print(f"  eligible names, median     {int(np.median([p.n_eligible for p in periods]))}")
    print(f"  mean monthly spread        {mean * 100:+.3f}%")
    print(f"  annualised                 {ann * 100:+.2f}%")
    print(f"  t-statistic                {t:+.2f}   (|t| > 2 is the usual bar)")
    print(f"  95% block-bootstrap CI     [{lo * 100:+.3f}%, {hi * 100:+.3f}%] monthly")
    print(
        f"  months the screen won      {(spreads > 0).sum()} of {len(spreads)}  ({(spreads > 0).mean() * 100:.0f}%)"
    )
    if not (lo <= 0 <= hi):
        print("  → the interval EXCLUDES zero on this sample.")
    else:
        print("  → the interval INCLUDES zero: this sample cannot distinguish the screen from 1/N.")
    by: dict[str, list[float]] = {}
    for p in periods:
        by.setdefault(p.weakness, []).append(p.spread)
    if len(by) > 1:
        print("\n  conditioned on the market-weakness regime the live screen paces by:")
        print(f"    {'regime':<9} {'n':>4}  {'mean':>9}  {'sd':>8}  {'t':>6}  wins")
        for level in ("normal", "elevated", "deep", "unknown"):
            if level not in by:
                continue
            arr = np.array(by[level])
            sd = arr.std(ddof=1) if len(arr) > 1 else float("nan")
            tt = arr.mean() / (sd / np.sqrt(len(arr))) if len(arr) > 1 and sd > 0 else float("nan")
            print(
                f"    {level:<9} {len(arr):>4}  {arr.mean() * 100:>+8.3f}%  {sd * 100:>7.2f}%  "
                f"{tt:>+6.2f}  {(arr > 0).sum()}/{len(arr)}"
            )
        # The dispersion column is not decoration. A regime with nine observations and a 7% standard
        # deviation produces eye-catching means from nothing, and this breakdown is exactly the kind
        # of table that gets quoted as a discovery. It is also a multiple comparison: three basket
        # sizes by three regimes is nine looks at one dataset, so a "significant" cell here needs a
        # far higher bar than |t| > 2 before it means anything.
        thin = [lvl for lvl, v in by.items() if len(v) < 20]
        if thin:
            print(
                f"    ⚠ {', '.join(thin)}: fewer than 20 months. Read the sd and the win count, not "
                "the mean — and treat any cell here as a hypothesis, never a result."
            )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--k", type=int, action="append", help="basket size (repeatable; default 8/15/30)"
    )
    ap.add_argument(
        "--biased-universe-too",
        action="store_true",
        help="also run the survivorship-biased static watchlist, clearly labelled",
    )
    args = ap.parse_args(argv)
    sizes = args.k or [8, 15, 30]

    prices = _load_prices(PANEL)
    benchmark = _load_benchmark()
    pit = Universe.from_csv(PIT_UNIVERSE)
    print(
        f"panel: {prices.adj_close.shape[1]} tickers, "
        f"{prices.adj_close.index[0].date()} → {prices.adj_close.index[-1].date()}"
    )
    print("HEADLINE universe: nifty50_membership.csv (point-in-time; dated entries and exits)")
    for k in sizes:
        report(run(prices, pit, benchmark, k=k), k=k, label="POINT-IN-TIME Nifty 50")

    if args.biased_universe_too:
        static_prices = _load_prices(STATIC_PANEL)
        static = Universe.static([str(t) for t in pd.read_csv(STATIC_UNIVERSE)["ticker"]])
        print("\n\n### SURVIVORSHIP-BIASED — today's watchlist applied to the past. This is the")
        print("### universe the live screen runs on, and it CANNOT be tested cleanly without")
        print("### point-in-time Nifty-100 membership. Never quote these as evidence.")
        for k in sizes:
            report(run(static_prices, static, benchmark, k=k), k=k, label="BIASED static watchlist")

    print("\nDevelopment evidence. No costs, no tax, no slippage; monthly rebalancing is not the")
    print("live policy. A positive spread here is necessary and nowhere near sufficient.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
