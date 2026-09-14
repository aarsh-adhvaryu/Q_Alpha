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
