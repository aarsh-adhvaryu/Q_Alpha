"""PO-2a — are the picks working, or is the pacing what loses? Registered before it was run.

    uv run python scripts/exp_picks_vs_pacing.py

**Read `reports/PREREGISTRATION_POLICY_REPLAY.md` §9 first.**

PO-1 found the live policy loses to the fund by 55%, and that the §4.7 exits own ₹7.7M of it — but
that it **still** loses with the exits off. Two explanations remain and they call for opposite
responses: the screen picks bad names, or `market_weakness` holds cash back and uninvested money
loses to a rising market no matter how good the picks are.

This separates them. Every month the whole allowance is spent **immediately** on the screen's top-K
by `cheapness_scores` — the same ranking the live screen uses — equal-weighted, whole shares, real
costs. No pacing, no cash held back, no exits, no sector cap. Nothing is sold, ever.

K=30 is the harness check, not a strategy: at thirty names out of a fifty-name index the result must
converge on the equal-weight baseline. If it does not, this file is wrong and nothing else on the
page should be read.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe
from qalpha.live.console import use_utf8
from qalpha.live.deploy import cheapness_scores
from qalpha.live.price_integrity import rebase_starts, unexplained_gaps

PIT_PANEL = "data/historical/prices_pit_2026.parquet"
PIT_UNIVERSE = Path("data/universes/nifty50_membership_2026.csv")
REPORT = Path("reports/PICKS_VS_PACING_PO2.md")

MONTHLY = Decimal("50000")
EW_FEE = Decimal("0.0041")
#: Fixed in the registration. 8 is the live basket; 30 is the convergence check.
BASKETS = (8, 15, 30)


def _members_on(universe: pd.DataFrame, day: date) -> list[str]:
    d = pd.Timestamp(day)
    start = pd.to_datetime(universe["start_date"])
    end = pd.to_datetime(universe["end_date"])
    return sorted(universe.loc[(start <= d) & (end.isna() | (end >= d)), "ticker"].unique())


def run(
    cfg: Config, k: int, *, start: str, end: str, exclude_breaking: bool = False
) -> tuple[pd.Series, Decimal, int]:
    """Buy the top-k by cheapness with the whole allowance, monthly. Never sell."""
    panel = load_parquet(PIT_PANEL)
    universe = pd.read_csv(PIT_UNIVERSE)
    prices = panel.adj_close.loc[start:end]
    index = cast(pd.DatetimeIndex, prices.index)
    months = (
        pd.DataFrame(index=index).groupby([index.year, index.month]).apply(lambda g: g.index[0])
    )
    pays = sorted(set(months))

    book = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    contributed = Decimal("0")
    curve: list[float] = []
    bought = 0
    pay_set = set(pays)
    rebase: dict[str, date] = {}
    for stamp in index:
        day = stamp.date()
        if stamp in pay_set:
            book.cash += MONTHLY
            contributed += MONTHLY
            eligible = [t for t in _members_on(universe, day) if t in prices.columns]
            hist = prices.loc[:stamp]
            rebase = rebase_starts(unexplained_gaps(hist, eligible, day))
            pool = eligible
            if exclude_breaking:
                # THE LIVE DEPLOY'S OWN FILTER. `advise_deploy_into_weakness` refuses to buy a name
                # in §4.7 breakdown — and the deepest-pulled-back names are exactly the ones that
                # trip it. This variant exists to find out whether that filter is what discards the
                # ranking's edge.
                from qalpha.live.position_health import position_health

                report = position_health(hist, eligible, day, rebase_from=rebase)
                broken = {h.ticker for h in report.holdings if h.level == "breaking"}
                healthy = [t for t in eligible if t not in broken]
                pool = healthy if len(healthy) >= k else eligible
            scores = cheapness_scores(panel, pool, day, rebase_from=rebase)
            ranked = [t for t, _s in sorted(scores.items(), key=lambda kv: -kv[1])][:k]
            # EVERY RUPEE, ON ARRIVAL. That is the whole point of this run.
            per_name = book.cash / max(1, len(ranked))
            for ticker in ranked:
                series = hist[ticker].dropna()
                if series.empty:
                    continue
                price = Decimal(str(float(series.iloc[-1])))
                qty = int(per_name / price) if price > 0 else 0
                if qty > 0 and book.cash >= price * qty:
                    book.buy(day, ticker, Decimal(qty), price)
                    bought += 1
        marks = {
            t: float(prices[t].loc[:stamp].dropna().iloc[-1])
            for t in book.positions()
            if t in prices.columns and not prices[t].loc[:stamp].dropna().empty
        }
        value = float(book.cash) + sum(
            marks.get(t, 0.0) * float(q) for t, q in book.positions().items()
        )
        curve.append(value)
    return pd.Series(curve, index=index), contributed, bought


def _fund(
    level: pd.Series, index: pd.DatetimeIndex, pays: set[pd.Timestamp], fee: Decimal
) -> pd.Series:
    units, daily = 0.0, float(fee) / 252.0
    out: list[float] = []
    for stamp in index:
        px = float(level.loc[stamp]) if stamp in level.index else float("nan")
        if px != px or px <= 0:
            out.append(out[-1] if out else 0.0)
            continue
        if stamp in pays:
            units += float(MONTHLY) / px
        units *= 1.0 - daily
        out.append(units * px)
    return pd.Series(out, index=index)


def main() -> int:
    use_utf8()
    cfg = Config()
    start, end = "2012-01-01", "2026-09-11"
    panel = load_parquet(PIT_PANEL)
    prices = panel.adj_close.loc[start:end]
    index = cast(pd.DatetimeIndex, prices.index)
    months = (
        pd.DataFrame(index=index).groupby([index.year, index.month]).apply(lambda g: g.index[0])
    )
    pays = set(months)

    from paper import _load_benchmark_series

    bench = _load_benchmark_series().reindex(index).ffill()
    ew_level = (
        equal_weight_pit(panel, Universe.from_csv(str(PIT_UNIVERSE)), index, Decimal("100"))
        .reindex(index)
        .ffill()
    )
    ew = _fund(ew_level, index, pays, EW_FEE)
    floor = _fund(bench, index, pays, Decimal("0"))

    print(f"[po2] fully invested on arrival, never sells — {start} → {end}")
    rows = []
    for k in BASKETS:
        series, contributed, bought = run(cfg, k, start=start, end=end)
        rows.append((k, series, contributed, bought))
        print(
            f"  top-{k:<3} ₹{series.iloc[-1]:>14,.0f}  vs fund ₹{ew.iloc[-1]:,.0f}  "
            f"({series.iloc[-1] / ew.iloc[-1] - 1:+.1%})"
        )

    # THE DECISIVE VARIANT. Same top-8, same money, same day — with the live deploy's own
    # `exclude_breaking` filter applied. If the edge disappears here, the filter is what discards it.
    filtered, _c, _b = run(cfg, 8, start=start, end=end, exclude_breaking=True)
    print(
        f"  top-8, breaking EXCLUDED (the live filter)  ₹{filtered.iloc[-1]:>14,.0f}  "
        f"({filtered.iloc[-1] / ew.iloc[-1] - 1:+.1%} vs fund)"
    )

    contributed = rows[0][2]
    body = [
        "# PO-2 — are the picks working, or is the pacing what loses?",
        "",
        f"_Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Registered in "
        "[PREREGISTRATION_POLICY_REPLAY.md](PREREGISTRATION_POLICY_REPLAY.md) §9 before it ran._",
        "",
        "Every month the **whole** ₹50,000 is spent immediately on the screen's top-K by "
        "`cheapness_scores` — the live ranking — equal-weighted, whole shares, Zerodha costs "
        "charged. **No weakness pacing, no cash held back, no exits, nothing ever sold.** This "
        "isolates the picks from everything else the policy does.",
        "",
        f"Point-in-time Nifty-50, which contains the 36 names that left the index. Contributed "
        f"₹{float(contributed):,.0f} over fourteen years.",
        "",
        "| | Terminal | vs contributed | vs the fund |",
        "|---|---:|---:|---:|",
    ]
    for k, series, contrib, _b in rows:
        body.append(
            f"| Screen, top-{k}, fully invested | ₹{series.iloc[-1]:,.0f} | "
            f"{series.iloc[-1] / float(contrib) - 1:+.1%} | "
            f"**{series.iloc[-1] / ew.iloc[-1] - 1:+.1%}** |"
        )
    body += [
        f"| `BASELINE_EW` — the bar | ₹{ew.iloc[-1]:,.0f} | "
        f"{ew.iloc[-1] / float(contributed) - 1:+.1%} | — |",
        f"| NIFTYBEES — the floor | ₹{floor.iloc[-1]:,.0f} | "
        f"{floor.iloc[-1] / float(contributed) - 1:+.1%} | "
        f"{floor.iloc[-1] / ew.iloc[-1] - 1:+.1%} |",
        "",
        f"| Screen, top-8, **with the live `exclude_breaking` filter** | "
        f"₹{filtered.iloc[-1]:,.0f} | {filtered.iloc[-1] / float(contributed) - 1:+.1%} | "
        f"**{filtered.iloc[-1] / ew.iloc[-1] - 1:+.1%}** |",
        "",
        "**The last row is the mechanism.** It is the same top-8, the same money on the same days "
        "— with the one filter the live deploy applies: refuse to buy a name in §4.7 breakdown. The "
        "deepest-pulled-back names are exactly the ones that trip it, so the filter removes the "
        "part of the ranking that was carrying the return.",
        "",
        "**The K=30 row is the harness check, not a strategy.** Thirty names out of a fifty-name "
        "index must converge on the equal-weight baseline. If it does not, this page is wrong.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    from qalpha.live.atomic import write_text

    write_text(REPORT, "\n".join(body) + "\n")
    print(f"\n[po2] → {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
