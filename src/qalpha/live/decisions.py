"""One decision, by one book, on one day — and the reason for it.

The reason is not commentary. It is what makes an autonomous book auditable afterwards: the
difference between "the book changed" and "the book changed *because*".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

HOLD = "HOLD"
BUY = "BUY"
SELL = "SELL"


@dataclass(frozen=True)
class Decision:
    on: date
    book: str
    action: str
    reason: str
    ticker: str | None = None
    quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                f"{self.book} recorded a {self.action} with no reason — an unexplained decision is "
                "not auditable."
            )

    def render(self) -> str:
        what = self.action
        if self.ticker:
            qty = f" {self.quantity}×" if self.quantity is not None else " "
            what = f"{self.action}{qty}{self.ticker}"
        return f"{self.on} · {self.book} · {what} — {self.reason}"


def decisions_markdown(decisions: Sequence[Decision]) -> str:
    """The log. A day with no decision still says so — silence is not the same as not running."""
    if not decisions:
        return "_No decisions recorded._"
    return "\n".join(f"- {d.render()}" for d in decisions)
