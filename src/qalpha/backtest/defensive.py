"""Defensive overlay: systemic-vs-idiosyncratic exit (Q_alpha.md §3.6, §4.7).

The slow core (annual-ish rebalance) is opportunistic and tax-efficient but, by design, slow to
dump a holding that is quietly dying between rebalances (the 2022 rotation / DLF-style value trap).
This module is the asymmetric counterweight: it never buys, it only flags a held name for exit, and
only when the name is in a **sustained, idiosyncratic** breakdown — *not* a market-wide dip.

The distinction (the whole point):
- **Idiosyncratic** — the stock is down hard *and* lagging the cross-sectional median by a wide
  margin → *this company* has a problem → exit.
- **Systemic** — the stock is down but so is everything else (excess vs the median is small) → it's
  market beta → HOLD (§4.7 "do not panic-sell in a crash"). Holding through 2020 was correct.

The cross-sectional median of trailing returns across all currently-priced names is the self-contained
"market" proxy (no benchmark plumbing needed, and it tracks the universe the strategy actually lives in).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from qalpha.config import DefensiveConfig


def idiosyncratic_exit_flags(
    adj_close: pd.DataFrame, held: list[str], cfg: DefensiveConfig
) -> list[str]:
    """Return the subset of ``held`` tickers in a sustained, idiosyncratic breakdown.

    ``adj_close`` is a wide TR-adjusted price frame (dates × tickers) ending on the evaluation date
    (no look-ahead — pass an ``as_of`` slice). A name is flagged iff it is BOTH down more than
    ``abs_drawdown_exit`` over ``lookback_days`` AND below the cross-sectional median trailing
    return by more than ``rel_underperf_exit``.
    """
    if len(adj_close) <= cfg.lookback_days:
        return []
    last = adj_close.iloc[-1]
    prior = adj_close.iloc[-1 - cfg.lookback_days]
    trailing = (last / prior - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    if trailing.empty:
        return []
    market = float(trailing.median())  # the systemic baseline: how the whole cross-section moved

    flags: list[str] = []
    for t in held:
        if t not in trailing.index:
            continue
        ret = float(trailing[t])
        excess = ret - market
        if ret < -cfg.abs_drawdown_exit and excess < -cfg.rel_underperf_exit:
            flags.append(t)
    return flags


@dataclass(frozen=True)
class GovernanceEvent:
    """A structured, factual governance/regulatory event (Q_alpha.md §3.11) — not sentiment.

    ``severity`` CRITICAL ⇒ freeze: exit the holding and blacklist it from re-purchase. This is the
    *event-driven* defence that the price-based rule can't do — it fires on a broken *business*
    (auditor resignation, SEBI action, promoter-pledge/asset-quality spiral), never on a quality
    name that's merely out of favour. Distinguishing the two is exactly the human-judgement call the
    price overlay gets wrong; here the *fact* makes the call.
    """

    date: date
    ticker: str
    severity: str  # CRITICAL (freeze) | HIGH (block new buy, dashboard alert)
    note: str


class GovernanceEvents:
    """A point-in-time table of governance events; answers 'what is frozen as of date d?'."""

    def __init__(self, events: list[GovernanceEvent]) -> None:
        self._events = sorted(events, key=lambda e: (e.date, e.ticker))

    @classmethod
    def from_csv(cls, path: str | Path) -> GovernanceEvents:
        """Load from a CSV with columns: date, ticker, severity, note."""
        df = pd.read_csv(path)
        events = [
            GovernanceEvent(
                date=pd.Timestamp(str(r["date"])).date(),
                ticker=str(r["ticker"]),
                severity=str(r["severity"]).upper().strip(),
                note=str(r.get("note", "")),
            )
            for r in df.to_dict("records")
        ]
        return cls(events)

    def blacklisted_asof(self, d: date) -> set[str]:
        """Tickers with a CRITICAL event on or before ``d`` (frozen — no hold, no buy).

        Permanent within the backtest: a structural-death freeze is not lifted automatically
        (§3.11 'no recommendations until manually resolved'). For HIGH-only names we don't freeze.
        """
        return {e.ticker for e in self._events if e.severity == "CRITICAL" and e.date <= d}
