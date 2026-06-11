"""Price panel abstraction (Q_alpha.md §5.5).

`PriceData` is the single object every downstream layer (factors, covariance, backtest, baselines)
reads from. It deliberately does **not** know about yfinance, Parquet, or the network — it is a
typed view over already-loaded prices. This keeps the compute layers unit-testable on synthetic
data and makes the no-look-ahead guarantee easy to enforce in one place (`as_of`).

Internally it stores wide DataFrames (index = trading date, columns = ticker) for each field:

* ``adj_close``  — dividend/split-adjusted close, used as the Total-Return proxy (§5.2/§5.5).
* ``close_raw``  — unadjusted close (for turnover/ADV in ₹).
* ``volume``     — daily share volume.

All compute uses ``adj_close`` returns exclusively (§5.5).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Sequence

_REQUIRED_LONG_COLS = {"date", "ticker", "close", "adj_close", "volume"}


class PriceData:
    """Typed, look-ahead-safe view over a wide price panel."""

    def __init__(self, adj_close: pd.DataFrame, close_raw: pd.DataFrame, volume: pd.DataFrame):
        # All three frames must share index/columns.
        if not (adj_close.index.equals(close_raw.index) and adj_close.index.equals(volume.index)):
            raise ValueError("price frames must share the same date index")
        if not (
            adj_close.columns.equals(close_raw.columns) and adj_close.columns.equals(volume.columns)
        ):
            raise ValueError("price frames must share the same ticker columns")
        self._adj_close = adj_close.sort_index()
        self._close_raw = close_raw.reindex(self._adj_close.index)
        self._volume = volume.reindex(self._adj_close.index)

    # ---- construction ----------------------------------------------------

    @classmethod
    def from_long(cls, df: pd.DataFrame) -> PriceData:
        """Build from a long DataFrame with columns: date, ticker, close, adj_close, volume."""
        missing = _REQUIRED_LONG_COLS - set(df.columns)
        if missing:
            raise ValueError(f"long frame missing columns: {sorted(missing)}")
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        adj_close = frame.pivot(index="date", columns="ticker", values="adj_close")
        close_raw = frame.pivot(index="date", columns="ticker", values="close")
        volume = frame.pivot(index="date", columns="ticker", values="volume")
        return cls(adj_close, close_raw, volume)

    # ---- accessors -------------------------------------------------------

    @property
    def tickers(self) -> list[str]:
        return list(self._adj_close.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        idx = self._adj_close.index
        assert isinstance(idx, pd.DatetimeIndex)
        return idx

    @property
    def adj_close(self) -> pd.DataFrame:
        return self._adj_close

    @property
    def close_raw(self) -> pd.DataFrame:
        return self._close_raw

    @property
    def volume(self) -> pd.DataFrame:
        return self._volume

    def returns(self) -> pd.DataFrame:
        """Daily Total-Return-adjusted simple returns (§5.5). First row is dropped (NaN)."""
        return self._adj_close.pct_change().iloc[1:]

    def adv(self, window: int) -> pd.DataFrame:
        """Average Daily traded Value in ₹ over ``window`` days: rolling mean of close×volume."""
        value = self._close_raw * self._volume
        return value.rolling(window=window, min_periods=window).mean()

    # ---- look-ahead control ---------------------------------------------

    def as_of(self, as_of_date: date, lookback: int | None = None) -> PriceData:
        """Return a view containing only rows with date <= ``as_of_date`` (no look-ahead).

        This is THE guard against look-ahead bias (§14 criterion 2). Every factor/covariance call
        in the backtest must go through a panel produced here. Optionally keep only the trailing
        ``lookback`` rows to bound compute.
        """
        ts = pd.Timestamp(as_of_date)
        mask = self._adj_close.index <= ts
        adj = self._adj_close.loc[mask]
        if lookback is not None:
            adj = adj.iloc[-lookback:]
        idx = adj.index
        return PriceData(adj, self._close_raw.loc[idx], self._volume.loc[idx])

    def subset(self, tickers: Sequence[str]) -> PriceData:
        """Restrict the panel to ``tickers`` (used to apply the point-in-time universe)."""
        cols = [t for t in tickers if t in self._adj_close.columns]
        return PriceData(self._adj_close[cols], self._close_raw[cols], self._volume[cols])
