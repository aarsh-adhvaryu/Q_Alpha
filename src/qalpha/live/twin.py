"""The digital twin — five books, one set of cash flows, and the only honest way to grade the system.

**The defect this exists to fix.** The GO scorecard graded a paper book running the *validated
funnel* — shrink-weighted, annual, tax-aware rebalancing. The real money runs the
deploy-into-weakness advisor, which shares no selection code and no names with it. Grading the thing
you do not run, in order to authorise the thing you do, is a category error: every criterion could
have gone green without saying anything about the money at risk. That book is archived
(``reports/ARCHIVE_2026-08-28.md``) and this replaces it.

**The design (PLAN_REDESIGN.md §1).** The real Zerodha account is the *state source*; a fake-money
twin is the *autonomous system*. Nothing autonomous ever touches Zerodha.

- ``REAL``      — the user's own orders, replayed from his tradebook.
- ``TWIN_FULL`` — the headline: everything on, the AI acting rather than advising.
- ``TWIN_NO_AI`` / ``TWIN_NO_HEDGE`` / ``TWIN_NO_EXITS`` — one factor removed each, so every gap is
  attributable to exactly one thing.
- ``BASELINE``  — the same rupees into NIFTYBEES. Does any of it beat doing nothing?

**Only ``TWIN_FULL − BASELINE`` gates** (GO criterion 3). The ablations are descriptive: four
comparisons at 95% throw a false positive about one run in five, so if an ablation could open the
gate, the gate would eventually open on noise. That is the bar forward run 1 was voided for.

**The load-bearing invariant: every book receives the same rupees on the same days.** The flows come
from the tradebook and nowhere else — there is no SIP schedule (§4c). A calendar injection the real
account never received would silently destroy the comparison, which is the flaw that voided forward
run 1's predecessor. :func:`assert_identical_flows` is that invariant, asserted rather than assumed.

Phase 2 builds the *structure* and wires ``REAL`` and ``BASELINE``, which are fully determined by the
tradebook. The twins are seeded and marked here; their autonomous decisions arrive in Phase 3, so
until then they hold cash and are honest about it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.track_record import Flow, benchmark_leg, flows_from_trades, xirr

#: The five books. ``REAL`` is observed, not simulated; ``BASELINE`` is arithmetic; the three
#: ``TWIN_*`` books decide for themselves (Phase 3).
REAL = "REAL"
TWIN_FULL = "TWIN_FULL"
TWIN_NO_AI = "TWIN_NO_AI"
TWIN_NO_HEDGE = "TWIN_NO_HEDGE"
TWIN_NO_EXITS = "TWIN_NO_EXITS"
BASELINE = "BASELINE"
#: The equal-weight index fund — the baseline that actually decides whether this system is worth
#: running. Phase 4 found that **76% of the screen's gap over NIFTYBEES is the equal-weight premium**,
#: and that premium is purchasable (Nifty-50 EW index funds exist; DSP 0.41% direct). Beating the
#: cap-weighted index is therefore not the achievement it looks like: the honest question is whether
#: the system beats a fund anyone can buy in five minutes. See reports/PHASE4_BACKTEST.md.
BASELINE_EW = "BASELINE_EW"

#: Books that make their own decisions — the ones Phase 3 gives policies to.
AUTONOMOUS = (TWIN_FULL, TWIN_NO_AI, TWIN_NO_HEDGE, TWIN_NO_EXITS)
#: Every book in the comparison, in report order.
ALL_BOOKS = (REAL, *AUTONOMOUS, BASELINE_EW, BASELINE)

#: The only comparison that opens the GO gate — and it gates against the **harder** baseline.
#: Gating against NIFTYBEES would let the system claim credit for the equal-weight premium it did
#: not create; a system that cannot beat the best cheap passive alternative should not run.
GATING_PAIR = (TWIN_FULL, BASELINE_EW)

#: Annual expense ratio of the cheapest Nifty-50 equal-weight index fund available (DSP, direct).
#: Charged against the EW baseline so it is a purchasable alternative, not an unattainable index.
EW_FUND_FEE = Decimal("0.0041")


@dataclass
class TwinBook:
    """One book in the comparison: a real FIFO portfolio plus the flows it has been given.

    A ``Portfolio`` rather than a thin holdings dict, because the whole system turns on tax — dated
    lots, FIFO consumption and the §2(42A) boundary all have to be real for a twin's sells to mean
    anything.
    """

    name: str
    portfolio: Portfolio
    flows: list[Flow] = field(default_factory=list)

    @property
    def net_invested(self) -> Decimal:
        """Everything in minus everything out — the basis every return is quoted against."""
        return sum((f.amount for f in self.flows), Decimal("0"))

    @property
    def start(self) -> date | None:
        return self.flows[0].on if self.flows else None

    def value(self, prices: dict[str, Decimal]) -> Decimal:
        """Shares **plus** the book's own uninvested cash.

        Unlike the real account — whose idle balance is the user's next instalment and must never be
        counted as performance (the +444% defect) — a twin's cash *is* part of the fund: it was
        handed the same rupees and chose not to deploy them. Not deploying is a decision the
        comparison must charge it for, so cash counts here and does not there.
        """
        return self.portfolio.cash + self.portfolio.holdings_value(prices)


def assert_identical_flows(books: Sequence[TwinBook]) -> None:
    """Every book must have received the same rupees on the same days, or nothing below means anything.

    The comparison's entire claim is *"same money, same dates, only the decisions differ."* If the
    flows drift, each book is answering a different question and the gaps are uninterpretable —
    which is how a predecessor run was lost. Cheap to check, fatal to skip.
    """
    if not books:
        return
    reference = [(f.on, f.amount) for f in books[0].flows]
    for book in books[1:]:
        actual = [(f.on, f.amount) for f in book.flows]
        if actual != reference:
            raise ValueError(
                f"{book.name} did not receive the same cash flows as {books[0].name} — "
                f"{len(actual)} flows vs {len(reference)}. Every book must see the same rupees on "
                "the same days; otherwise the books are answering different questions."
            )


def seed_books(
    trades: Sequence[object], cfg: Config, *, names: Sequence[str] = ALL_BOOKS
) -> dict[str, TwinBook]:
    """Build every book from one tradebook, each funded with the identical dated flows.

    ``REAL``'s holdings are the user's actual trades (replayed elsewhere); the others start as pure
    cash and spend it according to their own policy. Seeding them here — from the same source, in
    one place — is what makes :func:`assert_identical_flows` trivially true by construction rather
    than a hope.
    """
    flows = flows_from_trades(trades)
    books: dict[str, TwinBook] = {}
    for name in names:
        pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
        pf.cash = sum((f.amount for f in flows), Decimal("0"))
        books[name] = TwinBook(name=name, portfolio=pf, flows=list(flows))
    assert_identical_flows(list(books.values()))
    return books


@dataclass(frozen=True)
class BookMark:
    """One book's standing at ``as_of``: what it is worth, on what basis, over what window."""

    name: str
    as_of: date
    start: date | None
    net_invested: Decimal
    value: Decimal
    rate: float | None  # money-weighted (XIRR) — a lumpy SIP has no meaningful simple return

    @property
    def gain(self) -> Decimal:
        return self.value - self.net_invested


