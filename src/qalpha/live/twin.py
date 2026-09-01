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
- ``TWIN_NO_AI`` / ``TWIN_NO_EXITS`` — one factor removed each, so every gap is attributable to
  exactly one thing.
- ``TWIN_NO_HEDGE`` — ⚠️ **not a live ablation.** ``runner._hedge`` emits ``HEDGE_ON``/``HEDGE_OFF``
  decisions and moves no money: the overlay needs a futures position the real account cannot hold
  below ~₹19L (PLAN_REDESIGN §4b-i), so it is deliberately signal-only. The consequence is that
  ``TWIN_FULL − TWIN_NO_HEDGE`` is **₹0 by construction** and can never be evidence about the hedge.
  It is kept as a *signal log* — when the gauge fired, and for how long — and must never be reported
  as a measured hedge effect. Same shape as the defect that left the AI ablation starved, and named
  here so nobody reads its zero as a finding in 2027.
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
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.accounting.tax_lots import TaxLot
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.nav import unitized_nav
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

# ---- GO criterion 3: the statistic, pre-registered 2026-08-30 -----------------------------------
#
# **What was wrong before.** This used to be ``BACKTEST_NOISE_FLOOR = Decimal("8411106")`` — the p95
# of 60 no-skill draws from ``backtest_phase4.py``. That number was estimated over thirteen years and
# ₹78.5L of contributions **against the cap-weighted NIFTYBEES**, and then applied to a ₹3L book over
# twelve months **against the equal-weight fund**. Mismatched in scale, in horizon, and in benchmark:
# it asked a ₹3L book to beat luck by ₹84 lakh. The gate could not open, so twelve months of forward
# evidence would have bought a guaranteed non-answer. Retired, not re-tuned.
#
# **The replacement.** Every book receives *identical cash flows* (``assert_identical_flows``), so the
# ratio of terminal values isolates exactly what the strategy did differently — the flows cancel:
#
#     G = ln( V_TWIN_FULL / V_BASELINE_EW )
#
# Log relative wealth, not a difference of two XIRRs: no root-finding, no convergence failures on a
# lumpy SIP, and it is additive across sub-periods, so a 12-month G is the sum of its months. It is
# **scale-free** — the monthly SIP can grow the book by any factor and G is unmoved, which is the
# property the rupee floor lacked and the reason that floor died.
#
# Read it as a percentage with ``expm1(G)``: G = 0.02 is "2% more terminal wealth than the fund".
#
#: The null this is judged against, to be generated by a matched simulation and pre-registered
#: BEFORE the evaluation window closes. Its specification is fixed here on 2026-08-30 and may not be
#: changed while the clock runs — that is what voided forward run 1:
#:
#:   * 12-month windows drawn from point-in-time Nifty-50 history;
#:   * the same initial-capital-to-SIP ratio, ₹3L + ₹50,000/month;
#:   * identical deposit dates for the strategy leg and the benchmark leg;
#:   * random selection pushed through otherwise identical machinery (same costs, same tax, same
#:     whole-share rounding), so the null carries every friction the real book carries;
#:   * the equal-weight fund **net of its fee** as the benchmark leg.
#:
#: ``None`` until that null has been run — and ``None`` means the criterion reads CANNOT ASSESS, never
#: a pass. A bar that does not exist must never be silently treated as a bar of zero.
NULL_P95_LOG_REL_WEALTH: float | None = None

#: The day the registered 12-month window opens. **Immutable once the clock starts.**
#:
#: It exists because ``months`` was being counted from the first flow *ever recorded* — 2026-06-15,
#: two IPO-era trades that predate the experiment — so a window registered to open on 2026-08-31
#: would have reported "12 months" around June 2027, two months early, on evidence that includes a
#: period nobody registered. The evaluation window is a decision with a date; it is not "however far
#: back the tradebook happens to reach".
#:
#: Everything before this date is *starting basis*, already inside each book's opening value. The
#: gate measures what happens after it.
EVALUATION_START = date(2026, 8, 31)


def evaluation_months(as_of: date, *, start: date = EVALUATION_START) -> int:
    """Whole months of the registered window elapsed at ``as_of`` — never counted from a stray flow."""
    if as_of < start:
        return 0
    return max(0, (as_of.year - start.year) * 12 + as_of.month - start.month)


