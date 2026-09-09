"""The mandate — every limit the live layer obeys, stored once.

### Why this exists

Gate 1 asks that the budget and the risk limits be **stored once**. Before this module they were
scattered across three kinds of place, and two of them were not storage at all:

    cfg.deploy_policy.idle_cash_floor        a config field          (frozen, rule (a))
    cfg.deploy_policy.max_names_default      a config field          (frozen, rule (a))
    max_sector_weight: float = 0.30          a FUNCTION DEFAULT      in advise_deploy_into_weakness
    max_name_fraction: float = 0.20          a FUNCTION DEFAULT      in advise_deploy_into_weakness
    "type 50000"                             a sentence in OPERATING.md

A limit that lives in a function signature is not a mandate, it is an implementation detail that
happens to be load-bearing — and one nobody can read, change, or audit without reading the code.

**This does not change any number.** Every default below is the value already in force; the point is
that there is now one place to read them from and one place to change them. `src/qalpha/config.py`
is frozen under rule (a), so this lives in `live/` and is loaded from `data/mandate.json` when that
file exists.

### The reserved-cash rule, and where it comes from

`OPERATING.md` says: *"Add money → type the amount. Type `50000`. The number you type is a hard
budget"*, and *"Money for future instalments **stays in the broker account**. That is intended: the
system counts it and does not treat it as performance."*

So the broker balance is **not** the budget. On 2026-09-09 the account held ₹201,117 of settled
cash, of which one monthly instalment is deployable and the rest is next month's and the month
after's. `advisor.py` already knew it could not tell them apart — *"SIP instalment and cash waiting
to be deployed look identical from here; only the person who put it there knows which"* — and the
dashboard's auto brief nonetheless sized a basket against the whole balance.

:attr:`Mandate.monthly_budget` is that missing fact, taken from the operating page rather than
invented. :meth:`deployable` applies it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path

#: Where a customised mandate lives. Absent is normal: the defaults below are the live values.
MANDATE_PATH = Path("data/mandate.json")


@dataclass(frozen=True)
class Mandate:
    """What this account is allowed to do. Read it; never re-derive it from a call site."""

    #: One instalment. The most that may be proposed in a single deploy, however much cash is idle.
    #: From OPERATING.md §1 — "Type 50000".
    monthly_budget: Decimal = Decimal("50000")
    #: Below this, idle cash is not worth deploying and the page stops nudging.
    idle_cash_floor: Decimal = Decimal("5000")
    #: Names in a monthly basket. OPERATING.md: "slider 8 for the opening ₹1,00,000, 3–4 monthly".
    max_names: int = 4
    #: No single name may exceed this share of equity.
    max_name_fraction: float = 0.20
    #: No sector may exceed this share. **Measured on the book, not on one basket** — twelve
    #: individually-compliant baskets compound into a book that is half one sector, which is the
    #: breach that actually happens and the one a per-basket check cannot see.
    max_sector_weight: float = 0.30

    def deployable(self, available_cash: Decimal) -> Decimal:
        """How much of the broker balance may be proposed today.

        ``min(cash, monthly_budget)`` — never the whole balance. The account holds several future
        instalments and the system cannot tell which rupee is which, so it proposes at most one.
        Returns zero below the floor rather than a token amount.
        """
        if available_cash < self.idle_cash_floor:
            return Decimal("0")
        return min(available_cash, self.monthly_budget)

    def reserved(self, available_cash: Decimal) -> Decimal:
        """The part of the balance this mandate will not touch. Stated so it can be shown, not
        silently withheld — an amount that vanishes without explanation reads as a bug."""
        return max(Decimal("0"), available_cash - self.deployable(available_cash))

    def to_dict(self) -> dict[str, object]:
        return {
            "monthly_budget": str(self.monthly_budget),
            "idle_cash_floor": str(self.idle_cash_floor),
            "max_names": self.max_names,
            "max_name_fraction": self.max_name_fraction,
            "max_sector_weight": self.max_sector_weight,
        }


def load_mandate(path: Path = MANDATE_PATH) -> Mandate:
    """The mandate in force. A missing or unreadable file yields the documented defaults.

    Fail-soft on purpose: a malformed mandate must not take the page down, and the defaults are the
    values already in force, so falling back to them changes nothing. It says so loudly instead.
    """
    base = Mandate()
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"[mandate] {path} is unreadable — using the documented defaults")
        return base
    fields: dict[str, object] = {}
    for key in ("monthly_budget", "idle_cash_floor"):
        if key in raw:
            try:
                fields[key] = Decimal(str(raw[key]))
            except (ArithmeticError, ValueError):
                print(f"[mandate] {key}={raw[key]!r} is not a number — keeping the default")
    if "max_names" in raw:
        try:
            fields["max_names"] = int(raw["max_names"])
        except (TypeError, ValueError):
            print(
                f"[mandate] max_names={raw['max_names']!r} is not an integer — keeping the default"
            )
    for key in ("max_name_fraction", "max_sector_weight"):
        if key in raw:
            try:
                value = float(raw[key])
            except (TypeError, ValueError):
                print(f"[mandate] {key}={raw[key]!r} is not a number — keeping the default")
                continue
            # A cap outside (0, 1] is not a stricter rule, it is a typo — 20 meaning "20%" would
            # disable the cap entirely, which is the direction that loses money quietly.
            if not 0 < value <= 1:
                print(f"[mandate] {key}={value} is not a fraction in (0, 1] — keeping the default")
                continue
            fields[key] = value
    return replace(base, **fields)  # type: ignore[arg-type]