def mark(book: TwinBook, prices: dict[str, Decimal], as_of: date) -> BookMark:
    """Mark one book to ``prices``, money-weighted.

    XIRR, not a start-to-end percentage: contributions arrive whenever the user trades, so the money
    is not present for the whole window and a simple percentage would flatter late deposits into a
    rise and punish them in a fall.
    """
    value = book.value(prices)
    dated = [(f.on, -f.amount) for f in book.flows] + [(as_of, value)]
    return BookMark(
        name=book.name,
        as_of=as_of,
        start=book.start,
        net_invested=book.net_invested,
        value=value,
        rate=xirr(dated) if book.flows else None,
    )


def baseline_mark(flows: Sequence[Flow], series: pd.Series, as_of: date) -> BookMark | None:
    """The same rupees on the same days into NIFTYBEES — 'what if you had done nothing?'.

    ``None`` when the index has no price at or before the first flow: the comparison would be
    invented rather than measured, and an invented baseline is worse than no baseline.
    """
    leg = benchmark_leg(flows, series, as_of)
    if leg is None:
        return None
    net = sum((f.amount for f in flows), Decimal("0"))
    dated = [(f.on, -f.amount) for f in flows] + [(as_of, leg.value)]
    return BookMark(
        name=BASELINE,
        as_of=as_of,
        start=flows[0].on if flows else None,
        net_invested=net,
        value=leg.value,
        rate=xirr(dated) if flows else None,
    )


