"""Accounting engine: FIFO tax lots, Zerodha transaction costs, capital-gains tax.

This package is deliberately standalone (Q_alpha.md improvement #2) so the future live decision
engine (Phase 4, §4.6) imports the exact same tested code that the Phase 0 backtest runs on.
"""

from qalpha.accounting.capital_gains import CapitalGainsCalculator, RealizedGain
from qalpha.accounting.costs import CostBreakdown, Side, compute_costs
from qalpha.accounting.tax_lots import FIFOLedger, LotConsumption, TaxLot

__all__ = [
    "CapitalGainsCalculator",
    "CostBreakdown",
    "FIFOLedger",
    "LotConsumption",
    "RealizedGain",
    "Side",
    "TaxLot",
    "compute_costs",
]
