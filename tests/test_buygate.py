"""The gate in front of the screen — every check that existed and was never called.

**Found in review 2026-09-09, reproduced against the real entry point.** Each of these safeguards
was already written and already tested. None was in the buying path:

    ₹100 of cash in the account            → proposed ₹49,658 of purchases
    ledger 10 shares vs broker 25          → snapshot.usable False, basket produced anyway
    broker unreachable                     → cash silently became ₹0, saved, still proposed
    ₹49,766 of purchases already imported  → still offered the full ₹50,000
    prices three months stale              → four recommendations, snapshot marked fresh

That is rule 4 in CLAUDE.md — *"Test the caller, not only the function"* — and it is what these
tests are for. The last one matters as much as the rest: **a healthy account must still get its
basket**, or the fix is just a system that never buys.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from qalpha.live.buygate import MAX_PRICE_AGE_DAYS, evaluate
from qalpha.live.commitments import Allowance
from qalpha.live.session import InputSnapshot

TODAY = date(2026, 9, 9)
FRESH = date(2026, 9, 8)
FLOOR = Decimal("5000")
FULL = Allowance(Decimal("50000"), Decimal("0"), Decimal("0"))


def _snap(**kw: object) -> InputSnapshot:
    base: dict[str, object] = {
        "as_of": TODAY,
        "taken_at": datetime(2026, 9, 9, tzinfo=UTC),
        "holdings": {"VBL.NS": 147},
        "cash": Decimal("201117"),
        "budget": Decimal("50000"),
        "universe": ("VBL.NS",),
    }
    base.update(kw)
    return InputSnapshot(**base)  # type: ignore[arg-type]


def _gate(**kw: object):
    args: dict[str, object] = {
        "snapshot": _snap(),
        "allowance": FULL,
        "settled_cash": Decimal("201117"),
        "cash_confirmed": True,
        "price_as_of": FRESH,
        "today": TODAY,
        "floor": FLOOR,
    }
    args.update(kw)
    return evaluate(**args)  # type: ignore[arg-type]


def test_a_healthy_account_still_gets_its_basket() -> None:
    """First, because a gate that never opens is not a fix — it is a system that cannot buy."""
    gate = _gate()
    assert gate.open and gate.budget == Decimal("50000")
    assert gate.reasons == ()


def test_the_basket_can_never_exceed_the_cash_that_exists() -> None:
    """₹100 in the account bought a ₹49,658 basket. The allowance says what the mandate permits;
    the balance says what exists; a basket may never exceed either."""
    gate = _gate(settled_cash=Decimal("100"))
    assert not gate.open
    assert "below the ₹5,000 deploy floor" in gate.explain()

    partial = _gate(settled_cash=Decimal("12000"))
    assert partial.budget == Decimal("12000"), "cash below the allowance becomes the limit"
    assert "is the limit" in partial.explain()


def test_a_book_that_does_not_reconcile_proposes_nothing() -> None:
    gate = _gate(snapshot=_snap(missing_critical=("quantities disagree with the broker",)))
    assert not gate.open
    assert "does not reconcile" in gate.explain()


def test_unknown_cash_is_not_zero_and_is_not_a_basis_for_buying() -> None:
    """The broker outage that rewrote ₹2,01,117 as a confirmed ₹0 and kept proposing."""
    gate = _gate(settled_cash=None, cash_confirmed=False)
    assert not gate.open
    assert "Unknown is not zero" in gate.explain()


def test_a_last_known_balance_may_be_shown_but_never_spent() -> None:
    """A figure from the last snapshot is fine on the page and is not confirmation. The distinction
    is the whole reason the gate takes ``cash_confirmed`` separately from the number."""
    gate = _gate(settled_cash=Decimal("201117"), cash_confirmed=False)
    assert not gate.open
    assert "not confirmed with the broker just now" in gate.explain()


def test_an_allowance_already_spent_offers_nothing_further() -> None:
    """₹49,766 of purchases imported, and it still offered ₹50,000."""
    spent = Allowance(Decimal("50000"), Decimal("49766"), Decimal("0"))
    assert not _gate(allowance=spent).open


def test_money_reserved_by_an_unconfirmed_proposal_is_not_offered_again() -> None:
    reserved = Allowance(Decimal("50000"), Decimal("0"), Decimal("50000"))
    gate = _gate(allowance=reserved)
    assert not gate.open
    assert "fully committed" in gate.explain()


def test_stale_prices_make_a_diagnostic_not_a_recommendation() -> None:
    """Run on 9 September against prices ending 11 June: four purchase recommendations."""
    gate = _gate(price_as_of=date(2026, 6, 11))
    assert not gate.open
    assert "90 days old" in gate.explain() and "historical diagnostic" in gate.explain()

    edge = _gate(price_as_of=TODAY - __import__("datetime").timedelta(days=MAX_PRICE_AGE_DAYS))
    assert edge.open, "exactly at the limit is still usable; one day past is not"


def test_no_prices_at_all_proposes_nothing() -> None:
    assert not _gate(price_as_of=None).open


def test_a_closed_gate_always_says_why() -> None:
    """A gate that closes silently looks identical to a screen that found nothing, and those are
    completely different facts. Every closed path must carry a sentence."""
    for kw in (
        {"settled_cash": None, "cash_confirmed": False},
        {"snapshot": _snap(missing_critical=("x",))},
        {"price_as_of": None},
        {"price_as_of": date(2026, 1, 1)},
        {"allowance": Allowance(Decimal("50000"), Decimal("50000"), Decimal("0"))},
        {"settled_cash": Decimal("10")},
    ):
        gate = _gate(**kw)
        assert not gate.open
        assert gate.reasons, f"closed with no reason: {kw}"
        assert gate.explain().strip() not in ("", "**No basket this run.**")
