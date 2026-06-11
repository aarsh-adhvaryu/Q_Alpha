"""Capital-gains tax engine (Q_alpha.md §2.7, §4.6).

Turns FIFO lot consumptions into per-lot realized STCG/LTCG and the tax due. Key Indian rules
encoded here:

* **STCG 20%** (holding < 365 days), **LTCG 12.5%** (>= 365 days).
* **LTCG ₹1.25L annual exemption** (April–March FY), applied across the financial year — the
  calculator carries a running tally so once the exemption is exhausted, subsequent LTCG is taxed.
* **STT is excluded** from the gains computation. The sell-side deductible expenses passed in must
  therefore already exclude STT (use ``CostBreakdown.deductible_for_gains``).
* Indian FY runs **April–March**; the calculator buckets the LTCG exemption per FY automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from qalpha.accounting.tax_lots import LotConsumption
from qalpha.config import TaxConfig

_PAISE = Decimal("0.01")


def _paise(value: Decimal) -> Decimal:
    return value.quantize(_PAISE, rounding=ROUND_HALF_UP)


def financial_year(d: date) -> int:
    """Return the starting calendar year of the Indian FY containing ``d`` (Apr–Mar)."""
    return d.year if d.month >= 4 else d.year - 1


@dataclass(frozen=True)
class RealizedGain:
    """Per-lot realized gain (Q_alpha.md `realized_gain_events`)."""

    ticker: str
    lot_id: str
    quantity: Decimal
    acquisition_date: date
    sell_date: date
    holding_days: int
    gain_type: str  # "STCG" | "LTCG"
    cost_of_acquisition: Decimal
    sale_consideration: Decimal  # net of deductible transfer expenses (STT excluded)
    gain: Decimal  # pre-exemption realized gain (may be negative)
    taxable_gain: Decimal  # after LTCG exemption applied
    tax: Decimal


class CapitalGainsCalculator:
    """Computes capital-gains tax across a financial year, tracking the LTCG exemption.

    Stateful: it accumulates LTCG used against the ₹1.25L exemption per FY. Create one instance
    per backtest run (or per live FY) and feed it sell events in chronological order.
    """

    def __init__(self, cfg: TaxConfig) -> None:
        self._cfg = cfg
        # FY-start-year -> LTCG gains already realized this FY (for exemption tracking).
        self._ltcg_realized_by_fy: dict[int, Decimal] = {}

    def ltcg_realized(self, fy: int) -> Decimal:
        return self._ltcg_realized_by_fy.get(fy, Decimal("0.00"))

    def compute_sell(
        self,
        consumptions: list[LotConsumption],
        sell_price: Decimal,
        deductible_expenses: Decimal,
    ) -> list[RealizedGain]:
        """Compute realized gains + tax for one sell event spanning ``consumptions``.

        Args:
            consumptions: FIFO lot consumptions for this sell (from ``FIFOLedger.consume``).
            sell_price: execution price per share.
            deductible_expenses: total sell-side expenses deductible for gains (STT excluded);
                typically ``CostBreakdown.deductible_for_gains``. Allocated across lots pro-rata
                by quantity.

        Returns:
            One :class:`RealizedGain` per consumed lot. Mutates the FY LTCG tally for exemption.
        """
        total_qty = sum((c.quantity for c in consumptions), Decimal("0"))
        if total_qty <= 0:
            return []

        results: list[RealizedGain] = []
        for c in consumptions:
            qty_fraction = c.quantity / total_qty
            expense_alloc = _paise(deductible_expenses * qty_fraction)
            sale_consideration = _paise(sell_price * c.quantity - expense_alloc)
            gain = _paise(sale_consideration - c.cost_basis)

            is_ltcg = c.is_long_term
            gain_type = "LTCG" if is_ltcg else "STCG"

            taxable_gain, tax = self._tax_for_gain(gain, is_ltcg, c.sell_date)

            results.append(
                RealizedGain(
                    ticker=c.ticker,
                    lot_id=c.lot_id,
                    quantity=c.quantity,
                    acquisition_date=c.acquisition_date,
                    sell_date=c.sell_date,
                    holding_days=c.holding_days,
                    gain_type=gain_type,
                    cost_of_acquisition=c.cost_basis,
                    sale_consideration=sale_consideration,
                    gain=gain,
                    taxable_gain=taxable_gain,
                    tax=tax,
                )
            )
        return results

    def _tax_for_gain(
        self, gain: Decimal, is_ltcg: bool, sell_date: date
    ) -> tuple[Decimal, Decimal]:
        """Return (taxable_gain, tax) for a single lot, applying the LTCG FY exemption.

        Losses (gain < 0) produce zero tax here; loss set-off against other gains is a
        portfolio-level concern deferred past Phase 0 (tax-loss harvesting, §18, AUM > ₹10L).
        """
        if gain <= 0:
            return gain, Decimal("0.00")

        if not is_ltcg:
            tax = _paise(gain * self._cfg.stcg_rate)
            return gain, tax

        # LTCG: apply remaining ₹1.25L FY exemption before taxing.
        fy = financial_year(sell_date)
        used = self._ltcg_realized_by_fy.get(fy, Decimal("0.00"))
        remaining_exemption = max(self._cfg.ltcg_annual_exemption - used, Decimal("0.00"))
        self._ltcg_realized_by_fy[fy] = used + gain

        exempt_part = min(gain, remaining_exemption)
        taxable_gain = _paise(gain - exempt_part)
        tax = _paise(taxable_gain * self._cfg.ltcg_rate)
        return taxable_gain, tax

    def stcg_to_ltcg_penalty(self, oldest_lot_age_days: int) -> Decimal:
        """§3.4 boundary penalty multiplier for selling near the 365-day LTCG threshold.

        ``penalty = 1.0 + (2.0 * days_remaining / 35)`` for ages in [330, 365); 1.0 otherwise.
        At 330 days -> 3.0x, at 364 -> ~1.06x. The optimizer multiplies a sell's tax drag by this
        to discourage realizing STCG days before it would become cheaper LTCG.
        """
        if oldest_lot_age_days < 330 or oldest_lot_age_days >= 365:
            return Decimal("1.0")
        days_remaining = Decimal(365 - oldest_lot_age_days)
        return Decimal("1.0") + (Decimal("2.0") * days_remaining / Decimal("35"))
