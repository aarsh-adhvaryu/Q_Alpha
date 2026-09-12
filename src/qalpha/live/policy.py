"""What each twin book does, and why — the autonomy layer (PLAN_REDESIGN.md §1, Phase 3).

Phase 2 built five books receiving identical cash flows. This is what makes one of them *decide*.

**One policy, one configuration.** It was four — ``SYSTEM`` plus three ablations, each removing a
single factor so every gap was attributable to one thing. The ablations were deleted on 2026-09-12:
if separating the whole system from chance needs two hundred years, separating one of its three
parts needs longer still.

**The flags are no longer diagnostics; they are the policy.** ``use_exits=False`` is not an ablation
of ``SYSTEM``, it *is* ``SYSTEM``, registered in `reports/PREREGISTRATION_LIVE_POLICY.md` two days
before the evaluation window opened and frozen from 2026-09-14.

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
    """One book's configuration.

    **``ablated`` was removed on 2026-09-12** along with the three ablation books it existed for.
    It answered "which single factor does this configuration remove", which assumed every flag-off
    was a diagnostic. ``SYSTEM`` now ships ``use_exits=False`` as its **registered headline** (PL-1),
    so the property would have reported the live policy as an ablation of itself — a number labelled
    as something it is not, on the one surface that names what each book is.

    ``use_ai`` — the AI acts on selection, sizing, timing, the hedge and calling an exit, within the
    three guards it can never breach: it cannot invent a name outside the deterministic universe,
    cannot breach the 20% name / 30% sector caps, and cannot fail closed (no key, no response, an
    unparseable reply or a refusal all fall back to the deterministic path, so an AI outage degrades
    ``SYSTEM`` to its deterministic self rather than to nothing).

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


#: The one autonomous book — this IS the system, deciding for itself.
#:
#: **``use_exits=False``, registered in PL-1 on 2026-09-12, two days before the window opens.**
#: Selling to manage risk loses to the tax, measured twice on different engines: the frozen backtest
#: put the §4.7 exits **₹74.8 lakh behind buy-and-hold over 13 years, having paid ₹13.3 lakh of tax
#: to get there**, and ``PO-1``'s fourteen-year replay through this very runner put them at
#: **−₹7.7M**. Nothing in this repository has ever measured them as worth their cost.
#:
#: The price is real and is not hidden: **the backtested worst fall is −47.5% against the index's
#: −36.3%**, and removing the exit rule can only deepen a trough, never soften one. Nobody has yet
#: watched this system fall.
POLICIES: dict[str, Policy] = {SYSTEM: Policy(SYSTEM, use_exits=False)}

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
