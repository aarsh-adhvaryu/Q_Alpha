"""The books — one set of cash flows, four ways of using it.

- ``SYSTEM``      — the AI investor's paper book. Seeded from ``REAL``; mirrors it until a registered
  start date, then decides for itself.
- ``REAL``        — the user's own trades, replayed from his tradebook.
- ``BASELINE_EW`` — the same rupees into a Nifty-50 equal-weight index fund, net of its fee.
- ``BASELINE``    — the same rupees into NIFTYBEES, bought and held.

**Every book receives the same rupees on the same days.** The flows come from the tradebook and
nowhere else. :func:`assert_identical_flows` asserts it rather than assuming it, because a flow one
book got and another did not would silently make the comparison about timing instead of decisions.

Nothing here touches a broker. These are paper books.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction
from qalpha.accounting.portfolio import Portfolio
from qalpha.accounting.tax_lots import TaxLot
from qalpha.config import Config
from qalpha.live.flows import Flow, benchmark_leg, flows_from_trades, xirr
from qalpha.live.nav import unitized_nav

#: The user's own trades, replayed.
REAL = "REAL"
#: The AI investor's paper book.
SYSTEM = "SYSTEM"
#: The cap-weighted index, bought and held. The do-nothing comparison.
BASELINE = "BASELINE"
#: The equal-weight Nifty-50 index fund, net of its fee — the bar. Beating cap-weighted NIFTYBEES is
#: not the achievement it looks like: most of that gap is an equal-weight premium anyone can buy.
BASELINE_EW = "BASELINE_EW"

#: Books that make their own decisions.
DECIDING = (SYSTEM,)
#: Every book in the comparison, in report order.
ALL_BOOKS = (REAL, SYSTEM, BASELINE_EW, BASELINE)

#: Annual expense ratio of the cheapest Nifty-50 equal-weight index fund available (DSP, direct).
#: Charged against the EW baseline so it is a purchasable alternative, not an unattainable index.
EW_FUND_FEE = Decimal("0.0041")

#: Below a year of history an annualized rate is withheld from the page rather than extrapolated.
MIN_DAYS_FOR_A_RATE = 365


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
    #: The last date this book's policy was stepped. **Guards a re-run from acting twice.** The
    #: cron saves books mid-job; if a later stage fails and the job is retried, stepping again would
    #: re-execute that day's paper decisions — buying the same basket a second time — and the
    #: append-only record would show one day's flows twice. Compared, never trusted to a lock file.
    stepped_through: date | None = None
    #: The investor's own state for this book: version, model, orders waiting for their fill session,
    #: and the last review. Empty for a book no investor has run. Its records live in
    #: ``data/twin/manager/``; this is only what the next evening must know.
    manager: dict[str, Any] = field(default_factory=dict)
    #: The date through which corporate actions have been credited to **this** book. REAL and any
    #: book still mirroring it get theirs from the tradebook replay, which recomputes from scratch;
    #: a book deciding for itself has its own holdings and is credited forward from here. Two
    #: watermarks rather than one because a dividend credited twice is indistinguishable, afterwards,
    #: from a dividend that was larger.
    actions_through: date | None = None
    #: The earliest trade date any export has ever shown for this account. The export guard compares
    #: against it, so a later, shorter export cannot quietly replay REAL without its oldest lots.
    #: It only ever moves **backwards**: a longer export lowers it, a shorter one is refused.
    earliest_trade: date | None = None

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


def credit_actions(
    book: TwinBook,
    actions: Sequence[CorporateAction],
    *,
    through: date,
) -> list[str]:
    """Credit corporate actions due to a book that decides for itself, and say what changed.

    REAL, and any book still mirroring it, get their actions from the tradebook replay, which
    recomputes the whole book from the trades every run and therefore cannot double-credit. A book
    with its own holdings has no such replay, so it is credited **forward from a watermark**: only
    actions after the last date it was brought up to date, and never past ``through``.

    A book that has never been brought up to date is moved to ``through`` and credited nothing. That
    is deliberate: the alternative is replaying every action a book may already have received
    through some other path, and a dividend credited twice is indistinguishable, afterwards, from a
    dividend that was larger.

    Entitlement is the holding on the ex-date. A name the book does not hold is skipped rather than
    credited zero, so the note list is what actually happened.
    """
    since = book.actions_through or book.stepped_through or book.start
    notes: list[str] = []
    if since is not None:
        for action in sorted(actions, key=lambda a: (a.ex_date, a.ticker)):
            if not since < action.ex_date <= through:
                continue
            if book.portfolio.ledger.quantity_held(action.ticker) <= 0:
                continue
            notes.append(book.portfolio.apply_corporate_action(action).note)
    book.actions_through = through
    return notes


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


def partial_export_reason(trades: Sequence[object], earliest_seen: date | None) -> str | None:
    """Why this export cannot rebuild the books, or ``None`` when it reaches far enough back.

    ### The failure this closes

    ``REAL`` is replayed from the export on every run while the twins keep the flows they were
    credited. An export that starts *after* trading began therefore replays ``REAL`` short — it buys
    none of the earlier lots — and every twin appears to beat it by whatever those lots are worth.
    That is the empty-tradebook defect with one row in it instead of none, and the empty check alone
    does not see it. A Console export is chosen by date range in a dropdown, so this is the mistake
    a person actually makes.

    ### What it compares against, and why that changed

    ``earliest_seen`` is the earliest trade date **any** export has ever shown — a watermark the
    books keep. It used to be the first cash flow, which worked only while the flows came from the
    tradebook and the first flow therefore *was* the first trade. Once the books were funded from
    the broker's ledger, the first flow became a deposit, and money sits in an account before it
    buys anything: the guard fired on a complete export whose first trade was one day after the
    deposit that paid for it. The watermark says what the guard actually means, and is strictly
    tighter — it catches a shorter export even when no deposit precedes it.
    """
    if not trades or earliest_seen is None:
        return None
    earliest = min(t.trade_date for t in trades)  # type: ignore[attr-defined]
    if earliest <= earliest_seen:
        return None
    return (
        f"the export starts {earliest} but an earlier export showed trading from {earliest_seen}. "
        f"Replaying REAL from it would miss every trade before {earliest}, and each missing lot "
        "would read as a lead for every other book. Export from Zerodha Console covering "
        f"{earliest_seen} to today and drop it in data/tradebooks/ (overlapping ranges are safe — "
        "they de-duplicate on trade ids)."
    )


def seed_books(
    trades: Sequence[object],
    cfg: Config,
    *,
    names: Sequence[str] = ALL_BOOKS,
    flows: Sequence[Flow] | None = None,
) -> dict[str, TwinBook]:
    """Build every book from one tradebook, each funded with the identical dated flows.

    ``REAL``'s holdings are the user's actual trades, replayed. The baselines start as pure cash and
    buy their index with it. Seeding them here — from the same source, in one place — is what makes
    :func:`assert_identical_flows` trivially true by construction rather than a hope.

    **SYSTEM is seeded as a copy of REAL, not as cash**, and that is the whole shape of the
    experiment. It holds precisely what the user holds on the day it is created, follows the
    tradebook until :data:`EVALUATION_START`, and only then begins to choose. Two books from one
    state means every later difference between them is a decision — not a different starting point,
    and not the luck of when the money went in, which is what nine books funded by a cash-flow tap
    could never separate.
    """
    # Funding, when it has been imported from the broker's ledger, is the money that actually
    # entered the account. Falling back to the tradebook funds every book with what was *spent on
    # shares*, which leaves idle cash outside the comparison entirely.
    dated = list(flows) if flows is not None else flows_from_trades(trades)
    books: dict[str, TwinBook] = {}
    for name in names:
        pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
        pf.cash = sum((f.amount for f in dated), Decimal("0"))
        books[name] = TwinBook(name=name, portfolio=pf, flows=list(dated))
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
    #: How much of ``value`` is uninvested cash. The baselines hold none by construction: they buy
    #: fractional units of the fund with every rupee on the day it arrives. The investor may spend
    #: only ₹50,000 a month, so it holds cash for months — which *helps* it in a falling market and
    #: costs it in a rising one, for no decision it made. A lead that is only uninvested cash must
    #: not be readable as skill, so the figure sits beside the gain rather than inside it.
    cash: Decimal = Decimal("0")

    @property
    def gain(self) -> Decimal:
        return self.value - self.net_invested

    @property
    def invested(self) -> Decimal:
        """What is actually in the market — the part of the book that can gain or lose."""
        return self.value - self.cash


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
        cash=book.portfolio.cash,
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


#: **The first evening AI-PM-3 decides for SYSTEM** — the one start date in the repository.
#:
#: Written in ``reports/PREREGISTRATION_AI_PM3.md`` §7 in the same commit, and read by
#: ``agent.Registration.start``, so the evening run, the investor, the page and the evaluation cannot
#: disagree about when deciding began. Forward-dated: starting on days whose outcome is already known
#: is selection on the outcome. On a holiday the first review is the first session on or after it.
#:
#: ``None``: not started. SYSTEM mirrors REAL and nothing is measured. AI-PM-1 and AI-PM-2, whose
#: starts were set here before, were retired on 2026-09-15 without making a decision.
EVALUATION_START: date | None = None


def is_autonomous(as_of: date, *, start: date | None = EVALUATION_START) -> bool:
    """May ``SYSTEM`` decide for itself on this day?

    Before the registered start it mirrors the user: same holdings, no choices of its own. The date
    is a constant rather than a flag so that "when did it start deciding" has exactly one answer,
    on file, and cannot be nudged by a run that went badly. **No registered start means never** —
    an absent date is not a date in the past.
    """
    return start is not None and as_of >= start


@dataclass(frozen=True)
class Gap:
    """One book against another over the same flows. **Descriptive — it authorises nothing.**

    One book over months is mostly timing and luck. The rupee gap is shown for the reader; relative
    wealth is ``ln(NAV_left / NAV_right)`` on unitized NAVs, which a deposit does not dilute.
    """

    left: str
    right: str
    rupees: Decimal
    left_value: Decimal = Decimal("0")
    right_value: Decimal = Decimal("0")
    #: Unitized NAVs from the registered start. ``None`` until a window exists — never 1.0.
    left_nav: float | None = None
    right_nav: float | None = None

    @property
    def log_rel_wealth(self) -> float | None:
        if self.left_nav is None or self.right_nav is None:
            return None
        if self.left_nav <= 0 or self.right_nav <= 0:
            return None
        return math.log(self.left_nav / self.right_nav)

    def render(self) -> str:
        direction = "ahead of" if self.rupees >= 0 else "behind"
        head = f"**{self.left}** is {direction} **{self.right}** by ₹{abs(self.rupees):,.0f}"
        g = self.log_rel_wealth
        if g is None:
            return (
                f"{head} — relative wealth not measurable yet: no unitized NAVs on file for the "
                "registered window."
            )
        return f"{head} ({math.expm1(g) * 100:+.2f}% relative wealth since the start)."


def compare(marks: dict[str, BookMark], *, navs: Mapping[str, float] | None = None) -> list[Gap]:
    """SYSTEM against the fund, against doing nothing, and against what the user actually did."""
    out: list[Gap] = []
    for left, right in ((SYSTEM, BASELINE_EW), (SYSTEM, BASELINE), (SYSTEM, REAL)):
        if left not in marks or right not in marks:
            continue
        lm, rm = marks[left], marks[right]
        out.append(
            Gap(
                left=left,
                right=right,
                rupees=lm.gain - rm.gain,
                left_value=lm.value,
                right_value=rm.value,
                left_nav=(navs or {}).get(left),
                right_nav=(navs or {}).get(right),
            )
        )
    return out


def comparison_markdown(marks: dict[str, BookMark], gaps: Sequence[Gap]) -> str:
    lines = [
        "| Book | Net money in | In the market | Cash | Worth today | Gain | XIRR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ALL_BOOKS:
        m = marks.get(name)
        if m is None:
            continue
        # An annual rate from a few months of returns reads as a disaster or a miracle. Under a
        # year of history the rate is withheld, not extrapolated.
        young = m.start is None or (m.as_of - m.start).days < MIN_DAYS_FOR_A_RATE
        rate = (
            "— (under a year)" if young else ("—" if m.rate is None else f"{m.rate * 100:+.1f}%/yr")
        )
        lines.append(
            f"| {'**' + name + '**' if name == SYSTEM else name} | ₹{m.net_invested:,.0f} | "
            f"₹{m.invested:,.0f} | ₹{m.cash:,.0f} | "
            f"₹{m.value:,.0f} | ₹{m.gain:+,.0f} | {rate} |"
        )
    if gaps:
        lines += [
            "",
            "The baselines hold no cash: they buy the fund with every rupee on the day it arrives. "
            "A book holding cash is not a book that is winning or losing — read the gap with the "
            "cash column.",
            "",
            "Descriptive — what happened between two books, not evidence of skill:",
        ]
        lines += [f"- {g.render()}" for g in gaps]
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
    :func:`qalpha.live.benchmarks.equal_weight_pit`, which rebalances monthly over the names
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
#: every path-dependent question — the worst drawdown, the volatility of the gap, whether SYSTEM
#: and TWIN_NO_AI ever diverged and when — would have been permanently unanswerable. Not wrong:
#: *unaskable*. Every other defect on the August 2026 audit list operates on data that still exists
#: and can be recomputed. This one was deleting the evidence daily.
#:
#: One line per day is ~600 bytes; a decade is under 2 MB. There is no reason to prune it, ever.
TWIN_HISTORY = Path("data/twin/history.jsonl")


def _append_jsonl(path: Path, rows: Sequence[Mapping[str, object]], *, key: str) -> int:
    """Append ``rows`` to a JSONL file. **A correction never deletes what it corrects.**

    Until 2026-09-05 a same-key row *replaced* the row already on file. That is a rewrite wearing an
    append's name: re-running the cron after changing the code silently substituted the new rule's
    answer for the old rule's answer, on the same date, with nothing left to say it had happened.
    The whole reason this file exists is that ``marks.json`` used to be rewritten daily.

    Now a repeat key is written as a **new row with ``revision`` incremented**, and every earlier
    revision stays exactly where it was. Readers take the highest revision per key
    (:func:`latest_by_key`); auditors get the entire sequence, including what was believed before.

    **The guard is the point.** The rewrite is atomic (temp file + ``os.replace``) and it refuses
    outright if the result would be shorter than what is already on disk. A file whose whole job is
    to be un-loseable must not be truncatable by a bug in the thing that writes it.
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
    highest: dict[object, int] = {}
    for row in existing:
        k = row.get(key)
        if k is not None:
            try:
                highest[k] = max(highest.get(k, 0), int(str(row.get("revision", 0))))
            except ValueError:
                highest[k] = max(highest.get(k, 0), 0)
    appended: list[dict[str, object]] = []
    for incoming in rows:
        fresh: dict[str, object] = dict(incoming)
        k = fresh.get(key)
        if k is None:
            fresh.setdefault("revision", 0)
        else:
            fresh["revision"] = highest[k] + 1 if k in highest else 0
            highest[k] = int(str(fresh["revision"]))
        appended.append(fresh)
    out = list(existing) + appended
    if len(out) < len(existing):
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


