"""Fail-loud safety guards for the live advisory layer (Q_alpha.md §4.9).

The system **never auto-executes** — the user places every order himself. So a system failure can
only cost money *one* way: by showing him **wrong information he then acts on** — stale prices, a
missing quote silently dropped from the tax/cash math, or an expired broker session presented as
live. These guards turn that failure surface into explicit signals: when an input is stale or
incomplete the advisory layer **stops and shouts** (a blocking banner) instead of quietly computing
a recommendation on bad data. Pure functions over already-loaded data, so they're fully testable
without a live broker.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from qalpha.data.prices import PriceData


@dataclass(frozen=True)
class Guard:
    """One input-integrity check. ``blocking`` guards veto advice; non-blocking ones only warn."""

    name: str
    ok: bool
    blocking: bool
    detail: str


@dataclass(frozen=True)
class SafetyReport:
    """The combined verdict on whether the loaded inputs are safe to advise on."""

    guards: list[Guard]

    @property
    def safe_to_advise(self) -> bool:
        """True unless any *blocking* guard failed."""
        return not self.blocks

    @property
    def blocks(self) -> list[Guard]:
        return [g for g in self.guards if not g.ok and g.blocking]

    @property
    def warnings(self) -> list[Guard]:
        return [g for g in self.guards if not g.ok and not g.blocking]

    def render(self) -> str:
        if not self.guards:
            return "✓ No input checks ran."
        lines: list[str] = []
        if self.blocks:
            lines.append("🛑 **Advice withheld — an input failed a safety check:**")
            lines += [f"- {g.name}: {g.detail}" for g in self.blocks]
        if self.warnings:
            lines.append("⚠️ **Warnings (advice shown, but verify):**")
            lines += [f"- {g.name}: {g.detail}" for g in self.warnings]
        if not self.blocks and not self.warnings:
            lines.append("✓ All input checks passed.")
        return "\n".join(lines)


def _weekdays_between(a: date, b: date) -> int:
    """Count weekdays strictly after ``a`` up to and including ``b`` (0 if ``b`` <= ``a``)."""
    n, d = 0, a + timedelta(days=1)
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def price_freshness_guard(
    prices: PriceData, as_of: date, *, max_weekday_staleness: int = 1
) -> Guard:
    """Block if the price panel's most recent date is more than ``max_weekday_staleness`` weekdays
    behind ``as_of`` — a stalled data feed would otherwise mark holdings and size sells off old prices.
    """
    dates = prices.dates
    if len(dates) == 0:
        return Guard("price feed", False, True, "the price panel is empty — no data to advise on.")
    last = dates[-1].date()
    stale = _weekdays_between(last, as_of)
    if stale > max_weekday_staleness:
        return Guard(
            "price feed",
            False,
            True,
            f"latest price is {last} — {stale} weekdays stale (> {max_weekday_staleness}). "
            "The data feed may be down; refusing to advise on stale prices.",
        )
    return Guard("price feed", True, True, f"fresh — latest price {last}.")


def price_completeness_guard(prices_dec: Mapping[str, Decimal], required: Iterable[str]) -> Guard:
    """Block if any *held* name lacks a positive price. A missing/zero quote silently dropped from
    the cash/tax math understates the tax due or the cash a sell raises — so flag it loudly instead.
    """
    missing = sorted(
        t for t in required if prices_dec.get(t) is None or prices_dec.get(t, Decimal("0")) <= 0
    )
    if missing:
        return Guard(
            "holding prices",
            False,
            True,
            f"no live price for {', '.join(missing)} — these would be dropped from the tax/cash "
            "math, understating tax or proceeds. Fix the quote before trading on this advice.",
        )
    return Guard("holding prices", True, True, "every held name has a live price.")


def broker_session_guard(
    valid: bool, *, expires_at: datetime | None = None, now: datetime | None = None
) -> Guard:
    """Block if the Kite session is invalid/expired. Live holdings/prices shown under a dead token
    are last-known, not current — acting on them is the classic stale-session loss. (Pure: pass the
    session validity in; the dashboard supplies it from the live client.)
    """
    if not valid:
        return Guard(
            "broker session", False, True, "Kite session is not authenticated — log in (one-tap)."
        )
    if expires_at is not None and now is not None and now >= expires_at:
        return Guard(
            "broker session",
            False,
            True,
            f"Kite token expired at {expires_at:%Y-%m-%d %H:%M} — re-login before trading.",
        )
    return Guard("broker session", True, True, "authenticated.")


def assess_advice_inputs(
    prices: PriceData,
    prices_dec: Mapping[str, Decimal],
    held: Iterable[str],
    as_of: date,
    *,
    max_weekday_staleness: int = 1,
    session: Guard | None = None,
) -> SafetyReport:
    """Run every input-integrity guard for an advisory render and combine them.

    ``session`` is optional so the paper book (no broker) skips the session check; the live dashboard
    passes :func:`broker_session_guard`. The advisory UI shows :attr:`SafetyReport.render` and only
    computes a recommendation when :attr:`SafetyReport.safe_to_advise`.
    """
    guards = [
        price_freshness_guard(prices, as_of, max_weekday_staleness=max_weekday_staleness),
        price_completeness_guard(prices_dec, held),
    ]
    if session is not None:
        guards.append(session)
    return SafetyReport(guards)
