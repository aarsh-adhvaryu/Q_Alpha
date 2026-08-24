"""Your real account's forward track record — the instrument the backtest cannot be (PR-71).

The backtest in ``scripts/backtest_sip.py`` answers *"would this have worked over 2013–2026?"*. Run
it again next month and it answers the same question with one more month of history — a rounding
error on thirteen years. It is not a monitor, and it can never say anything about **your** holdings,
bought on **your** dates, at **your** prices.

This module is the monitor. It takes the trades you actually placed and asks the only question that
settles the matter: **had the same rupees gone into the index on the same days instead, where would
you be?** Same cash, same dates, one difference — the names. That difference is the entire claim the
system makes, and this measures it in rupees.

**Money-weighted, because the cash flows are lumpy.** A ₹50,000 SIP means the money is not all
present for the whole window, so a simple start-to-end percentage is not a rate of return — it
flatters late deposits into a bull run and punishes them in a fall. :func:`xirr` solves for the
annual rate that makes the dated flows net to the current value, which is what a bank would quote and
what you can compare against a fixed deposit.

**What it is measured against.** The basis is *net money in* — everything bought, minus everything
sold. The window runs from your first trade. Both travel with the number through
:class:`~qalpha.live.measures.ReturnMeasure`, per PR-4: a return without a basis and a window is not
readable, and the audit that produced this repo's trust problem was eight such numbers on one screen.

**It must be able to say you are behind.** A tracker that can only report good news is marketing, not
evidence. :func:`track_record_markdown` leads with the gap in rupees whichever way it points, and for
the first year it says plainly that the number is noise — the same bar the System-vs-Shadow
experiment holds itself to, and the reason forward run 1 was published as void.

Pure: trades and a price series in, numbers out. No network, no Streamlit, no broker call.

*Known approximation:* Zerodha's tradebook records execution price, not charges. Delivery brokerage
is ₹0, so the flows understate cost by roughly the STT/stamp/DP leg (~0.1%). That shifts both sides
of the comparison the same way and is far below the difference being measured.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.accounting.costs import Side
from qalpha.live.measures import ReturnMeasure

#: Below this many months of history the comparison is dominated by entry timing rather than by
#: selection, so the panel refuses to read a verdict into it. Chosen to match the pre-registration's
#: standard for the fake-money experiment: a difference is reportable only when it clears the noise.
MIN_MONTHS_FOR_A_VERDICT = 12

#: XIRR search bracket. The lower bound is just above total loss (−100% is a pole); the upper bound is
#: absurdly generous, so a failure to bracket means the flows are degenerate, not that the rate is high.
_RATE_FLOOR = -0.9999
_RATE_CEILING = 10.0
_TOLERANCE = 1e-7
_MAX_ITERATIONS = 200


@dataclass(frozen=True)
class Flow:
    """One dated movement of money into (positive) or out of (negative) the equity book.

    The brokerage cash account sits *outside* the portfolio by this definition, so selling A to buy B
    on the same day is an outflow and an inflow that very nearly cancel — which is the correct
    treatment: no new money arrived.
    """

    on: date
    amount: Decimal


def flows_from_trades(trades: Sequence[object]) -> list[Flow]:
    """Dated cash flows from a Zerodha tradebook, one per day, oldest first.

    Accepts anything with ``trade_date``/``side``/``quantity``/``price`` — i.e.
    :class:`~qalpha.live.tradebook.TradebookTrade`, which is what the private-gist master holds.
    Same-day trades are summed so a rebalance reads as its net effect rather than as churn.
    """
    by_day: dict[date, Decimal] = {}
    for trade in trades:
        value = Decimal(str(trade.quantity)) * Decimal(str(trade.price))  # type: ignore[attr-defined]
        signed = value if trade.side is Side.BUY else -value  # type: ignore[attr-defined]
        day = trade.trade_date  # type: ignore[attr-defined]
        by_day[day] = by_day.get(day, Decimal("0")) + signed
    return [Flow(on=d, amount=by_day[d]) for d in sorted(by_day)]


def xirr(dated: Sequence[tuple[date, Decimal]]) -> float | None:
    """The annual rate that discounts ``dated`` flows to zero — the money-weighted return.

    Sign convention is the spreadsheet one: money **leaving you** is negative, money **coming back**
    (including the terminal value of what you still hold) is positive.

    Solved by bisection rather than Newton because the NPV curve has a pole at −100% and Newton
    happily walks into it from a bad guess. Bisection cannot diverge; it just needs the root
    bracketed, and returns ``None`` when it is not — which for real flows means every one has the
    same sign (nothing to solve) or the answer lies outside a −99.99%…+1000% range.
    """
    if len(dated) < 2:
        return None
    flows = sorted(dated, key=lambda p: p[0])
    if not (any(a > 0 for _, a in flows) and any(a < 0 for _, a in flows)):
        return None
    t0 = flows[0][0]
    years = [(d - t0).days / 365.0 for d, _ in flows]
    amounts = [float(a) for _, a in flows]

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** t for a, t in zip(amounts, years, strict=True))

    low, high = _RATE_FLOOR, _RATE_CEILING
    f_low, f_high = npv(low), npv(high)
    if f_low * f_high > 0:
        return None
    for _ in range(_MAX_ITERATIONS):
        mid = (low + high) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < _TOLERANCE or (high - low) < _TOLERANCE:
            return mid
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2.0


def _price_on(series: pd.Series, day: date) -> Decimal | None:
    """The last index level at or before ``day`` — never after, so no future price is ever used."""
    stamp = pd.Timestamp(day)
    window = series.loc[:stamp].dropna()
    if window.empty:
        return None
    return Decimal(str(float(window.iloc[-1])))


@dataclass(frozen=True)
class BenchmarkLeg:
    """The counterfactual: the same rupees, on the same days, in the index instead."""

    units: Decimal
    value: Decimal
    exhausted: bool  # a sell exceeded the index sleeve — it ran out of units before you ran out


def benchmark_leg(flows: Sequence[Flow], series: pd.Series, as_of: date) -> BenchmarkLeg | None:
    """Replay ``flows`` into ``series`` (NIFTYBEES) and mark the result at ``as_of``.

    Returns ``None`` when the index has no price at or before the first flow — the comparison would
    otherwise be invented rather than measured.

    ``exhausted`` records the one case the arithmetic cannot represent honestly: if your book grew
    far faster than the index and you then sold a large chunk, the index sleeve funded with the same
    money does not hold enough to sell. Units are floored at zero and the flag is raised, because
    silently going short the index would report a number no one could have achieved.
    """
    units = Decimal("0")
    exhausted = False
    for flow in flows:
        price = _price_on(series, flow.on)
        if price is None or price <= 0:
            return None
        delta = flow.amount / price
        if units + delta < 0:
            delta, exhausted = -units, True
        units += delta
    now = _price_on(series, as_of)
    if now is None:
        return None
    return BenchmarkLeg(units=units, value=units * now, exhausted=exhausted)


@dataclass(frozen=True)
class TrackRecord:
    """What your account actually did, beside what the index would have done with the same money."""

    start: date
    as_of: date
    net_invested: Decimal  # everything bought minus everything sold — the basis
    value: Decimal  # what your holdings are worth now
    benchmark_value: Decimal | None  # what the same flows into NIFTYBEES would be worth
    benchmark_exhausted: bool
    rate: float | None  # your XIRR
    benchmark_rate: float | None
    n_flows: int

    @property
    def months(self) -> int:
        return max(
            0, (self.as_of.year - self.start.year) * 12 + self.as_of.month - self.start.month
        )

    @property
    def gain(self) -> Decimal:
        return self.value - self.net_invested

    @property
    def ahead_by(self) -> Decimal | None:
        """Rupees ahead of (or, when negative, behind) the same money in the index."""
        return None if self.benchmark_value is None else self.value - self.benchmark_value

    @property
    def measurable(self) -> bool:
        """Is there a positive basis to express a percentage against?"""
        return self.net_invested > 0

    @property
    def too_early(self) -> bool:
        return self.months < MIN_MONTHS_FOR_A_VERDICT

    def _pct(self, value: Decimal) -> float:
        return float((value - self.net_invested) / self.net_invested * 100)

    def measure(self) -> ReturnMeasure | None:
        if not self.measurable:
            return None
        return ReturnMeasure(
            label="Your account",
            pct=self._pct(self.value),
            basis="net money in (everything bought, less everything sold)",
            start=self.start,
            end=self.as_of,
            denominator=f"₹{self.net_invested:,.0f}",
        )

    def benchmark_measure(self) -> ReturnMeasure | None:
        if not self.measurable or self.benchmark_value is None:
            return None
        return ReturnMeasure(
            label="Same money in NIFTYBEES",
            pct=self._pct(self.benchmark_value),
            basis="net money in (everything bought, less everything sold)",
            start=self.start,
            end=self.as_of,
            denominator=f"₹{self.net_invested:,.0f}",
        )


def track_record(
    trades: Sequence[object],
    value: Decimal,
    benchmark: pd.Series,
    as_of: date,
) -> TrackRecord | None:
    """Build the record. ``None`` when there are no trades yet — nothing has happened to measure."""
    flows = flows_from_trades(trades)
    if not flows:
        return None
    net_invested = sum((f.amount for f in flows), Decimal("0"))
    leg = benchmark_leg(flows, benchmark, as_of)
    # Spreadsheet sign convention: money you put in leaves you (negative); today's value comes back.
    mine = [(f.on, -f.amount) for f in flows] + [(as_of, value)]
    theirs = [(f.on, -f.amount) for f in flows] + [(as_of, leg.value)] if leg is not None else []
    return TrackRecord(
        start=flows[0].on,
        as_of=as_of,
        net_invested=net_invested,
        value=value,
        benchmark_value=None if leg is None else leg.value,
        benchmark_exhausted=bool(leg is not None and leg.exhausted),
        rate=xirr(mine),
        benchmark_rate=xirr(theirs) if theirs else None,
        n_flows=len(flows),
    )


def _rate_text(rate: float | None) -> str:
    return "—" if rate is None else f"{rate * 100:+.1f}%/yr"


def track_record_markdown(record: TrackRecord | None) -> str:
    """The panel. Leads with the gap in rupees — in whichever direction it actually points."""
    if record is None:
        return (
            "**No track record yet.** Upload your Zerodha tradebook above and this panel starts "
            "measuring your real returns against the same money in an index fund."
        )
    lines = [
        f"### 📈 Your track record · {record.start} → {record.as_of} "
        f"({record.months} month{'s' if record.months != 1 else ''})",
        "",
        "| | Your account | Same money in NIFTYBEES |",
        "|---|---|---|",
        f"| Net money in | ₹{record.net_invested:,.0f} | ₹{record.net_invested:,.0f} |",
        f"| Worth today | **₹{record.value:,.0f}** | "
        + (f"₹{record.benchmark_value:,.0f}" if record.benchmark_value is not None else "—"),
    ]
    mine, theirs = record.measure(), record.benchmark_measure()
    if mine is not None:
        lines.append(
            f"| Return | {mine.pct:+.1f}% | "
            + (f"{theirs.pct:+.1f}%" if theirs is not None else "—")
        )
    lines.append(
        f"| Annual rate (XIRR) | {_rate_text(record.rate)} | {_rate_text(record.benchmark_rate)} |"
    )
    lines.append("")

    ahead = record.ahead_by
    if ahead is None:
        lines.append(
            "⚠️ **No index comparison available** — the benchmark series does not reach back to your "
            "first trade, so there is nothing honest to compare against yet."
        )
    elif ahead >= 0:
        lines.append(f"**You are ahead by ₹{ahead:,.0f}** versus the same money in the index.")
    else:
        lines.append(f"**You are behind by ₹{-ahead:,.0f}** versus the same money in the index.")

    if record.too_early:
        lines.append("")
        lines.append(
            f"⚠️ **Read this as noise, not as a verdict.** {record.months} month"
            f"{'s' if record.months != 1 else ''} of history is dominated by *when* you happened to "
            f"buy, not by *what* the system picked. A gap either way only starts to mean something "
            f"after ~{MIN_MONTHS_FOR_A_VERDICT} months, and the backtest's edge was measured over "
            "thirteen years."
        )
    if record.benchmark_exhausted:
        lines.append("")
        lines.append(
            "ℹ️ A sale was larger than the index sleeve the same cash flows would have funded, so "
            "the benchmark holds zero units from that point. The comparison understates the index "
            "leg — treat it as a floor, not an exact figure."
        )
    lines.append("")
    lines.append(
        "*Measured on the trades you actually placed. Both columns use the same rupees on the same "
        "days — the only difference is which names the money bought. Execution charges (~0.1%) are "
        "not in either column.*"
    )
    return "\n".join(lines)
