"""Phase-0 backtest: walk-forward engine, baselines, metrics, go/no-go report (Q_alpha.md §13).

The engine wires the funnel (factors -> sector allocator -> optimizer) to the portfolio accountant
(FIFO lots + Zerodha costs + capital-gains tax) and steps month by month with strict no-look-ahead
(every read goes through ``PriceData.as_of``). Its only purpose is the GO/NO-GO decision: does the
strategy beat do-nothing, Nifty 50, a SIP, and equal-weight net of costs and taxes (§14).
"""

from qalpha.backtest.engine import BacktestResult, run_backtest
from qalpha.backtest.portfolio import Portfolio, TradeRecord
from qalpha.backtest.strategy import select_and_weight

__all__ = [
    "BacktestResult",
    "Portfolio",
    "TradeRecord",
    "run_backtest",
    "select_and_weight",
]
