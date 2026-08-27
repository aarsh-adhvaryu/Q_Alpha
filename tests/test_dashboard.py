"""The Live tab's account tiles (design import, 2026-08-26).

Imported from the Zerodha-profile design project, whose own figures make the contract explicit:
Equity ₹1,91,312 + Cash ₹7,335 = the ₹1,98,647 account total in its allocation ring. Its "Equity"
is holdings **only** — and the shipped tile was ``market_value``, which includes cash.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.dashboard import account_overview, idle_cash_note

# ---- account overview tiles (design import, 2026-08-26) ------------------------------------------


def _acct(cash: str, *, buys: tuple[tuple[str, int, str], ...] = ()) -> Portfolio:
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal(cash))
    for ticker, qty, price in buys:
        pf.cash += Decimal(qty) * Decimal(price) * Decimal("1.01")
        pf.buy(date(2026, 6, 1), ticker, Decimal(qty), Decimal(price))
    pf.cash = Decimal(cash)
    return pf


def test_equity_is_shares_only_and_never_counts_the_cash_balance() -> None:
    """The old tile used ``market_value``, which includes cash.

    On an account holding a year of SIP instalments — ₹5,00,000 parked against ₹0 of stock — it read
    ₹5,00,000 of "Equity". Same defect family as the deploy heading that turned an 11-share order
    into 64: an amount labelled as something it is not, on the surface where buying happens.
    """
    pf = _acct("500000")
    ov = account_overview(pf, {})
    assert ov.holdings_value == Decimal("0")
    assert ov.cash == Decimal("500000")
    assert ov.account_total == Decimal("500000")
    assert pf.market_value({}) == Decimal("500000")  # the number the old tile showed as Equity


def test_the_two_tiles_add_up_to_the_account_total() -> None:
    """The imported design's own figures assert this: 1,91,312 + 7,335 = its 1,98,647 ring total."""
    pf = _acct("7335", buys=(("A.NS", 100, "1000"),))
    ov = account_overview(pf, {"A.NS": Decimal("1913.12")})
    assert ov.holdings_value + ov.cash == ov.account_total
    assert ov.cash_pct is not None
    assert abs(ov.cash_pct - float(ov.cash / ov.account_total * 100)) < 1e-9


def test_unrealised_pnl_is_measured_against_what_was_actually_paid() -> None:
    pf = _acct("0", buys=(("A.NS", 10, "100"),))
    ov = account_overview(pf, {"A.NS": Decimal("150")})
    assert ov.invested > Decimal("1000")  # cost basis includes the buy charges
    assert ov.unrealised == ov.holdings_value - ov.invested
    assert ov.unrealised_pct is not None and ov.unrealised_pct > 0


def test_a_partial_days_move_is_withheld_rather_than_reported_as_the_accounts() -> None:
    """Off-watchlist names are exactly the ones with no previous close, so partial is the common case.

    A day's P&L over some holdings reads as the whole account's move and is wrong invisibly.
    """
    pf = _acct("0", buys=(("A.NS", 10, "100"), ("B.NS", 10, "100")))
    prices = {"A.NS": Decimal("110"), "B.NS": Decimal("110")}
    assert account_overview(pf, prices, previous_close={"A.NS": Decimal("100")}).day_change is None
    full = account_overview(
        pf, prices, previous_close={"A.NS": Decimal("100"), "B.NS": Decimal("100")}
    )
    assert full.day_change == Decimal("200")


def test_an_unpriced_holding_is_named_never_valued_at_zero() -> None:
    pf = _acct("0", buys=(("A.NS", 10, "100"), ("GHOST.NS", 5, "50")))
    ov = account_overview(pf, {"A.NS": Decimal("100")})
    assert ov.unpriced == ("GHOST.NS",)
    assert ov.day_change is None  # cannot state a day's move over a book it cannot fully mark


def test_an_empty_account_reports_no_percentages_rather_than_dividing_by_zero() -> None:
    ov = account_overview(_acct("0"), {})
    assert ov.cash_pct is None
    assert ov.unrealised_pct is None
    assert ov.day_change_pct is None


def test_idle_cash_below_the_floor_says_there_is_nothing_to_do() -> None:
    note = idle_cash_note(Decimal("3000"), Decimal("5000"))
    assert "below the floor" in note
    assert "Nothing to do" in note


def test_idle_cash_above_the_floor_says_only_the_typed_amount_is_spent() -> None:
    """The line that would have prevented the 64-share order — state the deploy contract here too."""
    note = idle_cash_note(Decimal("500000"), Decimal("5000"))
    assert "₹500,000" in note
    assert "only that amount is spent" in note