def latest_by_key(rows: Sequence[Mapping[str, object]], *, key: str) -> list[dict[str, object]]:
    """The current view of an append-only record: highest ``revision`` per ``key``, order preserved.

    Superseded revisions stay on file and stay readable — this only decides which one *counts*.
    """
    best: dict[object, dict[str, object]] = {}
    order: list[object] = []
    for row in rows:
        k = row.get(key)
        if k is None:
            continue
        if k not in best:
            order.append(k)
        try:
            rev = int(str(row.get("revision", 0)))
        except ValueError:
            rev = 0
        prior = best.get(k)
        if prior is None or rev >= int(str(prior.get("revision", 0))):
            best[k] = dict(row)
    return [best[k] for k in order]


def append_history(
    marks: Mapping[str, BookMark],
    gaps: Sequence[Gap],
    *,
    as_of: date,
    path: Path = TWIN_HISTORY,
) -> int:
    """Record one day of every book, so a path exists to look back at. Returns total rows on file.

    Stores the **inputs to every later statistic**: value, net invested and XIRR per book, plus each
    gap. Drawdown, tracking error and anything else are recoverable from these, retroactively.
    """

    row: dict[str, object] = {
        "as_of": as_of.isoformat(),
        "books": {
            name: {
                "value": str(m.value),
                "net_invested": str(m.net_invested),
                # Uninvested cash, so a later reader can tell a lead that was earned from a lead
                # that is only money the book had not spent yet.
                "cash": str(m.cash),
                "xirr": m.rate,
                "start": m.start.isoformat() if m.start else None,
            }
            for name, m in sorted(marks.items())
        },
        "gaps": [
            {"pair": [g.left, g.right], "rupees": str(g.rupees), "log_rel_wealth": g.log_rel_wealth}
            for g in gaps
        ],
    }
    return _append_jsonl(path, [row], key="as_of")