@dataclass(frozen=True)
class Gap:
    """One book measured against another, and whether it is allowed to mean anything yet."""

    left: str
    right: str
    rupees: Decimal
    gates: bool  # only TWIN_FULL − BASELINE_EW opens the GO gate; the rest describe
    months: int
    left_value: Decimal = Decimal("0")
    right_value: Decimal = Decimal("0")
    #: Unitized NAVs from ``EVALUATION_START`` — the gating statistic's actual inputs.
    left_nav: float | None = None
    right_nav: float | None = None
    #: p95 of the pre-registered null, in log units. ``None`` until that null exists.
    null_p95: float | None = None

    @property
    def log_rel_wealth(self) -> float | None:
        """G = ln(NAV_left / NAV_right) — the gating statistic. ``None`` until both NAVs exist.

        **Corrected 2026-08-30.** This was ``ln(V_left / V_right)`` on raw book *values*, described
        as scale-free. It is not. Identical contributions do not cancel in a ratio, they dilute it::

            ln(110 / 100)             = 0.0953
            ln((110+100) / (100+100)) = 0.0488

        Nothing happened in the market, and the measured lead halved. The old test multiplied two
        finished marks by ten and passed, because that proves invariance under *multiplicative*
        scaling — which is not what a SIP does to a book. A monthly deposit is additive, so the raw
        statistic would have drifted toward zero all year, understating whatever the strategy did.

        Both legs are now **unitized NAVs** (:mod:`qalpha.live.nav`), measured from
        ``EVALUATION_START``, which *is* invariant to contributions — that is the entire point of
        unitization. The rupee gap is kept alongside for the reader, never as the criterion.
        """
        if self.left_nav is None or self.right_nav is None:
            return None
        if self.left_nav <= 0 or self.right_nav <= 0:
            return None
        return math.log(self.left_nav / self.right_nav)

    @property
    def readable(self) -> bool:
        """Is this gap old enough, and larger than the pre-registered null, to be evidence?"""
        if self.months < MIN_MONTHS_FOR_A_VERDICT:
            return False
        if self.null_p95 is None:
            return False
        g = self.log_rel_wealth
        return g is not None and abs(g) > self.null_p95

    def render(self) -> str:
        direction = "ahead of" if self.rupees >= 0 else "behind"
        head = f"**{self.left}** is {direction} **{self.right}** by ₹{abs(self.rupees):,.0f}"
        g = self.log_rel_wealth
        if g is not None:
            head += f" ({math.expm1(g) * 100:+.2f}% relative wealth, G={g:+.4f})"
        # Time first: before the window closes, no size of gap means anything, so the size is never
        # dressed up as a finding. This is the branch the report will sit in for the next 12 months.
        if self.months < MIN_MONTHS_FOR_A_VERDICT:
            return (
                f"{head} — **descriptive only**, {self.months} of {MIN_MONTHS_FOR_A_VERDICT} months. "
                "A window this short is dominated by *when* the money went in, not *what* was "
                "picked. No verdict before the locked 12-month evaluation."
            )
        if g is None:
            return (
                f"{head} — **not readable**: the unitized NAVs the statistic needs are not "
                "available yet (they accrue from EVALUATION_START in data/twin/history.jsonl)."
            )
        if self.null_p95 is None:
            return (
                f"{head} — **not yet readable**: the pre-registered null has not been run, so there "
                "is no bar to say whether this is bigger than chance. See NULL_P95_LOG_REL_WEALTH."
            )
        if not self.readable:
            return (
                f"{head}, which is **inside the ±{self.null_p95:.4f} null band** — that is not a "
                "result, it is what luck produces at this horizon."
            )
        return f"{head}, clearing the ±{self.null_p95:.4f} null band."


def _months_between(start: date | None, end: date) -> int:
    if start is None:
        return 0
    return max(0, (end.year - start.year) * 12 + end.month - start.month)


def compare(
    marks: dict[str, BookMark],
    *,
    null_p95: float | None = None,
    navs: Mapping[str, float] | None = None,
) -> list[Gap]:
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
                # The registered window, not "however far back the tradebook reaches".
                months=evaluation_months(lm.as_of),
                left_value=lm.value,
                right_value=rm.value,
                left_nav=(navs or {}).get(left),
                right_nav=(navs or {}).get(right),
                null_p95=null_p95,
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

