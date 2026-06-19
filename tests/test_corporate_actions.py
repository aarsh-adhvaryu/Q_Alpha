"""Corporate-actions tests (§14 criterion 5) — the Indian tax treatment must be exact.

Splits preserve cost basis + holding period; bonus shares are ₹0-cost with a *fresh* acquisition date
(so they can be STCG when the originals are LTCG); dividends are income (cash), never capital gains.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from qalpha.accounting.corporate_actions import CorporateAction, CorporateActionType
from qalpha.accounting.tax_lots import TaxLot
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config


def _book(cash: str = "0") -> Portfolio:
    return Portfolio(Config().cost, Config().tax, cash=Decimal(cash))


def _add(pf: Portfolio, qty: str, price: str, on: date) -> None:
    pf.ledger.add_lot(
        TaxLot(
            ticker="X.NS",
            acquisition_date=on,
            quantity_original=Decimal(qty),
            buy_price=Decimal(price),
        )
    )


def test_split_preserves_total_cost_and_acquisition_date() -> None:
    pf = _book()
    _add(pf, "10", "1000", date(2020, 1, 1))  # ₹10,000 cost
    res = pf.apply_corporate_action(CorporateAction.split("X.NS", date(2023, 1, 1), Decimal("5")))
    assert (res.shares_before, res.shares_after) == (Decimal("10"), Decimal("50"))
    (lot,) = pf.ledger.open_lots("X.NS")
    assert lot.quantity_remaining == Decimal("50")
    assert lot.acquisition_date == date(2020, 1, 1)  # holding period unbroken
    assert lot.total_buy_cost == Decimal("10000.00")  # total cost preserved
    assert lot.cost_basis_per_share == Decimal("200")  # 10000 / 50


def test_split_with_uneven_ratio_preserves_cost_to_the_paise() -> None:
    pf = _book()
    _add(pf, "9", "999", date(2021, 6, 1))  # ₹8,991
    pf.apply_corporate_action(CorporateAction.split("X.NS", date(2023, 1, 1), Decimal("3")))
    (lot,) = pf.ledger.open_lots("X.NS")
    assert lot.quantity_remaining == Decimal("27")
    assert lot.total_buy_cost == Decimal("8991.00")  # invariant through the 3:1 split


def test_split_scales_a_partially_sold_lot() -> None:
    pf = _book()
    _add(pf, "10", "1000", date(2020, 1, 1))
    pf.ledger.consume("X.NS", Decimal("4"), date(2021, 1, 1))  # 6 remain
    pf.apply_corporate_action(CorporateAction.split("X.NS", date(2023, 1, 1), Decimal("2")))
    (lot,) = pf.ledger.open_lots("X.NS")
    assert lot.quantity_remaining == Decimal("12")  # 6 × 2
    assert lot.quantity_original == Decimal("20")  # 10 × 2


def test_bonus_adds_zero_cost_lot_with_fresh_date() -> None:
    pf = _book()
    _add(pf, "10", "1000", date(2020, 1, 1))
    res = pf.apply_corporate_action(CorporateAction.bonus("X.NS", date(2023, 6, 1), Decimal("1")))
    assert res.shares_after == Decimal("20")
    lots = pf.ledger.open_lots("X.NS")
    assert len(lots) == 2
    orig = next(lt for lt in lots if lt.buy_price == Decimal("1000"))
    bonus = next(lt for lt in lots if lt.buy_price == Decimal("0"))
    assert orig.acquisition_date == date(2020, 1, 1) and orig.quantity_remaining == Decimal("10")
    assert bonus.acquisition_date == date(2023, 6, 1)  # fresh holding period
    assert bonus.quantity_remaining == Decimal("10")
    assert bonus.total_buy_cost == Decimal("0.00")  # nil cost of acquisition


def test_dividend_is_income_cash_not_capital_gains() -> None:
    pf = _book(cash="100")
    _add(pf, "10", "1000", date(2020, 1, 1))
    res = pf.apply_corporate_action(
        CorporateAction.dividend("X.NS", date(2023, 1, 1), Decimal("5.50"))
    )
    assert res.cash_received == Decimal("55.00")  # 10 × ₹5.50
    assert pf.cash == Decimal("155.00")
    assert pf.ledger.quantity_held("X.NS") == Decimal("10")  # lots untouched
    assert pf.gains.realized_ltcg_by_fy() == {}  # nothing recorded as a capital gain
    assert res.action.action_type is CorporateActionType.DIVIDEND


def test_sell_after_split_is_long_term_and_cost_correct() -> None:
    pf = _book()
    _add(pf, "10", "1000", date(2020, 1, 1))  # ₹10,000
    pf.apply_corporate_action(
        CorporateAction.split("X.NS", date(2023, 1, 1), Decimal("2"))
    )  # 20@500
    consumptions = pf.ledger.consume("X.NS", Decimal("20"), date(2023, 6, 1))
    gains = pf.gains.compute_sell(consumptions, Decimal("600"), Decimal("0"))
    (g,) = gains
    assert g.gain_type == "LTCG"  # original 2020 date carried through the split
    assert g.gain == Decimal("2000.00")  # 12,000 proceeds − 10,000 cost


def test_bonus_shares_are_short_term_from_allotment() -> None:
    pf = _book()
    _add(pf, "10", "1000", date(2020, 1, 1))  # long-term originals
    pf.apply_corporate_action(CorporateAction.bonus("X.NS", date(2024, 1, 1), Decimal("1")))
    # FIFO sells the 2020 originals first (LTCG), then the 2024 bonus lot (STCG, ₹0 cost).
    consumptions = pf.ledger.consume("X.NS", Decimal("20"), date(2024, 7, 1))
    assert consumptions[0].is_long_term and not consumptions[1].is_long_term
    gains = pf.gains.compute_sell(consumptions, Decimal("600"), Decimal("0"))
    stcg = next(g for g in gains if g.gain_type == "STCG")
    assert stcg.gain == Decimal("6000.00")  # 10 bonus shares × ₹600, ₹0 cost → all gain


def test_detector_parses_splits_and_dividends_since_cutoff() -> None:
    import pandas as pd

    from qalpha.live.corporate_actions_feed import corporate_actions_from_series

    splits = pd.Series({pd.Timestamp("2019-01-01"): 2.0, pd.Timestamp("2023-05-01"): 5.0})
    dividends = pd.Series({pd.Timestamp("2022-01-01"): 8.0, pd.Timestamp("2023-07-01"): 12.5})
    found = corporate_actions_from_series("X.NS", splits, dividends, date(2023, 1, 1))
    # only on/after the cutoff, sorted by ex-date
    assert [a.action_type.value for a in found] == ["SPLIT", "DIVIDEND"]
    assert found[0].ratio == Decimal("5.0") and found[0].ex_date == date(2023, 5, 1)
    assert found[1].amount_per_share == Decimal("12.5")
