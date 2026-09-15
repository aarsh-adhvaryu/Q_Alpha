"""Quant cards: the measurements an investor would take before judging a company, computed by code.

One card per name per evening, from data already on disk: the filed quarters (point in time), the
price panel, and the book. **Measurements for judgement, not signals.** This repository has already
tested price and factor signals out of sample and they did not survive (README §7); nothing here is
a buy or sell rule, and the prompt says so.

Every number is labelled as what was computed and carries what it was computed from. A number that
cannot be computed is ``None`` **with the reason next to it** — negative earnings make P/E
meaningless, three quarters are not a trailing year, a bank has no gross margin. Unknown is never
filled with a neighbour.

Formulas (each is its function's docstring too):

* **Trailing EPS** = sum of basic EPS over the four most recent consecutive quarters on file, same
  basis, public on the date. **P/E** = the unadjusted close that day ÷ trailing EPS, when EPS > 0.
* **P/E percentile** = where today's P/E sits among month-end P/Es over the last three years, each
  computed from the close and the filings public *on that month-end* — so the range is not
  rewritten by later restatements.
* **Volatility** = standard deviation of daily log returns over the last 252 sessions × √252.
* **Max drawdown** = the largest fall from a running peak over the same window.
* **Beta** = cov(name, benchmark) ÷ var(benchmark), daily returns, same window.
* **Move in σ** = today's return ÷ the daily standard deviation of the 252 sessions before today.
* **Marginal volatility of adding ₹X** = volatility of the book after buying ₹X of the name (paid
  from cash, which has none) minus volatility before. Weights by value; the covariance is the
  sample covariance of daily returns over the window.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from qalpha.live import financials as company_facts

QUANT_VERSION = "QUANT-1"

WINDOW = 252
PE_YEARS = 3
#: Fewer month-ends than this is not a range; a percentile of four numbers is noise with decimals.
MIN_PE_POINTS = 12
#: Default size of the "what if I added this much" measurement.
MARGINAL_ADD = Decimal("15000")


@dataclass(frozen=True)
class Measured:
    """A value, or ``None`` and why."""

    value: float | None
    why: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value} if self.value is not None else {"value": None, "why": self.why}


def _unknown(why: str) -> Measured:
    return Measured(None, why)


# ---- earnings ---------------------------------------------------------------------------------


def trailing_eps(quarters: Sequence[company_facts.Quarter]) -> Measured:
    """Sum of basic EPS over the four newest **consecutive** quarters, one basis. Newest first in."""
    if len(quarters) < 4:
        return _unknown(f"{len(quarters)} quarter(s) on file; a trailing year needs four")
    four = list(quarters[:4])
    if len({q.basis for q in four}) > 1:
        return _unknown("the four newest quarters mix consolidated and standalone filings")
    for newer, older in pairwise(four):
        gap = (newer.period_end - older.period_end).days
        if not 80 <= gap <= 100:
            return _unknown(
                f"quarters ending {older.period_end} and {newer.period_end} are not consecutive"
            )
    eps = [q.get("eps_basic") for q in four]
    if any(e is None for e in eps):
        return _unknown("basic EPS is not reported in one of the four quarters")
    return Measured(round(float(sum((e for e in eps if e is not None), Decimal("0"))), 4))


def pe_ratio(close: Decimal | None, eps: Measured) -> Measured:
    """Unadjusted close ÷ trailing EPS. Not meaningful at or below zero earnings."""
    if close is None:
        return _unknown("no close on this date")
    if eps.value is None:
        return _unknown(eps.why)
    if eps.value <= 0:
        return _unknown(f"trailing EPS is {eps.value}: P/E is not meaningful on losses")
    return Measured(round(float(close) / eps.value, 2))


def _month_ends(index: pd.DatetimeIndex, start: date, end: date) -> list[date]:
    days = index[(index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))]
    if len(days) == 0:
        return []
    last = pd.Series(days, index=days).groupby(days.to_period("M")).last()
    return [pd.Timestamp(str(d)).date() for d in last]


def pe_percentile(
    ticker: str,
    *,
    as_of: date,
    close_raw: pd.DataFrame,
    stored: list[company_facts.Quarter],
    today_pe: Measured,
) -> dict[str, Any]:
    """Today's P/E against its own month-end P/Es over three years, each point in time."""
    if today_pe.value is None:
        return {"percentile": None, "why": today_pe.why, "points": 0}
    if ticker not in close_raw:
        return {"percentile": None, "why": "no raw close series", "points": 0}
    start = date(as_of.year - PE_YEARS, as_of.month, min(as_of.day, 28))
    series = close_raw[ticker]
    history: list[float] = []
    for day in _month_ends(pd.DatetimeIndex(close_raw.index), start, as_of):
        if day >= as_of:
            continue
        raw = series.get(pd.Timestamp(day))
        if raw is None or pd.isna(raw) or float(raw) <= 0:
            continue
        pe = pe_ratio(
            Decimal(str(float(raw))),
            trailing_eps(company_facts.known_on(stored, ticker, day, limit=4)),
        )
        if pe.value is not None:
            history.append(pe.value)
    if len(history) < MIN_PE_POINTS:
        return {
            "percentile": None,
            "why": f"{len(history)} month-end P/E(s) computable; a range needs {MIN_PE_POINTS}",
            "points": len(history),
        }
    below = sum(1 for p in history if p < today_pe.value)
    return {
        "percentile": round(100 * below / len(history), 1),
        "low": round(min(history), 2),
        "median": round(float(np.median(history)), 2),
        "high": round(max(history), 2),
        "points": len(history),
    }