#: The daily record, one JSON object per line, **append-only**.
#:
#: **Why this file exists.** ``data/twin/marks.json`` is written with ``write_text`` — it holds
#: exactly one day and every run destroys the last. ``books.json`` is likewise a snapshot: current
#: lots, current flows, no path. So before this file, the twin retained *no history of any book*.
#: Twelve months of forward evidence would have arrived as a terminal value and nothing else, and
#: every path-dependent question — the worst drawdown, the volatility of the gap, whether TWIN_FULL
#: and TWIN_NO_AI ever diverged and when — would have been permanently unanswerable. Not wrong:
#: *unaskable*. Every other defect on the August 2026 audit list operates on data that still exists
#: and can be recomputed. This one was deleting the evidence daily.
#:
#: One line per day is ~600 bytes; a decade is under 2 MB. There is no reason to prune it, ever.
TWIN_HISTORY = Path("data/twin/history.jsonl")

#: Every AI keep/drop verdict, with the provenance needed to grade it later. Also append-only.
#: A verdict without its *decision date and the price on that date* cannot be scored afterwards —
#: the counterfactual ("what did the name we dropped go on to do?") is exactly the question the
#: whole AI experiment exists to answer, and it is unanswerable from a verdict alone.
AI_VERDICT_HISTORY = Path("data/twin/ai_verdicts.jsonl")


def _append_jsonl(path: Path, rows: Sequence[Mapping[str, object]], *, key: str) -> int:
    """Append ``rows`` to a JSONL file, replacing any existing rows with the same ``key`` value.

    Same-day idempotence without ever losing a *different* day: the cron may run twice, or be
    re-run by hand after a fix, and the second run must correct today's row rather than duplicate
    it. Everything else is carried through untouched.

    **The guard is the point.** The rewrite is atomic (temp file + ``os.replace``), and it refuses
    outright if it would end up shorter than what is already on disk minus today. A file whose whole
    job is to be un-loseable must not be truncatable by a bug in the thing that writes it.
    """
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, object]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing.append(json.loads(line))
            except json.JSONDecodeError:
                # A half-written line from a killed process. Keeping the file readable matters more
                # than that one row, but never drop it silently.
                print(f"[twin] WARNING: unparseable line in {path}, preserved as-is: {line[:80]}")
                continue
    superseded = {r[key] for r in rows if key in r}
    kept = [r for r in existing if r.get(key) not in superseded]
    out = kept + list(rows)
    if len(out) < len(existing) - len(superseded):
        raise RuntimeError(
            f"refusing to write {path}: {len(out)} rows would replace {len(existing)}. "
            "This file is append-only; a shrink is a bug, not an update."
        )
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for row in out:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    os.replace(tmp, path)
    return len(out)


def append_history(
    marks: Mapping[str, BookMark],
    gaps: Sequence[Gap],
    *,
    as_of: date,
    gate_verdict: str | None = None,
    path: Path = TWIN_HISTORY,
) -> int:
    """Record one day of every book, so a path exists to look back at. Returns total rows on file.

    Stores the **inputs to every later statistic**, not the statistics themselves: value, net
    invested and XIRR per book, plus the gating gap in both rupees and log relative wealth. Anything
    computed downstream — drawdown, tracking error, the significance of the gap — is recoverable from
    these, and recoverable *retroactively*, which is the whole point of keeping them.
    """
    gating = next((g for g in gaps if g.gates), None)
    row: dict[str, object] = {
        "as_of": as_of.isoformat(),
        "books": {
            name: {
                "value": str(m.value),
                "net_invested": str(m.net_invested),
                "xirr": m.rate,
                "start": m.start.isoformat() if m.start else None,
            }
            for name, m in sorted(marks.items())
        },
        "gate": {
            "verdict": gate_verdict,
            "pair": list(GATING_PAIR),
            "rupees": str(gating.rupees) if gating else None,
            "log_rel_wealth": gating.log_rel_wealth if gating else None,
            "months": gating.months if gating else None,
            "null_p95": gating.null_p95 if gating else None,
        },
    }
    return _append_jsonl(path, [row], key="as_of")


def load_history(path: Path = TWIN_HISTORY) -> list[dict[str, object]]:
    """Every recorded day, oldest first. Missing file → empty list, never an exception."""
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    rows.sort(key=lambda r: str(r.get("as_of", "")))
    return rows


