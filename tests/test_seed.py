"""The common starting line — every book seeded from one copy of the reconciled account.

``CORE_V1`` entered the record **already ₹10,293 ahead of TWIN_FULL**, and the entire gap was that
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
    identical_at_inception,
    seed_books,
    seed_record,
)
from qalpha.live.session import snapshot_from
from qalpha.live.tradebook import TradebookTrade

CFG = Config()
AS_OF = date(2026, 9, 9)
BOOKS = ("MODEL", "MODEL_NO_AI")
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
    books, _ = seed_books(acct, snap, BOOKS, CFG, path=tmp_path / "seed.json")

    assert set(books) == set(BOOKS)
    assert identical_at_inception(books) == []
    assert books["MODEL"].portfolio.positions() == books["MODEL_NO_AI"].portfolio.positions()
    assert books["MODEL"].portfolio.cash == books["MODEL_NO_AI"].portfolio.cash


def test_the_books_are_separate_objects_not_one_book_with_two_names(tmp_path: Path) -> None:
    """Sharing a portfolio would make every "independent" book the same book, and the ablation
    would measure nothing — which is precisely what a ₹0.00 System − Shadow difference looked like."""
    acct, snap = _account_and_snapshot()
    books, _ = seed_books(acct, snap, BOOKS, CFG, path=tmp_path / "seed.json")

    books["MODEL"].portfolio.cash = Decimal("1")
    assert books["MODEL_NO_AI"].portfolio.cash != Decimal("1")
    assert identical_at_inception(books) != [], "and the drift is detectable"


def test_the_books_inherit_the_real_lots_at_cost_with_their_dates(tmp_path: Path) -> None:
    """ "Starts at what my current holding is including the p&l." Re-marking to today would hand
    every book a free reset of a loss actually being carried, and its return would be measured from
    a base that never existed. The LTCG clock is inherited for the same reason."""
    acct, snap = _account_and_snapshot()
    books, record = seed_books(acct, snap, BOOKS, CFG, path=tmp_path / "seed.json")

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
        seed_books(acct, snap, BOOKS, CFG, path=tmp_path / "seed.json")


def test_re_seeding_is_refused_because_it_restarts_every_clock(tmp_path: Path) -> None:
    """Run 2 was demoted to "an operational rehearsal" that can never authorise anything because its
    treatment changed inside its own window. Re-seeding is the bigger version of that."""
    p = tmp_path / "seed.json"
    acct, snap = _account_and_snapshot()
    seed_books(acct, snap, BOOKS, CFG, path=p)

    with pytest.raises(AlreadySeededError, match="restarts every book's clock"):
        seed_books(acct, snap, BOOKS, CFG, path=p)

    again, _ = seed_books(acct, snap, BOOKS, CFG, force=True, path=p)
    assert set(again) == set(BOOKS), "explicit force is allowed; silence is not"


def test_the_reset_is_recorded_as_a_fact_not_inferred_from_a_timestamp(tmp_path: Path) -> None:
    p = tmp_path / "seed.json"
    acct, snap = _account_and_snapshot()
    _, record = seed_books(acct, snap, BOOKS, CFG, path=p)

    on_disk = seed_record(p)
    assert on_disk == record
    assert on_disk is not None
    assert on_disk.snapshot_digest == snap.digest(), "the books cite the snapshot they came from"
    assert on_disk.seeded_on == AS_OF
    assert set(on_disk.books) == set(BOOKS)


def test_an_unreadable_seed_record_reads_as_unseeded(tmp_path: Path) -> None:
    p = tmp_path / "seed.json"
    p.write_text("{ not json", encoding="utf-8")
    assert seed_record(p) is None


def test_the_record_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "seed.json"
    acct, snap = _account_and_snapshot()
    _, record = seed_books(acct, snap, BOOKS, CFG, path=p)
    assert json.loads(p.read_text(encoding="utf-8"))["snapshot_digest"] == record.snapshot_digest


def test_one_book_alone_cannot_disagree_with_itself(tmp_path: Path) -> None:
    acct, snap = _account_and_snapshot()
    books, _ = seed_books(acct, snap, ("MODEL",), CFG, path=tmp_path / "seed.json")
    assert identical_at_inception(books) == []