def margin_trend(quarters: Sequence[company_facts.Quarter]) -> dict[str, Any]:
    """Net margin of each of the four newest quarters, and the change newest vs oldest of them."""
    margins: list[tuple[str, float | None]] = []
    for q in list(quarters)[:4]:
        revenue, pat = q.get("revenue"), q.get("profit_after_tax")
        value = (
            None
            if revenue is None or pat is None or revenue <= 0
            else round(float(pat / revenue) * 100, 2)
        )
        margins.append((q.period_end.isoformat(), value))
    known = [m for _, m in margins if m is not None]
    change = round(known[0] - known[-1], 2) if len(known) >= 2 else None
    return {
        "net_margin_pct_by_quarter": dict(margins),
        "change_newest_vs_oldest_pp": change,
        "why": "" if change is not None else "fewer than two quarters with revenue and profit",
    }


def bank_measures(quarters: Sequence[company_facts.Quarter]) -> dict[str, Any] | None:
    """NII growth year on year, provisions as a share of operating profit, NPA ratios. Banks only."""
    if not quarters or not quarters[0].is_bank:
        return None
    latest = quarters[0]
    year_ago = next(
        (q for q in quarters if 330 <= (latest.period_end - q.period_end).days <= 400), None
    )

    def nii(q: company_facts.Quarter) -> Decimal | None:
        earned, expended = q.get("interest_earned"), q.get("interest_expended")
        return None if earned is None or expended is None else earned - expended

    now, before = nii(latest), None if year_ago is None else nii(year_ago)
    growth = (
        None
        if now is None or before is None or before <= 0
        else round(float(now / before - 1) * 100, 1)
    )
    provisions, operating = (
        latest.get("provisions"),
        latest.get("operating_profit_before_provisions"),
    )
    return {
        "nii_growth_yoy_pct": growth,
        "provisions_pct_of_operating_profit": (
            None
            if provisions is None or operating is None or operating <= 0
            else round(float(provisions / operating) * 100, 1)
        ),
        "gross_npa_pct": None
        if latest.get("gross_npa_pct") is None
        else str(latest.get("gross_npa_pct")),
        "net_npa_pct": None
        if latest.get("net_npa_pct") is None
        else str(latest.get("net_npa_pct")),
    }


# ---- prices -----------------------------------------------------------------------------------


def _returns(adj: pd.DataFrame, tickers: Sequence[str], as_of: date) -> pd.DataFrame:
    cols = [t for t in tickers if t in adj]
    frame = adj[cols].loc[: pd.Timestamp(as_of)].tail(WINDOW + 1)
    ratio = frame / frame.shift(1)
    return pd.DataFrame(
        np.log(ratio.to_numpy(dtype=float)), index=ratio.index, columns=ratio.columns
    ).iloc[1:]


