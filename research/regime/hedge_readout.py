"""Plain-English readout helpers for the hedge dashboard (clarity follow-up).

Translate the systemic-stress gauge / hedge jargon into everyday language + a good/bad read, so a
non-quant can tell at a glance what the overlay is doing and whether quiet is good (it is). Pure — no
I/O, no pandas — so they unit-test cleanly with primitives.
"""

from __future__ import annotations

_LEVEL_PLAIN = {
    "calm": "🟢 calm — the market is not stressed; the hedge stays OFF and costs nothing",
    "watch": "🟠 watch — some stress is building; the hedge is near its trigger",
    "elevated": "🔴 elevated — high systemic stress; the hedge is (or is near) ENGAGED",
}


def hedge_gauge_read(gauge: float, tau: float, level: str, *, hedge_on: bool) -> str:
    """One plain sentence on the stress gauge and whether the hedge is doing anything right now."""
    state = (
        "**ON** — the overlay would be short index futures to offset a market fall"
        if hedge_on
        else "**OFF** — nothing to do; the book rides as-is"
    )
    return (
        f"The stress gauge reads **{gauge:.2f}** out of 1.00 (it fires at **{tau:.2f}**) → "
        f"{_LEVEL_PLAIN.get(level, level)}. Hedge is {state}."
    )


def hedge_plain_summary(
    *, level: str, gauge: float, tau: float, hedge_on: bool, days: int, episodes: int
) -> str:
    """The one-screen 'in plain English' panel for the hedge forward paper run."""
    return "\n".join(
        [
            "### 🧭 In plain English",
            "",
            "- **What this is:** a *paper* (pretend-money) test of a tax-free hedge that shorts Nifty "
            "futures when the market looks fragile — to cut crash losses **without selling your "
            "shares or paying tax**.",
            f"- **Right now:** {hedge_gauge_read(gauge, tau, level, hedge_on=hedge_on)}",
            f"- **Track so far:** {days} trading days; the hedge has fired **{episodes}** time(s).",
            "- **Is a quiet chart good?** Yes. A calm market keeps the hedge off and the two lines "
            "identical — that's expected. It only earns its keep in a real crash, which can't be "
            "scheduled.",
        ]
    )


def hedge_glossary() -> str:
    """Every term on the hedge dashboard, defined in plain words."""
    return "\n".join(
        [
            "**The terms on this page, in plain words:**",
            "",
            "- **Systemic-stress gauge** — one 0–1 number for how fragile the *whole* market looks "
            "(built from global volatility, credit spreads, the dollar, USD-INR, drawdown, and "
            "cross-asset correlation). Higher = more fragile.",
            "- **τ (tau) / fire threshold** — the gauge level at which the hedge switches ON. Below "
            "it, the hedge stays off.",
            "- **Hedge ON / OFF** — whether the overlay is currently shorting index futures to offset "
            "a fall. It never touches your actual shares.",
            "- **Hedged vs unhedged** — two pretend books from the same start: one plain, one with "
            "the hedge. When the lines diverge, the hedge is doing something (usually during stress).",
            "- **Hedge effect (pts)** — percentage points the hedge added or subtracted vs doing "
            "nothing. Positive in crashes; a small drag in calm years (the cost of insurance).",
            "- **Episode** — one ON→OFF stretch where the hedge was engaged.",
            "- **Coincident** — the gauge moves *with* a crash, not before it — so it's protection, "
            "not prediction.",
            "- **Tax-free** — index futures are taxed as business income and the shares are never "
            "sold, so no capital-gains tax is triggered (the reason this beats 'just sell in a "
            "crash').",
        ]
    )
