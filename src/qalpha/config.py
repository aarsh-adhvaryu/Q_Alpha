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
    # bid/ask spread is unavailable. §4.8 caps live slippage at 0.2%. This is the FLAT fallback —
    # the size-aware square-root model below supersedes it when a backtest runs with
    # ``dynamic_slippage=True``.
    default_slippage_pct: Decimal = Decimal("0.002")

    # Size-aware market impact (Q_alpha.md §13, the Almgren square-root law):
    #   slippage_fraction = impact_k · σ_daily · √(trade_value / ADV),  clamped to [floor, cap].
    # Flat slippage is blind to order size; this charges the true cost of pushing a large notional
    # through a thinner name, so the §4.6 gate / optimiser naturally avoid (minimise) it. At
    # impact_k=1 the law equals ~0.2% exactly when an order is 1% of ADV at 2% daily vol — i.e. it
    # agrees with default_slippage_pct at the §3.3 order-size cap, and is cheaper below / dearer above.
    impact_k: Decimal = Decimal("1.0")
    slippage_floor_pct: Decimal = Decimal("0.0002")  # 2 bps: residual spread even for a tiny order
    slippage_cap_pct: Decimal = Decimal("0.02")  # 2%: sanity cap for illiquid / oversized orders


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
    # §4.6: rebalance only if risk improvement > this × (cost+tax). Spec value 2.0. NOTE: a Phase-0b
    # sweep (2012–24) found 2.0 too lenient — 3.0 roughly halved tax AND improved CAGR/Sharpe. Kept
    # at 2.0 pending walk-forward (out-of-sample) calibration (§6.2) rather than in-sample tuning.
    rebalance_net_benefit_multiple: Decimal = Decimal("2.0")


@dataclass(frozen=True)
class DefensiveConfig:
    """Defensive overlay — systemic vs idiosyncratic exit (Q_alpha.md §3.6, §4.7).

    Runs *between* the slow core rebalances. It exits a holding only when the name is in a
    **sustained, idiosyncratic** breakdown — actually bleeding over the lookback AND badly lagging
    the cross-sectional median (the 'market' proxy). A market-wide drawdown (everything down
    together → small excess) is NOT flagged — §4.7 "do not panic-sell in a crash". This is the
    asymmetric stop: slow to sell winners (core), fast to dump a lone bleeder. Thresholds are
    a-priori/round and must be **walk-forward calibrated** (§6.2), never fit in-sample.
    """

    lookback_days: int = 126  # ~6 months: a sustained bleed, not a blip
    abs_drawdown_exit: float = 0.10  # must actually be down > 10% over the window
    rel_underperf_exit: float = 0.10  # AND lag the cross-sectional median by > 10% (idiosyncratic)


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
    defensive: DefensiveConfig = field(default_factory=DefensiveConfig)
    capital: CapitalConfig = field(default_factory=CapitalConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)


DEFAULT_CONFIG = Config()
