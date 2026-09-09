"""What the system has already decided, and is still living with.

### The behaviour this exists for

*"I just don't want it to invest like — ok, it invested — after running every time. It should
actually take decisions of 'fine, I am waiting on this', or 'this seems to be invested well', then
it monitors."*

A run without memory cannot do that. It computes a basket, and the next run computes it again, and
nothing connects the two. Concretely, before this module:

    cash ₹2,01,117 → offers ₹50,000
    spend it, cash ₹1,51,117 → offers ₹50,000
    spend it, cash ₹1,01,117 → offers ₹50,000

``Mandate.deployable`` is ``min(cash, monthly_budget)`` and is stateless by design — it answers
"what does the mandate allow", not "what is left". This module answers the second, and the two must
never be confused: the allowance is a *fact about this month*, not a fact about the balance.

### A recommendation is not a fill

The distinction the whole module turns on. A proposal reserves allowance the moment it is made, so
the next run cannot propose the same rupees again — but it is **not** spending until a broker trade
confirms it. Kite itself separates orders from executed trades, and so does this:

    WAITING     nothing proposed; the trigger that would justify buying is recorded verbatim
    PROPOSED    put to the user; allowance RESERVED; not yet money
    FILLED      confirmed against the tradebook; allowance SPENT
    ABANDONED   the reason expired or the user declined; allowance RELEASED

An unconfirmed proposal that sits for too long is not quietly promoted to a purchase and not quietly
forgotten — :func:`stale_proposals` names it, because both of those would misstate the account.

### Why WAITING is a first-class state

A candidate the screen liked but could not buy is the thing a memoryless system loses every night.
Recording *what would justify buying it* turns "nothing happened today" into a checkable claim: the
trigger either fired or it did not, and either way the run can say which.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

COMMITMENTS_PATH = Path("data/session/commitments.jsonl")

State = Literal["waiting", "proposed", "filled", "abandoned"]

#: A proposal nobody confirmed within this many days is reported, never auto-promoted or dropped.
STALE_PROPOSAL_DAYS = 5


@dataclass(frozen=True)
class Commitment:
    """One decision the system is still carrying, and why."""

    id: str
    ticker: str
    state: State
    amount: Decimal
    on: date
    reason: str
    #: For ``waiting``: exactly what would justify buying. A wait with no trigger is a shrug.
    trigger: str = ""
    #: Set when a broker trade confirms a proposal. Until then a proposal is not money.
    filled_on: date | None = None

    @property
    def reserves(self) -> bool:
        """Does this hold back allowance? Proposed money is spoken for; waiting money is not."""
        return self.state == "proposed"

    @property
    def spent(self) -> bool:
        return self.state == "filled"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "state": self.state,
            "amount": str(self.amount),
            "on": self.on.isoformat(),
            "reason": self.reason,
            "trigger": self.trigger,
            "filled_on": self.filled_on.isoformat() if self.filled_on else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> Commitment:
        filled = raw.get("filled_on")
        state = str(raw.get("state", "waiting"))
        return cls(
            id=str(raw["id"]),
            ticker=str(raw["ticker"]),
            state=state if state in ("waiting", "proposed", "filled", "abandoned") else "waiting",  # type: ignore[arg-type]
            amount=Decimal(str(raw.get("amount", "0"))),
            on=date.fromisoformat(str(raw["on"])),
            reason=str(raw.get("reason", "")),
            trigger=str(raw.get("trigger", "")),
            filled_on=date.fromisoformat(str(filled)) if filled else None,
        )


def record(commitment: Commitment, path: Path = COMMITMENTS_PATH) -> None:
    """Append one state. Append-only: a proposal that later filled keeps its proposal row.

    The trail is the point. "It bought VBL" is not auditable; "it waited on VBL for nine days citing
    this trigger, proposed on the day the trigger fired, and the fill confirmed two days later" is.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as fh:
            fh.seek(-1, 2)
            needs_newline = fh.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as fh:
        if needs_newline:
            fh.write("\n")
        fh.write(json.dumps(commitment.to_dict()) + "\n")


def load(path: Path = COMMITMENTS_PATH) -> list[Commitment]:
    """Every recorded state, oldest first. A corrupt line costs one row, never the file."""
    if not path.exists():
        return []
    out: list[Commitment] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(Commitment.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError, ValueError, ArithmeticError):
            continue
    return out


def current(commitments: Iterable[Commitment]) -> dict[str, Commitment]:
    """The live view: the latest state per commitment id, in recording order."""
    out: dict[str, Commitment] = {}
    for c in commitments:
        out[c.id] = c
    return out


