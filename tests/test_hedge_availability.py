"""Can this book hold the smallest hedge that actually exists?"""

from __future__ import annotations

from qalpha.live.hedge import HEDGE_RATIO, NIFTY_LOT_SIZE, hedge_availability


def test_a_three_lakh_book_cannot_hedge_and_the_zero_is_explained() -> None:
    """The user's actual situation, and why TWIN_FULL - TWIN_NO_HEDGE is 0 by construction.

    The overlay needs a WHOLE futures contract. Wiring the returns model in as-is would have
    simulated a fraction of one -- a real number describing an impossible position. The honest
    output is: not purchasable here, and here is the size at which it becomes so.
    """
    a = hedge_availability(300_000, 25_000)
    assert not a.available and a.lots_affordable == 0
    assert "UNAVAILABLE" in a.render()
    assert "not a judgement about hedging" in a.render().lower()


def test_hedging_half_a_book_needs_twice_a_lot_s_notional() -> None:
    """The arithmetic that makes this further away than "one lot costs X" suggests.

        V_min = (lot_size x index) / h

    One contract at index 25,000 is 65 x 25,000 = Rs 16.25L of exposure. Offsetting HALF a book with
    it therefore needs a Rs 32.5L book, not a Rs 16.25L one.
    """
    a = hedge_availability(0, 25_000, lot_size=65, hedge_ratio=0.5)
    assert a.lot_notional == 65 * 25_000
    assert a.book_value_needed == a.lot_notional / 0.5
    assert a.book_value_needed == 3_250_000


def test_availability_flips_exactly_at_the_threshold() -> None:
    a = hedge_availability(0, 25_000, lot_size=65, hedge_ratio=0.5)
    need = a.book_value_needed
    assert not hedge_availability(need - 1, 25_000).available
    assert hedge_availability(need, 25_000).available


def test_lots_are_whole_because_halves_cannot_be_bought() -> None:
    a = hedge_availability(3_250_000 * 2.9, 25_000)
    assert a.lots_affordable == 2, "2.9 lots is 2 lots"


def test_a_zero_index_level_does_not_divide_by_zero() -> None:
    assert hedge_availability(1_000_000, 0.0).lots_affordable == 0


def test_the_lot_size_is_the_verified_one_not_the_first_guess() -> None:
    """It was 75 for three days and 75 was already stale. Pinned so a silent drift is caught.

    NSE rebaselined index-derivative lot sizes at end-December 2025. Nothing in this repo notices a
    contract-spec change on its own, so the number is asserted here and the caveat is asserted below.
    """
    assert NIFTY_LOT_SIZE == 65


def test_the_contract_size_is_flagged_as_needing_verification() -> None:
    """A stale lot size silently mis-states every rupee figure this module produces.

    NSE has revised the Nifty contract size more than once. The constant therefore has to carry its
    own warning where a reader will meet it -- asserted here so the caveat cannot be quietly deleted
    while the number stays.
    """
    import inspect

    from qalpha.live import hedge

    src = inspect.getsource(hedge)
    assert "Re-verify before quoting any rupee figure" in src
    assert NIFTY_LOT_SIZE > 0 and 0 < HEDGE_RATIO <= 1
