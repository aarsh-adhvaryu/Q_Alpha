"""Seeding every book from one copy of the reconciled account — the common starting line.

### What this fixes

``CORE_V1`` entered the record on 2026-09-07 **already ₹10,293 ahead of SYSTEM**, and the whole
gap was that it did not exist during the fall between 08-29 and 09-07. In the one day both books had
been alive they diverged by ₹475. A book cannot out- or under-perform over a period it was not in.

The fix is not cleverer accounting, it is a common birthday: **every book is seeded from the same
reconciled account, on the same day, in the same state.** After that they diverge only through their
own decisions, which is the thing being measured.

### Tax basis and performance basis are different things

I got this wrong first time and it is worth stating plainly. Preserving the tax basis and starting
performance at today's market value are **compatible**, not alternatives:

    you paid ₹100 · the share is now ₹90

    tax basis          ₹100 — preserved, with the purchase date. FIFO, LTCG and the §112A
                       boundary all depend on it, and the inherited ₹10 loss is real and visible.
    performance basis   ₹90 — the book starts here. Its decisions have earned nothing at inception,
                       so its return must begin at zero.

Seeding therefore does both: the lots carry their real dates and real cost, **and** an opening flow
equal to today's market value plus cash is recorded, so ``net_invested`` starts at what the book is
actually worth on day one.

Without that flow the books were seeded with ``flows=[]``, and the existing marking function read
₹2,59,917 of value against ₹0 invested and reported the whole thing as **gain**. That is the
₹4,01,677 defect exactly — parked money counted as performance — and it was one function call away
from a screen.

### Seeding is a reset event, and resets are what invalidate experiments

Run 2 was demoted from an experiment to "an operational rehearsal" that can never authorise anything
because its treatment changed inside its own window. Re-seeding is a bigger version of that: it
restarts every clock. So :func:`seed_books` **refuses** unless the caller says so explicitly, and it
records what it copied and from which snapshot, so the reset is a fact on file rather than an
inference from a timestamp.

It also refuses to seed from a snapshot that is not usable. A book seeded from an account that does
not tally with the broker is wrong from its first day, and every number it ever produces inherits
that.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.account import ReconciledAccount
from qalpha.live.session import InputSnapshot
from qalpha.live.track_record import Flow
from qalpha.live.twin import TwinBook

SEED_RECORD = Path("data/session/seed.json")


class AlreadySeededError(RuntimeError):
    """Raised rather than silently re-seeding. Re-seeding restarts every book's clock."""


class NotSeedableError(RuntimeError):
    """The account does not tally, so a book seeded from it is wrong from its first day."""


def _names(value: object) -> tuple[str, ...]:
    return tuple(str(b) for b in value) if isinstance(value, list | tuple) else ()


@dataclass(frozen=True)
class SeedRecord:
    """What was copied, from where, and when. The reset event, on file."""

    seeded_on: date
    snapshot_digest: str
    books: tuple[str, ...]
    holdings: Mapping[str, int]
    cash: Decimal
    #: Cost of the inherited lots — the TAX basis, preserved with the purchase dates.
    cost_basis: Decimal
    #: Market value plus cash on the seeding day — the PERFORMANCE basis, recorded as the opening
    #: flow so every book starts at a zero return. ``opening_value - cost_basis`` is the inherited
    #: P&L, which is real, visible, and not the book's own doing.
    opening_value: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, object]:
        return {
            "seeded_on": self.seeded_on.isoformat(),
            "snapshot_digest": self.snapshot_digest,
            "books": list(self.books),
            "holdings": dict(sorted(self.holdings.items())),
            "cash": str(self.cash),
            "cost_basis": str(self.cost_basis),
            "opening_value": str(self.opening_value),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> SeedRecord:
        held = raw.get("holdings")
        return cls(
            seeded_on=date.fromisoformat(str(raw["seeded_on"])),
            snapshot_digest=str(raw["snapshot_digest"]),
            books=_names(raw.get("books")),
            holdings=(
                {str(k): int(str(v)) for k, v in held.items()} if isinstance(held, dict) else {}
            ),
            cash=Decimal(str(raw.get("cash", "0"))),
            cost_basis=Decimal(str(raw.get("cost_basis", "0"))),
            opening_value=Decimal(str(raw.get("opening_value", "0"))),
        )


class UnreadableSeedRecordError(RuntimeError):
    """The record exists and cannot be read. That is a recovery problem, not permission to restart."""


def seed_record(path: Path = SEED_RECORD) -> SeedRecord | None:
    """The recorded reset, or ``None`` if the books have **never** been seeded.

    A file that exists but cannot be parsed raises. It used to return ``None``, which
    :func:`seed_books` read as "never seeded" — so truncating ``seed.json`` silently bought a full
    reset of every book with no ``force``. Corruption must require recovery; it must never grant
    permission. Verified in review 2026-09-09 by truncating the file and re-seeding successfully.
    """
    if not path.exists():
        return None
    try:
        return SeedRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError) as exc:
        raise UnreadableSeedRecordError(
            f"{path} exists but cannot be read ({exc}). The books may already be seeded; treating "
            "this as unseeded would restart every clock. Restore the file, or pass force=True if a "
            "reset is genuinely intended."
        ) from exc


