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


# ---- the heading must name what the orders cost (2026-08-24, found live) ------------------------


def _deploy_advice(cash: str, amount: str, price: str = "100", qty: int = 5):
    from qalpha.accounting.costs import Side
    from qalpha.backtest.portfolio import TradeRecord
    from qalpha.live.advisor import DeployAdvice

    orders = [
        TradeRecord(
            date=date(2026, 8, 24),
            ticker="A.NS",
            side=Side.BUY,
            quantity=Decimal(qty),
            price=Decimal(price),
            cost=Decimal("1"),
            tax=Decimal("0"),
            pool="core",
        )
    ]
    return DeployAdvice(
        as_of=date(2026, 8, 24),
        amount=Decimal(amount),
        buy_orders=orders,
        buy_cost=Decimal("1"),
        leftover_cash=Decimal("0"),
        naive_tax=Decimal("0"),
        naive_cost=Decimal("0"),
        tax_saved=Decimal("0"),
        idle_cash=Decimal(cash),
    )


def test_the_heading_names_the_total_the_orders_actually_cost() -> None:
    """A ₹1,00,000 heading over a ₹5,97,418 basket is how a 64-share order gets placed.

    The advisor has always deployed ``portfolio.cash + amount`` — putting idle cash to work is its
    documented job. The heading named only ``amount``. On a real account with a ₹5,00,000 balance
    that understated the basket by 6×, on the one surface where the number becomes an order.
    """
    advice = _deploy_advice(cash="500000", amount="100000", price="1000", qty=600)
    head = advice.render()
    assert advice.total_deployed == Decimal("600000")
    assert "₹600,000" in head
    assert "of idle cash already in your account" in head
    assert "₹100,000.00 of new money" in head


def test_it_says_what_to_do_about_earmarked_money() -> None:
    """Naming the number is not enough — the user needs the control that changes it.

    The first version of this warning told the user to move the money out of the broker account.
    That is a chore the software should absorb, not hand back — so it now points at the switch.
    """
    head = _deploy_advice(cash="400000", amount="50000").render()
    assert "deploy idle cash too" in head
    assert "earmarked for later" in head


def test_an_account_with_no_idle_cash_keeps_the_plain_heading() -> None:
    """The warning must not cry wolf on the ordinary case, or it stops being read."""
    head = _deploy_advice(cash="0", amount="50000").render()
    assert "of new money" in head
    assert "idle cash already in your account" not in head
    assert "⚠️" not in head


def test_the_order_total_is_stated_beside_the_transaction_cost() -> None:
    body = _deploy_advice(cash="0", amount="50000", price="100", qty=5).render()
    assert "Orders total ₹500.00" in body


def test_the_typed_amount_can_be_a_hard_budget() -> None:
    """A broker balance is not self-describing — the SIP instalment must be spendable-by-choice.

    Cash parked for next month and cash waiting to be deployed look identical from inside the
    advisor; only the person who put it there knows which is which. So this is a switch, not a
    smarter guess.
    """
    cfg = Config()
    portfolio = Portfolio(cfg.cost, cfg.tax, cash=Decimal("500000"))
    target = pd.Series({"A.NS": 0.5, "B.NS": 0.5})
    prices = {"A.NS": Decimal("100"), "B.NS": Decimal("100")}

    capped = advise_deploy(
        portfolio, Decimal("100000"), target, prices, date(2026, 8, 24), spend_idle_cash=False
    )
    assert capped.total_deployed <= Decimal("100000")
    assert capped.held_back == Decimal("500000")
    assert "left untouched" in capped.render()


def test_the_default_still_puts_idle_cash_to_work() -> None:
    """Unchanged contract for every existing caller — the autopilot depends on it."""
    cfg = Config()
    portfolio = Portfolio(cfg.cost, cfg.tax, cash=Decimal("500000"))
    target = pd.Series({"A.NS": 0.5, "B.NS": 0.5})
    prices = {"A.NS": Decimal("100"), "B.NS": Decimal("100")}

    full = advise_deploy(portfolio, Decimal("100000"), target, prices, date(2026, 8, 24))
    assert full.total_deployed > Decimal("500000")
    assert full.held_back == Decimal("0")


