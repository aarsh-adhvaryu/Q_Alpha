"""What each twin book does, and why — the autonomy layer (PLAN_REDESIGN.md §1, Phase 3).

Phase 2 built five books receiving identical cash flows. This is what makes four of them *decide*.

**One policy, four configurations.** ``TWIN_FULL`` runs everything; each ablation removes exactly one
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

from qalpha.live.twin import CORE_V1, TWIN_FULL, TWIN_NO_AI, TWIN_NO_EXITS, TWIN_NO_HEDGE

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
    ``TWIN_FULL`` to ``TWIN_NO_AI`` rather than to nothing).

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


#: The four autonomous books. Exactly one factor differs between the headline and each ablation.
POLICIES: dict[str, Policy] = {
    TWIN_FULL: Policy(TWIN_FULL),
    TWIN_NO_AI: Policy(TWIN_NO_AI, use_ai=False),
    TWIN_NO_HEDGE: Policy(TWIN_NO_HEDGE, use_hedge=False),
    TWIN_NO_EXITS: Policy(TWIN_NO_EXITS, use_exits=False),
}


#: **The frozen core treatment.** Deterministic screen, §4.7 exits, no AI, no hedge overlay.
#:
#: This is not an ablation and must never be added to :data:`POLICIES`. An ablation is defined
#: relative to ``TWIN_FULL`` and therefore moves whenever ``TWIN_FULL`` moves; a book that answers
#: "does the screen beat the fund?" over twelve months cannot afford to move at all. The AI, the
#: evidence adapter and the governor version independently and none of them reaches this book.
#:
#: **Changing any field here ends CORE_V1 and starts CORE_V2 with a new clock.** Nothing else does.
CORE_POLICY = Policy(CORE_V1, use_ai=False, use_hedge=False, use_exits=True)

#: Every book that steps daily: the run-2 ablation family plus the independent core track.
ALL_POLICIES: dict[str, Policy] = {**POLICIES, CORE_V1: CORE_POLICY}


def assert_core_is_not_an_ablation(policies: dict[str, Policy] = POLICIES) -> None:
    """``CORE_V1`` must stay out of the ablation family.

    If it were in :data:`POLICIES` it would be asserted against ``TWIN_FULL`` as a single-factor
    ablation, which it is not — and, worse, it would acquire the composite's identity, which is the
    exact coupling it exists to break.
    """
    if CORE_V1 in policies:
        raise ValueError(
            f"{CORE_V1} is in the ablation family. It is a separate experiment with its own clock "
            "and its own reset condition; it must not be defined relative to TWIN_FULL."
        )


def assert_single_factor_ablations(policies: dict[str, Policy] = POLICIES) -> None:
    """Each ablation must differ from the headline in exactly one flag.

    If two differ, its gap is attributable to neither — and a diagnostic that cannot attribute is
    worse than none, because it invites a story. Asserted rather than trusted to review.
    """
    head = policies[TWIN_FULL]
    assert head.ablated is None, "TWIN_FULL must have every factor on"
    for name, pol in policies.items():
        if name == TWIN_FULL:
            continue
        differences = sum(
            1
            for a, b in (
                (head.use_ai, pol.use_ai),
                (head.use_hedge, pol.use_hedge),
                (head.use_exits, pol.use_exits),
            )
            if a != b
        )
        if differences != 1:
            raise ValueError(
                f"{name} differs from {TWIN_FULL} in {differences} factors, not 1 — its gap would "
                "be attributable to none of them."
            )


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
