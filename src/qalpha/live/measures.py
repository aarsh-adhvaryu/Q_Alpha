"""Labelled return measurement — a basis and a window on every number (PLAN_TRUST_REPAIR PR-4).

The audit that triggered this found **eight return numbers on four bases over two windows**, none of
them labelled, on one screen. None was wrong. Two panels showing `+0.98%` and `+3.92%` were the same
NIFTYBEES series over windows 28 days apart; a book showing `+2.03%` beside `+2.73%` was the same
book measured on money contributed vs capital actually deployed. The reader could not tell, and the
reasonable conclusion from an unexplained contradiction is that the system is wrong somewhere.

So the fix is not new arithmetic — it is a vocabulary. A return is meaningless without two facts:

* **basis** — what the denominator is. "Up 2%" *of what?* Money put in? Money actually invested?
  The book's first mark? Each answers a different question and they legitimately disagree.
* **window** — over which dates. Two books started 28 days apart cannot be compared on the number
  alone, however carefully each was computed.

Every number that reaches a screen goes through :class:`ReturnMeasure`, so it cannot be rendered
without both. Pure and Streamlit-free: the same labels appear in the Markdown reports and the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

#: The four denominators this system actually uses, in plain words. Keys are stable identifiers used
#: in code; values are what the reader sees. Naming them here is the point — before PR-4 the choice
#: of denominator was implicit in whichever function happened to compute the number.
BASES: dict[str, str] = {
    "contributed": "money put in",
    "deployed": "capital actually invested (cash held aside excluded)",
    "starting_capital": "the notional starting capital",
    "first_mark": "the book's first recorded equity mark",
}


def _fmt_window(start: date | None, end: date | None) -> str:
    if start is None and end is None:
        return ""
    if start is None:
        return f"through {end}"
    if end is None:
        return f"from {start}"
    return f"{start} → {end}"


@dataclass(frozen=True)
class ReturnMeasure:
    """One return, with the two facts that make it readable: what it is measured against, and when.

    ``pct`` is already in percent (``+2.03`` not ``0.0203``) to match every existing call site.
    """

    label: str  # what this number is, e.g. "System book"
    pct: float
    basis: str  # a key of BASES, or free text if a one-off
    start: date | None = None
    end: date | None = None
    denominator: str | None = None  # the actual rupee figure, when it helps ("₹400,000")

    @property
    def basis_text(self) -> str:
        return BASES.get(self.basis, self.basis)

    def window_text(self) -> str:
        return _fmt_window(self.start, self.end)

    def short(self) -> str:
        """Just the number and its basis — for a metric tile's caption."""
        denom = f" {self.denominator}" if self.denominator else ""
        return f"{self.pct:+.2f}% vs {self.basis_text}{denom}"

    def render(self) -> str:
        """The full line: number, basis, denominator and window. Nothing implicit."""
        parts = [f"**{self.pct:+.2f}%**", f"vs {self.basis_text}"]
        if self.denominator:
            parts.append(f"({self.denominator})")
        window = self.window_text()
        if window:
            parts.append(f"· {window}")
        return f"{self.label}: " + " ".join(parts)


def measures_table(measures: list[ReturnMeasure]) -> str:
    """A Markdown table of several measures — the "how this is measured" panel.

    Used where more than one basis is genuinely informative. The alternative the audit found — several
    bases printed as bare percentages in different parts of one page — is what this exists to replace.
    """
    if not measures:
        return ""
    rows = ["| Measured as | Return | Against | Window |", "|---|---|---|---|"]
    for m in measures:
        denom = f" ({m.denominator})" if m.denominator else ""
        rows.append(
            f"| {m.label} | {m.pct:+.2f}% | {m.basis_text}{denom} | {m.window_text() or '—'} |"
        )
    return "\n".join(rows)


def cash_drag_note(contributed: ReturnMeasure, deployed: ReturnMeasure) -> str:
    """Name the gap between the money-put-in and money-invested views: it is cash drag, not an error.

    Load-bearing on the A/B experiment page. The gap was **0.70pp** when the audit ran, larger than
    the AI effect the study is trying to measure — so a reader who assumed the two numbers should
    agree would conclude the books disagreed with each other, when in fact both were right and the
    difference was undeployed cash.
    """
    gap = deployed.pct - contributed.pct
    if abs(gap) < 0.005:
        return (
            "Both bases agree to within a rounding step — effectively all contributed capital is "
            "deployed, so there is no cash drag to account for."
        )
    return (
        f"The **{gap:+.2f}pp** difference is **cash drag**, not a discrepancy: "
        f"*{contributed.basis_text}* counts every rupee contributed from the day it arrived, while "
        f"*{deployed.basis_text}* counts only what was actually at work. Money waiting in the wallet "
        "earns nothing and dilutes the first number. Both are correct; they answer different "
        "questions."
    )


def window_mismatch_note(measures: list[ReturnMeasure]) -> str:
    """Warn when numbers shown side by side do not share a window — '' when they do.

    The `+0.98%` / `+3.92%` confusion in the audit was exactly this: one NIFTYBEES series, two start
    dates 28 days apart, presented as though they were two contradictory baselines.
    """
    starts = {m.start for m in measures if m.start is not None}
    if len(starts) <= 1:
        return ""
    # Only ``start`` need be known: a caller comparing two live books legitimately has no end date
    # yet, and dropping those rows produced an empty list and a dangling sentence on the real page.
    spans = "; ".join(f"{m.label} {m.window_text()}" for m in measures if m.start is not None)
    return (
        "⚠️ **These cover different windows and are not directly comparable** — "
        f"{spans}. A later start in a rising market shows a smaller number for the same holding, "
        "which is a difference in measurement period, not in performance."
    )