def volatility(adj: pd.DataFrame, ticker: str, as_of: date) -> Measured:
    """Annualised standard deviation of daily log returns over the last 252 sessions."""
    r = _returns(adj, [ticker], as_of)
    if ticker not in r or r[ticker].count() < WINDOW // 2:
        return _unknown("fewer than half a year of daily prices")
    return Measured(round(float(r[ticker].std(ddof=1)) * math.sqrt(WINDOW) * 100, 2))


def max_drawdown(adj: pd.DataFrame, ticker: str, as_of: date) -> Measured:
    """The largest peak-to-trough fall over the last 252 sessions, in percent."""
    if ticker not in adj:
        return _unknown("no price series")
    s = adj[ticker].loc[: pd.Timestamp(as_of)].dropna().tail(WINDOW)
    if len(s) < WINDOW // 2:
        return _unknown("fewer than half a year of daily prices")
    return Measured(round(float((s / s.cummax() - 1).min()) * 100, 2))


def beta(adj: pd.DataFrame, ticker: str, benchmark: pd.Series, as_of: date) -> Measured:
    """cov(name, benchmark) ÷ var(benchmark) on daily log returns over the window."""
    if ticker not in adj:
        return _unknown("no price series")
    joined = pd.concat([adj[ticker], benchmark.rename("_bench")], axis=1)
    r = _returns(joined, [ticker, "_bench"], as_of).dropna()
    if len(r) < WINDOW // 2:
        return _unknown("fewer than half a year of overlapping prices")
    var = float(r["_bench"].var(ddof=1))
    if var == 0:
        return _unknown("the benchmark did not move")
    return Measured(round(float(r[ticker].cov(r["_bench"])) / var, 3))


def move_in_sigma(adj: pd.DataFrame, ticker: str, as_of: date) -> Measured:
    """Today's log return ÷ the daily standard deviation of the 252 sessions before it."""
    if ticker not in adj:
        return _unknown("no price series")
    s = adj[ticker].loc[: pd.Timestamp(as_of)].dropna()
    if len(s) < WINDOW // 2 + 2 or pd.Timestamp(s.index[-1]).date() != as_of:
        return _unknown("no close today, or too little history")
    r = pd.Series(np.log((s / s.shift(1)).to_numpy(dtype=float)), index=s.index).dropna()
    sd = float(r.iloc[:-1].tail(WINDOW).std(ddof=1))
    if sd == 0:
        return _unknown("the price did not move in a year")
    return Measured(round(float(r.iloc[-1]) / sd, 2))


def book_volatility(
    adj: pd.DataFrame, values: Mapping[str, Decimal], cash: Decimal, as_of: date
) -> Measured:
    """Annualised volatility of a book by value weights; cash has none. Unknown names make it unknown."""
    names = [t for t, v in values.items() if v > 0]
    total = cash + sum((values[t] for t in names), Decimal("0"))
    if total <= 0:
        return _unknown("the book has no value")
    if not names:
        return Measured(0.0)
    missing = [t for t in names if t not in adj]
    if missing:
        return _unknown(f"no price series for {', '.join(missing)}")
    r = _returns(adj, names, as_of).dropna()
    if len(r) < WINDOW // 2:
        return _unknown("fewer than half a year of overlapping prices")
    w = np.array([float(values[t] / total) for t in names])
    cov = r[names].cov().to_numpy()
    return Measured(round(math.sqrt(float(w @ cov @ w)) * math.sqrt(WINDOW) * 100, 3))


def marginal_volatility(
    adj: pd.DataFrame,
    ticker: str,
    *,
    values: Mapping[str, Decimal],
    cash: Decimal,
    as_of: date,
    add: Decimal = MARGINAL_ADD,
) -> Measured:
    """Book volatility after buying ₹``add`` of ``ticker`` from cash, minus before. Percentage points."""
    if add > cash:
        return _unknown(f"the book has ₹{cash:.0f} cash; adding ₹{add:.0f} is not affordable")
    before = book_volatility(adj, values, cash, as_of)
    after_values = dict(values)
    after_values[ticker] = after_values.get(ticker, Decimal("0")) + add
    after = book_volatility(adj, after_values, cash - add, as_of)
    if before.value is None or after.value is None:
        return _unknown(before.why or after.why)
    return Measured(round(after.value - before.value, 3))