def test_a_capped_deploy_sizes_names_against_the_money_actually_being_spent() -> None:
    """Targets computed on cash the user ruled out spending would skew every position."""
    cfg = Config()
    rich = Portfolio(cfg.cost, cfg.tax, cash=Decimal("900000"))
    poor = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    target = pd.Series({"A.NS": 0.5, "B.NS": 0.5})
    prices = {"A.NS": Decimal("100"), "B.NS": Decimal("100")}
    on = date(2026, 8, 24)
    a = advise_deploy(rich, Decimal("100000"), target, prices, on, spend_idle_cash=False)
    b = advise_deploy(poor, Decimal("100000"), target, prices, on, spend_idle_cash=False)
    assert {o.ticker: o.quantity for o in a.buy_orders} == {
        o.ticker: o.quantity for o in b.buy_orders
    }


# ---- advise_raise_cash: the final audit's findings #2 and #3 (2026-08-28) -----------------------
#
# The tab quoted its tax from the frozen backtest engine — which by its own docstring defers §70 loss
# set-off, and calls a lot long-term at 365 days when §2(42A) needs *more than* twelve calendar
# months — then bolted cess on at the end. The Sell tab quoted the ITR figure for the same shares.
# On a lot held exactly 365 days that was ₹620 against ₹32,754. Separately, the panel netted the cash
# against a pre-cess tax while reporting the post-cess one, and its sizing loop made a single pass,
# so it could silently raise less than asked. These are cross-surface and arithmetic properties, not
# assertions on particular rupee values.

_AUDIT_AS_OF = date(2026, 8, 28)


def _boundary_book() -> Portfolio:
    """Winners only, with an ITC lot held EXACTLY 365 days on the valuation date."""
    pf = _pf()
    _add(pf, "ITC.NS", "900", "250.00", date(2025, 8, 28))  # 365 days: STCG in law, LTCG to engine
    _add(pf, "SBIN.NS", "200", "600.00", date(2024, 1, 10))
    _add(pf, "HCLTECH.NS", "60", "1100.00", date(2024, 1, 10))
    return pf


_AUDIT_PRICES = {
    "ITC.NS": Decimal("425.00"),
    "SBIN.NS": Decimal("905.00"),
    "HCLTECH.NS": Decimal("1480.00"),
}


def test_raise_cash_quotes_the_same_tax_engine_as_the_sell_tab() -> None:
    """One book, one day, one set of shares — the two tabs must not disagree about the tax."""
    from qalpha.accounting.capital_gains import (
        apply_long_term_boundary,
        financial_year,
        net_capital_gains_tax,
    )

    cfg = Config()
    pf = _boundary_book()
    advice = advise_raise_cash(pf, Decimal("380000"), _AUDIT_PRICES, _AUDIT_AS_OF, cfg)

    # Replay the plan's own orders through the Sell tab's ITR path and demand the same number.
    clone = pf.clone()
    realized = []
    for o in advice.smart_orders:
        lots, _ = clone.preview_sell(_AUDIT_AS_OF, o.ticker, o.quantity, o.price)
        lots, _demoted = apply_long_term_boundary(lots, cfg.tax)
        realized.extend(lots)
        clone.sell(_AUDIT_AS_OF, o.ticker, o.quantity, o.price)
    itr = sum(
        (
            r.total_tax
            for r in net_capital_gains_tax(
                realized, cfg.tax, exemption_used_by_fy={financial_year(_AUDIT_AS_OF): Decimal("0")}
            )
        ),
        Decimal("0"),
    )
    assert advice.smart_tax == itr


def test_raise_cash_warns_that_a_365_day_lot_is_not_long_term_yet() -> None:
    """§2(42A) needs more than twelve calendar months; the Sell tab says so and this tab now does."""
    advice = advise_raise_cash(
        _boundary_book(), Decimal("380000"), _AUDIT_PRICES, _AUDIT_AS_OF, Config()
    )
    assert advice.boundary_demoted
    assert "NOT long-term yet" in advice.render()


