"""Zerodha cost-model tests (Q_alpha.md §4.6), checked against hand-computed values."""

from decimal import Decimal

from qalpha.accounting.costs import Side, compute_costs
from qalpha.config import CostConfig

CFG = CostConfig()


def test_buy_breakdown_matches_hand_calc() -> None:
    # Buy 10 @ ₹1000 => turnover ₹10,000.
    cb = compute_costs(Side.BUY, Decimal("10"), Decimal("1000"), CFG)
    assert cb.brokerage == Decimal("0.00")  # Zerodha: zero delivery brokerage
    assert cb.stt == Decimal("10.00")  # 0.1% of 10,000, charged on buy too (delivery)
    assert cb.exchange_txn == Decimal("0.30")  # 0.0000297 * 10000 = 0.297 -> 0.30
    assert cb.sebi == Decimal("0.01")  # 0.000001 * 10000
    assert cb.stamp_duty == Decimal("1.50")  # 0.00015 * 10000 (buy only)
    assert cb.gst == Decimal("0.06")  # 18% of (0 + 0.30 + 0.01)
    assert cb.dp_charge == Decimal("0.00")  # DP only on sell
    assert cb.slippage == Decimal("20.00")  # 0.2% of 10000
    assert cb.total == Decimal("31.87")


def test_sell_breakdown_matches_hand_calc() -> None:
    cb = compute_costs(Side.SELL, Decimal("10"), Decimal("1000"), CFG)
    assert cb.stamp_duty == Decimal("0.00")  # no stamp on sell
    assert cb.dp_charge == Decimal("13.50")  # CDSL DP per scrip on sell
    assert cb.stt == Decimal("10.00")
    assert cb.total == Decimal("43.87")  # 10 + 0.30 + 0.01 + 0.06 + 13.50 + 20.00


def test_deductible_for_gains_excludes_stt_and_slippage() -> None:
    cb = compute_costs(Side.SELL, Decimal("10"), Decimal("1000"), CFG)
    # brokerage 0 + exchange 0.30 + sebi 0.01 + stamp 0 + gst 0.06 + dp 13.50 = 13.87
    assert cb.deductible_for_gains == Decimal("13.87")
    # STT (10.00) and slippage (20.00) are NOT in the deductible figure.
    assert cb.deductible_for_gains == cb.total - cb.stt - cb.slippage


def test_zero_quantity_is_zero_cost() -> None:
    cb = compute_costs(Side.BUY, Decimal("0"), Decimal("1000"), CFG)
    assert cb.total == Decimal("0.00")
