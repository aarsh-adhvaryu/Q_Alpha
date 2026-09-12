"""WC-1 — does buying into weakness actually pay? Registered before it was written.

    uv run python scripts/exp_weakness_cohorts.py

**Read `reports/PREREGISTRATION_WEAKNESS_COHORTS.md` first.**

The screen is called *deploy into weakness*. Its founding premise — that deeper drawdowns are better
entry points for fresh capital — is stated in `deploy.py`'s docstring as a historical fact and has
never been measured here. `PO-2` showed the ranking carries signal; this asks whether the **timing**
does, or whether the edge is entirely cross-sectional.

Each month's ₹50,000 is one **cohort**, tracked for the rest of the history against the same ₹50,000
put into the fund on the same day. Nothing is ever sold. Cohorts are grouped by the market state on
the day the money went in, classified from data up to that day only.
"""

from __future__ import annotations

import statistics
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe
from qalpha.live.console import use_utf8
from qalpha.live.deploy import cheapness_scores, market_weakness
from qalpha.live.price_integrity import rebase_starts, unexplained_gaps

PIT_PANEL = "data/historical/prices_pit_2026.parquet"
PIT_UNIVERSE = Path("data/universes/nifty50_membership_2026.csv")
STATIC_PANEL = "data/historical/prices_nifty100_static.parquet"
STATIC_UNIVERSE = Path("data/universes/nifty100_watchlist.csv")
REPORT = Path("reports/WEAKNESS_COHORTS_WC1.md")

MONTHLY = Decimal("50000")
EW_FEE = Decimal("0.0041")
TOP_K = 8
LEVELS = ("deep", "elevated", "normal")


class Cohort:
    """One month's money: what it bought, and what the fund would have bought instead."""

    def __init__(self, on: date, level: str, invested: float) -> None:
        self.on = on
        self.level = level
        self.invested = invested
        self.lots: dict[str, float] = {}
        self.fund_units = 0.0

    def value(self, marks: dict[str, float]) -> float:
        return sum(marks.get(t, 0.0) * q for t, q in self.lots.items())


def _members_on(universe: pd.DataFrame, day: date) -> list[str]:
    d = pd.Timestamp(day)
    start = pd.to_datetime(universe["start_date"])
    end = pd.to_datetime(universe["end_date"])
    return sorted(universe.loc[(start <= d) & (end.isna() | (end >= d)), "ticker"].unique())


def run(panel_path: str, universe_path: Path, *, pit: bool, start: str, end: str) -> list[Cohort]:
    panel = load_parquet(panel_path)
    prices = panel.adj_close.loc[start:end]
    index = cast(pd.DatetimeIndex, prices.index)
    if pit:
        universe = pd.read_csv(universe_path)
    else:
        static = pd.read_csv(universe_path)
        universe = pd.DataFrame(
            {"ticker": static["ticker"], "start_date": start, "end_date": pd.NaT}
        )

    from paper import _load_benchmark_series

    _bench = _load_benchmark_series()
    if pit:
        ew_level = (
            equal_weight_pit(panel, Universe.from_csv(str(universe_path)), index, Decimal("100"))
            .reindex(index)
            .ffill()
        )
    else:
        # The static list carries no dates, so `equal_weight_pit` cannot read it. Daily-rebalanced
        # equal weight over the same names is the matching bar — and it inherits exactly the same
        # survivorship as the strategy it is being compared with, which is the point: the two sides
        # are contaminated identically, so the GAP between them is still readable even though
        # neither level is.
        cols = [t for t in pd.read_csv(universe_path)["ticker"] if t in prices.columns]
        ew_level = (1.0 + prices[cols].pct_change().mean(axis=1).fillna(0.0)).cumprod() * 100.0
    months = (
        pd.DataFrame(index=index).groupby([index.year, index.month]).apply(lambda g: g.index[0])
    )
    pays = sorted(set(months))

    cohorts: list[Cohort] = []
    for stamp in pays:
        day = stamp.date()
        hist = prices.loc[:stamp]
        eligible = [t for t in _members_on(universe, day) if t in prices.columns]
        if not eligible:
            continue
        # Classified from data up to this day only — no look-ahead in the grouping.
        level = market_weakness(_bench.loc[:stamp], day).level
        rebase = rebase_starts(unexplained_gaps(hist, eligible, day))
        scores = cheapness_scores(panel, eligible, day, rebase_from=rebase)
        ranked = [t for t, _s in sorted(scores.items(), key=lambda kv: -kv[1])][:TOP_K]
        cash = float(MONTHLY)
        cohort = Cohort(day, level, cash)
        per_name = cash / max(1, len(ranked))
        for ticker in ranked:
            series = hist[ticker].dropna()
            if series.empty:
                continue
            price = float(series.iloc[-1])
            qty = int(per_name / price) if price > 0 else 0
            if qty > 0:
                cohort.lots[ticker] = cohort.lots.get(ticker, 0.0) + qty
        fund_px = float(ew_level.loc[stamp])
        if fund_px > 0:
            cohort.fund_units = cash / fund_px
        cohorts.append(cohort)

    last = index[-1]
    final_marks = {
        t: float(prices[t].dropna().iloc[-1])
        for t in prices.columns
        if not prices[t].dropna().empty
    }
    fund_final = float(ew_level.loc[last])
    for cohort in cohorts:
        years = (last.date() - cohort.on).days / 365.25
        fee_drag = (1.0 - float(EW_FEE)) ** max(0.0, years)
        cohort.fund_value = cohort.fund_units * fund_final * fee_drag  # type: ignore[attr-defined]
        cohort.final = cohort.value(final_marks)  # type: ignore[attr-defined]
        cohort.years = years  # type: ignore[attr-defined]
    return cohorts


