"""The six the 2026-09-10 review reproduced through the real launcher.

Each was a defect in the running system, not a gap in a plan. They are pinned here as properties, in
the order of how directly they could mislead: money first, then the identity of a decision, then the
inputs behind it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from qalpha.accounting.costs import Side
from qalpha.live.buygate import evaluate
from qalpha.live.commitments import Allowance, Commitment, allowance, current, new_id
from qalpha.live.session import InputSnapshot
from qalpha.live.tradebook import TradebookTrade

TODAY = date(2026, 9, 10)
AUTHORISED = Decimal("50000")


def _c(id_: str, ticker: str, state: str, amount: str, **kw: object) -> Commitment:
    return Commitment(
        id=id_,
        ticker=ticker,
        state=state,  # type: ignore[arg-type]
        amount=Decimal(amount),
        on=kw.get("on", TODAY),  # type: ignore[arg-type]
        reason="",
        filled_on=kw.get("filled_on"),  # type: ignore[arg-type]
    )


def _buy(ticker: str, qty: str, price: str, on: date = TODAY) -> TradebookTrade:
    return TradebookTrade(
        on, ticker, Side.BUY, Decimal(qty), Decimal(price), "10:00", f"{ticker}{qty}"
    )


def _snap() -> InputSnapshot:
    return InputSnapshot(TODAY, datetime.now(UTC), {}, Decimal("12000"), AUTHORISED, ())


# --- 1. a partial fill was erased by the next proposal ------------------------------------------
def test_a_recorded_purchase_cannot_be_un_spent_by_a_later_proposal() -> None:
    """Reproduced: 1 share of VBL bought for ₹82 → spent ₹82; re-proposed the same day → spent ₹0.

    Ids were ``date:ticker``. After a partial fill the row reads ``filled``, so
    ``already_committed`` saw no open decision, the next run proposed the name again, and the new
    row carried the identical id — superseding the fill. Money that moved is not revised by a later
    intention.
    """
    trail = [
        _c(f"{TODAY}:VBL.NS", "VBL.NS", "proposed", "1640"),
        _c(f"{TODAY}:VBL.NS", "VBL.NS", "filled", "82", filled_on=TODAY),
        _c(f"{TODAY}:VBL.NS", "VBL.NS", "proposed", "1558"),  # the collision
    ]
    assert allowance(AUTHORISED, trail, period=TODAY).spent == Decimal("82")
    assert current(trail)[f"{TODAY}:VBL.NS"].state == "filled"


def test_a_second_proposal_on_one_day_gets_its_own_identity() -> None:
    """The other half. A unique id means the collision cannot arise in the first place."""
    first = new_id("VBL.NS", TODAY, [])
    trail = [_c(first, "VBL.NS", "filled", "82", filled_on=TODAY)]
    second = new_id("VBL.NS", TODAY, trail)
    assert first != second
    assert new_id("TCS.NS", TODAY, trail) == f"{TODAY}:TCS.NS", "a fresh name keeps the plain id"


# --- 2. reservations could exceed the cash that exists ------------------------------------------
def test_reserved_money_is_still_in_the_account_and_cannot_be_reserved_twice() -> None:
    """₹12,000 of cash carrying ₹10,000 of reservations still produced another ₹11,882 — ₹21,882
    promised against ₹12,000. Reserved money has not left the account yet, so it must be subtracted
    from the balance before the balance is offered again."""
    reserved = Allowance(AUTHORISED, Decimal("0"), Decimal("10000"))
    gate = evaluate(
        snapshot=_snap(),
        allowance=reserved,
        settled_cash=Decimal("12000"),
        cash_confirmed=True,
        price_as_of=TODAY,
        today=TODAY,
        floor=Decimal("5000"),
    )
    assert gate.budget == Decimal("0")
    assert "already reserved" in gate.explain()


def test_free_cash_above_the_floor_still_produces_a_budget() -> None:
    """The fix must not become "never buy again": ₹40,000 free under a ₹10,000 reservation is real."""
    reserved = Allowance(AUTHORISED, Decimal("0"), Decimal("10000"))
    gate = evaluate(
        snapshot=_snap(),
        allowance=reserved,
        settled_cash=Decimal("100000"),
        cash_confirmed=True,
        price_as_of=TODAY,
        today=TODAY,
        floor=Decimal("5000"),
    )
    assert gate.open and gate.budget == Decimal("40000")


# --- 3. purchases nobody proposed did not spend the month ---------------------------------------
def test_a_purchase_the_system_never_proposed_still_spends_the_allowance() -> None:
    """₹49,766 imported, reconciled correctly — and another ₹49,738 offered, because the allowance
    counted only its own decisions. The mandate limits what goes into the market."""
    trades = [_buy("VBL.NS", "100", "414.23"), _buy("TCS.NS", "5", "1700")]
    left = allowance(AUTHORISED, [], period=TODAY, trades=trades)
    assert left.spent == Decimal("41423") + Decimal("8500")
    assert left.remaining == Decimal("77")


def test_a_confirmed_proposal_is_not_counted_twice() -> None:
    """It is already in ``spent``; counting the same buy again would halve the month for nothing."""
    trades = [_buy("VBL.NS", "100", "414.23")]
    trail = [_c(f"{TODAY}:VBL.NS", "VBL.NS", "filled", "41423", filled_on=TODAY)]
    assert allowance(AUTHORISED, trail, period=TODAY, trades=trades).spent == Decimal("41423")


def test_last_months_purchases_do_not_touch_this_months_allowance() -> None:
    old = [_buy("VBL.NS", "100", "414.23", on=date(2026, 8, 5))]
    assert allowance(AUTHORISED, [], period=TODAY, trades=old).remaining == AUTHORISED


# --- 4/5/6. the inputs behind a decision --------------------------------------------------------
def test_a_stale_column_inside_a_fresh_panel_is_not_marked() -> None:
    """A panel dated 10 September can carry a holding whose last print is 24 July. The panel being
    fresh says nothing about the column, and marking it says "worth this today" about a seven-week-
    old number."""
    import inspect
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import local_run

    src = inspect.getsource(local_run._prices)
    assert "series.index[-1].date()" in src, "each column's own last quote must be read"
    assert "panel_end" in src and "MAX_PRICE_AGE_DAYS" in src


def test_the_fingerprint_covers_the_history_the_strategy_reads() -> None:
    """``cheapness_scores`` ranks on the fall from a rolling 1-YEAR high, so changing a candidate's
    older prices changes the basket. Hashing shape plus the last row left the digest identical."""
    import inspect
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import local_run

    src = inspect.getsource(local_run._panel_sha)
    assert "read_bytes()" in src, "the whole file, not a summary of its last row"
    assert "iloc[-1]" not in src


def test_the_mandates_caps_reach_the_screen() -> None:
    """A configured 20% sector cap produced 26.4% in one sector with no warning, because only
    ``max_names`` was ever passed. A limit that does not reach the caller is a comment."""
    import inspect
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import local_run

    src = inspect.getsource(local_run._proposal)
    assert "max_sector_weight=mandate.max_sector_weight" in src
    assert "max_name_fraction=mandate.max_name_fraction" in src
    assert "load_mandate()" not in src, "the mandate is passed in, not re-read per call"


def test_the_run_passes_the_tradebook_to_the_allowance() -> None:
    """The caller, not the function: ``unproposed_spend`` is worthless if `main` never hands it the
    trades. That is the shape of every defect in this review."""
    import inspect
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import local_run

    src = inspect.getsource(local_run.main)
    assert "trades=trades" in src, "the allowance must see the imported purchases"
