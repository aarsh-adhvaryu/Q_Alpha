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


def test_sell_tax_includes_the_4pct_cess() -> None:
    pf = _pf()
    _add(pf, "AAA", "2000", "100", date(2023, 1, 1))  # ₹200k LTCG, > exemption → taxable
    adv = advise_sell(pf, "AAA", Decimal("200"), date(2024, 6, 1), Config())

    base = adv.total_tax - adv.cess
    assert adv.cess > 0
    assert adv.cess == (base * Decimal("0.04")).quantize(Decimal("0.01"))  # 4% on the base tax
    assert adv.total_tax == base + adv.cess
    assert "Cess" in adv.render()


def test_sell_flags_pre2018_lot_without_fmv() -> None:
    pf = _pf()
    _add(pf, "OLDCO", "2000", "100", date(2016, 1, 1))  # pre-1-Feb-2018, long-term
    adv = advise_sell(pf, "OLDCO", Decimal("500"), date(2024, 6, 1), Config())

    assert adv.grandfather_unpriced == ["OLDCO"]
    assert "before 1-Feb-2018" in adv.render()


def test_sell_applies_grandfathering_when_fmv_supplied() -> None:
    pf = _pf()
    _add(pf, "OLDCO", "2000", "100", date(2016, 1, 1))  # actual cost ₹100/sh
    no_gf = advise_sell(pf, "OLDCO", Decimal("500"), date(2024, 6, 1), Config())
    # 31-Jan-2018 FMV ₹400/sh → cost steps up ₹100→₹400, so the taxable gain (and tax) fall sharply.
    gf = advise_sell(
        pf,
        "OLDCO",
        Decimal("500"),
        date(2024, 6, 1),
        Config(),
        grandfather_fmv={"OLDCO": Decimal("400")},
    )
    assert gf.total_tax < no_gf.total_tax
    assert gf.grandfather_saving > 0
    assert gf.grandfather_unpriced == []
    assert "grandfathering" in gf.render()


def test_short_term_near_boundary_flags_the_wait() -> None:
    pf = _pf()
    _add(pf, "BBB", "100", "100", date(2023, 8, 1))  # 349 days held on 2024-07-15 → ST
    adv = advise_sell(pf, "BBB", Decimal("200"), date(2024, 7, 15), Config())

    assert len(adv.boundary_waits) == 1
    wait = adv.boundary_waits[0]
    # §2(42A) is 12 CALENDAR months + a day, not 365 days: bought 2023-08-01 → the anniversary is
    # 2024-08-01 (366 days out, 2024 being a leap year) and the first long-term date is 2024-08-02.
    # The old "+365 days" rule said 2024-07-31 — two days early, i.e. it would have told the user to
    # sell while the gain was still taxed at 20%.
    assert wait.days_to_long_term == 18
    assert wait.long_term_date == date(2024, 8, 2)
    assert wait.estimated_saving > 0
    assert "turn long-term" in adv.render()


def test_sale_on_the_12_month_anniversary_is_still_short_term() -> None:
    """§2(42A): long-term needs *more than* 12 months. The engine's `>= 365 days` says otherwise.

    Selling exactly one year after the buy must be quoted at 20% (STCG), not 12.5% — the advisor
    re-classifies the engine's row so the real-money quote matches the ITR.
    """
    pf = _pf()
    _add(pf, "AAA", "100", "100", date(2025, 8, 12))  # 365 days held on 2026-08-12
    adv = advise_sell(pf, "AAA", Decimal("200"), date(2026, 8, 12), Config())

    assert adv.ltcg_gain == Decimal("0")  # NOT long-term yet
    assert adv.stcg_gain > 0
    assert adv.boundary_demoted  # the demotion is surfaced, not silent
    assert adv.total_tax > 0  # would have been ₹0 (sheltered by the LTCG exemption) before the fix
    assert "NOT long-term yet" in adv.render()
    assert "13 Aug 2026" in adv.render()  # the genuinely safe date

    # One day later it really is long-term, and the exemption shelters it.
    later = advise_sell(pf, "AAA", Decimal("200"), date(2026, 8, 13), Config())
    assert later.ltcg_gain > 0
    assert not later.boundary_demoted
    assert later.total_tax == Decimal("0")


def test_leap_year_anniversary_is_366_days_out() -> None:
    """Across a leap year the 12-month line is 366 days, so `>= 365` is two days early."""
    pf = _pf()
    _add(pf, "AAA", "100", "100", date(2023, 8, 1))
    # 2024-07-31 is 365 days later — the old rule called this long-term.
    assert advise_sell(pf, "AAA", Decimal("200"), date(2024, 7, 31), Config()).ltcg_gain == 0
    # 2024-08-01 is the anniversary itself — still short-term.
    assert advise_sell(pf, "AAA", Decimal("200"), date(2024, 8, 1), Config()).ltcg_gain == 0
    # 2024-08-02 is the first genuinely long-term day.
    assert advise_sell(pf, "AAA", Decimal("200"), date(2024, 8, 2), Config()).ltcg_gain > 0


def test_tax_free_quantity_respects_the_calendar_boundary() -> None:
    """A lot at exactly 365 days must not be counted as exemption-sheltered ₹0-tax stock."""
    pf = _pf()
    _add(pf, "AAA", "100", "100", date(2025, 8, 12))
    assert (
        advise_sell(pf, "AAA", Decimal("200"), date(2026, 8, 12), Config()).tax_free_quantity == 0
    )
    assert (
        advise_sell(pf, "AAA", Decimal("200"), date(2026, 8, 13), Config()).tax_free_quantity == 100
    )


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
    # The greedy whole-share fill drives idle cash below one share of the cheapest name (BBB ₹100),
    # not a share's worth stranded per name.
    assert adv.leftover_cash < Decimal("200")