def navs_from_history(
    rows: Sequence[Mapping[str, object]], *, start: date = EVALUATION_START
) -> dict[str, float]:
    """Each book's unitized NAV at the last recorded day, measured from ``start``.

    **Where the contributions come from.** Each row already carries every book's ``net_invested``, so
    the money added on a given day is simply the day-on-day *difference* in that figure — no separate
    flow file, and no way for the two to disagree. The append-only record turns out to hold exactly
    what the corrected statistic needs, which is the argument for having built it before the clock
    started rather than after.

    Rows before ``start`` are ignored: whatever happened before the registered window is opening
    basis, already inside the first value. Returns ``{}`` when fewer than one row qualifies, which
    propagates to a ``log_rel_wealth`` of ``None`` and a criterion 3 of ⚪ CANNOT ASSESS.
    """
    usable = [r for r in rows if str(r.get("as_of", "")) >= start.isoformat()]
    if not usable:
        return {}
    names: set[str] = set()
    for row in usable:
        books = row.get("books")
        if isinstance(books, Mapping):
            names.update(str(n) for n in books)

    out: dict[str, float] = {}
    for name in sorted(names):
        days: list[pd.Timestamp] = []
        values: list[float] = []
        invested: list[float] = []
        for row in usable:
            books = row.get("books")
            if not isinstance(books, Mapping) or name not in books:
                continue
            entry = books[name]
            if not isinstance(entry, Mapping):
                continue
            try:
                values.append(float(str(entry["value"])))
                invested.append(float(str(entry["net_invested"])))
            except (KeyError, TypeError, ValueError):
                continue
            days.append(pd.Timestamp(str(row["as_of"])))
        if len(days) < 1:
            continue
        # A day's contribution is the rise in net_invested since the previous recorded day.
        flows = [
            (days[i].date(), invested[i] - invested[i - 1])
            for i in range(1, len(invested))
            if invested[i] > invested[i - 1]
        ]
        series = pd.Series(values, index=pd.DatetimeIndex(days))
        out[name] = float(unitized_nav(series, flows).iloc[-1])
    return out


def append_ai_attempt(
    *,
    as_of: date,
    status: str,
    detail: str = "",
    raw: str = "",
    model: str = "",
    prompt_version: str = "",
    undeployed_cash: str = "",
    path: Path = AI_VERDICT_HISTORY,
) -> int:
    """Record that the AI step *happened*, whatever came of it. One row per eligible day.

    **Why silence is not good enough.** Before this, four very different days all produced no rows at
    all: cash under the deploy floor so the model was never asked; no API key; an error or refusal;
    and a clean run where the model kept every name. In August 2027 those are indistinguishable, and
    the difference between "the AI never got to speak" and "the AI looked and found nothing" is the
    difference between no experiment and a null result.

    ``raw`` keeps the model's actual response — the searched text behind the twelve-word reason.
    Without it a veto cannot be re-read later, and re-reading it is how a legitimate governance call
    is told apart from a fabrication.
    """
    row = {
        "as_of": as_of.isoformat(),
        "kind": "attempt",
        "status": status,
        "detail": detail[:500],
        "model": model,
        "prompt_version": prompt_version,
        "undeployed_cash": undeployed_cash,
        "raw": raw[:20000],
        "_key": f"{as_of.isoformat()}:__attempt__",
    }
    return _append_jsonl(path, [row], key="_key")


def append_ai_verdicts(
    verdicts: Mapping[str, Mapping[str, object]],
    prices: Mapping[str, Decimal],
    *,
    as_of: date,
    model: str,
    prompt_version: str,
    path: Path = AI_VERDICT_HISTORY,
) -> int:
    """Record every keep/drop verdict with what is needed to score it a year from now.

    ``price_at_decision`` is the load-bearing field: with it, the counterfactual for a dropped name
    is a lookup against any later price panel. Without it, a DROP is an opinion with no outcome
    attached and the experiment can never be settled.
    """
    rows = [
        {
            "as_of": as_of.isoformat(),
            "ticker": ticker,
            "call": str(v.get("call", "")),
            "confidence": str(v.get("confidence", "")),
            "reason": str(v.get("reason", "")),
            "source": str(v.get("source", "")),
            "price_at_decision": str(prices.get(ticker, "")),
            "model": model,
            "prompt_version": prompt_version,
            "kind": "verdict",
        }
        for ticker, v in sorted(verdicts.items())
    ]
    if not rows:
        return 0
    # Keyed on date+ticker so a same-day re-run corrects rather than duplicates.
    for r in rows:
        r["_key"] = f"{r['as_of']}:{r['ticker']}"
    return _append_jsonl(path, rows, key="_key")


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