#: Below this many months the comparison is dominated by *when* money went in, not by *what* was
#: picked. Same bar as ``track_record.MIN_MONTHS_FOR_A_VERDICT`` and the one that voided forward run
#: 1 — a difference smaller than the noise it sits in is not a result.
MIN_MONTHS_FOR_A_VERDICT = 12

#: GO criterion 3's bar, computed 2026-08-29 by ``scripts/backtest_phase4.py --null 60``: the p95 of
#: 60 no-skill draws over 2013-07 → 2026-06 at ₹1L + ₹50k/month on point-in-time Nifty-50. A live gap
#: inside this is not a result. **Scale-dependent** — it belongs to that contribution schedule, so a
#: materially different one needs the null re-run. See reports/PHASE4_BACKTEST.md.
BACKTEST_NOISE_FLOOR = Decimal("8362315")


@dataclass(frozen=True)
class Gap:
    """One book measured against another, and whether it is allowed to mean anything yet."""

    left: str
    right: str
    rupees: Decimal
    gates: bool  # only TWIN_FULL − BASELINE opens the GO gate; the rest describe
    months: int
    noise_floor: Decimal | None = None  # from the Phase 4 bootstrap; None until it exists

    @property
    def readable(self) -> bool:
        """Is this gap big enough, and old enough, to be evidence rather than noise?"""
        if self.months < MIN_MONTHS_FOR_A_VERDICT:
            return False
        if self.noise_floor is None:
            return False
        return abs(self.rupees) > self.noise_floor

    def render(self) -> str:
        direction = "ahead of" if self.rupees >= 0 else "behind"
        head = f"**{self.left}** is {direction} **{self.right}** by ₹{abs(self.rupees):,.0f}"
        if self.months < MIN_MONTHS_FOR_A_VERDICT:
            return (
                f"{head} — but {self.months} month(s) of history is dominated by *when* the money "
                f"went in, not *what* was picked. No verdict before "
                f"{MIN_MONTHS_FOR_A_VERDICT} months."
            )
        if self.noise_floor is None:
            return (
                f"{head} — **not yet readable**: the bootstrap noise floor (Phase 4) does not exist, "
                "so there is no bar to say whether this gap is bigger than chance."
            )
        if not self.readable:
            return (
                f"{head}, which is **inside the ±₹{self.noise_floor:,.0f} noise floor** — that is "
                "not a result, it is the measurement's own scale."
            )
        return f"{head}, clearing the ±₹{self.noise_floor:,.0f} noise floor."


def _months_between(start: date | None, end: date) -> int:
    if start is None:
        return 0
    return max(0, (end.year - start.year) * 12 + end.month - start.month)


def compare(marks: dict[str, BookMark], *, noise_floor: Decimal | None = None) -> list[Gap]:
    """Every comparison the design asks for, with exactly one of them marked as gating.

    Order matters for the report: the gating pair leads, the ablations follow as diagnostics, and
    ``TWIN_FULL − REAL`` — does autonomy beat the user's own judgement — comes last because it is
    information about *him*, never a pass/fail on the system.
    """
    pairs = [
        (TWIN_FULL, BASELINE_EW),  # the only gate — the purchasable alternative
        (TWIN_FULL, BASELINE),  # reported: the do-nothing floor, never the bar
        (TWIN_FULL, TWIN_NO_AI),
        (TWIN_FULL, TWIN_NO_HEDGE),
        (TWIN_FULL, TWIN_NO_EXITS),
        (TWIN_FULL, REAL),
    ]
    out: list[Gap] = []
    for left, right in pairs:
        if left not in marks or right not in marks:
            continue
        lm, rm = marks[left], marks[right]
        out.append(
            Gap(
                left=left,
                right=right,
                rupees=lm.gain - rm.gain,
                gates=(left, right) == GATING_PAIR,
                months=_months_between(lm.start, lm.as_of),
                noise_floor=noise_floor,
            )
        )
    return out