def test_the_raise_cash_panel_adds_up_on_its_own_face() -> None:
    """gross − charges − the tax it reports must equal the cash it says you receive."""
    pf = _pf()
    _add(pf, "SBIN.NS", "600", "600.00", date(2026, 6, 1))  # all short-term winners: nothing is
    _add(pf, "HCLTECH.NS", "200", "1100.00", date(2026, 6, 1))  # hidden inside the FY exemption
    advice = advise_raise_cash(pf, Decimal("400000"), _AUDIT_PRICES, _AUDIT_AS_OF, Config())
    assert advice.smart_tax > 0, "a test that passes only at zero tax proves nothing"
    assert advice.smart_raised == advice.gross_proceeds - advice.charges - advice.smart_tax


def test_raise_cash_keeps_drawing_until_the_target_is_met() -> None:
    """The single-pass loop under-raised whenever tax exceeded its 0.5% price buffer, and said nothing."""
    pf = _pf()
    _add(pf, "SBIN.NS", "600", "600.00", date(2026, 6, 1))
    _add(pf, "HCLTECH.NS", "200", "1100.00", date(2026, 6, 1))
    advice = advise_raise_cash(pf, Decimal("400000"), _AUDIT_PRICES, _AUDIT_AS_OF, Config())
    assert advice.smart_raised >= Decimal("400000")
    assert advice.shortfall == 0


def test_raise_cash_says_so_when_the_book_cannot_cover_the_request() -> None:
    """Falling short is fine; falling short silently is the defect."""
    pf = _pf()
    _add(pf, "SBIN.NS", "10", "600.00", date(2026, 6, 1))
    advice = advise_raise_cash(pf, Decimal("400000"), _AUDIT_PRICES, _AUDIT_AS_OF, Config())
    assert advice.shortfall > 0
    assert "short of the" in advice.render()


def test_raise_cash_exposes_the_lots_the_unverified_branch_warning_reads() -> None:
    """This tab exercises multi-lot/LTCG/set-off/exemption on essentially every use, and never said so."""
    advice = advise_raise_cash(
        _boundary_book(), Decimal("380000"), _AUDIT_PRICES, _AUDIT_AS_OF, Config()
    )
    assert advice.realized, "the warning helper reads `realized`; without it, it silently no-ops"


def test_raise_cash_never_sells_more_than_is_held() -> None:
    """The redraw loop must not walk past a holding's remaining quantity."""
    pf = _boundary_book()
    held = pf.positions()
    advice = advise_raise_cash(pf, Decimal("10000000"), _AUDIT_PRICES, _AUDIT_AS_OF, Config())
    sold: dict[str, Decimal] = {}
    for o in advice.smart_orders:
        sold[o.ticker] = sold.get(o.ticker, Decimal("0")) + o.quantity
    for ticker, qty in sold.items():
        assert qty <= held[ticker]


# ---- tax-loss harvesting (Phase 3, 2026-08-29) ---------------------------------------------------
#
# The tax computation always existed — §70 set-off and the §74 eight-year carry-forward live in
# net_capital_gains_tax. What never existed was a surface saying "these positions are at a loss;
# realising them before 31 March banks a loss carryable eight years"; capital_gains.py:137 calls
# harvesting itself "deferred past Phase 0".
#
# The load-bearing property is FIFO reachability. Lots cannot be chosen — a sale consumes the oldest
# first — so a gain lot in FRONT of a loss lot blocks it, and picking "the losers" by eye can realise
# a gain larger than the loss it was chasing.

_HARVEST_AS_OF = date(2027, 1, 15)


def _harvest_book(*lots: tuple[str, date, str, str]) -> Portfolio:
    pf = _pf()
    for ticker, on, qty, price in lots:
        _add(pf, ticker, qty, price, on)
    return pf


def test_a_plain_loser_is_offered() -> None:
    from qalpha.live.advisor import advise_harvest

    pf = _harvest_book(("A.NS", date(2026, 6, 1), "100", "500"))
    adv = advise_harvest(pf, {"A.NS": Decimal("400")}, _HARVEST_AS_OF, Config())
    (c,) = adv.actionable
    assert c.quantity == Decimal("100")
    assert c.net_gain == Decimal("-10000")
    assert c.gain_crossed == Decimal("0")


