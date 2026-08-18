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

    @property
    def buy_advice_safe(self) -> bool:
        """May the **buy** list render? Everything :attr:`safe_to_advise` requires, plus a fresh
        watchlist panel — the separate price source the buy side is sized off, which nothing checked
        before PR-2. Sell/raise-cash deliberately do not consult this: they are priced off the core
        panel, so a stale watchlist must not silence them.
        """
        return self.safe_to_advise and all(
            g.ok for g in self.guards if g.name == "watchlist prices"
        )

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


def watchlist_freshness_guard(
    panel: PriceData | None,
    as_of: date,
    *,
    max_weekday_staleness: int = 3,
    download_ok: bool = True,
) -> Guard:
    """Block the **buy** side when the Nifty-100 watchlist panel is stale or failed to download.

    The gap this closes (PR-2 / T1.3): :func:`assess_advice_inputs` validated only the *core* panel —
    the one that prices names you already own — while the buy list is priced off a completely
    separate watchlist panel whose freshness nothing checked. Its refresh runs with ``check=False``,
    so a failed download left the previous panel on disk and the advisor sized a confident
    recommendation off it with no banner at all.

    Non-blocking by design: a stale *buy* panel must not veto **Sell** or **Raise cash**, which are
    priced off the core panel and are unaffected. The buy surface gates on
    :attr:`SafetyReport.buy_advice_safe` instead, which this guard drives.
    """
    if not download_ok:
        return Guard(
            "watchlist prices",
            False,
            False,
            "the watchlist price download failed — any buy list would be priced off the previous "
            "panel. Buy suggestions are withheld; selling and raising cash are unaffected.",
        )
    if panel is None or len(panel.dates) == 0:
        return Guard(
            "watchlist prices", False, False, "no watchlist price panel — buy suggestions withheld."
        )
    last = panel.dates[-1].date()
    stale = _weekdays_between(last, as_of)
    if stale > max_weekday_staleness:
        return Guard(
            "watchlist prices",
            False,
            False,
            f"latest watchlist price is {last} — {stale} weekdays stale "
            f"(> {max_weekday_staleness}). Buy suggestions are withheld rather than sized off old "
            "prices; selling and raising cash are unaffected.",
        )
    return Guard("watchlist prices", True, False, f"fresh — latest watchlist price {last}.")


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
    watchlist: PriceData | None = None,
    watchlist_download_ok: bool = True,
    max_watchlist_staleness: int = 3,
) -> SafetyReport:
    """Run every input-integrity guard for an advisory render and combine them.

    ``session`` is optional so the paper book (no broker) skips the session check; the live dashboard
    passes :func:`broker_session_guard`. The advisory UI shows :attr:`SafetyReport.render` and only
    computes a recommendation when :attr:`SafetyReport.safe_to_advise`.

    ``watchlist`` is the **separate** panel the buy list is priced off (PR-2). It was outside this
    report entirely, which is how a buy recommendation could be sized off prices nothing had checked.
    Pass it — and ``watchlist_download_ok=False`` when its refresh failed — and the buy surface gates
    on :attr:`SafetyReport.buy_advice_safe`. Omit it and nothing changes: sell/raise-cash callers that
    never touch the watchlist keep exactly their previous verdict.
    """
    guards = [
        price_freshness_guard(prices, as_of, max_weekday_staleness=max_weekday_staleness),
        price_completeness_guard(prices_dec, held),
    ]
    if session is not None:
        guards.append(session)
    if watchlist is not None or not watchlist_download_ok:
        guards.append(
            watchlist_freshness_guard(
                watchlist,
                as_of,
                max_weekday_staleness=max_watchlist_staleness,
                download_ok=watchlist_download_ok,
            )
        )
    return SafetyReport(guards)