def sync_flows(
    books: dict[str, TwinBook],
    trades: Sequence[object],
    credits: Sequence[OffMarketCredit] = (),
) -> list[Flow]:
    """Credit any **new or amended** cash flows to every book, keeping them identical.

    Without this the twin's flows freeze at seed time while ``REAL`` is replayed fresh from the
    tradebook every run — so the user's next purchase lands in ``REAL`` and in none of the books it
    is compared against. The identical-flow invariant would break **silently, on the next SIP**, and
    every gap after that would be measuring different amounts of money rather than different
    decisions. It is the flaw that voided a predecessor run, arriving by a different door.

    Diffed **by day**, not by count: ``flows_from_trades`` nets each day's trades into one flow, so a
    new trade on a day already seen *amends* that day's amount rather than appending a flow. Both
    cases are credited as a delta, and the amended case is exactly the one a length check misses —
    which is why this compares amounts.

    Returns the deltas applied, so the caller can log what changed rather than infer it.
    """
    if not books:
        return []
    current = flows_with_off_market(trades, credits)
    known = {f.on: f.amount for f in next(iter(books.values())).flows}
    deltas = [
        Flow(on=f.on, amount=f.amount - known.get(f.on, Decimal("0")))
        for f in current
        if f.amount != known.get(f.on, Decimal("0"))
    ]
    if not deltas:
        return []
    for book in books.values():
        for d in deltas:
            book.portfolio.cash += d.amount
        book.flows = list(current)
    assert_identical_flows(list(books.values()))
    return deltas


def comparison_frame(marks: dict[str, BookMark]) -> pd.DataFrame:
    """Every book's return on one basis, for plotting — long form, ready for a chart.

    Return **against net money in**, because that is the only basis every book shares: they were
    handed the same rupees on the same days, so it is the one denominator that makes the bars
    comparable rather than merely adjacent.
    """
    rows = [
        {
            "Book": name,
            "Return %": float(m.gain / m.net_invested * 100) if m.net_invested else 0.0,
            "Gain": float(m.gain),
            "Value": float(m.value),
        }
        for name in ALL_BOOKS
        if (m := marks.get(name)) is not None
    ]
    return pd.DataFrame(rows)


def holdings_frame(book: TwinBook, prices: dict[str, Decimal]) -> pd.DataFrame:
    """One row per holding with its share of the book — the input to a composition chart.

    Weights are of **equity**, not of equity + cash. A slice labelled with the account total would
    understate every position: on the real account the same mistake read HCLTECH at 3.3% when it was
    17.8%, and it is the number concentration is judged by.
    """
    equity = book.portfolio.holdings_value(prices)
    rows = [
        {
            "Ticker": t.removesuffix(".NS"),
            "Value": float(q * prices[t]),
            "Share %": float(q * prices[t] / equity * 100) if equity else 0.0,
        }
        for t, q in sorted(book.portfolio.positions().items())
        if t in prices
    ]
    # An empty frame has no columns, so sorting by name raises KeyError — which took the live
    # dashboard down on a book that held nothing (or whose names the panel could not price).
    # Return the shape the caller expects rather than an untyped empty frame.
    columns = ["Ticker", "Value", "Share %"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values("Value", ascending=False)
        .reset_index(drop=True)
    )


# ---- off-market credits: IPO allotments, gifts, demat transfers -----------------------------------

OFF_MARKET_PATH = Path("data/twin/off_market.json")


@dataclass(frozen=True)
class OffMarketCredit:
    """Shares that arrived **outside** the tradebook — an IPO allotment, a gift, a demat transfer.

    A Zerodha tradebook export contains *trades*. An IPO allotment is not a trade: the shares appear
    in holdings with no matching row, so a tradebook replay silently under-counts the account. That
    already shows up as a reconciliation warning on the Live tab; for the twin it is worse, because
    the money was never credited to any book. ``REAL`` would hold shares the twins were never funded
    for, and every gap after that would compare different amounts of money — the identical-flow
    invariant broken from the opposite direction to a missed SIP.

    Recording one here credits the **cost** to every book as a dated flow (so the twins can deploy
    the same rupees their own way) and gives ``REAL`` the actual lot (so its tax and holding period
    are right). ``cost_per_share`` is the IPO issue price — the acquisition cost for §48, not the
    listing price.
    """

    ticker: str
    on: date
    quantity: Decimal
    cost_per_share: Decimal
    note: str = ""

    @property
    def amount(self) -> Decimal:
        return self.quantity * self.cost_per_share


