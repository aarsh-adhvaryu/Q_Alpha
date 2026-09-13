"""Every tunable number the accounting uses, in one place.

Money is ``decimal.Decimal`` everywhere it touches accounting; a float is never a rupee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class CostConfig:
    """Zerodha delivery-equity cost model (README §Costs).

    Rates are deliberately data, not code — verify against a live Zerodha contract note before
    the go-live phases. Values are the published rates as of 2025-26.
    """

    # Brokerage: Zerodha charges ZERO on delivery equity (the headline improvement over HDFC).
    brokerage_pct: Decimal = Decimal("0.0")
    brokerage_flat: Decimal = Decimal("0.0")

    # Securities Transaction Tax — 0.1% on BUY and SELL for delivery. Tracked as a cost but
    # EXCLUDED from the capital-gains computation (§2.7, §4.6).
    stt_pct: Decimal = Decimal("0.001")

    # NSE exchange transaction charge (~0.00297% of turnover).
    exchange_txn_pct: Decimal = Decimal("0.0000297")

    # SEBI turnover fee (₹10 per crore = 0.0001%).
    sebi_pct: Decimal = Decimal("0.000001")

    # Stamp duty — 0.015% on BUY side only.
    stamp_duty_buy_pct: Decimal = Decimal("0.00015")

    # GST 18% applied to (brokerage + exchange_txn + sebi).
    gst_pct: Decimal = Decimal("0.18")

    # CDSL DP charge per scrip on SELL (Zerodha: ₹13.5 + GST), independent of quantity.
    dp_charge_per_sell: Decimal = Decimal("13.5")

    # Slippage assumption (fraction of trade value) when no bid/ask spread is available. The flat
    # fallback; the size-aware square-root model below supersedes it when one is supplied.
    default_slippage_pct: Decimal = Decimal("0.002")

    # Size-aware market impact (the Almgren square-root law):
    #   slippage_fraction = impact_k · σ_daily · √(trade_value / ADV),  clamped to [floor, cap].
    # Flat slippage is blind to order size; this charges the true cost of pushing a large notional
    # through a thinner name. At impact_k=1 the law equals ~0.2% exactly when an order is 1% of ADV
    # at 2% daily vol — it agrees with default_slippage_pct there, and is cheaper below / dearer above.
    impact_k: Decimal = Decimal("1.0")
    slippage_floor_pct: Decimal = Decimal("0.0002")  # 2 bps: residual spread even for a tiny order
    slippage_cap_pct: Decimal = Decimal("0.02")  # 2%: sanity cap for illiquid / oversized orders


@dataclass(frozen=True)
class TaxConfig:
    """Indian capital-gains tax (README §Tax). FY runs April–March."""

    stcg_rate: Decimal = Decimal("0.20")  # holding < 365 days
    ltcg_rate: Decimal = Decimal("0.125")  # holding >= 365 days
    ltcg_annual_exemption: Decimal = Decimal("125000")  # ₹1.25L LTCG exempt per FY
    ltcg_holding_days: int = 365

    # Health & Education Cess — a flat 4% surcharge on the computed income-tax (incl. capital-gains
    # tax), so the real effective rates are 20.8% (STCG) / 13% (LTCG). Applied by the reconciliation
    # path (`net_capital_gains_tax`), not by `compute_sell` per trade. Surcharge (income-slab
    # dependent) is left out: it needs the user's total income, which nothing here models.
    cess_rate: Decimal = Decimal("0.04")


@dataclass(frozen=True)
class Config:
    cost: CostConfig = field(default_factory=CostConfig)
    tax: TaxConfig = field(default_factory=TaxConfig)
