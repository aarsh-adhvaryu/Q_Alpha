"""Deterministic tax-smart advisor (Q_alpha.md §14 crit 10).

Lots are added directly with zero buy-side cost so the gain-per-share is exact (price − buy_price),
keeping the tax assertions clean. Every figure must come from the validated FIFO/cost/tax engine.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from qalpha.accounting.tax_lots import TaxLot
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.advisor import (
    advise_deploy,
    advise_raise_cash,
    advise_sell,
)


def _pf(cash: str = "0") -> Portfolio:
    cfg = Config()
    return Portfolio(cfg.cost, cfg.tax, cash=Decimal(cash))


def _add(pf: Portfolio, ticker: str, qty: str, price: str, on: date) -> None:
    pf.ledger.add_lot(
        TaxLot(
            ticker=ticker,
            acquisition_date=on,
            quantity_original=Decimal(qty),
            buy_price=Decimal(price),
        )
    )


# ---- advise_sell --------------------------------------------------------------------------------


def test_sell_uses_exemption_and_reports_tax_free_quantity() -> None:
    pf = _pf()
    _add(pf, "AAA", "2000", "100", date(2023, 1, 1))  # long-term by 2024-06-01
    adv = advise_sell(pf, "AAA", Decimal("200"), date(2024, 6, 1), Config())

    assert adv.quantity == Decimal("2000")
    assert adv.exemption_remaining == Decimal("125000")
    # Gain ≈ ₹200k > ₹1.25L exemption → the full exemption shelters part, the rest is taxed.
    assert adv.ltcg_sheltered == Decimal("125000.00")
    assert adv.total_tax > 0
    # ₹1.25L exemption ÷ ₹100 gain/share = 1250 shares sellable tax-free.
    assert adv.tax_free_quantity == Decimal("1250")
    assert "for ₹0 tax" in adv.render()


def test_small_long_term_sale_is_fully_tax_free() -> None:
    pf = _pf()
    _add(pf, "AAA", "1000", "100", date(2023, 1, 1))  # ₹100k gain < exemption
    adv = advise_sell(pf, "AAA", Decimal("200"), date(2024, 6, 1), Config())

    assert adv.total_tax == 0
    assert adv.tax_free_quantity == Decimal("1000")


def test_short_term_near_boundary_flags_the_wait() -> None:
    pf = _pf()
    _add(pf, "BBB", "100", "100", date(2023, 8, 1))  # 349 days held on 2024-07-15 → ST
    adv = advise_sell(pf, "BBB", Decimal("200"), date(2024, 7, 15), Config())

    assert len(adv.boundary_waits) == 1
    wait = adv.boundary_waits[0]
    assert wait.days_to_long_term == 16
    assert wait.long_term_date == date(2024, 7, 31)  # acquisition + 365 days (2024 is a leap year)
    assert wait.estimated_saving > 0
    assert "turn long-term" in adv.render()


def test_sell_unknown_ticker_raises() -> None:
    with pytest.raises(ValueError):
        advise_sell(_pf(), "ZZZ", Decimal("1"), date(2024, 1, 1), Config())


# ---- advise_raise_cash --------------------------------------------------------------------------


def test_raise_cash_prefers_low_tax_source() -> None:
    pf = _pf()
    _add(pf, "AAA", "1000", "200", date(2023, 1, 1))  # a loser at ₹150 now → tax-free to sell
    _add(pf, "BBB", "1000", "100", date(2024, 3, 1))  # short-term winner at ₹300 → heavily taxed
    prices = {"AAA": Decimal("150"), "BBB": Decimal("300")}

    adv = advise_raise_cash(pf, Decimal("100000"), prices, date(2024, 9, 1))

    # The whole ₹100k comes from the loser (₹0 tax); the naive pro-rata sell taxes the winner.
    assert adv.smart_tax == 0
    assert {o.ticker for o in adv.smart_orders} == {"AAA"}
    assert adv.naive_tax > 0
    assert adv.tax_saved == adv.naive_tax
    assert adv.smart_raised >= Decimal("100000")


# ---- advise_deploy ------------------------------------------------------------------------------


def test_deploy_routes_new_money_to_underweights_tax_free() -> None:
    pf = _pf()
    # Embedded long-term gain large enough that trimming exceeds the ₹1.25L exemption (so the naive
    # rebalance genuinely realizes tax): 2000 sh at ₹50 cost, now ₹300.
    _add(pf, "AAA", "2000", "50", date(2023, 1, 1))
    target = pd.Series({"AAA": 0.5, "BBB": 0.5})
    prices = {"AAA": Decimal("300"), "BBB": Decimal("100")}

    adv = advise_deploy(pf, Decimal("100000"), target, prices, date(2024, 6, 1))

    # New money buys the underweight (BBB) — no sells, so ₹0 capital-gains tax...
    assert adv.buy_orders
    assert all(o.side.name == "BUY" for o in adv.buy_orders)
    assert all(o.tax == 0 for o in adv.buy_orders)
    # ...whereas a full rebalance would trim the appreciated AAA and realize tax.
    assert adv.naive_tax > 0
    assert adv.tax_saved == adv.naive_tax
