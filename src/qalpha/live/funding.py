"""External funding: money that entered or left the broker account, and nothing else.

**Why this is not the tradebook.** The books were funded by what the tradebook showed *spent on
shares* — so a deposit that had not been invested yet did not exist to them, and the ₹2,01,117
sitting in the account was outside every comparison. Two different things were both being called
"invested": money put in, and money put to work. This file is the first: dated deposits and
withdrawals, read from the broker's ledger.

**It carries no personal data.** The ledger names a client id in every line of its description — and
in its file name — so only the date, the amount and the voucher type survive the import, and the
provenance is the statement's kind plus a digest of its bytes. That still identifies *which* export
this came from, to anyone holding the file, without publishing the account number: this record is
committed and the statement it came from is not.

A settlement is not funding. It moves money between cash and shares *inside* the account, and
counting it would report a ₹3 lakh purchase as ₹3 lakh of new money.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from qalpha.live.flows import Flow

FUNDING_PATH = Path("data/twin/funding.json")


@dataclass(frozen=True)
class Movement:
    """One external cash movement. Positive into the account, negative out."""

    on: date
    amount: Decimal
    kind: str  # the broker's own voucher type, e.g. "Bank Receipts"


@dataclass(frozen=True)
class Funding:
    """Everything the ledger says about money crossing the account boundary."""

    movements: tuple[Movement, ...]
    #: The broker's own closing balance, kept so the modelled cash can be checked against it.
    closing_balance: Decimal
    #: Which statement this came from and when it was imported — provenance, not the file itself,
    #: and never its name: a Zerodha export is named for the client id.
    source: str
    imported_at: str

    @property
    def net(self) -> Decimal:
        return sum((m.amount for m in self.movements), Decimal("0"))

    def flows(self) -> list[Flow]:
        """One flow per day, oldest first — the shape every book is funded with."""
        by_day: dict[date, Decimal] = {}
        for m in self.movements:
            by_day[m.on] = by_day.get(m.on, Decimal("0")) + m.amount
        return [Flow(on=day, amount=by_day[day]) for day in sorted(by_day) if by_day[day] != 0]


def provenance(statement: Path) -> str:
    """Identify a statement without naming its owner: its kind, and a digest of its bytes.

    The file name is ``ledger-<client id>.xlsx``. Recording it would have put the account number
    into a tracked file, which is the one thing this module exists to prevent. The digest still
    answers "is this the export that produced the record?" for anyone holding the export.
    """
    import hashlib

    kind = statement.stem.split("-", 1)[0] or "statement"
    digest = hashlib.sha256(statement.read_bytes()).hexdigest()[:12]
    return f"{kind} · sha256:{digest}"


def save(funding: Funding, path: Path = FUNDING_PATH) -> None:
    from qalpha.live import atomic

    atomic.write_text(
        path,
        json.dumps(
            {
                "source": funding.source,
                "imported_at": funding.imported_at,
                "closing_balance": str(funding.closing_balance),
                "movements": [
                    {"on": m.on.isoformat(), "amount": str(m.amount), "kind": m.kind}
                    for m in funding.movements
                ],
            },
            indent=2,
        )
        + "\n",
    )


def load(path: Path = FUNDING_PATH) -> Funding | None:
    """The imported funding, or ``None`` when none has been imported. Never a guess."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Funding(
            movements=tuple(
                Movement(
                    on=date.fromisoformat(str(m["on"])),
                    amount=Decimal(str(m["amount"])),
                    kind=str(m.get("kind", "")),
                )
                for m in raw["movements"]
            ),
            closing_balance=Decimal(str(raw.get("closing_balance", "0"))),
            source=str(raw.get("source", "")),
            imported_at=str(raw.get("imported_at", "")),
        )
    except (OSError, ValueError, KeyError):
        print(f"[funding] {path} is unreadable — treating funding as not imported")
        return None
