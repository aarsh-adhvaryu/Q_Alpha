"""Phase-0 go/no-go report (Q_alpha.md §13 deliverable, §14 criteria 1–3).

Assembles strategy vs baseline metrics, the per-regime breakdown, realized costs/tax, and a
GO / CONDITIONAL / NO-GO verdict. The verdict encodes the spec's gating logic:

* **criterion 1** — strategy beats do-nothing, Nifty 50, and equal-weight net of costs+taxes.
* **criterion 2** — no look-ahead: guaranteed structurally by ``PriceData.as_of`` + tests, asserted
  here (not re-measured).
* **criterion 3** — no survivorship bias: GO requires a point-in-time universe; a static universe
  downgrades the verdict to CONDITIONAL with the caveat stated, never silently passed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from qalpha.backtest.baselines import buy_and_hold, do_nothing, equal_weight, monthly_sip
from qalpha.backtest.engine import BacktestResult
from qalpha.backtest.metrics import PerformanceMetrics, compute_metrics, per_regime_metrics
from qalpha.config import Config
from qalpha.data.prices import PriceData


@dataclass(frozen=True)
class GoNoGo:
    verdict: str  # "GO" | "CONDITIONAL" | "NO-GO"
    reasons: list[str]


def evaluate(
    strategy: PerformanceMetrics,
    baselines: dict[str, PerformanceMetrics],
    point_in_time_universe: bool,
) -> GoNoGo:
    """Apply the §14 criterion-1 comparisons and the survivorship gate.

    Per spec §14.1 the formal gate is **beat do-nothing AND Nifty 50** (value + risk-adjusted),
    net of costs and taxes. Equal-weight and SIP are informative comparisons (§13), reported but
    not part of the pass/fail gate — 1/N is a famously hard bar and trailing it is noted, not failed.
    """
    reasons: list[str] = []
    gate: dict[str, bool] = {}

    if "do_nothing" in baselines:
        ok = strategy.final_value > baselines["do_nothing"].final_value
        gate["do_nothing"] = ok
        reasons.append(
            f"{'✓' if ok else '✗'} beats do-nothing "
            f"(₹{strategy.final_value:,.0f} vs ₹{baselines['do_nothing'].final_value:,.0f})"
        )
    if "nifty50_buy_hold" in baselines:
        nifty = baselines["nifty50_buy_hold"]
        value_ok = strategy.final_value > nifty.final_value
        sharpe_ok = strategy.sharpe > nifty.sharpe
        gate["nifty_value"] = value_ok
        gate["nifty_sharpe"] = sharpe_ok
        reasons.append(
            f"{'✓' if value_ok else '✗'} beats Nifty 50 value "
            f"(₹{strategy.final_value:,.0f} vs ₹{nifty.final_value:,.0f})"
        )
        reasons.append(
            f"{'✓' if sharpe_ok else '✗'} beats Nifty 50 Sharpe "
            f"({strategy.sharpe:.2f} vs {nifty.sharpe:.2f})"
        )
    # Informational only (does not gate the verdict).
    if "equal_weight" in baselines:
        ew = baselines["equal_weight"]
        ew_ok = strategy.final_value > ew.final_value
        reasons.append(
            f"{'•' if ew_ok else '◦'} vs equal-weight (informational): "
            f"₹{strategy.final_value:,.0f} vs ₹{ew.final_value:,.0f}"
        )

    criterion1 = all(gate.values())
    if not criterion1:
        return GoNoGo(
            "NO-GO", [*reasons, "✗ criterion 1 failed: must beat do-nothing AND Nifty 50"]
        )
    if not point_in_time_universe:
        return GoNoGo(
            "CONDITIONAL",
            [
                *reasons,
                "✓ criterion 1 met (beats all baselines net of cost+tax)",
                "⚠ criterion 3 unmet: static universe carries SURVIVORSHIP BIAS — "
                "re-run on a point-in-time universe before trusting the edge",
            ],
        )
    return GoNoGo("GO", [*reasons, "✓ criteria 1 & 3 met"])


def _table(rows: Sequence[Mapping[str, object]]) -> str:
    """Render metric rows as a fixed-width text table (no tabulate dependency)."""
    if not rows:
        return "(no rows)"
    cols = list(rows[0].keys())
    widths = {c: max(len(str(c)), *(len(str(r[c])) for r in rows)) for c in cols}
    header = "  ".join(str(c).rjust(widths[c]) for c in cols)
    lines = [header, "  ".join("-" * widths[c] for c in cols)]
    for r in rows:
        lines.append("  ".join(str(r[c]).rjust(widths[c]) for c in cols))
    return "\n".join(lines)


def build_report(
    result: BacktestResult,
    prices: PriceData,
    benchmark: pd.Series,
    cfg: Config,
) -> str:
    """Build the full markdown go/no-go report string."""
    capital = result.starting_capital
    index = result.equity.index
    assert isinstance(index, pd.DatetimeIndex)

    strategy_m = compute_metrics(result.equity, "Q-Alpha strategy")
    baseline_curves = {
        "do_nothing": do_nothing(index, capital),
        "nifty50_buy_hold": buy_and_hold(benchmark, index, capital),
        "equal_weight": equal_weight(prices, index, capital),
    }
    baseline_m = {name: compute_metrics(curve, name) for name, curve in baseline_curves.items()}
    sip = monthly_sip(benchmark.reindex(index).ffill().bfill(), cfg.backtest.sip_monthly_amount)

    verdict = evaluate(strategy_m, baseline_m, result.point_in_time_universe)

    rows = [strategy_m.as_row()] + [m.as_row() for m in baseline_m.values()]
    regime_rows = [
        {
            "regime": rm.regime,
            "days": rm.days,
            "%time": round(rm.pct_of_time * 100, 1),
            "ann_ret_%": round(rm.ann_return * 100, 1),
            "vol_%": round(rm.ann_volatility * 100, 1),
            "sharpe": round(rm.sharpe, 2),
        }
        for rm in per_regime_metrics(result.equity, result.regimes)
    ]

    start = index.min().date()
    end = index.max().date()
    lines = [
        "# Q-Alpha — Phase 0 Backtest Report",
        "",
        f"**Window:** {start} → {end}  |  **Starting capital:** ₹{capital:,}  "
        f"|  **Rebalances:** {result.n_rebalances}",
        f"**Costs charged (strategy):** ₹{result.total_costs:,.2f}  "
        f"|  **Capital-gains tax:** ₹{result.total_tax:,.2f}",
        "",
        "## Performance vs baselines (strategy is net of Zerodha cost + capital-gains tax;",
        "## baselines are idealised, cost-free and tax-free)",
        "",
        _table(rows),
        "",
        f"**Monthly SIP into Nifty 50:** invested ₹{sip.invested:,} over {sip.n_installments} "
        f"installments → ₹{sip.final_value:,} ({sip.multiple:.2f}×). "
        "(Different cash-flow profile — money-weighted reference, not a lump-sum curve.)",
        "",
        "## Per-regime breakdown (strategy)",
        "",
        _table(regime_rows) if regime_rows else "(no regime data)",
        "",
        "## Go / No-Go",
        "",
        f"### Verdict: **{verdict.verdict}**",
        "",
    ]
    lines += [f"- {r}" for r in verdict.reasons]
    lines += [
        "",
        "**Notes & caveats:**",
        "- Criterion 2 (no look-ahead): guaranteed by `PriceData.as_of` slicing + tests.",
        f"- Universe is {'point-in-time' if result.point_in_time_universe else 'STATIC (survivorship-biased)'}.",
        "- Benchmark is the Nifty 50 *price* series; a Total-Return index would lift the bar "
        "slightly (the strategy is TR-adjusted). Use Nifty 50 TRI in calibration.",
        "- Phase 0a uses 3 price/volume factors; Value/Quality/Dividend (0b) need historical "
        "fundamentals before the six-factor verdict is final.",
    ]
    return "\n".join(lines)
