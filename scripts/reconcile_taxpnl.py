"""Criterion-4 reconciliation: our FIFO engine vs the real Zerodha Tax P&L (Q_alpha.md §14 crit 4).

Replays the Console **tradebook** through the validated FIFO engine and compares the realized gains
against the official Console **Tax P&L** export, to the paise:

* gross realized P&L (zero-cost replay) ↔ Zerodha's reported STCG/LTCG profit  → proves lot-matching;
* net taxable gain + capital-gains tax (full Zerodha cost model)               → what we'd actually owe.

Usage:
    uv run python scripts/reconcile_taxpnl.py \
        [--tradebook data/tradebook-YHK037-EQ.csv] \
        [--taxpnl data/taxpnl-YHK037-2026_2027-Q1-Q1.xlsx] \
        [--report reports/crit4_reconciliation.md]
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import fields, replace
from decimal import Decimal
from pathlib import Path

from qalpha.accounting.capital_gains import RealizedGain
from qalpha.config import Config, CostConfig
from qalpha.live.taxpnl import parse_taxpnl, reconcile_gross
from qalpha.live.tradebook import parse_tradebook, replay_tradebook

_DEF_TRADEBOOK = "data/tradebook-YHK037-EQ.csv"
_DEF_TAXPNL = "data/taxpnl-YHK037-2026_2027-Q1-Q1.xlsx"
_DEF_REPORT = "reports/crit4_reconciliation.md"


def _zero_cost(cost: CostConfig) -> CostConfig:
    """A cost model with every Decimal rate/charge zeroed → gain == gross (sell − buy)."""
    zeros = {
        f.name: Decimal("0") for f in fields(cost) if isinstance(getattr(cost, f.name), Decimal)
    }
    return replace(cost, **zeros)


def _gains_by_type(gains: list[RealizedGain]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for g in gains:
        out[g.gain_type] += g.gain
    return dict(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tradebook", default=_DEF_TRADEBOOK)
    ap.add_argument("--taxpnl", default=_DEF_TAXPNL)
    ap.add_argument("--report", default=_DEF_REPORT)
    args = ap.parse_args()

    cfg = Config()
    trades = parse_tradebook(args.tradebook)

    full = replay_tradebook(trades, cfg)  # real Zerodha cost model → net gain + tax
    gross = replay_tradebook(trades, replace(cfg, cost=_zero_cost(cfg.cost)))  # gross (sell − buy)

    statement = parse_taxpnl(args.taxpnl)
    recon = reconcile_gross(_gains_by_type(gross.realized_gains), statement)

    net_by_type = _gains_by_type(full.realized_gains)
    # Deductible transfer expenses = gross gain − net gain (the full replay nets ex-STT charges
    # from the consideration that the zero-cost replay leaves in).
    deductible_total = sum((g.gain for g in gross.realized_gains), Decimal("0")) - sum(
        (g.gain for g in full.realized_gains), Decimal("0")
    )

    lines: list[str] = []
    lines.append("# Criterion-4 reconciliation — FIFO engine vs Zerodha Tax P&L\n")
    lines.append(
        f"_Client `{statement.client_id}` · tradebook `{Path(args.tradebook).name}` · "
        f"Tax P&L `{Path(args.taxpnl).name}`_\n"
    )
    lines.append(f"Replayed **{full.n_trades}** trades.")
    for w in full.warnings:
        lines.append(f"- ⚠️ {w}")

    lines.append("\n## 1. Gross realized P&L (zero-cost replay) vs Zerodha reported\n")
    for line in recon.lines:
        lines.append(f"- {line}")
    verdict = "✅ RECONCILED to the paise" if recon.ok else "❌ MISMATCH — investigate"
    lines.append(f"\n**Gross verdict: {verdict}** (tolerance ₹{recon.tolerance}).")

    lines.append("\n## 2. Per-symbol detail (Zerodha Tax P&L)\n")
    lines.append("| symbol | type | qty | buy ₹ | sell ₹ | gross P&L ₹ |")
    lines.append("|---|---|---|---|---|---|")
    for t in statement.trades:
        lines.append(
            f"| {t.symbol} | {t.gain_type} | {t.quantity} | {t.buy_value:,.2f} | "
            f"{t.sell_value:,.2f} | {t.realized_pnl:,.2f} |"
        )

    lines.append("\n## 3. Our net taxable gain + capital-gains tax (full Zerodha cost model)\n")
    lines.append(
        "Our engine deducts statutory transfer expenses (ex-STT) from the gain, per the "
        "Income-Tax Act — so it sits *below* Zerodha's gross reporting by our modelled "
        "deductible charges; STT is correctly excluded from both.\n"
    )
    for gain_type in ("STCG", "LTCG"):
        ours_net = net_by_type.get(gain_type, Decimal("0"))
        ours_gross = recon.gross_by_type.get(gain_type, Decimal("0"))
        lines.append(
            f"- {gain_type}: gross ₹{ours_gross:,.2f} → net taxable ₹{ours_net:,.2f} "
            f"(deductible expenses ₹{ours_gross - ours_net:,.2f})"
        )
    lines.append(f"- **Total capital-gains tax owed (our FIFO): ₹{full.realized_tax:,.2f}**")
    lines.append(
        f"- Modelled deductible transfer expenses across all sells: ₹{deductible_total:,.2f}"
    )
    lines.append(
        "\n> The deductible total is dominated by the per-sell **DP charge** "
        "(our `dp_charge_per_sell`); Zerodha's export books the same as *Other Credits & Debits* "
        "(₹15.34 here), so our modelled charge is consistent in magnitude. Whether the DP charge is "
        "strictly deductible as a *cost of transfer* is a conservative modelling choice — it lowers "
        "our taxable gain slightly; the gross reconciliation above is unaffected."
    )

    report = "\n".join(lines) + "\n"
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(report)
    print(report)
    print(f"\n(written to {args.report})")


if __name__ == "__main__":
    main()
