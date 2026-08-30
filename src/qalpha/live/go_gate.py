"""The GO gate — six criteria, and the honesty to say when it cannot assess one (PLAN_REDESIGN §2).

**Replaces** ``live/go_scorecard.py``, which graded a paper book running the *validated funnel* while
the real money runs the deploy-into-weakness advisor. Every one of its five criteria could have gone
green without saying anything about the money at risk. That book is archived
(``reports/ARCHIVE_2026-08-28.md``); this grades the composite system the twin actually runs.

**Four verdicts, not two.** ``CANNOT_ASSESS`` is deliberately distinct from ``RED``: missing evidence
is not failure, and collapsing the two is how a stale benchmark once reported a calm market when the
truth was *no data*. A criterion that cannot be assessed **blocks a GO** exactly as a red does — it
simply reports a different reason, and names what would settle it.

**Nothing here defaults.** Every criterion takes its evidence explicitly; there is no fetch, no
fallback, and no zero standing in for an unknown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

GREEN = "GREEN"
AMBER = "AMBER"
RED = "RED"
CANNOT_ASSESS = "CANNOT_ASSESS"

#: GO criterion 1 — below this, a gap is dominated by *when* money went in, not *what* was picked.
MIN_MONTHS = 12
#: GO criterion 2 — the system has never been watched through a fall. Nothing substitutes for one.
VOLATILITY_EVENT_DRAWDOWN = -0.10


@dataclass(frozen=True)
class Criterion:
    """One requirement, its verdict, and — when it is not green — what would settle it."""

    name: str
    verdict: str
    reading: str
    settles_it: str = ""

    @property
    def icon(self) -> str:
        return {GREEN: "🟢", AMBER: "🟡", RED: "🔴", CANNOT_ASSESS: "⚪"}[self.verdict]

    @property
    def blocks(self) -> bool:
        """Anything but green blocks a GO — including 'cannot assess'."""
        return self.verdict != GREEN


@dataclass(frozen=True)
class Evidence:
    """Everything the gate needs, gathered by the caller. ``None`` means *unknown*, never zero."""

    months_of_flows: int | None = None
    worst_drawdown_in_window: float | None = None
    #: Descriptive only — the rupee gap, for the human reading the report. Never the criterion.
    gap_vs_ew_baseline: Decimal | None = None
    #: The criterion: G = ln(V_TWIN_FULL / V_BASELINE_EW). Scale-free, so the SIP growing the book
    #: does not move it. See ``twin.NULL_P95_LOG_REL_WEALTH`` for the pre-registered specification.
    log_rel_wealth: float | None = None
    #: p95 of that pre-registered null, in log units. ``None`` → CANNOT ASSESS, never a pass.
    null_p95: float | None = None
    reconciled_complex_sale: bool | None = None
    reconciled_corporate_action: bool | None = None
    tradebook_reconciles: bool | None = None
    unguarded_price_gaps: int | None = None


def _track_length(e: Evidence) -> Criterion:
    if e.months_of_flows is None:
        return Criterion(
            "Track length",
            CANNOT_ASSESS,
            "no cash flows on record",
            "upload the tradebook — the flows are its only source",
        )
    if e.months_of_flows >= MIN_MONTHS:
        return Criterion("Track length", GREEN, f"{e.months_of_flows} months of real cash flows")
    return Criterion(
        "Track length",
        AMBER,
        f"{e.months_of_flows} of {MIN_MONTHS} months",
        f"{MIN_MONTHS - e.months_of_flows} more months. Calendar time; nothing accelerates it.",
    )


def _volatility_event(e: Evidence) -> Criterion:
    if e.worst_drawdown_in_window is None:
        return Criterion(
            "Volatility event withstood",
            CANNOT_ASSESS,
            "no benchmark series covering the window",
            "refresh the benchmark — a stale copy once read a −2.2% fall as 0.0%",
        )
    if e.worst_drawdown_in_window <= VOLATILITY_EVENT_DRAWDOWN:
        return Criterion(
            "Volatility event withstood",
            GREEN,
            f"worst in-window fall {e.worst_drawdown_in_window:.1%}",
        )
    return Criterion(
        "Volatility event withstood",
        AMBER,
        f"worst in-window fall {e.worst_drawdown_in_window:.1%}, "
        f"gate needs ≤ {VOLATILITY_EVENT_DRAWDOWN:.0%}",
        "a real market fall. Nobody has watched this system through one.",
    )


def _beats_baseline(e: Evidence) -> Criterion:
    if e.log_rel_wealth is None:
        return Criterion(
            "Beats the equal-weight fund",
            CANNOT_ASSESS,
            "no comparison computed",
            "seed and mark the twin books",
        )
    # Relative wealth, not rupees: both books receive identical flows, so the ratio isolates the
    # selection difference and does not move when the monthly SIP grows the book. The rupee gap is
    # carried alongside for the human, never as the criterion — that confusion is what produced an
    # ₹84 lakh bar for a ₹3 lakh book.
    pct = math.expm1(e.log_rel_wealth) * 100
    rupees = "" if e.gap_vs_ew_baseline is None else f" (₹{e.gap_vs_ew_baseline:+,.0f})"
    if e.null_p95 is None:
        return Criterion(
            "Beats the equal-weight fund",
            CANNOT_ASSESS,
            f"relative wealth {pct:+.2f}%{rupees}, but the pre-registered null has not been run",
            "generate the matched null (twin.NULL_P95_LOG_REL_WEALTH names its specification) — "
            "without a bar, no gap can be read, and a missing bar is never a bar of zero",
        )
    if e.log_rel_wealth > e.null_p95:
        return Criterion(
            "Beats the equal-weight fund",
            GREEN,
            f"ahead {pct:+.2f}%{rupees}, clearing the ±{e.null_p95:.4f} null band",
        )
    return Criterion(
        "Beats the equal-weight fund",
        AMBER if e.log_rel_wealth > 0 else RED,
        f"relative wealth {pct:+.2f}%{rupees}, inside the ±{e.null_p95:.4f} null band",
        "a gap larger than luck produces. The bar is the fund anyone can buy, not the index.",
    )


def _tax_reconciled(e: Evidence) -> Criterion:
    if e.reconciled_complex_sale is None:
        return Criterion(
            "Tax reconciled",
            CANNOT_ASSESS,
            "no reconciliation on record",
            "upload a Console Tax P&L covering a sale",
        )
    if e.reconciled_complex_sale:
        return Criterion("Tax reconciled", GREEN, "a multi-lot or LTCG sale matched to Zerodha")
    return Criterion(
        "Tax reconciled",
        AMBER,
        "only a single-lot, all-STCG, no-loss sale has ever matched (₹25.25, Δ ₹0.00)",
        "one multi-lot or LTCG sale, reconciled afterwards. §70 set-off fires on every harvest "
        "and has never been confirmed by a third party.",
    )


def _corporate_action(e: Evidence) -> Criterion:
    if e.reconciled_corporate_action is None:
        return Criterion("Corporate action reconciled", CANNOT_ASSESS, "no record", "a live action")
    if e.reconciled_corporate_action:
        return Criterion("Corporate action reconciled", GREEN, "one applied and matched")
    return Criterion(
        "Corporate action reconciled",
        AMBER,
        "never",
        "one split, bonus or dividend applied live and matched. Demerger is not modelled at all.",
    )


def _data_integrity(e: Evidence) -> Criterion:
    if e.tradebook_reconciles is None or e.unguarded_price_gaps is None:
        return Criterion(
            "Data integrity", CANNOT_ASSESS, "not checked", "run the live reconciliation"
        )
    if e.tradebook_reconciles and e.unguarded_price_gaps == 0:
        return Criterion("Data integrity", GREEN, "tradebook matches the broker; no ungated gaps")
    problems = []
    if not e.tradebook_reconciles:
        problems.append("tradebook does not match broker holdings")
    if e.unguarded_price_gaps:
        problems.append(f"{e.unguarded_price_gaps} unguarded price gap(s)")
    return Criterion(
        "Data integrity",
        RED,
        "; ".join(problems),
        "off-market credits never appear in a tradebook export — add those lots.",
    )


@dataclass(frozen=True)
class GateReport:
    """The verdict, and every criterion behind it."""

    as_of: date
    criteria: list[Criterion]

    @property
    def verdict(self) -> str:
        """``GO`` only when every criterion is green. Anything else is ``NOT YET``."""
        return "GO" if not any(c.blocks for c in self.criteria) else "NOT YET"

    @property
    def blocking(self) -> list[Criterion]:
        return [c for c in self.criteria if c.blocks]

    def render(self) -> str:
        head = (
            f"# GO gate — **{self.verdict}** ({self.as_of})\n\n"
            if self.verdict == "GO"
            else (
                f"# GO gate — **{self.verdict}** ({self.as_of})\n\n"
                f"**{len(self.blocking)} of {len(self.criteria)} criteria are not green.** "
                "The system is not validated for real money.\n\n"
            )
        )
        rows = ["| | Criterion | Reading |", "|---|---|---|"]
        rows += [f"| {c.icon} | {c.name} | {c.reading} |" for c in self.criteria]
        tail = ""
        if self.blocking:
            tail = "\n\n**What would settle each:**\n" + "\n".join(
                f"- **{c.name}** — {c.settles_it}" for c in self.blocking if c.settles_it
            )
        return head + "\n".join(rows) + tail


def build_gate(evidence: Evidence, as_of: date) -> GateReport:
    """Grade all six criteria. Never softens, never defaults, never invents a reading."""
    return GateReport(
        as_of=as_of,
        criteria=[
            _track_length(evidence),
            _volatility_event(evidence),
            _beats_baseline(evidence),
            _tax_reconciled(evidence),
            _corporate_action(evidence),
            _data_integrity(evidence),
        ],
    )
