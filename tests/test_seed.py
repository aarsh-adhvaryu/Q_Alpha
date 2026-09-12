"""The common starting line — every book seeded from one copy of the reconciled account.

``CORE_V1`` entered the record **already ₹10,293 ahead of SYSTEM**, and the entire gap was that
it did not exist during the fall between 2026-08-29 and 09-07. In the one day both had been alive
they diverged by ₹475. A book cannot out- or under-perform over a period it was not in.

The fix is a common birthday, and these pin it: identical at inception, at cost basis with the real
dates, independent objects, and a reset that cannot happen by accident.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live.account import reconcile
from qalpha.live.seed import (
    AlreadySeededError,
    NotSeedableError,
    UnreadableSeedRecordError,
    identical_at_inception,
    seed_books,
    seed_record,
)
from qalpha.live.session import snapshot_from
from qalpha.live.tradebook import TradebookTrade

CFG = Config()
AS_OF = date(2026, 9, 9)
BOOKS = ("MODEL", "MODEL_NO_AI")
PRICES = {"VBL.NS": Decimal("399.45"), "TCS.NS": Decimal("2203.25")}
BOUGHT_ON = date(2026, 8, 29)


def _trades() -> list[TradebookTrade]:
    return [
        TradebookTrade(
            BOUGHT_ON, "VBL.NS", Side.BUY, Decimal("147"), Decimal("414.23"), "10:00", "1"
        ),
        TradebookTrade(
            BOUGHT_ON, "TCS.NS", Side.BUY, Decimal("10"), Decimal("2340.04"), "10:01", "2"
        ),
    ]


def _account_and_snapshot(**kw: object):
    broker = kw.get("broker", {"VBL.NS": Decimal("147"), "TCS.NS": Decimal("10")})
    acct = reconcile(_trades(), broker, Decimal("201117"), CFG, AS_OF)  # type: ignore[arg-type]
    snap = snapshot_from(
        acct,
        budget=Decimal("50000"),
        universe=("VBL.NS", "TCS.NS"),
        taken_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    return acct, snap


def test_every_book_starts_byte_identical(tmp_path: Path) -> None:
    """The CORE_V1 defect, prevented. Checked rather than assumed, because an inception difference
    is invisible afterwards and shows up months later looking like skill."""
    acct, snap = _account_and_snapshot()
    books, _ = seed_books(acct, snap, BOOKS, CFG, PRICES, path=tmp_path / "seed.json")

    assert set(books) == set(BOOKS)
    assert identical_at_inception(books) == []
    assert books["MODEL"].portfolio.positions() == books["MODEL_NO_AI"].portfolio.positions()
    assert books["MODEL"].portfolio.cash == books["MODEL_NO_AI"].portfolio.cash


def test_the_books_are_separate_objects_not_one_book_with_two_names(tmp_path: Path) -> None:
    """Sharing a portfolio would make every "independent" book the same book, and the ablation
    would measure nothing — which is precisely what a ₹0.00 System − Shadow difference looked like."""
    acct, snap = _account_and_snapshot()
    books, _ = seed_books(acct, snap, BOOKS, CFG, PRICES, path=tmp_path / "seed.json")

    books["MODEL"].portfolio.cash = Decimal("1")
    assert books["MODEL_NO_AI"].portfolio.cash != Decimal("1")
    assert identical_at_inception(books) != [], "and the drift is detectable"


def test_the_books_inherit_the_real_lots_at_cost_with_their_dates(tmp_path: Path) -> None:
    """ "Starts at what my current holding is including the p&l." Re-marking to today would hand
    every book a free reset of a loss actually being carried, and its return would be measured from
    a base that never existed. The LTCG clock is inherited for the same reason."""
    acct, snap = _account_and_snapshot()
    books, record = seed_books(acct, snap, BOOKS, CFG, PRICES, path=tmp_path / "seed.json")

    lots = books["MODEL"].portfolio.ledger.open_lots("VBL.NS")
    assert [lot.acquisition_date for lot in lots] == [BOUGHT_ON], "the purchase date travels"
    assert lots[0].buy_price == Decimal("414.23"), "the execution price is preserved"
    # And the cost basis is HIGHER than it, because brokerage and stamp duty are part of what the
    # shares cost. A basis equal to the execution price would understate cost and therefore
    # overstate every gain computed from it.
    assert lots[0].cost_basis_per_share > lots[0].buy_price
    assert record.cost_basis > 0 and record.holdings == {"VBL.NS": 147, "TCS.NS": 10}


def test_seeding_from_a_book_that_does_not_tally_is_refused(tmp_path: Path) -> None:
    """A book seeded from an account that disagrees with the broker is wrong from its first day, and
    every number it ever produces inherits that."""
    acct, snap = _account_and_snapshot(broker={"VBL.NS": Decimal("294")})
    assert not snap.usable
    with pytest.raises(NotSeedableError, match="does not tally"):
        seed_books(acct, snap, BOOKS, CFG, PRICES, path=tmp_path / "seed.json")


def test_re_seeding_is_refused_because_it_restarts_every_clock(tmp_path: Path) -> None:
    """Run 2 was demoted to "an operational rehearsal" that can never authorise anything because its
    treatment changed inside its own window. Re-seeding is the bigger version of that."""
    p = tmp_path / "seed.json"
    acct, snap = _account_and_snapshot()
    seed_books(acct, snap, BOOKS, CFG, PRICES, path=p)

    with pytest.raises(AlreadySeededError, match="restarts every book's clock"):
        seed_books(acct, snap, BOOKS, CFG, PRICES, path=p)

    again, _ = seed_books(acct, snap, BOOKS, CFG, PRICES, force=True, path=p)
    assert set(again) == set(BOOKS), "explicit force is allowed; silence is not"


def test_the_reset_is_recorded_as_a_fact_not_inferred_from_a_timestamp(tmp_path: Path) -> None:
    p = tmp_path / "seed.json"
    acct, snap = _account_and_snapshot()
    _, record = seed_books(acct, snap, BOOKS, CFG, PRICES, path=p)

    on_disk = seed_record(p)
    assert on_disk == record
    assert on_disk is not None
    assert on_disk.snapshot_digest == snap.digest(), "the books cite the snapshot they came from"
    assert on_disk.seeded_on == AS_OF
    assert set(on_disk.books) == set(BOOKS)


def test_a_damaged_seed_record_does_not_grant_an_accidental_reset(tmp_path: Path) -> None:
    """FOUND IN REVIEW 2026-09-09. Seed once, truncate seed.json, seed again — and it succeeded
    without ``force``, because an unreadable record was read as "never seeded". Corruption is a
    recovery problem; it must never be permission to restart every book's clock."""
    p = tmp_path / "seed.json"
    acct, snap = _account_and_snapshot()
    seed_books(acct, snap, BOOKS, CFG, PRICES, path=p)
    p.write_text("{ truncated", encoding="utf-8")

    with pytest.raises(UnreadableSeedRecordError, match="cannot be read"):
        seed_record(p)
    with pytest.raises(UnreadableSeedRecordError):
        seed_books(acct, snap, BOOKS, CFG, PRICES, path=p)

    # A genuinely absent record is still "never seeded" — that is a different fact.
    assert seed_record(tmp_path / "never-written.json") is None


