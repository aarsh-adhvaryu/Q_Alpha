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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import groupby

from qalpha.accounting.tax_lots import LotConsumption
from qalpha.config import TaxConfig

_PAISE = Decimal("0.01")
_ZERO = Decimal("0.00")


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

    def realized_ltcg_by_fy(self) -> dict[int, Decimal]:
        """Snapshot the per-FY LTCG tally — needed to persist a live/paper book across days."""
        return dict(self._ltcg_realized_by_fy)

    def restore_ltcg_by_fy(self, by_fy: Mapping[int, Decimal]) -> None:
        """Restore the per-FY LTCG tally from a snapshot (inverse of realized_ltcg_by_fy)."""
        self._ltcg_realized_by_fy = {int(fy): Decimal(str(v)) for fy, v in by_fy.items()}

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


# ---- FY loss set-off (Indian §70/§74) -----------------------------------------------------------


@dataclass(frozen=True)
class NetCapitalGains:
    """A financial year's capital-gains tax *after* intra-year loss set-off + the LTCG exemption.

    Gross :class:`RealizedGain` records tax each lot in isolation (a loss → ₹0, never offsetting a
    gain). The legally-correct figure nets losses against gains within the FY, so this is the truth
    a real Tax P&L reconciles to and the number the advisor should quote.
    """

    fy: int
    stcg: Decimal  # gross short-term gains (positive lots)
    stcl: Decimal  # short-term losses, as a positive magnitude
    ltcg: Decimal  # gross long-term gains
    ltcl: Decimal  # long-term losses, as a positive magnitude
    taxable_stcg: Decimal  # net STCG after STCL set-off
    taxable_ltcg: Decimal  # net LTCG after loss set-off AND exemption
    ltcg_exempted: Decimal  # LTCG sheltered by the ₹1.25L FY exemption
    stcg_tax: Decimal
    ltcg_tax: Decimal
    total_tax: Decimal
    carryforward_stcl: Decimal  # STCL left unused this FY (carry forward up to 8 AYs — not applied)
    carryforward_ltcl: Decimal  # LTCL left unused this FY (sets off only future LTCG)


def net_capital_gains_tax(
    gains: Iterable[RealizedGain],
    cfg: TaxConfig,
    *,
    exemption_used_by_fy: Mapping[int, Decimal] | None = None,
) -> list[NetCapitalGains]:
    """Legally-correct per-FY capital-gains tax with intra-year loss set-off (one row per FY).

    Indian set-off rules (Income-tax Act §70/§71, intra-year):

    * **Short-term capital loss (STCL)** sets off against STCG **and** LTCG.
    * **Long-term capital loss (LTCL)** sets off against **only** LTCG.

    To minimise tax, STCL is applied to STCG first (taxed 20%) before spilling to LTCG (12.5%); LTCL
    then offsets any remaining LTCG; the ₹1.25L FY exemption shelters the net LTCG. ``exemption_used_
    by_fy`` is the LTCG already sheltered earlier in the same FY (so an incremental advisor sell uses
    only the *remaining* shelter). Losses unused this FY are reported as carry-forward but **not**
    carried across years here (that 8-AY mechanism is a Phase-0 deferral, like tax-loss harvesting).
    """
    used_by_fy = exemption_used_by_fy or {}
    rows: list[NetCapitalGains] = []
    keyed = sorted(gains, key=lambda g: financial_year(g.sell_date))
    for fy, group in groupby(keyed, key=lambda g: financial_year(g.sell_date)):
        items = list(group)
        stcg = sum((g.gain for g in items if not _is_ltcg(g) and g.gain > 0), _ZERO)
        stcl = -sum((g.gain for g in items if not _is_ltcg(g) and g.gain < 0), _ZERO)
        ltcg = sum((g.gain for g in items if _is_ltcg(g) and g.gain > 0), _ZERO)
        ltcl = -sum((g.gain for g in items if _is_ltcg(g) and g.gain < 0), _ZERO)

        # STCL → STCG first (higher rate), then the remainder → LTCG.
        s_used = min(stcl, stcg)
        net_stcg = stcg - s_used
        stcl_left = stcl - s_used
        s_to_ltcg = min(stcl_left, ltcg)
        ltcg_after_stcl = ltcg - s_to_ltcg
        stcl_left -= s_to_ltcg

        # LTCL → only LTCG.
        l_used = min(ltcl, ltcg_after_stcl)
        net_ltcg = ltcg_after_stcl - l_used
        ltcl_left = ltcl - l_used

        # ₹1.25L exemption shelters the net LTCG (after any shelter already used this FY).
        remaining_exemption = max(_ZERO, cfg.ltcg_annual_exemption - used_by_fy.get(fy, _ZERO))
        exempted = min(net_ltcg, remaining_exemption)
        taxable_ltcg = net_ltcg - exempted

        stcg_tax = _paise(net_stcg * cfg.stcg_rate)
        ltcg_tax = _paise(taxable_ltcg * cfg.ltcg_rate)
        rows.append(
            NetCapitalGains(
                fy=fy,
                stcg=stcg,
                stcl=stcl,
                ltcg=ltcg,
                ltcl=ltcl,
                taxable_stcg=net_stcg,
                taxable_ltcg=taxable_ltcg,
                ltcg_exempted=exempted,
                stcg_tax=stcg_tax,
                ltcg_tax=ltcg_tax,
                total_tax=stcg_tax + ltcg_tax,
                carryforward_stcl=stcl_left,
                carryforward_ltcl=ltcl_left,
            )
        )
    return rows


def net_tax_total(
    gains: Iterable[RealizedGain],
    cfg: TaxConfig,
    *,
    exemption_used_by_fy: Mapping[int, Decimal] | None = None,
) -> Decimal:
    """Total capital-gains tax across all FYs after loss set-off (sum of :func:`net_capital_gains_tax`)."""
    return sum(
        (
            r.total_tax
            for r in net_capital_gains_tax(gains, cfg, exemption_used_by_fy=exemption_used_by_fy)
        ),
        _ZERO,
    )


def _is_ltcg(g: RealizedGain) -> bool:
    return g.gain_type == "LTCG"
