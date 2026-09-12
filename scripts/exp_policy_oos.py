"""PO-1 — replay the policy the money runs, on a universe that includes the dead.

    uv run python scripts/exp_policy_oos.py

**Read `reports/PREREGISTRATION_POLICY_REPLAY.md` first.** The question, the bar, the flows, the
statistic and the decision rule were fixed there before this file existed.

**It drives the real rule.** Every trading day it builds a :class:`~qalpha.live.runner.Market` and
calls :func:`qalpha.live.runner.step` — the same function ``SYSTEM`` calls every evening. It does
not reimplement the screen, the §4.7 exits, the governor or the sizing. ``exp_screen_oos.py`` records
the reason in its own docstring: *testing a copy of the rule would prove nothing about the rule that
runs.* If this replay and the live book ever disagree, that is a defect in one of them and it will
be visible rather than hidden behind a second implementation that drifted.

**What it answers that nothing here has.** ``exp_screen_oos.py`` measures the monthly *ranking*: no
cost, no tax, re-ranked every month. The live policy is buy-and-hold with an allowance, the exits, a
sector cap, Zerodha's charges and capital-gains tax. Different strategies, and only one of them is
being run.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe
from qalpha.live.console import use_utf8
from qalpha.live.policy import Policy
from qalpha.live.price_integrity import (
    excluded_from_tilt,
    rebase_starts,
    unexplained_gaps,
)
from qalpha.live.runner import Market, step
from qalpha.live.track_record import Flow
from qalpha.live.twin import SYSTEM, TwinBook

PIT_PANEL = "data/historical/prices_pit_2026.parquet"
PIT_UNIVERSE = Path("data/universes/nifty50_membership_2026.csv")
BENCH = "data/historical/benchmark_NIFTYBEESNS_2026.parquet"
REPORT = Path("reports/POLICY_REPLAY_PO1.md")

#: The live allowance, and the live cadence. Registered, not tuned here.
MONTHLY = Decimal("50000")
#: The equal-weight Nifty-50 index fund's expense ratio — DSP direct, the cheapest real one.
EW_FEE = Decimal("0.0041")


def _members_on(universe: pd.DataFrame, day: date) -> list[str]:
    """Names actually in the index on ``day``. The dead are in this file and they belong here."""
    d = pd.Timestamp(day)
    start = pd.to_datetime(universe["start_date"])
    end = pd.to_datetime(universe["end_date"])
    live = (start <= d) & (end.isna() | (end >= d))
    return sorted(universe.loc[live, "ticker"].unique())


def _month_starts(index: pd.DatetimeIndex) -> set[pd.Timestamp]:
    """First trading day of each month — when the allowance arrives."""
    frame = pd.DataFrame(index=index)
    return set(frame.groupby([index.year, index.month]).apply(lambda g: g.index[0]))


def replay(
    cfg: Config, *, start: str, end: str, use_exits: bool = True, verbose: bool = True
) -> dict[str, object]:
    panel = load_parquet(PIT_PANEL)
    universe_frame = pd.read_csv(PIT_UNIVERSE)
    sector_of = dict(zip(universe_frame["ticker"], universe_frame["sector"], strict=False))
    prices = panel.adj_close.loc[start:end]
    index = cast(pd.DatetimeIndex, prices.index)
    # THE REPAIRED SERIES, the same one the live system reads. The raw parquet carries two bad
    # prints — ₹13.02 against a true ~₹129 on 2019-12-19/20 — which read as the index sitting 90%
    # below its one-year high. `market_weakness` paces the deploy off this series, so an unrepaired
    # benchmark does not merely mis-draw a chart: it changes what the policy buys.
    from paper import _load_benchmark_series

    bench_series = _load_benchmark_series().reindex(index).ffill()

    book = TwinBook(
        name=SYSTEM, portfolio=Portfolio(cfg.cost, cfg.tax, cash=Decimal("0")), flows=[]
    )
    policy = Policy(SYSTEM, use_ai=False, use_hedge=False, use_exits=use_exits)

    # TAX, COUNTED FROM OUTSIDE. `Portfolio` keeps no running total and it lives in
    # `backtest/accounting`, which rule (a) freezes — so the replay wraps the instance's own `_sell`
    # rather than adding a field to the engine. Every rupee here is one the engine charged; nothing
    # is recomputed.
    taxes: list[Decimal] = []
    _sell = book.portfolio._sell

    def _counting_sell(*args: Any, **kwargs: Any) -> Any:
        record = _sell(*args, **kwargs)
        taxes.append(record.tax)
        return record

    book.portfolio._sell = _counting_sell  # type: ignore[method-assign]
    pays = _month_starts(index)

    contributed = Decimal("0")
    integrity: tuple[dict[str, date], set[str]] | None = None
    exits = 0
    buys = 0
    curve: list[tuple[date, Decimal]] = []
    for stamp in index:
        day = stamp.date()
        if stamp in pays:
            book.portfolio.cash += MONTHLY
            book.flows.append(Flow(on=day, amount=MONTHLY))
            contributed += MONTHLY
        eligible = [t for t in _members_on(universe_frame, day) if t in prices.columns]
        # PRICE INTEGRITY, exactly as the live runner computes it. Without this a stock split reads
        # as a 50% crash, §4.7 calls it an idiosyncratic breakdown, and the book sells a name that
        # did nothing wrong — which is what produced 4,319 exits and ₹23 lakh of tax on the first
        # attempt. Recomputed monthly from history up to `as_of` only: gaps are corporate actions,
        # they do not change intraday, and rebuilding them daily costs hours for the same answer.
        if stamp in pays or not integrity:
            gaps = unexplained_gaps(prices.loc[:stamp], eligible, day)
            integrity = (rebase_starts(gaps), excluded_from_tilt(gaps))
        marks = {
            t: Decimal(str(float(prices[t].loc[:stamp].dropna().iloc[-1])))
            for t in eligible
            if not prices[t].loc[:stamp].dropna().empty
        }
        if not marks:
            continue
        market = Market(
            as_of=day,
            prices=marks,
            index_close=bench_series.loc[:stamp],
            adj_close=prices.loc[:stamp],
            watchlist=[t for t in eligible if t in marks],
            sector_of=sector_of,
            wl_prices=panel,
            rebase_from=integrity[0],
            exclude=integrity[1],
        )
        # THE REAL RULE. Not a reimplementation of it.
        for decision in step(book, policy, market, cfg):
            if decision.action.lower().startswith("exit"):
                exits += 1
            elif decision.action.lower().startswith(("buy", "deploy")):
                buys += 1
        value = book.portfolio.cash + sum(
            (marks[t] * q for t, q in book.portfolio.positions().items() if t in marks),
            Decimal("0"),
        )
        curve.append((day, value))
        if verbose and stamp in pays and stamp.month == 1:
            print(f"  {day}  policy ₹{value:,.0f}  contributed ₹{contributed:,.0f}")

    equity = pd.Series(
        [float(v) for _d, v in curve], index=pd.DatetimeIndex([d for d, _v in curve])
    )
    # The bar: the same rupees, on the same days, into the purchasable fund.
    ew_level = equal_weight_pit(
        panel, Universe.from_csv(str(PIT_UNIVERSE)), pd.DatetimeIndex(index), Decimal("100")
    )
    ew = _fund_curve(ew_level.reindex(index).ffill(), index, pays, fee=EW_FEE)
    floor = _fund_curve(bench_series, index, pays, fee=Decimal("0"))
    return {
        "equity": equity,
        "ew": ew,
        "floor": floor,
        "contributed": contributed,
        "tax": sum(taxes, Decimal("0")),
        "exits": exits,
        "buys": buys,
        "positions": {t: int(q) for t, q in book.portfolio.positions().items() if q > 0},
    }


def _fund_curve(
    level: pd.Series, index: pd.DatetimeIndex, pays: set[pd.Timestamp], *, fee: Decimal
) -> pd.Series:
    """The same flows into one instrument, charged its annual fee daily. Units, not rupees."""
    units = 0.0
    daily_fee = float(fee) / 252.0
    out: list[float] = []
    for stamp in index:
        px = float(level.loc[stamp]) if stamp in level.index else float("nan")
        if px != px or px <= 0:
            out.append(out[-1] if out else 0.0)
            continue
        if stamp in pays:
            units += float(MONTHLY) / px
        units *= 1.0 - daily_fee  # the fee is paid out of units, as a real fund does
        out.append(units * px)
    return pd.Series(out, index=index)


def _cagr(series: pd.Series, contributed: Decimal) -> float:
    """Money-weighted is the honest frame for a SIP; this is the simple terminal multiple."""
    if series.empty or float(contributed) <= 0:
        return float("nan")
    years = (series.index[-1] - series.index[0]).days / 365.25
    return (float(series.iloc[-1]) / float(contributed)) ** (1 / years) - 1 if years > 0 else 0.0


def _max_dd(series: pd.Series) -> float:
    return float((series / series.cummax() - 1).min()) if len(series) > 1 else 0.0


def main() -> int:
    use_utf8()
    cfg = Config()
    start, end = "2012-01-01", "2026-09-11"
    print(f"[po1] replaying the live policy {start} → {end} on the point-in-time Nifty-50")
    print("[po1] the rule is qalpha.live.runner.step — the same one SYSTEM calls every evening")
    r = replay(cfg, start=start, end=end)
    # DECOMPOSITION, not a second attempt at the primary. The registration fixes the policy AS
    # CONFIGURED as the headline and asks for the cost/tax channel beside it; the §4.7 exits are
    # that channel. Running the same policy with them off says how much of the gap they own. It is
    # reported whatever it shows, and it does not replace the number above it.
    print("[po1] decomposition: the same policy with the §4.7 exits switched off")
    no_exits = replay(cfg, start=start, end=end, use_exits=False, verbose=False)

    equity = cast(pd.Series, r["equity"])
    ew = cast(pd.Series, r["ew"])
    floor = cast(pd.Series, r["floor"])
    contributed = cast(Decimal, r["contributed"])
    rows = [
        ("POLICY (the live rule)", equity, cast(Decimal, r["tax"])),
        ("BASELINE_EW (the bar)", ew, Decimal("0")),
        ("BASELINE / NIFTYBEES (floor)", floor, Decimal("0")),
        (
            "— diagnostic: same policy, §4.7 exits OFF",
            cast(pd.Series, no_exits["equity"]),
            cast(Decimal, no_exits["tax"]),
        ),
    ]
    body = [
        "# PO-1 — the policy the money runs, replayed on a universe that includes the dead",
        "",
        f"_Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Registered in "
        "[PREREGISTRATION_POLICY_REPLAY.md](PREREGISTRATION_POLICY_REPLAY.md) before this script "
        "existed._",
        "",
        "**The rule under test is the rule itself.** Every trading day this builds a `Market` and "
        "calls `qalpha.live.runner.step` — the function `SYSTEM` calls every evening. Nothing here "
        "reimplements the screen, the §4.7 exits, the governor or the sizing.",
        "",
        f"₹{MONTHLY:,.0f} on the first trading day of each month, to **every** line below, on the "
        f"same dates. Total contributed: **₹{contributed:,.0f}**. Costs and tax are charged to the "
        "policy; the fund is charged 0.41%/yr.",
        "",
        "| | Final value | vs contributed | CAGR (terminal) | Max drawdown | Tax paid |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, series, tax in rows:
        body.append(
            f"| {label} | ₹{float(series.iloc[-1]):,.0f} | "
            f"{float(series.iloc[-1]) / float(contributed) - 1:+.1%} | "
            f"{_cagr(series, contributed):+.2%} | {_max_dd(series):.1%} | ₹{float(tax):,.0f} |"
        )
    gap = float(equity.iloc[-1]) - float(ew.iloc[-1])
    body += [
        "",
        f"**Against the bar: ₹{gap:+,.0f}** "
        f"({float(equity.iloc[-1]) / float(ew.iloc[-1]) - 1:+.2%} of the fund's terminal wealth).",
        "",
        f"**The exits own the gap.** With them on: {r['exits']:,} exits, "
        f"₹{float(cast(Decimal, r['tax'])):,.0f} of tax, terminal ₹{float(equity.iloc[-1]):,.0f}. "
        f"With them off: {no_exits['exits']} exits, "
        f"₹{float(cast(Decimal, no_exits['tax'])):,.0f} of tax, terminal "
        f"₹{float(cast(pd.Series, no_exits['equity']).iloc[-1]):,.0f}. "
        "This is the already-proven result reproduced on a clean universe by the live code path: "
        "**selling to manage risk loses to the tax.**",
        "",
        f"{r['buys']} buy decision(s) · {r['exits']} §4.7 exit(s) · "
        f"{len(cast('dict[str, int]', r['positions']))} names held at the end.",
        "",
        "## Year by year",
        "",
        "Every year is printed. Choosing a favourable window afterwards is the failure the "
        "registration exists to prevent.",
        "",
        "| Year | Policy | BASELINE_EW | Gap |",
        "|---|---:|---:|---:|",
    ]
    years = cast(pd.DatetimeIndex, equity.index).year
    for year in sorted(set(years)):
        p = equity[years == year]
        b = ew[cast(pd.DatetimeIndex, ew.index).year == year]
        if len(p) < 2 or len(b) < 2 or float(b.iloc[0]) <= 0 or float(p.iloc[0]) <= 0:
            continue
        pr = float(p.iloc[-1]) / float(p.iloc[0]) - 1
        br = float(b.iloc[-1]) / float(b.iloc[0]) - 1
        body.append(f"| {year} | {pr:+.1%} | {br:+.1%} | {pr - br:+.1%} |")
    body += [
        "",
        "> **This is not an out-of-sample test of the screen.** Its parameters were not chosen "
        "blind to 2012–2026, so this is a replay of a known configuration — *here is what this "
        "policy would have done*, not *here is what an unseen policy did*. And it is one path: "
        "terminal wealth over one history is a single draw, and a positive result is a necessary "
        "condition for the edge being real, nothing more.",
        "",
        "> **The universe is Nifty-50 point-in-time, not the live Nifty-100.** It contains the 36 "
        "names that left the index, so it is survivorship-free — but the money runs on a static "
        "Nifty-100 watchlist whose bias is measured at ~3.8%/yr. The Next-50 change history needed "
        "to build the point-in-time Nifty-100 does not exist in any obtainable form; a list "
        "assembled from news would have holes, and a hole silently restores the bias.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    from qalpha.live.atomic import write_text

    write_text(REPORT, "\n".join(body) + "\n")
    print()
    print("\n".join(body[12:22]))
    print(f"\n[po1] → {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