def test_the_record_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "seed.json"
    acct, snap = _account_and_snapshot()
    _, record = seed_books(acct, snap, BOOKS, CFG, PRICES, path=p)
    assert json.loads(p.read_text(encoding="utf-8"))["snapshot_digest"] == record.snapshot_digest


def test_one_book_alone_cannot_disagree_with_itself(tmp_path: Path) -> None:
    acct, snap = _account_and_snapshot()
    books, _ = seed_books(acct, snap, ("MODEL",), CFG, PRICES, path=tmp_path / "seed.json")
    assert identical_at_inception(books) == []


# --- found in review 2026-09-09 -----------------------------------------------------------------
def test_the_books_start_at_a_zero_return_not_at_their_whole_worth(tmp_path: Path) -> None:
    """FOUND IN REVIEW. The books were seeded with ``flows=[]``, so ``net_invested`` was ₹0 and the
    marking function read ₹2,59,917 of value against ₹0 invested and called the lot of it **gain**.

    That is the ₹4,01,677 defect exactly — parked money counted as performance — and it was one
    function call from a screen. The opening flow is today's MARKET value plus cash, so a book that
    has decided nothing yet reports a zero return.
    """
    acct, snap = _account_and_snapshot()
    books, record = seed_books(acct, snap, BOOKS, CFG, PRICES, path=tmp_path / "seed.json")

    market = Decimal("147") * PRICES["VBL.NS"] + Decimal("10") * PRICES["TCS.NS"]
    expected = market + acct.cash
    assert record.opening_value == expected
    for book in books.values():
        assert [f.amount for f in book.flows] == [expected], "one opening flow, at market"
        assert sum(f.amount for f in book.flows) == expected


def test_the_tax_basis_and_the_performance_basis_are_both_kept_and_are_different(
    tmp_path: Path,
) -> None:
    """You paid ₹414.23, it is worth ₹399.45. The lot keeps ₹414.23 so FIFO and LTCG stay right; the
    opening flow uses ₹399.45 so the book's own decisions start from zero. Both, not either."""
    acct, snap = _account_and_snapshot()
    _, record = seed_books(acct, snap, BOOKS, CFG, PRICES, path=tmp_path / "seed.json")

    assert record.cost_basis > 0
    assert record.opening_value != record.cost_basis, "they are different numbers, kept apart"
    # The inherited loss is real, visible, and not the book's doing.
    inherited = record.opening_value - acct.cash - record.cost_basis
    assert inherited < 0, "these positions are underwater, and the book inherits that"


def test_seeding_refuses_a_holding_with_no_purchase_history(tmp_path: Path) -> None:
    """A RUN tolerates a name bought in Kite; a SEED does not. Seeding claims "this is a copy of your
    account", and a copy whose opening cost basis is a guess makes every gain it reports a guess."""
    acct, snap = _account_and_snapshot(
        broker={"VBL.NS": Decimal("147"), "TCS.NS": Decimal("10"), "HDFCBANK.NS": Decimal("25")}
    )
    assert acct.undated_tickers == ("HDFCBANK.NS",)
    with pytest.raises(NotSeedableError, match="no purchase history"):
        seed_books(
            acct,
            snap,
            BOOKS,
            CFG,
            {**PRICES, "HDFCBANK.NS": Decimal("1900")},
            path=tmp_path / "seed.json",
        )


def test_seeding_refuses_when_a_holding_cannot_be_priced(tmp_path: Path) -> None:
    """Without a price the opening value cannot be computed, and a book seeded without one reports
    its entire worth as gain — which is the defect two tests above."""
    acct, snap = _account_and_snapshot()
    with pytest.raises(NotSeedableError, match="no price for"):
        seed_books(
            acct, snap, BOOKS, CFG, {"VBL.NS": Decimal("399.45")}, path=tmp_path / "seed.json"
        )
