"""Point-in-time investable universe (Q_alpha.md §5.4 — survivorship-bias protection).

The screener at any historical rebalance date must see exactly the stocks that were investable on
*that* date — including names that later delisted or were dropped from the index. Using today's
constituents for the whole history is the classic survivorship bias that overstates returns.

This module models membership as a set of intervals: ``(ticker, start_date, end_date)``. A blank
``end_date`` means "still a member". ``members_on(d)`` returns the tickers live on date ``d``.

Sourcing those intervals for NSE indices is the #1 Phase-0 data risk (see plan / README). Until a
clean point-in-time file exists, ``Universe.static(...)`` builds a survivorship-BIASED universe
from a fixed ticker list and marks itself ``point_in_time=False`` so the backtest report can state
the caveat honestly rather than hide it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class Membership:
    ticker: str
    start: date
    end: date | None  # None => still a member

    def active_on(self, d: date) -> bool:
        if d < self.start:
            return False
        return self.end is None or d <= self.end


class Universe:
    """A point-in-time (or, if flagged, static) set of index memberships."""

    def __init__(self, memberships: list[Membership], *, point_in_time: bool = True):
        self._memberships = memberships
        self.point_in_time = point_in_time

    @classmethod
    def static(cls, tickers: list[str]) -> Universe:
        """Survivorship-BIASED universe: every ticker treated as a member for all time.

        Use only as a fallback when point-in-time membership is unavailable. The resulting backtest
        must carry an explicit survivorship caveat in its report.
        """
        far_past = date(1990, 1, 1)
        memberships = [Membership(t, far_past, None) for t in tickers]
        return cls(memberships, point_in_time=False)

    @classmethod
    def from_csv(cls, path: str | Path) -> Universe:
        """Load membership intervals from a CSV: columns ticker, start_date, [end_date].

        ``end_date`` may be blank for still-active members. Dates are ISO ``YYYY-MM-DD``.
        """
        df = pd.read_csv(path)
        required = {"ticker", "start_date"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"universe CSV missing columns: {sorted(missing)}")
        memberships: list[Membership] = []
        for record in df.to_dict("records"):
            end_raw = record.get("end_date")
            end = None if end_raw is None or pd.isna(end_raw) else pd.Timestamp(str(end_raw)).date()
            memberships.append(
                Membership(
                    ticker=str(record["ticker"]),
                    start=pd.Timestamp(str(record["start_date"])).date(),
                    end=end,
                )
            )
        return cls(memberships, point_in_time=True)

    def members_on(self, d: date) -> list[str]:
        """Tickers that were index members on date ``d`` (sorted, de-duplicated)."""
        return sorted({m.ticker for m in self._memberships if m.active_on(d)})

    @property
    def all_tickers(self) -> list[str]:
        """Every ticker that has ever appeared (the full data-pull set)."""
        return sorted({m.ticker for m in self._memberships})
