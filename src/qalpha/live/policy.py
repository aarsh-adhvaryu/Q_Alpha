"""What each twin book does, and why — the autonomy layer (PLAN_REDESIGN.md §1, Phase 3).

Phase 2 built five books receiving identical cash flows. This is what makes four of them *decide*.

**One policy, four configurations.** ``SYSTEM`` runs everything; each ablation removes exactly one
factor, so every gap in the comparison is attributable to one thing. That is why the flags are
subtractive (``use_ai=False``) rather than a menu — an ablation must differ from the headline in one
respect and no other, or the diagnostic it produces means nothing.

**Every decision carries a reason, enforced by the type.** A book that acts without recording why is
unauditable, and this repo's entire failure history is surfaces that could not explain themselves.
:class:`Decision` cannot be constructed without one.

**Nothing here touches Zerodha.** These policies drive fake-money books only. The user places every
real order; a component reaches his screen only by graduating (§2a), and then as advice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from qalpha.live.twin import SYSTEM

#: What a book did on a day, in the log and on the panel.
DEPLOY = "DEPLOY"
EXIT = "EXIT"
HARVEST = "HARVEST"
HEDGE_ON = "HEDGE_ON"
HEDGE_OFF = "HEDGE_OFF"
HOLD = "HOLD"


@dataclass(frozen=True)
class Policy:
    """One book's configuration. Subtractive by design — see the module docstring.

    ``use_ai`` — the AI acts on selection, sizing, timing, the hedge and calling an exit, within the
    three guards it can never breach: it cannot invent a name outside the deterministic universe,
    cannot breach the 20% name / 30% sector caps, and cannot fail closed (no key, no response, an
    unparseable reply or a refusal all fall back to the deterministic path, so an AI outage degrades
    ``SYSTEM`` to ``TWIN_NO_AI`` rather than to nothing).

    ``use_hedge`` — the short-futures overlay while the stress gauge is elevated. Twin-only for
    years: no index derivative trades below ~₹15L of notional (§4b-i).

    ``use_exits`` — the §4.7 idiosyncratic-breakdown test and the pre-registered drawdown exit (§4).

    Harvesting is deliberately **not** a flag. It is not a strategy bet — it converts a paper loss
    into a carry-forward asset and costs no capital-gains tax — so removing it would test nothing.
    """

    name: str
    use_ai: bool = True
    use_hedge: bool = True
    use_exits: bool = True

    @property
    def ablated(self) -> str | None:
        """Which single factor this configuration removes, or ``None`` for the headline."""
        for flag, label in (
            (self.use_ai, "AI"),
            (self.use_hedge, "hedge"),
            (self.use_exits, "exits"),
        ):
            if not flag:
                return label
        return None


#: The one autonomous book. Every factor on — this IS the system, deciding for itself.
#:
#: **It was four, plus a separate core track, and they are gone** (2026-09-12). The three ablations
#: (``TWIN_NO_AI``, ``TWIN_NO_HEDGE``, ``TWIN_NO_EXITS``) each removed one factor to attribute the
#: gap to a component. That is a harder question than the one we cannot answer: if separating the
#: whole system from chance needs two hundred years, separating one of its three parts needs longer
#: still. Four books of it was arithmetic nobody could ever read.
POLICIES: dict[str, Policy] = {SYSTEM: Policy(SYSTEM)}

#: Every book that steps daily. One entry, kept as a mapping because the runner iterates it.
ALL_POLICIES: dict[str, Policy] = dict(POLICIES)


@dataclass(frozen=True)
class Decision:
    """One action, on one day, by one book — **with the reason that produced it**.

    The reason is not commentary. It is the only thing that makes an autonomous book auditable
    afterwards, and the difference between "the twin beat you" and "the twin beat you *because*".
    """

    on: date
    book: str
    action: str
    reason: str
    ticker: str | None = None
    quantity: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError(
                f"{self.book} recorded a {self.action} with no reason — an unexplained decision is "
                "not auditable, and this system's failures have all been surfaces that could not "
                "explain themselves."
            )

    def render(self) -> str:
        what = self.action
        if self.ticker:
            qty = f" {self.quantity}×" if self.quantity is not None else " "
            what = f"{self.action}{qty}{self.ticker}"
        return f"{self.on} · {self.book} · {what} — {self.reason}"


def decisions_markdown(decisions: Sequence[Decision]) -> str:
    """The log. A day with no action still says so — silence is not the same as not running."""
    if not decisions:
        return (
            "_No decisions recorded. If the runner is live this means every book held; if it is "
            "not, this panel looks identical — check the last mark date._"
        )
    return "\n".join(f"- {d.render()}" for d in decisions)
