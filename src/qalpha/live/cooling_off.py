"""Deliberate exits — names the user has decided to leave, which the screen must not re-buy.

**The first piece of state in this system that records the user's intent rather than the market's.**
Everything else is derived: prices, health, cheapness, tax. This file is the one place the system is
told something it cannot work out for itself, and that asymmetry is why it is opt-in, expiring, and
always visible rather than a silent filter.

The gap it closes: selling is taxed, buying is not, and the screen has no memory. Sell out of a name
because you have gone off the company, and next month's deploy may re-buy it because it still ranks —
so you paid capital-gains tax to exit something the system re-entered weeks later. Pure waste, and
invisible unless you happen to read the buy list carefully.

Three deliberate design choices:

* **Opt-in, never inferred.** Selling for cash and selling to exit look identical in a tradebook, and
  guessing wrong in either direction is worse than asking. The user ticks a box.
* **It expires.** A view held in August is not evidence about the following June. An exit lapses
  after ``DEFAULT_MONTHS`` unless renewed, so the list cannot quietly ossify into a permanent
  blacklist nobody remembers creating.
* **It blocks buying, never selling.** The system already never sells. This only removes a name from
  the *candidate* side, so the worst it can do is leave money in cash for one deploy.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

COOLING_OFF_PATH = Path("data/cooling_off.json")

#: How long a deliberate exit stands before it lapses. Six months is long enough to cover the
#: re-buy window that motivates this (the screen re-ranks monthly) and short enough that a view
#: formed on old information has to be renewed rather than inherited.
DEFAULT_MONTHS = 6


def _add_months(d: date, months: int) -> date:
    """``d`` plus ``months`` calendar months, clamped to the end of the target month."""
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    last = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ][month - 1]
    return date(year, month, min(d.day, last))


@dataclass(frozen=True)
class Exit:
    """One name the user has decided to leave, and when that decision lapses."""

    ticker: str
    on: date
    months: int = DEFAULT_MONTHS
    reason: str = ""

    @property
    def until(self) -> date:
        return _add_months(self.on, self.months)

    def active_on(self, d: date) -> bool:
        return d < self.until

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "on": self.on.isoformat(),
            "months": self.months,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> Exit:
        return cls(
            ticker=str(raw["ticker"]),
            on=date.fromisoformat(str(raw["on"])),
            months=int(str(raw.get("months") or DEFAULT_MONTHS)),
            reason=str(raw.get("reason", "") or ""),
        )


def load_exits(path: Path = COOLING_OFF_PATH) -> list[Exit]:
    """Every recorded exit, expired ones included (they stay as a record; only *use* expires)."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        raw = json.loads(text)
    except ValueError:
        return []  # a corrupt file must never block a deploy — it fails open, like every guard here
    return [Exit.from_dict(r) for r in raw if isinstance(r, dict) and r.get("ticker")]


def save_exits(exits: Iterable[Exit], path: Path = COOLING_OFF_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [e.to_dict() for e in exits]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record_exit(
    ticker: str,
    on: date,
    *,
    months: int = DEFAULT_MONTHS,
    reason: str = "",
    exits: Iterable[Exit] | None = None,
) -> list[Exit]:
    """Add or refresh an exit. Re-recording the same name **restarts** its clock rather than stacking."""
    kept = [e for e in (exits or []) if e.ticker != ticker]
    return sorted([*kept, Exit(ticker, on, months, reason)], key=lambda e: (e.ticker, e.on))


def clear_exit(ticker: str, exits: Iterable[Exit]) -> list[Exit]:
    """Drop an exit entirely — the user changed their mind and wants the name buyable again."""
    return [e for e in exits if e.ticker != ticker]


def excluded_on(d: date, exits: Iterable[Exit]) -> set[str]:
    """Names the screen must not buy on ``d``. Expired exits fall out on their own."""
    return {e.ticker for e in exits if e.active_on(d)}


def exits_note(d: date, exits: Iterable[Exit]) -> str:
    """The on-screen record — '' when nothing is on cooling-off.

    Always rendered when non-empty. A filter that reflects the user's own past instruction is
    precisely the kind that should never operate silently: six months later, the reason it removed a
    name has to be visible or it becomes indistinguishable from a bug.
    """
    live = sorted((e for e in exits if e.active_on(d)), key=lambda e: e.until)
    if not live:
        return ""
    rows = [
        f"🚫 **{len(live)} name{'s' if len(live) != 1 else ''} you chose to exit — not being bought "
        "back.** You told the system to leave these alone; it lapses on its own unless you renew it:",
    ]
    rows += [
        f"  - **{e.ticker.removesuffix('.NS')}** until {e.until}"
        + (f" — {e.reason}" if e.reason else "")
        for e in live
    ]
    return "\n".join(rows)
