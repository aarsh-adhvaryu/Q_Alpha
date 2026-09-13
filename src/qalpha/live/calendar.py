"""Whether the exchange traded on a given day, and what to call the day if it did not.

**The panel decides; this names.** Whether a session happened is read from the price panel — a bar
exists or it does not. This module supplies the *reason* a weekday has no bar, so a run can say
"Ganesh Chaturthi" or "Sunday" instead of reporting a missing price, and can tell a holiday apart
from a download that failed.

The holiday list is what we know, not what exists. **A weekday absent from it is not proof that the
exchange traded** — that is why nothing here decides anything: :func:`closure_reason` returning
``None`` on a weekday means "no known closure", and the caller must still find a real bar.
"""

from __future__ import annotations

from datetime import date

#: NSE cash-market closures, from the exchange's own circular (NSE/CMTR/71775, 12 December 2025).
#: Update from the next year's circular; an out-of-date list makes a run say "no known closure"
#: about a real holiday, which is honest, rather than inventing a session.
KNOWN_CLOSURES: dict[date, str] = {
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 4): "Holi",
    date(2026, 3, 21): "Id-ul-Fitr (Ramzan Id)",
    date(2026, 3, 26): "Ram Navami",
    date(2026, 3, 31): "Mahavir Jayanti",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 27): "Bakri Id",
    date(2026, 6, 26): "Muharram",
    date(2026, 8, 15): "Independence Day",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 10): "Diwali-Balipratipada",
    date(2026, 11, 24): "Guru Nanak Dev Jayanti",
    date(2026, 12, 25): "Christmas",
}


def closure_reason(day: date) -> str | None:
    """Why the exchange was shut, or ``None`` when no closure is known for that day."""
    if day.weekday() >= 5:
        return day.strftime("%A")
    return KNOWN_CLOSURES.get(day)


def describe(day: date, *, traded: bool) -> str:
    """One sentence about a day, for a page or a log line.

    ``traded`` comes from the price panel, never from this module: a bar exists or it does not.
    """
    name = day.strftime("%A %d %b %Y")
    if traded:
        return f"{name} — a trading session"
    reason = closure_reason(day)
    if reason:
        return f"{name} — the exchange was closed ({reason})"
    return f"{name} — no closing prices, and no closure known for that day"
