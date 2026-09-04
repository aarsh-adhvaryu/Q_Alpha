"""The risk governor — deterministic checks a recommendation must survive (PLAN_SYSTEM §L4).

**Why this layer exists.** The opportunity engine's job is to find things worth buying; it is
optimistic by construction. Nothing downstream of it was ever asked *"and should this be allowed?"*
as a separate question, so every constraint lived inside the thing it was meant to constrain — and a
constraint enforced by the code it constrains is a convention, not an invariant.

The governor is that separate question. It computes what a book would *become* and reports every rule
the outcome breaks. It proposes nothing and never picks a name.

**The first check is here because it was a live defect.** ``deploy_target`` applies the 30% sector cap
to the names selected *that round*. At the documented monthly SIP setting (slider 3–4) the cap is
arithmetically unreachable — with three names one is 33%, so any two in a sector is 67% — and the cap
is silently satisfied by a basket too small to violate it. Twelve individually-compliant monthly
baskets simulated over 2025-08 → 2026-07 produce a book that is **36.9% POWER**, past our own cap,
because nothing had ever measured the *cumulative* mix. Zerodha's Kite nudges on exactly this at 50%
of holdings, which is how the gap became visible: our cap is stricter on paper and weaker in practice,
because it constrains the wrong denominator.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

#: House sector cap, measured on the **resulting book**. Stricter than Kite's 50% holdings nudge.
MAX_SECTOR_WEIGHT = Decimal("0.30")
#: Kite nudges the user at this level of a single sector across total holdings. Reported alongside
#: ours so a breach can be read against the bar the broker itself applies.
KITE_NUDGE_WEIGHT = Decimal("0.50")


@dataclass(frozen=True)
class SectorExposure:
    """One sector's share of the book, before and after a proposed basket."""

    sector: str
    value_before: Decimal
    value_after: Decimal
    weight_before: Decimal
    weight_after: Decimal

    @property
    def breaches_house_cap(self) -> bool:
        return self.weight_after > MAX_SECTOR_WEIGHT

    @property
    def breaches_kite_nudge(self) -> bool:
        return self.weight_after > KITE_NUDGE_WEIGHT

    @property
    def worsens(self) -> bool:
        """Does the basket push this sector further up? A breach already present is not made worse."""
        return self.weight_after > self.weight_before


@dataclass(frozen=True)
class ConcentrationReport:
    """What the book becomes if the proposed orders are placed."""

    exposures: tuple[SectorExposure, ...]
    book_value_after: Decimal

    @property
    def breaches(self) -> tuple[SectorExposure, ...]:
        """House-cap breaches the basket **causes or worsens** — never one it merely inherits.

        A book already over the cap cannot be un-breached by refusing to buy something else, and a
        buy in a *different* sector actively dilutes it. Flagging that would train the reader to
        ignore the flag, which is how a guard dies.
        """
        return tuple(e for e in self.exposures if e.breaches_house_cap and e.worsens)

    @property
    def clear(self) -> bool:
        return not self.breaches

    def render(self) -> str:
        """Plain-English, for a surface where the label becomes an order."""
        if not self.exposures:
            return "No priced holdings to measure sector concentration against."
        lines = []
        for e in sorted(self.exposures, key=lambda x: -x.weight_after):
            mark = ""
            if e.breaches_kite_nudge and e.worsens:
                mark = f"  ⛔ past Kite's {KITE_NUDGE_WEIGHT:.0%} nudge"
            elif e.breaches_house_cap and e.worsens:
                mark = f"  ⚠️ over the {MAX_SECTOR_WEIGHT:.0%} house cap"
            lines.append(
                f"- **{e.sector}** {e.weight_before:.1%} → **{e.weight_after:.1%}**"
                f" (₹{e.value_after:,.0f}){mark}"
            )
        head = (
            "**Sector mix of the resulting book**"
            if self.clear
            else "⚠️ **This basket pushes a sector past the cap**"
        )
        tail = ""
        if not self.clear:
            names = ", ".join(e.sector for e in self.breaches)
            tail = (
                f"\n\nThe per-basket cap did not catch this: it constrains the names chosen *this "
                f"round*, and at 3–4 names a 30% cap cannot bind. {names} is over the cap on the "
                f"**book**, which is the denominator that matters and the one Kite nudges on."
            )
        return head + "\n" + "\n".join(lines) + tail


def sector_concentration(
    holdings: Mapping[str, int],
    orders: Sequence[tuple[str, int, Decimal]],
    prices: Mapping[str, Decimal],
    sector_of: Mapping[str, str],
) -> ConcentrationReport:
    """Sector weights of the book **after** ``orders``, the way Kite computes them.

    Args:
        holdings: ticker → quantity currently held.
        orders: ``(ticker, quantity, price)`` triples proposed for purchase.
        prices: ticker → mark. A holding with no mark is **excluded and cannot be silently valued at
            zero** — omitting it would shrink the denominator and understate every other sector.
        sector_of: ticker → sector. Unknown maps to ``"UNKNOWN"``, which is reported rather than
            dropped, because an unclassified position is still concentration risk.

    Returns:
        A :class:`ConcentrationReport` over every sector present before or after.
    """
    before: dict[str, Decimal] = {}
    after: dict[str, Decimal] = {}

    for ticker, qty in holdings.items():
        price = prices.get(ticker)
        if price is None or qty <= 0:
            continue
        sector = sector_of.get(ticker, "UNKNOWN")
        value = Decimal(qty) * price
        before[sector] = before.get(sector, Decimal(0)) + value
        after[sector] = after.get(sector, Decimal(0)) + value

    for ticker, qty, price in orders:
        if qty <= 0 or price <= 0:
            continue
        sector = sector_of.get(ticker, "UNKNOWN")
        after[sector] = after.get(sector, Decimal(0)) + Decimal(qty) * price

    total_before = sum(before.values(), Decimal(0))
    total_after = sum(after.values(), Decimal(0))
    exposures = tuple(
        SectorExposure(
            sector=sector,
            value_before=before.get(sector, Decimal(0)),
            value_after=after.get(sector, Decimal(0)),
            weight_before=(
                before.get(sector, Decimal(0)) / total_before if total_before > 0 else Decimal(0)
            ),
            weight_after=(
                after.get(sector, Decimal(0)) / total_after if total_after > 0 else Decimal(0)
            ),
        )
        for sector in sorted(set(before) | set(after))
    )
    return ConcentrationReport(exposures=exposures, book_value_after=total_after)
