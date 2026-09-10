"""May this run propose a purchase, and for how much? One gate, in front of the screen.

### Why this exists

Every safeguard below already existed and was tested. **None of them was in the buying path.** The
local run asked the screen for orders and then rendered whatever came back, so on 2026-09-09 a
review reproduced all of these against the real entry point:

    ₹100 of cash in the account            → proposed ₹49,658 of purchases
    ledger 10 shares vs broker 25          → snapshot.usable False, basket produced anyway
    broker unreachable                     → cash silently became ₹0, saved, still proposed
    ₹49,766 of purchases already imported  → still offered the full ₹50,000
    prices three months stale              → four recommendations, snapshot marked fresh

That is rule 4 in CLAUDE.md — *"Test the caller, not only the function"* — and every one of these is
a function that passed its own tests while nothing called it.

### The rule

**Zero is a real answer, and it always comes with a reason.** A gate that closes silently looks
identical to a screen that found nothing, and those are completely different facts. So the budget
and the reasons travel together, and a closed gate is rendered as a sentence rather than as an
empty basket.

Pure: no I/O, no clock of its own. Everything it judges is passed in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from qalpha.live.commitments import Allowance
from qalpha.live.session import InputSnapshot

#: Prices older than this cannot support a purchase proposal. A basket priced off a three-month-old
#: panel is a historical diagnostic, and calling it a recommendation is the whole defect.
MAX_PRICE_AGE_DAYS = 4


@dataclass(frozen=True)
class BuyGate:
    """How much may be proposed, and — always — why it is not more."""

    budget: Decimal
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def open(self) -> bool:
        return self.budget > 0

    def explain(self) -> str:
        if self.open and not self.reasons:
            return f"Proposing against {_inr(self.budget)}."
        head = (
            f"Proposing against {_inr(self.budget)}, held down by:"
            if self.open
            else "**No basket this run.**"
        )
        return head + " " + " ".join(self.reasons)


def _inr(value: Decimal) -> str:
    return f"₹{float(value):,.0f}"


def evaluate(
    *,
    snapshot: InputSnapshot,
    allowance: Allowance,
    settled_cash: Decimal | None,
    cash_confirmed: bool,
    price_as_of: date | None,
    today: date,
    floor: Decimal,
) -> BuyGate:
    """Decide the budget. Each check can only ever *reduce* it, and each names itself.

    ``settled_cash`` is ``None`` when the balance is genuinely unknown — which is different from
    zero and must never be rendered as it. ``cash_confirmed`` is False when the figure came from a
    saved snapshot rather than from the broker just now: usable for display, not for spending.
    """
    reasons: list[str] = []

    if not snapshot.usable:
        return BuyGate(
            Decimal("0"),
            (
                "The account does not reconcile with the broker — "
                + "; ".join(snapshot.missing_critical)
                + ". Nothing is proposed on a book that does not match reality.",
            ),
        )

    if settled_cash is None:
        return BuyGate(
            Decimal("0"),
            (
                "The cash balance is unknown — the broker was not reachable and no earlier figure "
                "is on file. Unknown is not zero, and neither is a basis for buying.",
            ),
        )

    if not cash_confirmed:
        return BuyGate(
            Decimal("0"),
            (
                f"The balance shown ({_inr(settled_cash)}) is the last one on file, not confirmed "
                "with the broker just now. Log in and run again before buying against it.",
            ),
        )

    if price_as_of is None:
        return BuyGate(
            Decimal("0"), ("No price data, so nothing can be priced, let alone proposed.",)
        )

    age = (today - price_as_of).days
    if age > MAX_PRICE_AGE_DAYS:
        return BuyGate(
            Decimal("0"),
            (
                f"The newest prices are from {price_as_of}, {age} days old. A basket priced off "
                "that is a historical diagnostic, not a recommendation — refresh the panel first.",
            ),
        )

    budget = allowance.remaining
    if budget <= 0:
        return BuyGate(Decimal("0"), (allowance.explain(),))

    # THE ONE THAT LET ₹100 BUY ₹49,658. The allowance says what the mandate permits this month; the
    # balance says what exists. A basket may never exceed either.
    #
    # And the cash that matters is UNSPOKEN-FOR cash. Money already reserved by an unconfirmed
    # proposal is still sitting in the account — it has not left yet — so comparing the new budget
    # against the raw balance let ₹12,000 of cash carry ₹10,000 of reservations and then take
    # another ₹11,882: ₹21,882 promised against ₹12,000. Reservations are subtracted first.
    free_cash = settled_cash - allowance.reserved
    if allowance.reserved > 0:
        reasons.append(
            f"{_inr(allowance.reserved)} of the {_inr(settled_cash)} balance is already reserved by "
            f"an unconfirmed proposal, leaving {_inr(max(Decimal('0'), free_cash))} unspoken for."
        )
    if free_cash < budget:
        reasons.append(
            f"{_inr(max(Decimal('0'), free_cash))} of free cash is less than the {_inr(budget)} "
            "allowance remaining, so the cash is the limit."
        )
        budget = max(Decimal("0"), free_cash)

    if budget < floor:
        return BuyGate(
            Decimal("0"),
            (
                *reasons,
                f"{_inr(budget)} is below the {_inr(floor)} deploy floor — a basket this small pays "
                "a round trip to do nothing.",
            ),
        )
    return BuyGate(budget, tuple(reasons))


def describe(gate: BuyGate, extra: Sequence[str] = ()) -> list[str]:
    """The gate's reasons as page notes, so a closed gate is never a blank section."""
    return [*gate.reasons, *extra]
