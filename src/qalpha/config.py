"""Central configuration for Q-Alpha.

Every tunable parameter the spec flags as "validate/calibrate via backtest" (Q_alpha.md §16)
lives here, so the logic modules never hard-code a magic number. Phase 0 sweeps these to find
the values that survive walk-forward validation.

Money is represented with `decimal.Decimal` everywhere it touches accounting (Q_alpha.md §5.2);
statistical/factor math runs in float64 (numpy) where Decimal would be both meaningless and slow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class CostConfig:
    """Zerodha delivery-equity cost model (Q_alpha.md §4.6, broker swapped from HDFC).

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

    # Slippage assumption (fraction of trade value) used by the backtest when an explicit
    # bid/ask spread is unavailable. §4.8 caps live slippage at 0.2%.
    default_slippage_pct: Decimal = Decimal("0.002")


@dataclass(frozen=True)
class TaxConfig:
    """Indian capital-gains tax (Q_alpha.md §4.6). FY runs April–March."""

    stcg_rate: Decimal = Decimal("0.20")  # holding < 365 days
    ltcg_rate: Decimal = Decimal("0.125")  # holding >= 365 days
    ltcg_annual_exemption: Decimal = Decimal("125000")  # ₹1.25L LTCG exempt per FY
    ltcg_holding_days: int = 365


@dataclass(frozen=True)
class LiquidityConfig:
    """Pre-screening liquidity gates (Q_alpha.md §3.2/§3.3). ADV in ₹."""

    order_size_cap_pct_adv: Decimal = Decimal("0.01")  # never exceed 1% of ADV
    min_adv_tactical: Decimal = Decimal("2500000")  # ₹25L
    min_adv_core: Decimal = Decimal("5000000")  # ₹50L
    zero_volume_ban_days: int = 3  # Volume-Velocity gate
    adv_window_days: int = 20


@dataclass(frozen=True)
class FactorConfig:
    """Six-factor model parameters (Q_alpha.md §3.2)."""

    momentum_lookback_days: int = 252  # 12 months
    momentum_skip_days: int = 21  # skip most-recent 1m (short-term reversal)
    volatility_window_days: int = 30
    trading_days_per_year: int = 252


# Regime -> [momentum, value, quality, volatility, liquidity, dividend] (Q_alpha.md §3.2).
REGIME_FACTOR_WEIGHTS: dict[str, tuple[float, float, float, float, float, float]] = {
    "bull": (0.25, 0.15, 0.20, 0.15, 0.10, 0.15),
    "bear": (0.10, 0.20, 0.25, 0.15, 0.10, 0.20),
    "high_vol": (0.10, 0.15, 0.20, 0.25, 0.15, 0.15),
    "crash": (0.10, 0.25, 0.25, 0.10, 0.10, 0.20),
    "rotation": (0.25, 0.15, 0.20, 0.15, 0.10, 0.15),
}

FACTOR_NAMES: tuple[str, ...] = (
    "momentum",
    "value",
    "quality",
    "volatility",
    "liquidity",
    "dividend",
)


@dataclass(frozen=True)
class RegimeConfig:
    """India-VIX threshold regime classifier (Q_alpha.md §4.7). Thresholds are §16 tunables."""

    vix_bull_max: float = 20.0
    vix_bear_max: float = 25.0
    vix_high_vol_max: float = 35.0
    # >35 => crash. "rotation" is set by the sector-rotation flag, not VIX alone.


@dataclass(frozen=True)
class OptimizerConfig:
    """Sector allocator + portfolio optimizer (Q_alpha.md §3.3/§3.4)."""

    sector_weight_min: float = 0.05
    sector_weight_max: float = 0.30
    max_single_stock: float = 0.20  # 20% of core
    ewma_halflife_days: int = 60  # §3.8
    drift_threshold: float = 0.05  # §3.4 (5–10%; start at 5%)
    rebalance_net_benefit_multiple: Decimal = Decimal("2.0")  # §4.6 risk improvement > 2× cost


@dataclass(frozen=True)
class CapitalConfig:
    """Capital structure (Q_alpha.md §2). Phase 0 backtests the core sleeve primarily."""

    starting_capital: Decimal = Decimal("200000")
    core_ratio: Decimal = Decimal("0.50")
    tactical_ratio: Decimal = Decimal("0.25")
    contingency_ratio: Decimal = Decimal("0.25")

    def max_core_stocks(self, total_core_capital: Decimal) -> int:
        """§2.0 scaling formula: min(20, max(5, floor(capital/200000) + 4))."""
        return min(20, max(5, int(total_core_capital // Decimal("200000")) + 4))


@dataclass(frozen=True)
class BacktestConfig:
    """Walk-forward harness (Q_alpha.md §13 Phase 0)."""

    rebalance_freq: str = "ME"  # pandas month-end offset alias
    start: str = "2010-01-01"
    end: str = "2025-12-31"
    benchmark_ticker: str = "^NSEI"  # Nifty 50
    sip_monthly_amount: Decimal = Decimal("10000")


@dataclass(frozen=True)
class Config:
    """Top-level config aggregating every sub-config."""

    cost: CostConfig = field(default_factory=CostConfig)
    tax: TaxConfig = field(default_factory=TaxConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    factor: FactorConfig = field(default_factory=FactorConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    capital: CapitalConfig = field(default_factory=CapitalConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)


DEFAULT_CONFIG = Config()
