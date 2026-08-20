"""Backtest the deploy-into-weakness screen as an actual SIP — the test it never had.

**Why this exists.** The screen that picks names for the Add-money advisor has never been measured
against anything. Every other guard in this repo (continuity, breakdown filter, sector cap,
stickiness) improves its *coherence*; none of them establishes that it makes money, or that it beats
simply buying the index with the same cash on the same days. This script asks that question directly,
on the user's real plan: a lump sum followed by a monthly SIP.

**Two universes, deliberately.**

* ``pit`` — point-in-time Nifty-50 membership. 36 of the 87 names in that file *left* the index, and
  they stay in the simulation for exactly as long as they were members. This is the honest test.
* ``watchlist`` — today's Nifty-100 list, held fixed across 14 years. This is **survivorship-biased
  by construction**: every name in it is one that survived to 2026. It is run only to size that bias,
  and its number must never be quoted as a result.

**Baseline.** The same rupees on the same dates into NIFTYBEES. This is the comparison that matters:
if the screen cannot beat it, the honest recommendation is an index fund.

No look-ahead: every decision uses the same ``advise_deploy_into_weakness`` the live app calls, which
slices prices at ``as_of``. Costs and taxes come from the same validated engine.

    uv run python scripts/backtest_sip.py [--start 2013-07-01] [--lump 100000] [--sip 50000]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.backtest.portfolio import Portfolio, to_decimal_price
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.deploy import advise_deploy_into_weakness
from qalpha.live.position_health import position_health
from qalpha.live.price_integrity import repair_price_spikes

WATCHLIST_PRICES = Path("data/historical/prices_watchlist.parquet")
WATCHLIST_CSV = Path("data/universes/nifty100_watchlist.csv")
PIT_PRICES = Path("data/historical/prices_pit_2026.parquet")
PIT_CSV = Path("data/universes/nifty50_membership_2026.csv")
BENCHMARK = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")
NIFBEES = "NIFTYBEES.NS"


@dataclass
class Result:
    """One simulated plan: what it ended up worth, and how it behaved getting there."""

    label: str
    contributed: Decimal = Decimal("0")
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    names_held: int = 0
    trades: int = 0
    costs: Decimal = Decimal("0")
    tax_paid: Decimal = Decimal("0")  # real capital-gains tax — the price of every optimiser sell

    @property
    def final(self) -> float:
        return float(self.equity_curve.iloc[-1]) if len(self.equity_curve) else 0.0

    @property
    def profit(self) -> float:
        return self.final - float(self.contributed)

    @property
    def total_return_pct(self) -> float:
        c = float(self.contributed)
        return (self.final - c) / c * 100 if c else 0.0

    def max_drawdown_pct(self) -> float:
        """Worst peak-to-trough fall of the *invested* book.

        Contributions are stripped first: a series that grows partly because money was added would
        otherwise understate every drawdown, and the point here is how bad it felt to hold.
        """
        if len(self.equity_curve) < 2:
            return 0.0
        curve = self.equity_curve
        peak = curve.cummax()
        return float(((curve - peak) / peak).min() * 100)


def _month_starts(dates: list[date], start: date, end: date) -> list[date]:
    """First available trading day of each month in range — the SIP schedule."""
    out: list[date] = []
    seen: set[tuple[int, int]] = set()
    for d in dates:
        if d < start or d > end:
            continue
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _mark(holdings: dict[str, int], adj: pd.DataFrame, upto: pd.Timestamp) -> pd.Series:
    """Daily mark-to-market of a fixed holdings vector, forward-filled and causal."""
    cols = [t for t in holdings if t in adj.columns]
    if not cols:
        return pd.Series(dtype=float)
    sub = adj.loc[:upto, cols].ffill()
    qty = pd.Series({t: float(holdings[t]) for t in cols})
    return (sub * qty).sum(axis=1)


def run_screen(
    prices: PriceData,
    sector_of: dict[str, str],
    universe_on,  # callable(date) -> list[str]
    index_close: pd.Series,
    schedule: list[date],
    *,
    lump: Decimal,
    sip: Decimal,
    max_names: int,
    label: str,
    maintain: str = "none",
) -> Result:
    """Simulate the plan through the live advisor, one deploy per month.

    ``maintain`` decides whether anything is ever *sold* — the question of whether an optimizer
    earns its keep on a real, taxable account:

    * ``"none"``   — buy and hold. New money is the only lever. (What the live advisor does today.)
    * ``"prune"``  — each month, sell any holding the §4.7 test now calls broken and recycle the
      proceeds into the next deploy. This is "optimise on the falls" in its most direct form.
    * ``"annual"`` — once a year, trim back toward equal weight across the current roster.

    Both selling modes run through the same validated FIFO/cost/tax engine, so the capital-gains bill
    is real and lands where it actually would: STCG at 20% inside a year, LTCG at 12.5% after.
    """
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    res = Result(label=label)
    curve_parts: list[pd.Series] = []
    adj = prices.adj_close

    for i, d in enumerate(schedule):
        amount = lump if i == 0 else sip
        pf.cash += amount
        res.contributed += amount
        names = [t for t in universe_on(d) if t in adj.columns]
        if len(names) < 3:
            continue
        advice = advise_deploy_into_weakness(
            pf, amount, names, sector_of, prices, index_close, d, max_names=max_names
        )
        for o in advice.deploy.buy_orders:
            rec = pf.buy(d, o.ticker, Decimal(int(o.quantity)), Decimal(str(o.price)))
            if rec is not None:
                res.trades += 1
                res.costs += rec.cost

        # --- maintenance: the only place this simulation ever sells -------------------------------
        if maintain != "none":
            live = sorted(t for t, q in pf.positions().items() if q > 0)
            px = {
                t: to_decimal_price(float(adj[t].loc[: pd.Timestamp(d)].dropna().iloc[-1]))
                for t in live
                if t in adj.columns and not adj[t].loc[: pd.Timestamp(d)].dropna().empty
            }
            to_sell: dict[str, Decimal] = {}
            if maintain == "prune":
                report = position_health(adj, live, d)
                to_sell = {
                    h.ticker: pf.positions()[h.ticker]
                    for h in report.holdings
                    if h.level == "breaking" and h.ticker in px
                }
            elif maintain == "annual" and d.month == 1 and live:
                value = sum(px[t] * pf.positions()[t] for t in live if t in px)
                fair = value / len(live) if live else Decimal("0")
                for t in live:
                    if t not in px:
                        continue
                    excess = px[t] * pf.positions()[t] - fair
                    trim = int(excess / px[t]) if excess > 0 else 0
                    if trim > 0:
                        to_sell[t] = Decimal(trim)
            for t, qty in to_sell.items():
                rec = pf.sell(d, t, qty, px[t])
                res.trades += 1
                res.costs += rec.cost
                res.tax_paid += rec.tax

        held = {t: int(q) for t, q in pf.positions().items() if q > 0}
        end = pd.Timestamp(schedule[i + 1]) if i + 1 < len(schedule) else adj.index[-1]
        seg = _mark(held, adj.loc[pd.Timestamp(d) : end], pd.Timestamp(end))
        if len(seg):
            curve_parts.append(seg.iloc[:-1] if i + 1 < len(schedule) else seg)

    res.names_held = len([t for t, q in pf.positions().items() if q > 0])
    res.equity_curve = pd.concat(curve_parts) if curve_parts else pd.Series(dtype=float)
    return res


def run_index(
    bench: pd.Series, schedule: list[date], *, lump: Decimal, sip: Decimal, label: str
) -> Result:
    """The do-nothing comparison: identical rupees, identical dates, all into NIFTYBEES."""
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    res = Result(label=label)
    units = 0
    curve_parts: list[pd.Series] = []

    for i, d in enumerate(schedule):
        amount = lump if i == 0 else sip
        pf.cash += amount
        res.contributed += amount
        hist = bench.loc[: pd.Timestamp(d)].dropna()
        if hist.empty:
            continue
        px = Decimal(str(float(hist.iloc[-1])))
        qty = int(pf.cash / px)
        if qty > 0:
            rec = pf.buy(d, NIFBEES, Decimal(qty), px)
            if rec is not None:
                units += qty
                res.trades += 1
                res.costs += rec.cost
        end = pd.Timestamp(schedule[i + 1]) if i + 1 < len(schedule) else bench.index[-1]
        seg = bench.loc[pd.Timestamp(d) : end].ffill() * units
        if len(seg):
            curve_parts.append(seg.iloc[:-1] if i + 1 < len(schedule) else seg)

    res.names_held = 1
    res.equity_curve = pd.concat(curve_parts) if curve_parts else pd.Series(dtype=float)
    return res


def _report(results: list[Result]) -> str:
    rows = [
        "| Plan | Put in | Ended at | Return | Worst fall | Names | Trades | Costs | CG tax |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        rows.append(
            f"| {r.label} | ₹{float(r.contributed):,.0f} | ₹{r.final:,.0f} | "
            f"{r.total_return_pct:+.1f}% | {r.max_drawdown_pct():.1f}% | "
            f"{r.names_held} | {r.trades} | ₹{float(r.costs):,.0f} | ₹{float(r.tax_paid):,.0f} |"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2013-07-01")
    ap.add_argument("--lump", type=int, default=100_000)
    ap.add_argument("--sip", type=int, default=50_000)
    ap.add_argument("--names", type=int, default=8)
    args = ap.parse_args(argv)

    start = date.fromisoformat(args.start)
    lump, sip = Decimal(args.lump), Decimal(args.sip)

    bench_df = pd.read_parquet(BENCHMARK)
    bench = pd.Series(
        bench_df["adj_close"].to_numpy(), index=pd.DatetimeIndex(bench_df["date"])
    ).sort_index()
    # The benchmark carries two corrupt prints (₹13.02 against a true ~₹129 on 2019-12-19/20). Left
    # in, they hand the baseline a fake −90% drawdown and tell market_weakness the index is 90% off
    # its high — a full-wallet "deep" deploy on a typo.
    bench, repaired = repair_price_spikes(bench)
    if repaired:
        print(f"[backtest] repaired {len(repaired)} corrupt benchmark print(s): {repaired}")

    results: list[Result] = []

    # 1. Honest test — point-in-time Nifty-50 membership, survivorship included.
    pit = load_parquet(str(PIT_PRICES))
    universe = Universe.from_csv(str(PIT_CSV))
    pit_sectors = {
        str(r.ticker): str(r.sector) for r in pd.read_csv(PIT_CSV).itertuples() if r.ticker
    }
    wl_peek = load_parquet(str(WATCHLIST_PRICES))
    # One schedule for every plan. The panels end on different days, and a plan that gets an extra
    # month of contributions is not comparable to one that does not — identical cash flows on
    # identical dates is the whole basis of the comparison.
    dates = [d.date() for d in pit.dates]
    end = min(dates[-1], [d.date() for d in wl_peek.dates][-1])
    schedule = _month_starts(dates, start, end)
    print(f"[backtest] {len(schedule)} monthly deploys, {schedule[0]} → {schedule[-1]}")

    results.append(run_index(bench, schedule, lump=lump, sip=sip, label="NIFTYBEES (do nothing)"))
    results.append(
        run_screen(
            pit,
            pit_sectors,
            universe.members_on,
            bench,
            schedule,
            lump=lump,
            sip=sip,
            max_names=args.names,
            label="Screen — PIT Nifty-50 (honest)",
        )
    )

    # 2. Biased contrast — today's Nifty-100, held fixed. Sizes the survivorship effect only.
    wl = wl_peek
    wl_df = pd.read_csv(WATCHLIST_CSV)
    wl_sectors = {str(t): str(s) for t, s in zip(wl_df["ticker"], wl_df["sector"], strict=True)}
    wl_names = [str(t) for t in wl_df["ticker"]]
    wl_schedule = _month_starts([d.date() for d in wl.dates], start, end)
    results.append(
        run_screen(
            wl,
            wl_sectors,
            lambda _d: wl_names,
            bench,
            wl_schedule,
            lump=lump,
            sip=sip,
            max_names=args.names,
            label="Screen — today's Nifty-100 (SURVIVORSHIP-BIASED)",
        )
    )

    print()
    print(_report(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
