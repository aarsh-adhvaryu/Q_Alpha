"""Backtest portfolio accountant (Q_alpha.md §2.6, §4.6).

Holds cash + a FIFO lot ledger and executes rebalances by translating target *weights* into integer
share trades, charging realistic Zerodha costs and Indian capital-gains tax on every sell. Money is
Decimal throughout; prices cross the float→Decimal boundary here (rounded to paise).

Accounting choices (documented because they matter for the net-of-cost result):

* **Integer shares** — NSE trades whole shares, so target values are floored to whole shares. This
  reproduces the rounding drag the spec cites as the QUBO motivation (§15.1) instead of hiding it.
* **Buy-side cost basis** excludes STT and modelled slippage (neither is deductible for capital
  gains, §2.7); both still leave the cash account. Deductible statutory charges are folded into the
  lot so FIFO gains are computed correctly.
* **Sells execute before buys** so freed proceeds fund purchases within the same rebalance.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import cast

import pandas as pd

from qalpha.accounting.capital_gains import CapitalGainsCalculator, RealizedGain
from qalpha.accounting.corporate_actions import (
    CorporateAction,
    CorporateActionResult,
    CorporateActionType,
    apply_to_ledger,
)
from qalpha.accounting.costs import CostBreakdown, Side, compute_costs
from qalpha.accounting.slippage import SlippageModel
from qalpha.accounting.tax_lots import FIFOLedger, TaxLot
from qalpha.config import CostConfig, TaxConfig

_PAISE = Decimal("0.01")


def to_decimal_price(price: float) -> Decimal:
    """Convert a float price to a paise-rounded Decimal (the float→Decimal boundary)."""
    return Decimal(str(price)).quantize(_PAISE, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TradeRecord:
    """One executed trade in the backtest."""

    date: date
    ticker: str
    side: Side
    quantity: Decimal
    price: Decimal
    cost: Decimal  # all-in transaction cost (incl. STT + slippage)
    tax: Decimal  # capital-gains tax realized on a sell (0 for buys)
    pool: str = "core"


@dataclass
class Portfolio:
    """Cash + FIFO holdings with cost/tax-aware rebalancing."""

    cost_cfg: CostConfig
    tax_cfg: TaxConfig
    cash: Decimal = Decimal("0")
    ledger: FIFOLedger = field(default_factory=FIFOLedger)
    # Optional size-aware slippage (Q_alpha.md §13). When None, trades use the flat
    # ``cost_cfg.default_slippage_pct``; the backtest engine sets a ``SquareRootSlippage`` snapshot
    # (causal as-of ADV + daily vol) per rebalance date when run with ``dynamic_slippage=True``.
    slippage_model: SlippageModel | None = None
    gains: CapitalGainsCalculator = field(init=False)

    def __post_init__(self) -> None:
        self.gains = CapitalGainsCalculator(self.tax_cfg)

    # ---- persistence (live/paper book survives across daily runs) --------

    def to_state(self) -> dict[str, object]:
        """JSON-safe full state: cash + open FIFO lots + the per-FY LTCG exemption tally.

        Enough to reconstruct an identical accountant — the tally matters because the ₹1.25L LTCG
        exemption is carried across the financial year (see :class:`CapitalGainsCalculator`).
        """
        lots = [
            lot.to_dict() for t in self.ledger.all_tickers() for lot in self.ledger.open_lots(t)
        ]
        return {
            "cash": str(self.cash),
            "lots": lots,
            "ltcg_by_fy": {str(fy): str(v) for fy, v in self.gains.realized_ltcg_by_fy().items()},
        }

    @classmethod
    def from_state(
        cls, state: Mapping[str, object], cost_cfg: CostConfig, tax_cfg: TaxConfig
    ) -> Portfolio:
        """Reconstruct a portfolio from :meth:`to_state` (inverse round-trip)."""
        pf = cls(cost_cfg, tax_cfg, cash=Decimal(str(state["cash"])))
        for raw in cast(list[Mapping[str, str | None]], state["lots"]):
            pf.ledger.add_lot(TaxLot.from_dict(raw))
        ltcg = cast(Mapping[str, str], state["ltcg_by_fy"])
        pf.gains.restore_ltcg_by_fy({int(fy): Decimal(v) for fy, v in ltcg.items()})
        return pf

    def clone(self) -> Portfolio:
        """A deep copy — cash, FIFO ledger, and FY exemption tally — for dry-running trades."""
        return copy.deepcopy(self)

    # ---- valuation -------------------------------------------------------

    def positions(self) -> dict[str, Decimal]:
        held: dict[str, Decimal] = {}
        for ticker in self.ledger.all_tickers():
            qty = self.ledger.quantity_held(ticker)
            if qty > 0:
                held[ticker] = qty
        return held

    def holdings_value(self, prices: Mapping[str, Decimal]) -> Decimal:
        total = Decimal("0")
        for ticker, qty in self.positions().items():
            if ticker in prices:
                total += qty * prices[ticker]
        return total

    def market_value(self, prices: Mapping[str, Decimal]) -> Decimal:
        """Total portfolio market value: cash + holdings (Risk/Compute view, §2.6)."""
        return self.cash + self.holdings_value(prices)

    def current_weights(self, prices: Mapping[str, Decimal]) -> dict[str, float]:
        mv = self.market_value(prices)
        if mv <= 0:
            return {}
        return {
            t: float(qty * prices[t] / mv) for t, qty in self.positions().items() if t in prices
        }

    # ---- rebalancing -----------------------------------------------------

    def rebalance(
        self,
        on_date: date,
        target_weights: pd.Series,
        prices: Mapping[str, Decimal],
        *,
        min_trade_fraction: float = 0.0,
    ) -> list[TradeRecord]:
        """Trade toward ``target_weights`` (fraction of total MV) at ``prices``. Sells then buys.

        ``min_trade_fraction`` imposes a no-trade band: a name already held is left untouched if the
        rebalance would move its weight by less than this fraction of total portfolio value. This
        suppresses dust trades that realize tax for negligible benefit (Q_alpha.md §4.6 spirit).
        """
        total_value = self.market_value(prices)
        held = self.positions()
        band_value = Decimal(str(min_trade_fraction)) * total_value

        desired_shares: dict[str, Decimal] = {}
        for ticker, weight in target_weights.items():
            t = str(ticker)
            if weight <= 0 or t not in prices or prices[t] <= 0:
                continue
            target_value = Decimal(str(weight)) * total_value
            shares = (target_value / prices[t]).to_integral_value(rounding=ROUND_DOWN)
            if shares > 0:
                desired_shares[t] = shares

        # No-trade band: keep current quantity when the proposed move is below the band.
        if band_value > 0:
            for t in set(held) | set(desired_shares):
                if t not in prices:
                    continue
                cur = held.get(t, Decimal("0"))
                des = desired_shares.get(t, Decimal("0"))
                if cur > 0 and abs(des - cur) * prices[t] < band_value:
                    desired_shares[t] = cur

        records: list[TradeRecord] = []
        tickers = set(held) | set(desired_shares)

        # Sells first (frees cash for buys in the same rebalance).
        for ticker in sorted(tickers):
            cur = held.get(ticker, Decimal("0"))
            des = desired_shares.get(ticker, Decimal("0"))
            if des < cur and ticker in prices:
                records.append(self._sell(on_date, ticker, cur - des, prices[ticker]))

        # Buys, affordability-capped by remaining cash.
        for ticker in sorted(tickers):
            cur = held.get(ticker, Decimal("0"))
            des = desired_shares.get(ticker, Decimal("0"))
            if des > cur:
                rec = self._buy(on_date, ticker, des - cur, prices[ticker])
                if rec is not None:
                    records.append(rec)
        return records

    def liquidate(
        self, on_date: date, tickers: Iterable[str], prices: Mapping[str, Decimal]
    ) -> list[TradeRecord]:
        """Fully sell the named holdings to cash — the defensive stop-loss exit (Q_alpha.md §3.6).

        Unconditional by design: a stop bypasses the §4.6 net-benefit gate (§4.6 "cost never
        overrides a stop — you exit regardless"). Proceeds sit as cash until the next core
        rebalance redeploys them. Reuses the same FIFO/cost/tax ``_sell`` path as every other trade.
        """
        held = self.positions()
        records: list[TradeRecord] = []
        for t in sorted(set(tickers)):
            qty = held.get(t, Decimal("0"))
            if qty > 0 and t in prices and prices[t] > 0:
                records.append(self._sell(on_date, t, qty, prices[t]))
        return records

    def estimate_rebalance(
        self,
        on_date: date,
        target_weights: pd.Series,
        prices: Mapping[str, Decimal],
        *,
        min_trade_fraction: float = 0.0,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """Dry-run a rebalance WITHOUT mutating state: return (cost, tax, turnover_value).

        Lets the decision layer see the real rupee friction (Zerodha cost + FIFO capital-gains tax)
        of a proposed rebalance before committing — the core of the §4.6 net-benefit gate. Works by
        deep-copying the portfolio (cash, lot ledger, FY exemption state) and replaying the trade on
        the copy, so the exact same execution code produces the estimate.
        """
        clone = copy.deepcopy(self)
        trades = clone.rebalance(
            on_date, target_weights, prices, min_trade_fraction=min_trade_fraction
        )
        cost = sum((t.cost for t in trades), Decimal("0.00"))
        tax = sum((t.tax for t in trades), Decimal("0.00"))
        turnover = sum((t.quantity * t.price for t in trades), Decimal("0.00"))
        return cost, tax, turnover

    def sell(self, on_date: date, ticker: str, qty: Decimal, price: Decimal) -> TradeRecord:
        """Sell ``qty`` shares of ``ticker`` at ``price`` (mutates: FIFO, cost, tax, cash).

        The public single-name sell — the live execution layer fills specific quantities, and the
        tax-smart advisor uses it to cost a multi-name raise-cash plan exactly (the FY LTCG exemption
        depletes across sequential sells, so the order matters). Reuses the same ``_sell`` path as
        every rebalance, so the FIFO/cost/tax numbers are identical to the validated backtest.
        """
        if qty <= 0:
            raise ValueError("sell quantity must be positive")
        return self._sell(on_date, ticker, qty, price)

    def buy(self, on_date: date, ticker: str, qty: Decimal, price: Decimal) -> TradeRecord | None:
        """Buy ``qty`` shares of ``ticker`` at ``price`` (mutates; affordability-capped by cash).

        The public single-name buy, symmetric with :meth:`sell`: the live execution layer fills
        specific quantities, and the advisor uses it to route fresh capital into underweights. Reuses
        the same ``_buy`` path (whole shares, Zerodha costs, cash cap) as every rebalance. Returns
        ``None`` if not even one share is affordable.
        """
        if qty <= 0:
            raise ValueError("buy quantity must be positive")
        return self._buy(on_date, ticker, qty, price)

    def apply_corporate_action(self, action: CorporateAction) -> CorporateActionResult:
        """Apply a split / bonus / dividend to the book (§14 criterion 5).

        Splits and bonuses reshape the FIFO lots (cost-basis and holding-period rules per
        :mod:`qalpha.accounting.corporate_actions`); a dividend credits cash as **income** — it never
        touches the tax lots, so it can't pollute the capital-gains computation. Returns an audit
        record of what changed.
        """
        before = self.ledger.quantity_held(action.ticker)
        cash = apply_to_ledger(self.ledger, action)
        self.cash += cash
        after = self.ledger.quantity_held(action.ticker)
        if action.action_type is CorporateActionType.SPLIT:
            note = f"Split ×{action.ratio} on {action.ticker}: {before} → {after} shares (cost + holding period preserved)."
        elif action.action_type is CorporateActionType.BONUS:
            note = f"Bonus ×{action.ratio} on {action.ticker}: +{after - before} shares at ₹0 cost, dated {action.ex_date}."
        else:
            note = f"Dividend ₹{action.amount_per_share}/sh on {before} {action.ticker}: ₹{cash} cash (income, not capital gains)."
        return CorporateActionResult(action, before, after, cash, note)

    def preview_sell(
        self, on_date: date, ticker: str, qty: Decimal, price: Decimal
    ) -> tuple[list[RealizedGain], CostBreakdown]:
        """Dry-run a single sell WITHOUT mutating: return its per-lot realized gains + cost breakdown.

        Deep-copies the ledger + FY exemption tally and replays the FIFO consumption on the copy, so
        the advisor can show exactly which lots a sale consumes (STCG vs LTCG, holding days, tax) and
        how much the ₹1.25L exemption shelters — using the same engine that executes the trade.
        """
        clone = copy.deepcopy(self)
        cb = compute_costs(Side.SELL, qty, price, self.cost_cfg)
        consumptions = clone.ledger.consume(ticker, qty, on_date)
        realized = clone.gains.compute_sell(consumptions, price, cb.deductible_for_gains)
        return realized, cb

    def _slippage_pct(self, ticker: str, qty: Decimal, price: Decimal) -> Decimal | None:
        """Per-trade slippage fraction from the active model (None ⇒ flat ``default_slippage_pct``)."""
        if self.slippage_model is None:
            return None
        return self.slippage_model.pct(ticker, qty * price)

    def _sell(self, on_date: date, ticker: str, qty: Decimal, price: Decimal) -> TradeRecord:
        cb = compute_costs(
            Side.SELL, qty, price, self.cost_cfg, self._slippage_pct(ticker, qty, price)
        )
        consumptions = self.ledger.consume(ticker, qty, on_date)
        realized = self.gains.compute_sell(consumptions, price, cb.deductible_for_gains)
        tax = sum((g.tax for g in realized), Decimal("0.00"))
        proceeds = qty * price - cb.total - tax
        self.cash += proceeds
        return TradeRecord(on_date, ticker, Side.SELL, qty, price, cb.total, tax)

    def _affordable_qty(self, ticker: str, price: Decimal, cash: Decimal) -> Decimal:
        """Largest whole-share quantity whose all-in buy outlay fits in ``cash``.

        Starts from a cost-inclusive estimate (buy costs are ~0.3% — STT, slippage, stamp) then
        decrements to the exact boundary. Slippage is re-evaluated at each candidate size so the
        size-aware model stays self-consistent.
        """
        estimate = (cash / (price * Decimal("1.004"))).to_integral_value(rounding=ROUND_DOWN)
        qty = max(Decimal("0"), estimate)
        while qty > 0:
            cb = compute_costs(
                Side.BUY, qty, price, self.cost_cfg, self._slippage_pct(ticker, qty, price)
            )
            if qty * price + cb.total <= cash:
                break
            qty -= 1
        return qty

    def _buy(self, on_date: date, ticker: str, qty: Decimal, price: Decimal) -> TradeRecord | None:
        cb = compute_costs(
            Side.BUY, qty, price, self.cost_cfg, self._slippage_pct(ticker, qty, price)
        )
        outlay = qty * price + cb.total
        if outlay > self.cash:
            qty = self._affordable_qty(ticker, price, self.cash)
            if qty <= 0:
                return None
            cb = compute_costs(
                Side.BUY, qty, price, self.cost_cfg, self._slippage_pct(ticker, qty, price)
            )
            outlay = qty * price + cb.total
        self.cash -= outlay
        # Cost basis excludes STT + slippage (not deductible); keeps deductible statutory charges.
        deductible_other = cb.exchange_txn + cb.sebi + cb.gst
        self.ledger.add_lot(
            TaxLot(
                ticker=ticker,
                acquisition_date=on_date,
                quantity_original=qty,
                buy_price=price,
                brokerage=cb.brokerage,
                stamp_duty=cb.stamp_duty,
                other_costs=deductible_other,
            )
        )
        return TradeRecord(on_date, ticker, Side.BUY, qty, price, cb.total, Decimal("0.00"))