def correlation_to_book(
    adj: pd.DataFrame, ticker: str, values: Mapping[str, Decimal], as_of: date
) -> Measured:
    """Correlation of the name's daily returns with the rest of the book's (value-weighted)."""
    others = [t for t, v in values.items() if v > 0 and t != ticker and t in adj]
    if not others:
        return _unknown("nothing else is held")
    if ticker not in adj:
        return _unknown("no price series")
    r = _returns(adj, [ticker, *others], as_of).dropna()
    if len(r) < WINDOW // 2:
        return _unknown("fewer than half a year of overlapping prices")
    total = sum((values[t] for t in others), Decimal("0"))
    w = np.array([float(values[t] / total) for t in others])
    rest = r[others].to_numpy() @ w
    return Measured(round(float(np.corrcoef(r[ticker].to_numpy(), rest)[0, 1]), 3))


# ---- the card ---------------------------------------------------------------------------------


def card(
    ticker: str,
    *,
    as_of: date,
    known: date,
    close_raw: pd.DataFrame,
    adj: pd.DataFrame,
    benchmark: pd.Series,
    benchmark_name: str,
    stored: list[company_facts.Quarter],
    values: Mapping[str, Decimal],
    cash: Decimal,
    sector_of: Mapping[str, str],
) -> dict[str, Any]:
    """Every measurement for one name. ``values`` is the book's holdings at today's close."""
    quarters = company_facts.known_on(stored, ticker, known, limit=8)
    raw = close_raw[ticker].get(pd.Timestamp(as_of)) if ticker in close_raw else None
    close = None if raw is None or pd.isna(raw) or float(raw) <= 0 else Decimal(str(float(raw)))
    eps = trailing_eps(quarters)
    pe = pe_ratio(close, eps)
    nav = cash + sum(values.values(), Decimal("0"))
    sector = sector_of.get(ticker, "")
    sector_value = sum(
        (v for t, v in values.items() if sector and sector_of.get(t) == sector), Decimal("0")
    )
    summary = company_facts.summarise(quarters, as_of=known) or {}
    return {
        "id": f"quant:{ticker}",
        "ticker": ticker,
        "as_of": as_of.isoformat(),
        "version": QUANT_VERSION,
        "epistemic": "COMPUTED",
        "valuation": {
            "trailing_eps": eps.as_dict(),
            "pe": pe.as_dict(),
            "pe_vs_own_3y": pe_percentile(
                ticker, as_of=known, close_raw=close_raw, stored=stored, today_pe=pe
            ),
        },
        "growth": {
            "revenue_yoy_pct": summary.get("revenue_growth_yoy_pct"),
            "profit_yoy_pct": summary.get("profit_growth_yoy_pct"),
            "why": "" if summary else "no filed quarter public on this date",
        },
        "margins": margin_trend(quarters),
        "bank": bank_measures(quarters),
        "risk": {
            "volatility_1y_pct": volatility(adj, ticker, as_of).as_dict(),
            "max_drawdown_1y_pct": max_drawdown(adj, ticker, as_of).as_dict(),
            f"beta_to_{benchmark_name}": beta(adj, ticker, benchmark, as_of).as_dict(),
            "move_today_in_sigma": move_in_sigma(adj, ticker, as_of).as_dict(),
            "correlation_to_rest_of_book": correlation_to_book(
                adj, ticker, values, as_of
            ).as_dict(),
            f"book_volatility_change_if_adding_{int(MARGINAL_ADD)}_pp": marginal_volatility(
                adj, ticker, values=values, cash=cash, as_of=as_of
            ).as_dict(),
        },
        "weight": {
            "name_pct_of_book": None
            if nav <= 0
            else round(float(values.get(ticker, Decimal("0")) / nav) * 100, 2),
            "sector": sector or None,
            "sector_pct_of_book": None
            if nav <= 0 or not sector
            else round(float(sector_value / nav) * 100, 2),
        },
        "note": (
            "Measurements computed by code from filings public on this date and the price panel. "
            "Not signals: price and factor rules tested here did not survive out of sample."
        ),
    }