def comparison_markdown(marks: dict[str, BookMark], gaps: Sequence[Gap]) -> str:
    """The panel. Leads with the gating comparison and says plainly what does *not* count."""
    lines = ["| Book | Net money in | Worth today | Gain | XIRR |", "|---|---:|---:|---:|---:|"]
    for name in ALL_BOOKS:
        m = marks.get(name)
        if m is None:
            continue
        rate = "—" if m.rate is None else f"{m.rate * 100:+.1f}%/yr"
        lines.append(
            f"| {'**' + name + '**' if name == TWIN_FULL else name} | ₹{m.net_invested:,.0f} | "
            f"₹{m.value:,.0f} | ₹{m.gain:+,.0f} | {rate} |"
        )
    gating = [g for g in gaps if g.gates]
    others = [g for g in gaps if not g.gates]
    if gating:
        lines += [
            "",
            "**The gate** (GO criterion 3 — the only comparison that authorises anything):",
        ]
        lines += [f"- {g.render()}" for g in gating]
    if others:
        lines += [
            "",
            "**Diagnostics — descriptive, never gating.** Four comparisons at 95% confidence throw "
            "a false positive about one run in five, so these attribute; they do not authorise:",
        ]
        lines += [f"- {g.render()}" for g in others]
    return "\n".join(lines)


def ew_fund_mark(
    flows: Sequence[Flow],
    ew_series: pd.Series,
    as_of: date,
    *,
    fee: Decimal = EW_FUND_FEE,
) -> BookMark | None:
    """The same rupees into an equal-weight index **fund** — the bar that decides whether to bother.

    ``ew_series`` is a point-in-time equal-weight index level (see
    :func:`qalpha.backtest.baselines.equal_weight_pit`, which rebalances monthly over the names
    actually in the index that month rather than holding today's survivors). The fund's annual fee is
    charged continuously, because the premium is only worth what it is worth **after** the cost of
    buying it — an unattainable zero-fee index is not an alternative anyone can hold.

    Note the asymmetry that makes this a fair fight rather than a rigged one: the fund rebalances
    internally with **no capital-gains tax at the fund level**, which the twin cannot do. It pays a
    fee the twin never pays. Both are real.
    """
    leg = benchmark_leg(flows, ew_series, as_of)
    if leg is None or not flows:
        return None
    years = Decimal(str((as_of - flows[0].on).days / 365.25))
    value = leg.value * (Decimal("1") - fee) ** years
    net = sum((f.amount for f in flows), Decimal("0"))
    dated = [(f.on, -f.amount) for f in flows] + [(as_of, value)]
    return BookMark(
        name=BASELINE_EW,
        as_of=as_of,
        start=flows[0].on,
        net_invested=net,
        value=value,
        rate=xirr(dated),
    )


# ---- persistence: the books have to survive between cron runs ------------------------------------

TWIN_STATE = Path("data/twin/books.json")


def save_books(books: dict[str, TwinBook], path: Path = TWIN_STATE) -> None:
    """Persist every book's portfolio and flows.

    The flows are stored **per book** rather than once, deliberately: it costs a few bytes and makes
    :func:`assert_identical_flows` a real check on reload instead of a tautology. If a bug ever gave
    one book a different flow, storing them once would hide it forever.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": date.today().isoformat(),
        "books": {
            name: {
                "portfolio": book.portfolio.to_state(),
                "flows": [{"on": f.on.isoformat(), "amount": str(f.amount)} for f in book.flows],
            }
            for name, book in books.items()
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_books(cfg: Config, path: Path = TWIN_STATE) -> dict[str, TwinBook]:
    """Reload the books, re-checking the identical-flow invariant rather than trusting the file."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    books = {
        name: TwinBook(
            name=name,
            portfolio=Portfolio.from_state(entry["portfolio"], cfg.cost, cfg.tax),
            flows=[
                Flow(on=date.fromisoformat(f["on"]), amount=Decimal(f["amount"]))
                for f in entry["flows"]
            ],
        )
        for name, entry in raw["books"].items()
    }
    assert_identical_flows(list(books.values()))
    return books
