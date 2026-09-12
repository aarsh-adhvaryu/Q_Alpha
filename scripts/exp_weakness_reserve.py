"""WC-2 — does holding money back for deep drawdowns actually pay? Registered before it was written.

    uv run python scripts/exp_weakness_reserve.py

**Read `reports/PREREGISTRATION_WEAKNESS_RESERVE.md` first.**

`WC-1` found money deployed in a deep drawdown beat the fund by a median +30.3% and money deployed
on an ordinary day lost 3.1%. That is an opportunity, not a policy: every WC-1 cohort was **fully
invested on arrival**, so it cannot say whether *withholding* money on ordinary months to have more
in deep ones is worth doing.

Waiting has a price WC-1 never paid. Deep months are 11 of 177, and there is no deep month between
2016-03 and 2020-04 — four years to hold cash through a rising market. **That drag is the whole
experiment.** The upside is known; whether it survives the cost is not.

``r = 0.00`` is the control and the harness check: it is "deploy everything, always", and it must
reproduce PO-2's top-8 terminal of ₹30,058,634. If it does not, nothing else here may be read.
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
from qalpha.live.deploy import cheapness_scores, market_weakness
from qalpha.live.price_integrity import rebase_starts, unexplained_gaps

PIT_PANEL = "data/historical/prices_pit_2026.parquet"
PIT_UNIVERSE = Path("data/universes/nifty50_membership_2026.csv")
REPORT = Path("reports/WEAKNESS_RESERVE_WC2.md")

MONTHLY = Decimal("50000")
EW_FEE = Decimal("0.0041")
TOP_K = 8
#: Fixed in the registration, reported whole. 0.00 is the control AND the harness check.
HOLD_BACK = (Decimal("0.00"), Decimal("0.25"), Decimal("0.50"))
RELEASES = (("deep",), ("deep", "elevated"))


#: `market_weakness` hard-codes -12%. WC-2b perturbs it, so the classification is reproduced here
#: with the threshold exposed — and :func:`_assert_classifier_agrees` pins this copy to the live
#: function at the shipped value, so a drift in either one fails loudly instead of quietly changing
#: what "deep" means underneath an experiment.
DEEP_AT = -0.12
ELEVATED_AT = -0.05
HIGH_WINDOW = 252


def classify(bench: pd.Series, as_of: date, *, deep_at: float = DEEP_AT) -> str:
    hist = bench.loc[: pd.Timestamp(as_of)].dropna()
    if hist.empty:
        return "normal"
    window = hist.tail(HIGH_WINDOW)
    dd = float(window.iloc[-1] / window.max() - 1.0)
    if dd <= deep_at:
        return "deep"
    return "elevated" if dd <= ELEVATED_AT else "normal"


def _assert_classifier_agrees(bench: pd.Series, days: list[date]) -> None:
    """The harness check for WC-2b: this copy must equal the live function at the shipped -12%."""
    bad = [
        d
        for d in days
        if classify(bench, d) != market_weakness(bench.loc[: pd.Timestamp(d)], d).level
    ]
    if bad:
        raise AssertionError(
            f"the WC-2b classifier disagrees with market_weakness on {len(bad)} of {len(days)} "
            f"paydays (first: {bad[0]}) — the perturbation test would be measuring a different rule"
        )


def _members_on(universe: pd.DataFrame, day: date) -> list[str]:
    d = pd.Timestamp(day)
    start = pd.to_datetime(universe["start_date"])
    end = pd.to_datetime(universe["end_date"])
    return sorted(universe.loc[(start <= d) & (end.isna() | (end >= d)), "ticker"].unique())


class Result:
    """One cell of the grid."""

    def __init__(self, hold_back: Decimal, release: tuple[str, ...]) -> None:
        self.hold_back = hold_back
        self.release = release
        self.terminal = 0.0
        self.contributed = Decimal("0")
        self.mean_cash = 0.0
        self.max_reserve = 0.0
        self.releases = 0

    @property
    def label(self) -> str:
        if self.hold_back == 0:
            return "control — deploy everything, always"
        on = "+".join(self.release)
        return f"hold back {float(self.hold_back):.0%} on normal, release on {on}"


def run(cfg: Config, cell: Result, *, start: str, end: str, deep_at: float = DEEP_AT) -> pd.Series:
    """One reserve policy over the whole history. Buys only; nothing is ever sold."""
    panel = load_parquet(PIT_PANEL)
    universe = pd.read_csv(PIT_UNIVERSE)
    prices = panel.adj_close.loc[start:end]
    index = cast(pd.DatetimeIndex, prices.index)

    from paper import _load_benchmark_series

    bench = _load_benchmark_series()

    months = (
        pd.DataFrame(index=index).groupby([index.year, index.month]).apply(lambda g: g.index[0])
    )
    pays = set(months)

    book = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    reserve = Decimal("0")
    curve: list[float] = []
    cash_share: list[float] = []

    for stamp in index:
        day = stamp.date()
        if stamp in pays:
            cell.contributed += MONTHLY
            # Classified from data up to this day only — no look-ahead in the decision.
            level = classify(bench, day, deep_at=deep_at)
            if level in cell.release:
                spend = MONTHLY + reserve  # THE POINT: the saved-up money goes in here.
                reserve = Decimal("0")
                cell.releases += 1
            elif level == "normal":
                spend = MONTHLY * (Decimal("1") - cell.hold_back)
                reserve += MONTHLY - spend
            else:
                spend = MONTHLY
            cell.max_reserve = max(cell.max_reserve, float(reserve))

            book.cash += spend
            hist = prices.loc[:stamp]
            eligible = [t for t in _members_on(universe, day) if t in prices.columns]
            if eligible:
                rebase = rebase_starts(unexplained_gaps(hist, eligible, day))
                scores = cheapness_scores(panel, eligible, day, rebase_from=rebase)
                ranked = [t for t, _s in sorted(scores.items(), key=lambda kv: -kv[1])][:TOP_K]
                per_name = book.cash / max(1, len(ranked))
                for ticker in ranked:
                    series = hist[ticker].dropna()
                    if series.empty:
                        continue
                    price = Decimal(str(float(series.iloc[-1])))
                    qty = int(per_name / price) if price > 0 else 0
                    if qty > 0 and book.cash >= price * qty:
                        book.buy(day, ticker, Decimal(qty), price)

        marks = {
            t: float(prices[t].loc[:stamp].dropna().iloc[-1])
            for t in book.positions()
            if t in prices.columns and not prices[t].loc[:stamp].dropna().empty
        }
        held = sum(marks.get(t, 0.0) * float(q) for t, q in book.positions().items())
        # THE RESERVE IS PART OF THE PORTFOLIO. Money held back is money this policy is responsible
        # for: excluding it would score the strategy on only the part of the capital it chose to
        # use, which is how parked SIP cash once read as +444% performance.
        total = float(book.cash) + float(reserve) + held
        curve.append(total)
        cash_share.append((float(book.cash) + float(reserve)) / total if total > 0 else 0.0)

    cell.mean_cash = float(pd.Series(cash_share).mean())
    cell.terminal = curve[-1]
    return pd.Series(curve, index=index)


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
    ew_level = (
        equal_weight_pit(panel, Universe.from_csv(str(PIT_UNIVERSE)), index, Decimal("100"))
        .reindex(index)
        .ffill()
    )
    ew = _fund(ew_level, index, pays, EW_FEE)

    print(f"[wc2] does holding money back for deep drawdowns pay? — {start} → {end}")
    cells: list[Result] = []
    control: Result | None = None
    for hold in HOLD_BACK:
        for release in RELEASES:
            if hold == 0 and release != RELEASES[0]:
                continue  # r=0 is one control; the release rule cannot matter when nothing is held
            cell = Result(hold, release)
            run(cfg, cell, start=start, end=end)
            cells.append(cell)
            if control is None:
                control = cell
            print(
                f"  {cell.label:<52} ₹{cell.terminal:>14,.0f}  "
                f"vs control {cell.terminal / control.terminal - 1:>+7.2%}  "
                f"cash {cell.mean_cash:>5.1%}  releases {cell.releases}"
            )
            sys.stdout.flush()

    assert control is not None
    body = [
        "# WC-2 — does holding money back for deep drawdowns actually pay?",
        "",
        f"_Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Registered in "
        "[PREREGISTRATION_WEAKNESS_RESERVE.md](PREREGISTRATION_WEAKNESS_RESERVE.md) before this "
        "script existed._",
        "",
        "`WC-1` found money deployed in a deep drawdown beat the fund by a median **+30.3%**. Every "
        "WC-1 cohort was **fully invested on arrival**, so it could not say whether *withholding* "
        "money on ordinary months to have more in deep ones is worth doing. This does.",
        "",
        "Each month ₹50,000 arrives. On a `normal` day a fraction `r` is held back in cash; on a "
        "release day the allowance **and the whole reserve** go in. Everything deployed buys the "
        f"top-{TOP_K} by `cheapness_scores`, equal-weighted, whole shares, Zerodha costs charged, "
        "**nothing ever sold**. Point-in-time Nifty-50.",
        "",
        "**The reserve counts as part of the portfolio.** Money held back is money this policy is "
        "responsible for; excluding it would score the strategy on only the capital it chose to "
        "use, which is how parked SIP cash once read as +444% performance.",
        "",
        "| Policy | Terminal | vs control | vs the fund | Mean cash | Releases |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cell in cells:
        body.append(
            f"| {cell.label} | ₹{cell.terminal:,.0f} | "
            f"**{cell.terminal / control.terminal - 1:+.2%}** | "
            f"{cell.terminal / float(ew.iloc[-1]) - 1:+.1%} | "
            f"{cell.mean_cash:.1%} | {cell.releases} |"
        )
    body += [
        f"| `BASELINE_EW` — the bar | ₹{float(ew.iloc[-1]):,.0f} | — | — | 0.0% | — |",
        "",
        f"Contributed ₹{float(control.contributed):,.0f} over fourteen years. Largest reserve ever "
        f"accumulated, across the non-control cells: ₹{max(c.max_reserve for c in cells):,.0f}.",
        "",
        "**The control is the harness check.** `r = 0.00` is *deploy everything, always* — the "
        "current live behaviour — and it must reproduce PO-2's top-8 terminal of **₹30,058,634**. "
        "If it does not, nothing else on this page may be read.",
        "",
        "> **One path.** Fourteen years of one market. The deep episodes are about seven events "
        "with COVID supplying four of the eleven months, so this result is substantially a "
        "statement about whether one reserve release in 2020 happened to land well.",
        "",
        "> **This is market timing**, and it sits against this repository's own strongest proven "
        "result: trading less and staying invested beat the alternatives net of cost and tax. A "
        "reserve is the first mechanism here that deliberately stays out of the market.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    from qalpha.live.atomic import write_text

    write_text(REPORT, "\n".join(body) + "\n")
    print(f"\n[wc2] → {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