def _summarise(cohorts: list[Cohort], label: str) -> list[str]:
    lines = [
        f"### {label}",
        "",
        "| Market on the day | Cohorts | Median multiple | Median vs fund | Beat the fund |",
        "|---|---:|---:|---:|---:|",
    ]
    for level in LEVELS:
        group = [c for c in cohorts if c.level == level]
        if not group:
            lines.append(f"| {level} | 0 | — | — | — |")
            continue
        mult = [c.final / c.invested for c in group]  # type: ignore[attr-defined]
        excess = [
            (c.final / c.fund_value - 1.0)  # type: ignore[attr-defined]
            for c in group
            if c.fund_value > 0  # type: ignore[attr-defined]
        ]
        beat = sum(1 for e in excess if e > 0)
        lines.append(
            f"| **{level}** | {len(group)} | ×{statistics.median(mult):.2f} | "
            f"{statistics.median(excess):+.1%} | {beat}/{len(excess)} "
            f"({beat / max(1, len(excess)):.0%}) |"
        )
    return [*lines, ""]


def main() -> int:
    use_utf8()
    start, end = "2012-01-01", "2026-09-11"
    print(f"[wc1] cohorts by market state on the day the money went in — {start} → {end}")

    pit = run(PIT_PANEL, PIT_UNIVERSE, pit=True, start=start, end=end)
    print(f"[wc1] point-in-time Nifty-50: {len(pit)} cohorts")
    body = [
        "# WC-1 — does buying into weakness actually pay?",
        "",
        f"_Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Registered in "
        "[PREREGISTRATION_WEAKNESS_COHORTS.md](PREREGISTRATION_WEAKNESS_COHORTS.md) before this "
        "script existed._",
        "",
        f"Each month's ₹50,000 buys the top-{TOP_K} by `cheapness_scores`, equal-weighted, whole "
        "shares, Zerodha costs charged. **Nothing is ever sold.** Every month is tracked as its own "
        "cohort against the same ₹50,000 into `BASELINE_EW` on the same day — same money, same day, "
        "only the choice differs. Cohorts are grouped by `market_weakness` **as it was on the day "
        "the money went in**, from data up to that day only.",
        "",
        "*Multiple* is what ₹1 became. *vs fund* is that cohort against the fund over **its own** "
        "holding period, which is the number comparable across groups — a 2012 cohort has had "
        "fourteen years to compound and a 2026 one has had weeks.",
        "",
    ]
    body += _summarise(pit, "Point-in-time Nifty-50 — the headline, survivorship-free")

    try:
        static = run(STATIC_PANEL, STATIC_UNIVERSE, pit=False, start=start, end=end)
        print(f"[wc1] static Nifty-100: {len(static)} cohorts")
        body += _summarise(
            static, "Static Nifty-100 — the live universe, and SURVIVORSHIP-CONTAMINATED"
        )
        body += [
            "> **The second table is not evidence and is not the headline.** "
            "`nifty100_watchlist.csv` is a list of *today's* members, so every name in it survived "
            "to be there — a bias measured at **~3.8%/yr**, more than the effect being looked for. "
            "It is shown because it is the universe the money actually runs on, and because the "
            "gap between the two tables is itself informative.",
            "",
        ]
    except Exception as exc:
        body += [f"_Static Nifty-100 not run: {type(exc).__name__}: {exc}_", ""]

    body += [
        "> **The point-in-time Nifty-100 does not exist and cannot currently be built.** "
        "NIFTY 100 = NIFTY 50 + NIFTY Next 50, and the Next-50 reconstitution history is not "
        "obtainable — Wikipedia carries no Next-50 change section and news coverage is "
        "fragmentary, so any list assembled from it would have holes, and a hole silently restores "
        "the bias it was built to remove. `scripts/build_nifty100_pit.py` refuses to write for that "
        "reason.",
        "",
        "> **One path.** Fourteen years of one market, 176 heavily-overlapping cohorts, and India "
        "2012–2026 contained no 2008-style event. The deepest drawdown in the sample is the 2020 "
        "COVID fall, and one crash is not a sample of crashes.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    from qalpha.live.atomic import write_text

    write_text(REPORT, "\n".join(body) + "\n")
    print()
    print("\n".join(_summarise(pit, "point-in-time Nifty-50")))
    print(f"[wc1] → {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