def load_off_market(path: Path = OFF_MARKET_PATH) -> list[OffMarketCredit]:
    """Read the recorded off-market credits, oldest first."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    credits = [
        OffMarketCredit(
            ticker=str(e["ticker"]),
            on=date.fromisoformat(str(e["on"])),
            quantity=Decimal(str(e["quantity"])),
            cost_per_share=Decimal(str(e["cost_per_share"])),
            note=str(e.get("note", "")),
        )
        for e in raw.get("credits", [])
    ]
    return sorted(credits, key=lambda c: c.on)


def flows_with_off_market(
    trades: Sequence[object], credits: Sequence[OffMarketCredit]
) -> list[Flow]:
    """Tradebook flows **plus** off-market credits, netted per day and ordered.

    The credit is money the user put in, so every book must receive it on the day it arrived —
    exactly as a purchase would be. Netting per day matters because an allotment can land on a day
    that already has trades.
    """
    by_day: dict[date, Decimal] = {f.on: f.amount for f in flows_from_trades(trades)}
    for credit in credits:
        by_day[credit.on] = by_day.get(credit.on, Decimal("0")) + credit.amount
    return [Flow(on=d, amount=by_day[d]) for d in sorted(by_day)]


def apply_off_market(portfolio: Portfolio, credits: Sequence[OffMarketCredit]) -> None:
    """Give ``REAL`` the actual lots, so its holding period and FIFO cost basis are correct.

    Added as dated lots rather than bought, because no cash left the account through the broker on
    that date — the money went out at application, and the shares arrived on allotment. The
    acquisition date is what §2(42A) counts from, and it is the allotment date.
    """
    for credit in credits:
        portfolio.ledger.add_lot(
            TaxLot(
                ticker=credit.ticker,
                acquisition_date=credit.on,
                quantity_original=credit.quantity,
                buy_price=credit.cost_per_share,
            )
        )


def unexplained_holdings(
    replayed: Portfolio, broker_qty: Mapping[str, Decimal], broker_price: Mapping[str, Decimal]
) -> list[OffMarketCredit]:
    """Shares the broker holds that the tradebook cannot explain — detected, not typed.

    ``kite.holdings()`` returns **settled demat holdings**, so an IPO allotment appears there as soon
    as it credits. That gives three of the four fields for free: the ticker, the quantity, and
    ``average_price`` — which for an allotment *is* the issue price paid. The one thing the broker
    cannot supply is the **acquisition date**: ``holdings()`` carries no purchase dates at all.

    So the missing shares are dated **conservatively by the caller** rather than guessed. Assuming a
    recent acquisition makes them short-term, which taxes at 20% instead of 12.5% — an over-statement.
    The user can set the true allotment date in ``off_market.json`` to recover the correct twelve-month
    clock; until then the figure is wrong in the direction that cannot cost him money.
    """
    held = replayed.positions()
    out: list[OffMarketCredit] = []
    for ticker, qty in sorted(broker_qty.items()):
        gap = qty - held.get(ticker, Decimal("0"))
        price = broker_price.get(ticker)
        if gap > 0 and price is not None and price > 0:
            out.append(
                OffMarketCredit(
                    ticker=ticker,
                    on=date.today(),  # placeholder; the caller stamps the conservative date
                    quantity=gap,
                    cost_per_share=price,
                    note="detected from broker holdings — date unknown",
                )
            )
    return out


def off_market_snippet(credits: Sequence[OffMarketCredit]) -> str:
    """A ready-to-paste ``off_market.json`` entry, pre-filled with everything the broker knew.

    Only ``on`` is left for the user, because it is the only field he holds that the API does not.
    """
    lines = [
        '  "credits": [',
        *[
            "    {"
            f'"ticker": "{c.ticker}", "on": "YYYY-MM-DD", '
            f'"quantity": "{c.quantity.normalize()}", '
            f'"cost_per_share": "{c.cost_per_share}", "note": "IPO allotment"'
            "}" + ("," if i < len(credits) - 1 else "")
            for i, c in enumerate(credits)
        ],
        "  ]",
    ]
    return "\n".join(lines)
