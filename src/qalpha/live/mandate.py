"""The mandate: everything the investor is allowed to do, in one versioned place.

These numbers were constants in three files. That is survivable while there is one version of one
investor; it stops being survivable the moment a record has to say *which* limits produced it. A
version of this project is a fixed description — model, prompt, packet contents, tools, limits — and
a limit that lives in three files is a limit that can change in one of them.

**The mandate is part of the version.** Changing a number here changes what the record means, so a
change is a new version with its own registration, never an edit to a running one. The defaults
below are the registration's; ``data/mandate.json`` may override them for an experiment, and
whatever was actually in force is written into every receipt.

Nothing here is a preference. Each number is a constraint with a reason, and the reason is next to
it, because a limit whose reason is lost is a limit someone will eventually "tidy up".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Any

MANDATE_PATH = Path("data/mandate.json")


@dataclass(frozen=True)
class Mandate:
    """One investor version's complete set of powers and limits."""

    # ---- identity ---------------------------------------------------------------------------
    #: The version label. Every decision, receipt and logbook entry is stamped with it, and a record
    #: is never relabelled: a different model, prompt, packet or limit is a different version.
    version: str = "AI-PM-2"
    #: Pinned by id. A different model is a different treatment, never a silent swap or a fallback.
    model: str = "claude-sonnet-5"

    # ---- what it may hold -------------------------------------------------------------------
    #: At most this many names after buying. A book of thirty names is an index fund with extra
    #: steps, and one the investor cannot have read the filings of.
    max_names: int = 8
    #: What a **purchase** may take a name or a sector to. A buy is cut to fit; the investor's own
    #: decision never breaches these.
    name_cap: Decimal = Decimal("0.20")
    sector_cap: Decimal = Decimal("0.30")
    #: How far a position may then **drift** on price alone before the investor is asked to look.
    #: A cap that forces a sale the moment the market moves a holding to 20.9% pays capital-gains
    #: tax to undo a gain; this repository has measured that trade and it loses. Buying stays
    #: capped; drift is shown, never acted on by code.
    drift_band: Decimal = Decimal("0.02")
    #: Long-only. There is no borrow, no short, no leverage, and no instrument but listed equity.
    long_only: bool = True

    # ---- what it may spend ------------------------------------------------------------------
    #: Purchases per calendar month, whatever cash the book holds. The user's own plan is a ₹50,000
    #: instalment; a book that spent a year of instalments the day they arrived would be running a
    #: different strategy from the one under test. Sells are never capped — raising cash is always
    #: allowed, and freed cash does not raise the limit.
    monthly_budget: Decimal = Decimal("50000")

    # ---- what it may see --------------------------------------------------------------------
    #: Candidates put in front of it each evening, on top of everything it holds.
    candidates: int = 8
    #: Verified filing/news events per name, most recent first.
    events_per_name: int = 6
    #: Its own past notes per name, and for the portfolio. Its beliefs, never evidence.
    notes_per_name: int = 3
    portfolio_notes: int = 3
    #: Rows of its own scorecard — past decisions and what happened to them.
    scorecard_rows: int = 20
    #: One adjusted-close point per ~month over the trailing year, plus the last close.
    price_step: int = 21
    #: Quarters of filed financials held for each name. More than the four shown, because
    #: year-on-year growth needs the same quarter a year earlier to be on hand.
    financial_quarters: int = 8
    #: Quarters actually rendered into the packet.
    financial_quarters_shown: int = 4

    # ---- what model calls may cost -----------------------------------------------------------
    #: US dollars of priced model calls per calendar month (India time), across everything. A
    #: target the ledger enforces by reserving before each call — see :mod:`qalpha.live.spend`.
    spend_cap_usd: Decimal = Decimal("15")
    #: Of the cap, what is kept for decisions (the evening review and confirmations). Reading and
    #: backfills can never commit more than ``spend_cap_usd - spend_decisions_reserve_usd``, so a
    #: long backfill cannot spend the money the next review needs.
    spend_decisions_reserve_usd: Decimal = Decimal("6")

    # ---- how it runs ------------------------------------------------------------------------
    #: A daily bar is final only after this time on its own day; before it the vendor can serve a
    #: live price, and a live price is not a close.
    evening: time = time(17, 0)
    max_output_tokens: int = 16_000
    #: §2(42A): the holding period that separates short-term from long-term capital gains.
    long_term_days: int = 365

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON, for the receipt that records what was in force."""
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            out[key] = str(value) if isinstance(value, Decimal | time) else value
        return out


DEFAULT = Mandate()


def load(path: Path | None = None) -> Mandate:
    """The mandate in force. The defaults above unless a file deliberately overrides them.

    An unreadable or unknown field is refused rather than ignored: a mandate file that silently
    does nothing is worse than no mandate file, because it looks like it worked.
    """
    # Resolved at CALL time. A default bound at definition time is the module constant as it
    # was on import, so a test that redirects MANDATE_PATH would still read the live file.
    path = MANDATE_PATH if path is None else path
    if not path.exists():
        return DEFAULT
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} is not readable JSON: {exc}") from exc
    fields = {f: getattr(DEFAULT, f) for f in DEFAULT.__dataclass_fields__}
    unknown = sorted(set(raw) - set(fields) - {"_note"})
    if unknown:
        raise ValueError(f"{path} sets fields that are not part of the mandate: {unknown}")
    changes: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "_note":
            continue
        current = fields[key]
        if isinstance(current, Decimal):
            changes[key] = Decimal(str(value))
        elif isinstance(current, time):
            hour, _, minute = str(value).partition(":")
            changes[key] = time(int(hour), int(minute or 0))
        elif isinstance(current, bool):
            changes[key] = bool(value)
        elif isinstance(current, int):
            changes[key] = int(value)
        else:
            changes[key] = value
    return replace(DEFAULT, **changes)


@dataclass(frozen=True)
class Sizing:
    """How intentions become orders when a portfolio is meant to **expand**: breadth and depth.

    Separate from :class:`Mandate` on purpose. AI-PM-2's mandate is written into every AI-PM-2
    receipt; adding these numbers to it would change what a registered version was shown. A version
    that sizes by these rules registers them itself.

    **Nothing here ever sells.** Every rule limits *purchases*. A position that grows past a limit by
    price alone pauses further buying of it and asks for a review; a sale needs its own recorded
    investment or risk reason from the investor.
    """

    name: str
    #: Most names after a **new** purchase. Never a reason to sell; a count above it after a rule
    #: change simply stops new names.
    max_names: int
    #: A purchase may take a name / sector to this share of the book (cash included).
    name_cap: Decimal
    sector_cap: Decimal
    #: Conviction tier → (low, high) target share of the book. ``None``: the investor's desired
    #: exposure is used as given, capped by ``name_cap``.
    tiers: dict[str, tuple[Decimal, Decimal]] | None
    #: A new position opens at least this large, or not at all. ``0``: no minimum. New purchases only.
    min_new_position: Decimal
    #: Monthly purchase allowance, and what unspent allowance may roll up to.
    monthly_allowance: Decimal
    allowance_ceiling: Decimal
    #: Above these, buying that name / sector pauses and the investor is asked to review it.
    review_name_above: Decimal
    review_sector_above: Decimal
    #: A name above this must be addressed at the weekly review (keep, with a reason, or reduce).
    address_name_above: Decimal
    #: Cash above this share of the book for this many months, while candidates qualify, is flagged.
    idle_cash_above: Decimal
    idle_months: int

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in asdict(self).items():
            if isinstance(value, Decimal):
                out[key] = str(value)
            elif isinstance(value, dict):
                out[key] = {k: [str(v) for v in band] for k, band in value.items()}
            else:
                out[key] = value
        return out


#: AI-PM-2's purchase limits, as a sizing rule set: eight names, 20% / 30%, ₹50,000 a month, no
#: rollover, no tiers. The live book keeps these.
CURRENT_SIZING = Sizing(
    name="AI-PM-2-LIMITS",
    max_names=8,
    name_cap=Decimal("0.20"),
    sector_cap=Decimal("0.30"),
    tiers=None,
    min_new_position=Decimal("0"),
    monthly_allowance=Decimal("50000"),
    allowance_ceiling=Decimal("50000"),
    review_name_above=Decimal("0.22"),
    review_sector_above=Decimal("0.32"),
    address_name_above=Decimal("0.30"),
    idle_cash_above=Decimal("0.25"),
    idle_months=2,
)

#: The expanding rules, run first on a shadow book. Each number is a registered choice:
#: tiers scale positions with capital (depth); the name ceiling is the research capacity reviews can
#: sustain (breadth); ₹15,000 is the smallest position worth researching and paying costs on; unspent
#: allowance rolls over up to ₹1,00,000 so a month without conviction is not a month's money lost.
EXPAND_SIZING = Sizing(
    name="EXPAND-1",
    max_names=40,
    name_cap=Decimal("0.20"),
    sector_cap=Decimal("0.30"),
    tiers={
        "core": (Decimal("0.08"), Decimal("0.12")),
        "standard": (Decimal("0.04"), Decimal("0.06")),
        "starter": (Decimal("0.02"), Decimal("0.03")),
    },
    min_new_position=Decimal("15000"),
    monthly_allowance=Decimal("50000"),
    allowance_ceiling=Decimal("100000"),
    review_name_above=Decimal("0.20"),
    review_sector_above=Decimal("0.30"),
    address_name_above=Decimal("0.30"),
    idle_cash_above=Decimal("0.25"),
    idle_months=2,
)
