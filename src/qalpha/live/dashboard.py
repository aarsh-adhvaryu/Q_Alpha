"""Render the paper-book dashboard — the human/consumer-facing view of what the system is doing.

Produces a committable Markdown report (renders on GitHub) + a CSV of the equity track record, so
anyone can see — without running anything — today's recommendation, current holdings, the equity
curve vs Nifty 50 TRI, realized tax, and any orders awaiting human approval. This is the answer to
"how does a consumer know what it's doing": the system writes its own status, no AI in the loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pandas as pd

from qalpha.data.prices import PriceData
from qalpha.live.go_scorecard import build_scorecard
from qalpha.live.paper import DailyPlan, PaperBook, _prices_on
from qalpha.live.runlog import RunLogEntry, health_markdown


@dataclass(frozen=True)
class PaperFreshness:
    """Is the daily paper-run pipeline actually alive? (So the dashboard shows it, not assumes it.)"""

    last_update: date | None
    weekdays_stale: int  # full weekdays elapsed since the last mark (0 = up to date)
    is_stale: bool
    note: str


def _weekdays_after(a: date, b: date) -> int:
    """Count weekdays strictly after ``a`` up to and including ``b`` (0 if b <= a)."""
    n, d = 0, a + timedelta(days=1)
    while d <= b:
        if d.weekday() < 5:  # Mon-Fri
            n += 1
        d += timedelta(days=1)
    return n


def paper_freshness(book: PaperBook, today: date) -> PaperFreshness:
    """Freshness of the committed paper book vs the weekday cron meant to update it.

    The pipeline runs weekdays, so one elapsed weekday (today's mark may not have run yet) is OK;
    **two or more** means it missed a day → stale. Surfaced in the dashboard so the daily run is
    *seen* working, not trusted blindly.
    """
    curve = book.equity_curve
    if not curve:
        return PaperFreshness(None, 0, True, "No marks yet — the daily pipeline hasn't run.")
    last = date.fromisoformat(str(curve[-1]["date"]))
    stale_days = max(0, _weekdays_after(last, today) - 1)  # 1 weekday grace (today not yet marked)
    is_stale = stale_days >= 1
    if is_stale:
        note = f"⚠️ Stale — last marked {last}, {stale_days} weekday(s) missed. Check the cron."
    else:
        note = f"✓ Up to date — last marked {last}."
    return PaperFreshness(last, stale_days, is_stale, note)


def systemic_risk_markdown(index_close: pd.Series, as_of: date) -> str:
    """Read-only 'systemic risk' watch panel — informational only, the system takes no action.

    Reports the product-side :func:`~qalpha.live.deploy.market_weakness` reading (Nifty drawdown from
    its rolling 1-year high) as a normal/elevated/deep risk gauge, and — when elevated — notes that
    the research-validated **tax-free short-futures hedge overlay** would suggest *considering* a
    hedge. This is the lightweight product signal; the richer cross-asset fragility gauge lives in
    the research repo. Nothing here trades, sells, or hedges — it is a dashboard advisory, like the
    paper book is a notional record.
    """
    from qalpha.live.deploy import market_weakness  # local import: avoids a package import cycle

    w = market_weakness(index_close, as_of)
    badge = {"normal": "🟢 NORMAL", "elevated": "🟠 ELEVATED", "deep": "🔴 DEEP STRESS"}[w.level]
    lines = [
        "## 🛡 Systemic-risk watch (read-only)",
        "",
        f"**{badge}** — Nifty is **{w.drawdown * 100:+.1f}%** from its 1-year high (as of {as_of}).",
        "",
    ]
    if w.level == "normal":
        lines.append(
            "- No elevated systemic stress on this signal. No hedge indicated. Keep investing "
            "steadily; route fresh capital tax-free as usual."
        )
    else:
        lines.append(
            "- **Stress elevated.** The research-validated tax-free **short index-futures hedge** "
            "(keep the shares, nullify the exposure — proven to cut COVID drawdown −25→−10% on the "
            "book) would suggest *considering* a hedge here."
        )
        lines.append(
            "- This is **informational only** — the product places no derivatives trade. Executing a "
            "futures hedge is a separate, manually-operated decision (F&O account + real-cost review)."
        )
    lines += [
        "",
        "_Lightweight product signal (index drawdown). The richer cross-asset fragility gauge "
        "(vol·credit·FX·correlation) lives in the research repo. This panel never trades._",
    ]
    return "\n".join(lines)


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


def go_readiness_markdown(book: PaperBook, benchmark: pd.Series, as_of: date) -> str:
    """The deterministic GO scorecard for the forward paper run, as dashboard markdown.

    A real multi-criterion verdict (not a countdown): it flips to GO the moment the evidence clears —
    earlier than the 6-month target if it does, NO-GO if the strategy misbehaves live. See
    :mod:`qalpha.live.go_scorecard`.
    """
    return build_scorecard(book.equity_curve, benchmark, as_of).render()


def render_markdown(
    book: PaperBook,
    prices: PriceData,
    benchmark: pd.Series,
    plan: DailyPlan,
    as_of: date,
    run_log: list[RunLogEntry] | None = None,
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

    lines.append("## GO readiness (criterion 6)")
    lines.append("")
    lines.append(go_readiness_markdown(book, benchmark, as_of))
    lines.append("")
    if run_log is not None:
        lines.append(health_markdown(run_log))
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