def _in_period(day: date, period: date) -> bool:
    """Same calendar month. The mandate's allowance is monthly, so the period is a month."""
    return (day.year, day.month) == (period.year, period.month)


@dataclass(frozen=True)
class Allowance:
    """How much of this month's instalment is actually left, and where the rest went."""

    authorised: Decimal
    spent: Decimal
    reserved: Decimal

    @property
    def remaining(self) -> Decimal:
        return max(Decimal("0"), self.authorised - self.spent - self.reserved)

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    def explain(self) -> str:
        """Said out loud, because an allowance that silently reaches zero looks like a broken run."""
        if self.exhausted:
            parts = []
            if self.spent > 0:
                parts.append(f"₹{self.spent:,.0f} already bought")
            if self.reserved > 0:
                parts.append(f"₹{self.reserved:,.0f} proposed and awaiting confirmation")
            return (
                f"This month's ₹{self.authorised:,.0f} is fully committed"
                + (" — " + ", ".join(parts) if parts else "")
                + ". Nothing further is proposed until next month or until a proposal is released."
            )
        return (
            f"₹{self.remaining:,.0f} of this month's ₹{self.authorised:,.0f} is uncommitted"
            + (f" (₹{self.spent:,.0f} bought" if self.spent > 0 else "")
            + (f", ₹{self.reserved:,.0f} awaiting confirmation" if self.reserved > 0 else "")
            + (")" if self.spent > 0 or self.reserved > 0 else "")
            + "."
        )


def allowance(authorised: Decimal, commitments: Iterable[Commitment], *, period: date) -> Allowance:
    """This month's remaining allowance — the fix for "it offers ₹50,000 every single run".

    ``authorised`` is the mandate's monthly instalment. What has already been bought is subtracted,
    and so is anything proposed and not yet confirmed: a proposal that did not reduce the allowance
    would let the next run propose the same rupees again, which is precisely the behaviour being
    removed.
    """
    live = current(commitments).values()
    spent = sum(
        (c.amount for c in live if c.spent and _in_period(c.filled_on or c.on, period)),
        Decimal("0"),
    )
    reserved = sum(
        (c.amount for c in live if c.reserves and _in_period(c.on, period)), Decimal("0")
    )
    return Allowance(authorised=authorised, spent=spent, reserved=reserved)


def waiting(commitments: Iterable[Commitment]) -> list[Commitment]:
    """Candidates the system is watching, and the trigger it is watching for."""
    return [c for c in current(commitments).values() if c.state == "waiting"]


def open_proposals(commitments: Iterable[Commitment]) -> list[Commitment]:
    """Proposed and unconfirmed. These hold allowance and must not be proposed again."""
    return [c for c in current(commitments).values() if c.reserves]


def stale_proposals(
    commitments: Iterable[Commitment], today: date, *, days: int = STALE_PROPOSAL_DAYS
) -> list[Commitment]:
    """Proposals nobody confirmed or declined, past their patience.

    Neither promoted to a purchase nor quietly dropped — both would misstate the account. They are
    named so the user can say which happened, because only he knows whether he placed the order.
    """
    cutoff = today - timedelta(days=days)
    return [c for c in open_proposals(commitments) if c.on <= cutoff]


def already_committed(commitments: Iterable[Commitment], ticker: str) -> Commitment | None:
    """Is there an open decision on this name? Stops a second proposal for the same allocation."""
    for c in current(commitments).values():
        if c.ticker == ticker and c.state in ("proposed", "waiting"):
            return c
    return None


def summary(commitments: Sequence[Commitment], allowance_now: Allowance, today: date) -> str:
    """What the run should say when it did no buying — the difference between a system that is
    waiting on purpose and one that simply did nothing."""
    lines = [allowance_now.explain()]
    for c in sorted(open_proposals(commitments), key=lambda c: c.on):
        age = (today - c.on).days
        lines.append(
            f"• {c.ticker.removesuffix('.NS')} — proposed {c.on} ({age}d ago), "
            f"₹{c.amount:,.0f} reserved, not yet confirmed as bought."
        )
    for c in sorted(waiting(commitments), key=lambda c: c.ticker):
        lines.append(
            f"• {c.ticker.removesuffix('.NS')} — waiting. {c.trigger or 'no trigger recorded'}"
        )
    stale = stale_proposals(commitments, today)
    if stale:
        names = ", ".join(c.ticker.removesuffix(".NS") for c in stale)
        lines.append(
            f"⚠️ {names}: proposed more than {STALE_PROPOSAL_DAYS} days ago and still unconfirmed. "
            "Did you place it? Confirming releases or spends the allowance; only you know which."
        )
    return "\n".join(lines)