def _cost_of(portfolio: Portfolio) -> Decimal:
    total = Decimal("0")
    for ticker in portfolio.positions():
        for lot in portfolio.ledger.open_lots(ticker):
            total += lot.cost_basis_per_share * lot.quantity_remaining
    return total


def seed_books(
    account: ReconciledAccount,
    snapshot: InputSnapshot,
    names: Sequence[str],
    cfg: Config,
    prices: Mapping[str, Decimal],
    *,
    force: bool = False,
    path: Path = SEED_RECORD,
) -> tuple[dict[str, TwinBook], SeedRecord]:
    """Create every book as an identical copy of the reconciled account. Once.

    Each book gets its **own** ``Portfolio`` — a state round-trip, not a shared reference — so a
    decision in one cannot silently move another's lots. They start byte-identical and diverge only
    through what they decide.
    """
    if not snapshot.usable:
        raise NotSeedableError(
            "the account does not tally with the broker, so a book seeded from it is wrong from "
            "its first day: " + "; ".join(snapshot.missing_critical)
        )
    # A RUN tolerates a name whose tax history is unknown; a SEED does not. Seeding claims "this is
    # a copy of your account", and a copy whose opening cost basis is a guess makes every gain it
    # ever reports a guess too. Uploading the tradebook is the fix, and it is a fix the user has.
    if account.undated_tickers and not force:
        raise NotSeedableError(
            "these holdings have no purchase history: "
            + ", ".join(t.removesuffix(".NS") for t in account.undated_tickers)
            + ". A seeded book's opening cost basis would be a guess, and every gain measured from "
            "it would inherit that. Upload a tradebook covering them, or pass force=True."
        )
    unpriced = sorted(t for t in account.portfolio.positions() if t not in prices)
    if unpriced:
        raise NotSeedableError(
            "no price for "
            + ", ".join(unpriced)
            + " — the opening value cannot be computed, and a "
            "book seeded without one reports its entire worth as gain."
        )
    existing = seed_record(path)
    if existing is not None and not force:
        raise AlreadySeededError(
            f"seeded on {existing.seeded_on} from snapshot {existing.snapshot_digest}. "
            "Re-seeding restarts every book's clock and ends the comparison in progress — run 2 was "
            "demoted to a rehearsal for exactly this. Pass force=True only if that is intended."
        )

    # THE OPENING FLOW. Without it the books carried flows=[], `net_invested` was ₹0, and the
    # marking function reported the book's entire worth as gain — the ₹4,01,677 defect, one call
    # away from a screen. The flow is today's MARKET value plus cash, not the cost basis: the tax
    # basis stays on the lots, and the book's performance starts at zero because its own decisions
    # have earned nothing yet.
    opening_value = sum(
        (q * prices[t] for t, q in account.portfolio.positions().items()), Decimal("0")
    )
    opening = Flow(on=snapshot.as_of, amount=opening_value + account.cash)

    state = account.portfolio.to_state()
    books = {
        name: TwinBook(
            name=name,
            # from_state per book: separate objects, identical contents. Sharing one portfolio
            # would make every "independent" book the same book with several names.
            portfolio=Portfolio.from_state(json.loads(json.dumps(state)), cfg.cost, cfg.tax),
            flows=[opening],
            stepped_through=None,
        )
        for name in names
    }
    record = SeedRecord(
        seeded_on=snapshot.as_of,
        snapshot_digest=snapshot.digest(),
        books=tuple(names),
        holdings=dict(snapshot.holdings),
        cash=account.cash,
        cost_basis=_cost_of(account.portfolio),
        opening_value=opening.amount,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")
    return books, record


def identical_at_inception(books: Mapping[str, TwinBook]) -> list[str]:
    """Do all the books really start the same? Returns the differences; empty means they do.

    Checked rather than assumed, because "they were seeded together" is exactly the kind of claim
    that stays in a docstring while a refactor quietly breaks it — and an inception difference is
    invisible afterwards, showing up months later as skill.
    """
    if len(books) < 2:
        return []
    items = sorted(books.items())
    (_, first), rest = items[0], items[1:]
    base = first.portfolio.positions()
    base_cash = first.portfolio.cash
    out: list[str] = []
    for name, book in rest:
        if book.portfolio.positions() != base:
            out.append(f"{name}: holdings differ from {items[0][0]}")
        if book.portfolio.cash != base_cash:
            out.append(f"{name}: cash ₹{book.portfolio.cash:,.0f} vs ₹{base_cash:,.0f}")
    return out
