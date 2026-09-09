"""Seeding every book from one copy of the reconciled account — the common starting line.

### What this fixes

``CORE_V1`` entered the record on 2026-09-07 **already ₹10,293 ahead of TWIN_FULL**, and the whole
gap was that it did not exist during the fall between 08-29 and 09-07. In the one day both books had
been alive they diverged by ₹475. A book cannot out- or under-perform over a period it was not in.

The fix is not cleverer accounting, it is a common birthday: **every book is seeded from the same
reconciled account, on the same day, in the same state.** After that they diverge only through their
own decisions, which is the thing being measured.

### Seeded at cost basis, not re-marked to today

The books inherit your positions with their **real acquisition dates and real cost**, which means
they inherit your unrealised P&L — currently −₹11,029 — and your LTCG clocks. Re-marking to today's
price would hand every book a free reset of a loss you are actually carrying, and its "return" would
be measured from a base that never existed.

Because every book inherits the *same* opening loss, it cancels in any comparison between them; and
because the twin measures against **net money in**, it does not distort the returns either.

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
    #: Cost of the inherited lots. With the market value at seeding this states the opening P&L
    #: every book starts with — the number that would otherwise look like performance later.
    cost_basis: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "seeded_on": self.seeded_on.isoformat(),
            "snapshot_digest": self.snapshot_digest,
            "books": list(self.books),
            "holdings": dict(sorted(self.holdings.items())),
            "cash": str(self.cash),
            "cost_basis": str(self.cost_basis),
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
        )


def seed_record(path: Path = SEED_RECORD) -> SeedRecord | None:
    """The recorded reset, or ``None`` if the books have never been seeded."""
    if not path.exists():
        return None
    try:
        return SeedRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        print(f"[seed] {path} is unreadable — treating the books as unseeded")
        return None


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
    existing = seed_record(path)
    if existing is not None and not force:
        raise AlreadySeededError(
            f"seeded on {existing.seeded_on} from snapshot {existing.snapshot_digest}. "
            "Re-seeding restarts every book's clock and ends the comparison in progress — run 2 was "
            "demoted to a rehearsal for exactly this. Pass force=True only if that is intended."
        )

    state = account.portfolio.to_state()
    books = {
        name: TwinBook(
            name=name,
            # from_state per book: separate objects, identical contents. Sharing one portfolio
            # would make every "independent" book the same book with several names.
            portfolio=Portfolio.from_state(json.loads(json.dumps(state)), cfg.cost, cfg.tax),
            flows=[],
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
