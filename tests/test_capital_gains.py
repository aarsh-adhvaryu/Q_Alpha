"""Capital-gains engine tests (Q_alpha.md §2.7, §4.6): STCG/LTCG split, ₹1.25L FY exemption."""

from datetime import date
from decimal import Decimal

from qalpha.accounting.capital_gains import (
    CapitalGainsCalculator,
    RealizedGain,
    apply_grandfathering,
    financial_year,
    grandfathered_cost_of_acquisition,
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
    # ₹10,000 STCG, ₹4,000 STCL → net ₹6,000 STCG @ 20% = ₹1,200 + 4% cess ₹48 = ₹1,248.
    [row] = net_capital_gains_tax([_gain("STCG", "10000"), _gain("STCG", "-4000")], CFG)
    assert row.taxable_stcg == Decimal("6000")
    assert row.stcg_tax == Decimal("1200.00")  # base tax, before cess
    assert row.cess == Decimal("48.00")  # 4% Health & Education Cess
    assert row.total_tax == Decimal("1248.00")
    assert row.carryforward_stcl == Decimal("0")


def test_stcl_spills_to_ltcg_when_stcg_exhausted() -> None:
    # ₹2,000 STCG, ₹5,000 STCL, ₹200,000 LTCG. STCL kills STCG (2k) then 3k spills to LTCG.
    rows = net_capital_gains_tax(
        [_gain("STCG", "2000"), _gain("STCG", "-5000"), _gain("LTCG", "200000")], CFG
    )
    [row] = rows
    assert row.taxable_stcg == Decimal("0")
    # LTCG 200,000 − 3,000 spilled STCL − 125,000 exemption = 72,000 taxable @ 12.5% = 9,000 + cess.
    assert row.taxable_ltcg == Decimal("72000")
    assert row.ltcg_exempted == Decimal("125000")
    assert row.total_tax == Decimal("9360.00")  # 9,000 + 4% cess ₹360


def test_ltcl_does_not_set_off_against_stcg() -> None:
    # ₹50,000 STCG, ₹30,000 LTCL → LTCL cannot touch STCG; STCG stays fully taxable, LTCL carries.
    [row] = net_capital_gains_tax([_gain("STCG", "50000"), _gain("LTCG", "-30000")], CFG)
    assert row.taxable_stcg == Decimal("50000")
    assert row.total_tax == Decimal("10400.00")  # 50,000 * 20% = 10,000 + 4% cess ₹400
    assert row.carryforward_ltcl == Decimal("30000")


def test_exemption_already_used_this_fy_is_respected() -> None:
    # ₹100,000 LTCG but ₹125,000 exemption already consumed this FY → fully taxable.
    [row] = net_capital_gains_tax(
        [_gain("LTCG", "100000")], CFG, exemption_used_by_fy={2025: Decimal("125000")}
    )
    assert row.ltcg_exempted == Decimal("0")
    assert row.taxable_ltcg == Decimal("100000")
    assert row.total_tax == Decimal("13000.00")  # 100,000 * 12.5% = 12,500 + 4% cess ₹500


def test_setoff_groups_by_financial_year() -> None:
    # A gain in FY2024 and a loss in FY2025 do NOT net across the year boundary.
    gains = [_gain("STCG", "10000", date(2025, 2, 1)), _gain("STCG", "-10000", date(2025, 6, 1))]
    rows = net_capital_gains_tax(gains, CFG)
    assert {r.fy for r in rows} == {2024, 2025}
    fy24 = next(r for r in rows if r.fy == 2024)
    assert fy24.total_tax == Decimal("2080.00")  # ₹2,000 + 4% cess; next-FY loss can't reach it
    assert net_tax_total(gains, CFG) == Decimal("2080.00")


# ---- §74 carry-forward of losses (up to 8 assessment years) --------------------------------------


def test_stcl_carries_forward_to_offset_a_later_year_gain() -> None:
    # ₹40k STCL in FY2024, then ₹40k STCG in FY2025 → the b/f loss wipes the later gain to ₹0.
    gains = [_gain("STCG", "-40000", date(2024, 6, 1)), _gain("STCG", "40000", date(2025, 6, 1))]
    rows = net_capital_gains_tax(gains, CFG)
    fy24 = next(r for r in rows if r.fy == 2024)
    fy25 = next(r for r in rows if r.fy == 2025)
    assert fy24.carryforward_stcl == Decimal("40000")  # loss booked, carried
    assert fy25.taxable_stcg == Decimal("0")  # b/f loss absorbs the gain
    assert fy25.total_tax == Decimal("0.00")
    assert fy25.carryforward_stcl == Decimal("0")  # fully used


def test_loss_does_not_carry_backward() -> None:
    # ₹40k STCG in FY2024 then ₹40k STCL in FY2025 → the earlier gain is still fully taxed.
    gains = [_gain("STCG", "40000", date(2024, 6, 1)), _gain("STCG", "-40000", date(2025, 6, 1))]
    rows = net_capital_gains_tax(gains, CFG)
    fy24 = next(r for r in rows if r.fy == 2024)
    assert fy24.total_tax == Decimal("8320.00")  # 40,000 * 20% + 4% cess — loss can't reach back


def test_ltcl_carried_forward_offsets_only_future_ltcg() -> None:
    # FY2024 LTCL ₹200k; FY2025 has STCG ₹50k + LTCG ₹300k. B/f LTCL hits only the LTCG.
    gains = [
        _gain("LTCG", "-200000", date(2024, 6, 1)),
        _gain("STCG", "50000", date(2025, 6, 1)),
        _gain("LTCG", "300000", date(2025, 6, 1)),
    ]
    rows = net_capital_gains_tax(gains, CFG)
    fy25 = next(r for r in rows if r.fy == 2025)
    assert fy25.taxable_stcg == Decimal("50000")  # STCG untouched by the b/f LTCL
    # LTCG 300k − 200k b/f LTCL − 125k exemption = wait: 100k left, exemption shelters 100k → 0 taxable
    assert fy25.taxable_ltcg == Decimal("0")


def test_carry_forward_expires_after_8_assessment_years() -> None:
    # A loss in FY2015 cannot offset a gain in FY2024 (9 FYs later → past the 8-AY window).
    gains = [_gain("STCG", "-40000", date(2015, 6, 1)), _gain("STCG", "40000", date(2024, 6, 1))]
    rows = net_capital_gains_tax(gains, CFG)
    fy24 = next(r for r in rows if r.fy == 2024)
    assert fy24.taxable_stcg == Decimal("40000")  # expired loss cannot help
    assert fy24.total_tax == Decimal("8320.00")


# ---- §112A grandfathering (equity acquired before 2018-02-01) ------------------------------------


def _ltcg_lot(acq: date, cost: str, sale: str, ticker: str = "OLD") -> RealizedGain:
    """A long-term RealizedGain: total cost of acquisition ``cost``, net sale consideration ``sale``."""
    c, s = Decimal(cost), Decimal(sale)
    return RealizedGain(
        ticker=ticker,
        lot_id="l",
        quantity=Decimal("100"),
        acquisition_date=acq,
        sell_date=date(2026, 6, 1),
        holding_days=(date(2026, 6, 1) - acq).days,
        gain_type="LTCG",
        cost_of_acquisition=c,
        sale_consideration=s,
        gain=s - c,
        taxable_gain=max(Decimal("0"), s - c),
        tax=Decimal("0"),
    )


def test_grandfather_steps_cost_up_to_31jan2018_fmv() -> None:
    # Pre-2018 lot: actual ₹10,000, FMV ₹25,000 (< sale ₹30,000) → cost steps up to the FMV.
    cost = grandfathered_cost_of_acquisition(
        Decimal("10000"), Decimal("25000"), Decimal("30000"), date(2017, 1, 1)
    )
    assert cost == Decimal("25000")


def test_grandfather_is_capped_at_sale_value_no_artificial_loss() -> None:
    # FMV ₹40,000 but sale only ₹30,000 → capped at sale value, so it cannot manufacture a loss.
    cost = grandfathered_cost_of_acquisition(
        Decimal("10000"), Decimal("40000"), Decimal("30000"), date(2017, 1, 1)
    )
    assert cost == Decimal("30000")


def test_grandfather_keeps_actual_cost_when_higher() -> None:
    # Actual cost already above the FMV → no step-up (never reduces the cost).
    cost = grandfathered_cost_of_acquisition(
        Decimal("28000"), Decimal("25000"), Decimal("30000"), date(2017, 1, 1)
    )
    assert cost == Decimal("28000")


def test_grandfather_does_not_apply_after_cutoff() -> None:
    # Acquired on/after 2018-02-01 → actual cost is used unchanged, whatever the FMV.
    cost = grandfathered_cost_of_acquisition(
        Decimal("10000"), Decimal("25000"), Decimal("30000"), date(2018, 2, 1)
    )
    assert cost == Decimal("10000")


def test_apply_grandfathering_reduces_gain_and_flags_unpriced() -> None:
    priced = _ltcg_lot(date(2017, 1, 1), "10000", "30000", ticker="OLD")  # FMV supplied
    unpriced = _ltcg_lot(date(2016, 5, 1), "5000", "40000", ticker="NOFMV")  # no FMV
    recent = _ltcg_lot(date(2020, 1, 1), "10000", "30000", ticker="NEW")  # post-cutoff
    adjusted, missing = apply_grandfathering(
        [priced, unpriced, recent], Decimal("300"), {"OLD": Decimal("250")}
    )
    by_ticker = {g.ticker: g for g in adjusted}
    # OLD: FMV 250×100=25,000 < sale 30,000 → cost 25,000, gain 30,000−25,000 = 5,000.
    assert by_ticker["OLD"].cost_of_acquisition == Decimal("25000.00")
    assert by_ticker["OLD"].gain == Decimal("5000.00")
    # NOFMV: pre-2018 but no FMV → untouched (conservative) and reported as unpriced.
    assert by_ticker["NOFMV"].gain == Decimal("35000")  # 40,000 − 5,000, unchanged
    assert [g.ticker for g in missing] == ["NOFMV"]
    # NEW: post-cutoff → never touched.
    assert by_ticker["NEW"].gain == Decimal("20000")
