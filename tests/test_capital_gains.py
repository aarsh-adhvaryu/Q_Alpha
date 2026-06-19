"""Capital-gains engine tests (Q_alpha.md §2.7, §4.6): STCG/LTCG split, ₹1.25L FY exemption."""

from datetime import date
from decimal import Decimal

from qalpha.accounting.capital_gains import (
    CapitalGainsCalculator,
    RealizedGain,
    financial_year,
    net_capital_gains_tax,
    net_tax_total,
)
from qalpha.accounting.tax_lots import LotConsumption
from qalpha.config import TaxConfig

CFG = TaxConfig()


def _gain(kind: str, gain: str, sell: date = date(2025, 6, 1)) -> RealizedGain:
    """Minimal RealizedGain for set-off tests — only gain_type, gain and FY (sell_date) matter."""
    g = Decimal(gain)
    return RealizedGain(
        ticker="X",
        lot_id="l",
        quantity=Decimal("1"),
        acquisition_date=date(2024, 1, 1),
        sell_date=sell,
        holding_days=400 if kind == "LTCG" else 100,
        gain_type=kind,
        cost_of_acquisition=Decimal("0"),
        sale_consideration=g,
        gain=g,
        taxable_gain=g if g > 0 else Decimal("0"),
        tax=Decimal("0"),
    )


def _consumption(acq: date, sell: date, qty: str, basis: str, price: str) -> LotConsumption:
    return LotConsumption(
        lot_id="x",
        ticker="TCS",
        quantity=Decimal(qty),
        acquisition_date=acq,
        sell_date=sell,
        buy_price=Decimal(price),
        cost_basis=Decimal(basis),
    )


def test_financial_year_april_boundary() -> None:
    assert financial_year(date(2026, 2, 10)) == 2025  # Feb -> previous FY
    assert financial_year(date(2026, 4, 1)) == 2026  # Apr -> new FY


def test_stcg_taxed_at_20pct() -> None:
    calc = CapitalGainsCalculator(CFG)
    c = _consumption(date(2025, 11, 1), date(2026, 2, 10), "4", "6000.00", "1500")
    [g] = calc.compute_sell([c], sell_price=Decimal("1600"), deductible_expenses=Decimal("13.87"))
    assert g.gain_type == "STCG"
    # sale = 1600*4 - 13.87 = 6386.13; gain = 386.13; tax = 20% = 77.23
    assert g.sale_consideration == Decimal("6386.13")
    assert g.gain == Decimal("386.13")
    assert g.tax == Decimal("77.23")


def test_ltcg_exemption_consumed_across_two_sells_same_fy() -> None:
    calc = CapitalGainsCalculator(CFG)

    # First LTCG sell with a ₹1,00,000 gain — fully under the ₹1.25L exemption.
    c1 = _consumption(date(2024, 1, 1), date(2026, 2, 10), "100", "100000.00", "1000")
    [g1] = calc.compute_sell([c1], sell_price=Decimal("2000"), deductible_expenses=Decimal("0"))
    assert g1.gain_type == "LTCG"
    assert g1.gain == Decimal("100000.00")
    assert g1.taxable_gain == Decimal("0.00")
    assert g1.tax == Decimal("0.00")

    # Second LTCG sell, ₹50,000 gain, same FY — only ₹25,000 exemption remains.
    c2 = _consumption(date(2024, 1, 1), date(2026, 2, 20), "50", "50000.00", "1000")
    [g2] = calc.compute_sell([c2], sell_price=Decimal("2000"), deductible_expenses=Decimal("0"))
    assert g2.taxable_gain == Decimal("25000.00")
    assert g2.tax == Decimal("3125.00")  # 25000 * 12.5%

    assert calc.ltcg_realized(2025) == Decimal("150000.00")


