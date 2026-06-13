"""Render the paper-book dashboard — the human/consumer-facing view of what the system is doing.

Produces a committable Markdown report (renders on GitHub) + a CSV of the equity track record, so
anyone can see — without running anything — today's recommendation, current holdings, the equity
curve vs Nifty 50 TRI, realized tax, and any orders awaiting human approval. This is the answer to
"how does a consumer know what it's doing": the system writes its own status, no AI in the loop.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd

from qalpha.data.prices import PriceData
from qalpha.live.paper import DailyPlan, PaperBook, _prices_on


def _benchmark_return_pct(benchmark: pd.Series, start: date, as_of: date) -> float | None:
    idx = pd.DatetimeIndex(benchmark.index)
    window = benchmark[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(as_of))]
    if len(window) < 2:
        return None
    first, last = float(window.iloc[0]), float(window.iloc[-1])
    return (last - first) / first * 100.0 if first > 0 else None


def _sparkline(values: list[float]) -> str:
    if len(values) < 2:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    return "".join(blocks[min(7, int((v - lo) / span * 7))] for v in values)


def render_markdown(
    book: PaperBook,
    prices: PriceData,
    benchmark: pd.Series,
    plan: DailyPlan,
    as_of: date,
) -> str:
    prices_dec = _prices_on(prices, as_of)
    equity = book.portfolio.market_value(prices_dec)
    ret = book.total_return_pct(prices, as_of)
    bench = _benchmark_return_pct(benchmark, book.start_date, as_of)
    bench_str = f"{bench:+.2f}%" if bench is not None else "—"
    days = (as_of - book.start_date).days
    weights = book.portfolio.current_weights(prices_dec)

    lines: list[str] = []
    lines.append("# Q-Alpha — Paper-Trading Dashboard")
    lines.append("")
    lines.append(
        f"_Notional paper trading (no real money) of the validated tax-aware strategy. "
        f"As of **{as_of}** · generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}._"
    )
    lines.append("")
    lines.append("## At a glance")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Started | {book.start_date} ({days} days) |")
    lines.append(f"| Notional capital | ₹{book.starting_capital:,.0f} |")
    lines.append(f"| Equity (marked) | ₹{equity:,.0f} |")
    lines.append(f"| Return since start | **{ret:+.2f}%** |")
    lines.append(f"| Nifty 50 TRI (same window) | {bench_str} |")
    lines.append(f"| Cash | ₹{book.portfolio.cash:,.0f} |")
    lines.append(f"| Realized tax to date | ₹{book.realized_tax():,.2f} |")
    lines.append(f"| Rebalances | {len(book.history)} |")
    lines.append(f"| Strategy | shrink-weighted, annual, tax-aware (band {book.params.band}) |")
    lines.append("")

    lines.append("## Today's recommendation")
    lines.append("")
    if plan.has_orders:
        lines.append(f"⚠️ **ACTION NEEDED — {plan.decision.reason}**")
        lines.append("")
        lines.append("| Side | Ticker | Qty | Price |")
        lines.append("|---|---|---|---|")
        for o in plan.proposed_orders:
            lines.append(f"| {o.side.name} | {o.ticker} | {o.quantity} | ₹{o.price} |")
        lines.append("")
        lines.append("_Approve with:_ `uv run python scripts/paper.py apply`")
    else:
        lines.append(f"✅ **HOLD** — {plan.decision.reason}. No orders today.")
    lines.append("")

    lines.append("## Holdings")
    lines.append("")
    if weights:
        lines.append("| Ticker | Qty | Price | Value | Weight |")
        lines.append("|---|---|---|---|---|")
        for t, q in sorted(book.portfolio.positions().items()):
            px = prices_dec.get(t, Decimal("0"))
            val = q * px
            lines.append(f"| {t} | {q} | ₹{px} | ₹{val:,.0f} | {weights.get(t, 0.0) * 100:.1f}% |")
    else:
        lines.append("_No holdings yet._")
    lines.append("")

    curve = book.equity_curve
    lines.append("## Equity track record")
    lines.append("")
    if len(curve) >= 2:
        spark = _sparkline([float(p["equity"]) for p in curve])
        lines.append(f"`{spark}`  ({len(curve)} daily marks; full series in `paper_equity.csv`)")
        lines.append("")
        lines.append("| Date | Equity | Return |")
        lines.append("|---|---|---|")
        for p in curve[-10:]:
            eq = Decimal(p["equity"])
            r = float((eq - book.starting_capital) / book.starting_capital) * 100
            lines.append(f"| {p['date']} | ₹{eq:,.0f} | {r:+.2f}% |")
    else:
        lines.append("_Track record begins — one daily mark recorded so far._")
    lines.append("")
    lines.append("---")
    lines.append(
        "_The decision engine is the same code validated in the backtest "
        "([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the "
        "pipeline, not by hand._"
    )
    return "\n".join(lines) + "\n"


def equity_csv(book: PaperBook) -> str:
    """The equity track record as CSV (durable, plottable)."""
    rows = ["date,equity,cash,return_pct"]
    for p in book.equity_curve:
        eq = Decimal(p["equity"])
        r = (
            float((eq - book.starting_capital) / book.starting_capital) * 100
            if book.starting_capital > 0
            else 0.0
        )
        rows.append(f"{p['date']},{eq},{p['cash']},{r:.4f}")
    return "\n".join(rows) + "\n"
