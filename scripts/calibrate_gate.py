"""§4.6 net-benefit gate-multiplier — out-of-sample calibration (PLAN.md Stage 0; iron rule §6.2).

The walk-forward showed the real driver is *low realized turnover*; at MONTHLY cadence the §4.6 gate
(execute only if annual risk-reduction ₹ > multiplier × cost+tax) IS the adaptive turnover throttle.
So the multiplier is the knob to calibrate — but **out-of-sample**, never by picking the in-sample
winner. We sweep it at monthly cadence across the same independent sub-periods used in walkforward.py
and ask: which value is robustly good across regimes (and can monthly+gate match structural annual)?

Run: uv run python scripts/calibrate_gate.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from run_phase0 import PIT_PRICES_PARQUET, _load_benchmark, _load_universe_csv

from qalpha.backtest.baselines import equal_weight_pit
from qalpha.backtest.engine import run_backtest
from qalpha.backtest.metrics import compute_metrics, max_drawdown
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe

CSV = "data/universes/nifty50_membership.csv"
CAPITAL = Config().capital.starting_capital
MULTIPLIERS = ["1.0", "2.0", "3.0", "5.0"]
WINDOWS = [
    ("FULL  2012-2024", "2012-01-01", "2024-12-31"),
    ("W1    2012-2018", "2012-01-01", "2018-12-31"),
    ("W2    2015-2021", "2015-01-01", "2021-12-31"),
    ("W3    2018-2024", "2018-01-01", "2024-12-31"),
]


def _cfg(mult: str) -> Config:
    base = Config()
    from decimal import Decimal

    return replace(
        base, optimizer=replace(base.optimizer, rebalance_net_benefit_multiple=Decimal(mult))
    )


def _ann(curve: pd.Series) -> float:
    yrs = max((curve.index[-1] - curve.index[0]).days / 365.25, 1e-9)
    return float((curve.iloc[-1] / curve.iloc[0]) ** (1.0 / yrs) - 1.0)


def main() -> None:
    _t, sector_of = _load_universe_csv(Path(CSV))
    prices = load_parquet(PIT_PRICES_PARQUET)
    universe = Universe.from_csv(CSV)
    idx = run_backtest(
        prices,
        sector_of,
        universe,
        Config(),
        start="2012-01-01",
        end="2024-12-31",
        tax_aware=True,
        min_trade_fraction=0.10,
        rebalance_freq="Y",
    ).equity.index
    tri = _load_benchmark("NIFTYBEES.NS", "2012-01-01", "2024-12-31", refresh=False)
    one_n = equal_weight_pit(prices, universe, idx, CAPITAL)  # type: ignore[arg-type]

    print("§4.6 multiplier OOS sweep — MONTHLY cadence (the gate is the turnover throttle).")
    print("Each cell: CAGR% / Sharpe / tax₹ / #rebalances actually executed.\n")
    for label, ws, we in WINDOWS:
        tri_w = tri[(tri.index >= pd.Timestamp(ws)) & (tri.index <= pd.Timestamp(we))]
        n_w = one_n[(one_n.index >= pd.Timestamp(ws)) & (one_n.index <= pd.Timestamp(we))]
        print(f"[{label}]   bench: TRI {_ann(tri_w) * 100:.1f}% | 1/N {_ann(n_w) * 100:.1f}%")
        hdr = f"{'mult':>5} | {'CAGR%':>6} | {'Sharpe':>6} | {'maxDD%':>7} | {'tax ₹':>9} | {'#rebal':>6}"
        print(hdr)
        print("-" * len(hdr))
        for mult in MULTIPLIERS:
            res = run_backtest(
                prices,
                sector_of,
                universe,
                _cfg(mult),
                start=ws,
                end=we,
                tax_aware=True,
                min_trade_fraction=0.10,
                rebalance_freq="M",
            )
            if not res.trades:
                continue
            fts = pd.Timestamp(min(t.date for t in res.trades))
            eq = res.equity[res.equity.index >= fts]
            m = compute_metrics(eq, mult)
            print(
                f"{mult:>5} | {m.cagr * 100:6.1f} | {m.sharpe:6.2f} | "
                f"{max_drawdown(eq) * 100:7.1f} | {float(res.total_tax):9,.0f} | {res.n_rebalances:6d}"
            )
        print()


if __name__ == "__main__":
    main()