def test_loss_incurs_no_tax() -> None:
    calc = CapitalGainsCalculator(CFG)
    c = _consumption(date(2025, 11, 1), date(2026, 2, 10), "4", "8000.00", "2000")
    [g] = calc.compute_sell([c], sell_price=Decimal("1500"), deductible_expenses=Decimal("13.87"))
    assert g.gain < 0
    assert g.tax == Decimal("0.00")


def test_stcg_ltcg_boundary_penalty_decays() -> None:
    calc = CapitalGainsCalculator(CFG)
    assert calc.stcg_to_ltcg_penalty(330) == Decimal("3.0")
    assert calc.stcg_to_ltcg_penalty(329) == Decimal("1.0")  # outside window
    assert calc.stcg_to_ltcg_penalty(365) == Decimal("1.0")  # already LTCG
    # 350 days -> 1 + 2*15/35 = 1.857...
    assert round(float(calc.stcg_to_ltcg_penalty(350)), 2) == 1.86


# ---- §70/§74 loss set-off -----------------------------------------------------------------------


def test_stcl_sets_off_against_stcg_first() -> None:
    # ₹10,000 STCG, ₹4,000 STCL → net ₹6,000 STCG taxed at 20% = ₹1,200 (vs ₹2,000 gross, no set-off).
    [row] = net_capital_gains_tax([_gain("STCG", "10000"), _gain("STCG", "-4000")], CFG)
    assert row.taxable_stcg == Decimal("6000")
    assert row.total_tax == Decimal("1200.00")
    assert row.carryforward_stcl == Decimal("0")


def test_stcl_spills_to_ltcg_when_stcg_exhausted() -> None:
    # ₹2,000 STCG, ₹5,000 STCL, ₹200,000 LTCG. STCL kills STCG (2k) then 3k spills to LTCG.
    rows = net_capital_gains_tax(
        [_gain("STCG", "2000"), _gain("STCG", "-5000"), _gain("LTCG", "200000")], CFG
    )
    [row] = rows
    assert row.taxable_stcg == Decimal("0")
    # LTCG 200,000 − 3,000 spilled STCL − 125,000 exemption = 72,000 taxable @ 12.5% = 9,000.
    assert row.taxable_ltcg == Decimal("72000")
    assert row.ltcg_exempted == Decimal("125000")
    assert row.total_tax == Decimal("9000.00")


def test_ltcl_does_not_set_off_against_stcg() -> None:
    # ₹50,000 STCG, ₹30,000 LTCL → LTCL cannot touch STCG; STCG stays fully taxable, LTCL carries.
    [row] = net_capital_gains_tax([_gain("STCG", "50000"), _gain("LTCG", "-30000")], CFG)
    assert row.taxable_stcg == Decimal("50000")
    assert row.total_tax == Decimal("10000.00")  # 50,000 * 20%
    assert row.carryforward_ltcl == Decimal("30000")


def test_exemption_already_used_this_fy_is_respected() -> None:
    # ₹100,000 LTCG but ₹125,000 exemption already consumed this FY → fully taxable.
    [row] = net_capital_gains_tax(
        [_gain("LTCG", "100000")], CFG, exemption_used_by_fy={2025: Decimal("125000")}
    )
    assert row.ltcg_exempted == Decimal("0")
    assert row.taxable_ltcg == Decimal("100000")
    assert row.total_tax == Decimal("12500.00")


def test_setoff_groups_by_financial_year() -> None:
    # A gain in FY2024 and a loss in FY2025 do NOT net across the year boundary.
    gains = [_gain("STCG", "10000", date(2025, 2, 1)), _gain("STCG", "-10000", date(2025, 6, 1))]
    rows = net_capital_gains_tax(gains, CFG)
    assert {r.fy for r in rows} == {2024, 2025}
    fy24 = next(r for r in rows if r.fy == 2024)
    assert fy24.total_tax == Decimal("2000.00")  # the gain is taxed; next-FY loss can't reach it
    assert net_tax_total(gains, CFG) == Decimal("2000.00")