def load_history(path: Path = TWIN_HISTORY) -> list[dict[str, object]]:
    """Every recorded day, oldest first, at its **current revision**.

    Superseded revisions remain on file; :func:`latest_by_key` decides which one counts. Missing
    file → empty list, never an exception.
    """
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
    return latest_by_key(rows, key="as_of")


def navs_from_history(
    rows: Sequence[Mapping[str, object]], *, start: date | None = EVALUATION_START
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

    With no registered start there is no window to unitize from, so the answer is ``{}`` —
    unmeasured, never a NAV of 1.0.
    """
    if start is None:
        return {}
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
                "stepped_through": (
                    book.stepped_through.isoformat() if book.stepped_through else None
                ),
                "actions_through": (
                    book.actions_through.isoformat() if book.actions_through else None
                ),
                "earliest_trade": (
                    book.earliest_trade.isoformat() if book.earliest_trade else None
                ),
                "manager": book.manager,
            }
            for name, book in books.items()
        },
    }
    # Atomic: a failure mid-write must leave yesterday's books, not a truncated file.
    from qalpha.live import atomic

    atomic.write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


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
            stepped_through=(
                date.fromisoformat(entry["stepped_through"])
                if entry.get("stepped_through")
                else None
            ),
            actions_through=(
                date.fromisoformat(entry["actions_through"])
                if entry.get("actions_through")
                else None
            ),
            earliest_trade=(
                date.fromisoformat(entry["earliest_trade"]) if entry.get("earliest_trade") else None
            ),
            manager=dict(entry.get("manager") or {}),
        )
        for name, entry in raw["books"].items()
    }
    assert_identical_flows(list(books.values()))
    return books


def sync_flows(
    books: dict[str, TwinBook],
    trades: Sequence[object],
    credits: Sequence[OffMarketCredit] = (),
    *,
    flows: Sequence[Flow] | None = None,
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
    current = list(flows) if flows is not None else flows_with_off_market(trades, credits)
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