def test_a_winner_is_never_offered() -> None:
    from qalpha.live.advisor import advise_harvest

    pf = _harvest_book(("D.NS", date(2026, 6, 1), "10", "100"))
    assert advise_harvest(pf, {"D.NS": Decimal("150")}, _HARVEST_AS_OF, Config()).actionable == []


def test_a_gain_lot_in_front_that_cancels_the_loss_makes_it_unreachable() -> None:
    """The FIFO trap. Selling both lots nets to zero, so there is no loss to bank — offer nothing."""
    from qalpha.live.advisor import advise_harvest

    pf = _harvest_book(
        ("B.NS", date(2026, 5, 1), "50", "100"),  # +₹5,000 at ₹200
        ("B.NS", date(2026, 7, 1), "50", "300"),  # −₹5,000 at ₹200
    )
    assert advise_harvest(pf, {"B.NS": Decimal("200")}, _HARVEST_AS_OF, Config()).actionable == []


def test_a_large_gain_in_front_of_a_small_loss_is_refused() -> None:
    """Selling by eye here would realise ₹15,000 of gain to chase ₹600 of loss."""
    from qalpha.live.advisor import advise_harvest

    pf = _harvest_book(
        ("C.NS", date(2026, 5, 1), "100", "50"),  # +₹15,000 at ₹200
        ("C.NS", date(2026, 7, 1), "10", "260"),  # −₹600
    )
    assert advise_harvest(pf, {"C.NS": Decimal("200")}, _HARVEST_AS_OF, Config()).actionable == []


def test_a_small_gain_in_front_of_a_big_loss_is_crossed_and_disclosed() -> None:
    """Crossing IS correct when the loss behind is worth more — but the crossing must be stated."""
    from qalpha.live.advisor import advise_harvest

    pf = _harvest_book(
        ("E.NS", date(2026, 5, 1), "10", "180"),  # +₹200 at ₹200
        ("E.NS", date(2026, 7, 1), "100", "300"),  # −₹10,000
    )
    adv = advise_harvest(pf, {"E.NS": Decimal("200")}, _HARVEST_AS_OF, Config())
    (c,) = adv.actionable
    assert c.lots_consumed == 2
    assert c.quantity == Decimal("110"), "must sell the whole prefix, not just the loss lot"
    assert c.net_gain == Decimal("-9800")
    assert c.gain_crossed == Decimal("200")
    assert "already netted off" in adv.render()


def test_a_loss_smaller_than_the_round_trip_is_not_worthwhile() -> None:
    """Banking a loss that costs more than it saves is churn wearing a tax costume."""
    from qalpha.live.advisor import advise_harvest

    pf = _harvest_book(("F.NS", date(2026, 6, 1), "1", "100.10"))
    adv = advise_harvest(pf, {"F.NS": Decimal("100")}, _HARVEST_AS_OF, Config())
    assert adv.candidates and adv.candidates[0].net_gain < 0
    assert adv.actionable == [], "a ₹0.10 loss cannot beat the round-trip charges"


def test_it_says_a_banked_loss_is_not_cash_back_when_there_are_no_gains() -> None:
    """His actual position: no realised gains, so the loss carries forward rather than cutting a bill."""
    from qalpha.live.advisor import advise_harvest

    pf = _harvest_book(("A.NS", date(2026, 6, 1), "100", "500"))
    md = advise_harvest(pf, {"A.NS": Decimal("400")}, _HARVEST_AS_OF, Config()).render()
    assert "no realised gains" in md
    assert "carries forward" in md
    assert "not cash back" in md
    assert "file your ITR by the due date" in md


def test_nothing_to_harvest_says_so_plainly() -> None:
    from qalpha.live.advisor import advise_harvest

    pf = _harvest_book(("D.NS", date(2026, 6, 1), "10", "100"))
    assert (
        "Nothing to do"
        in advise_harvest(pf, {"D.NS": Decimal("150")}, _HARVEST_AS_OF, Config()).render()
    )
