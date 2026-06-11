"""Capital-gains engine tests (Q_alpha.md §2.7, §4.6): STCG/LTCG split, ₹1.25L FY exemption."""

from datetime import date
from decimal import Decimal

from qalpha.accounting.capital_gains import CapitalGainsCalculator, financial_year
from qalpha.accounting.tax_lots import LotConsumption
from qalpha.config import TaxConfig

CFG = TaxConfig()


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
