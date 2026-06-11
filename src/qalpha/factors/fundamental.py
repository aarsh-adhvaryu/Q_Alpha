"""Fundamental factors: Value, Quality, Dividend (Q_alpha.md §3.2, Phase 0b).

Each returns a per-ticker score oriented so **higher = more attractive**, computed from the
point-in-time :class:`FundamentalsStore` joined with current raw prices. Value and Quality are
themselves averages of sector-relative percentile sub-ranks (the spec defines them that way), so
they reuse :func:`sector_percentile_ranks`; NaN sub-metrics (e.g. EV/EBITDA and D/E for banks) drop
out via nan-aware averaging.

Prices use **raw close** (not TR-adjusted) for valuation ratios — P/E is actual price over reported
EPS. Returns/risk elsewhere still use adjusted close. Cross-sectional ranking makes the scores
robust to residual split/adjustment quirks.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import numpy as np
import pandas as pd

from qalpha.data.fundamentals import FundamentalsStore
from qalpha.factors.score import sector_percentile_ranks


def _ratios(latest: pd.DataFrame, price: pd.Series) -> pd.DataFrame:
    """Compute per-ticker valuation/quality ratios from latest fundamentals + raw price."""
    df = latest.copy()
    df["price"] = price.reindex(df.index)
    shares = df["shares_cr"]
    net_worth = df["equity_capital"].fillna(0) + df["reserves"].fillna(0)

    eps = df["net_profit"] / shares  # ₹cr / cr = ₹ per share
    bvps = net_worth / shares
    market_cap = df["price"] * shares  # ₹ × cr = ₹cr
    ev = market_cap + df["borrowings"].fillna(0) - df["cash"].fillna(0)

    out = pd.DataFrame(index=df.index)
    out["pe"] = df["price"] / eps.where(eps > 0)
    out["pb"] = df["price"] / bvps.where(bvps > 0)
    out["ev_ebitda"] = ev / df["ebitda"].where(df["ebitda"] > 0)  # NaN for banks (ebitda NaN)
    out["roe"] = df["net_profit"] / net_worth.where(net_worth > 0) * 100.0
    out["de"] = (df["borrowings"] / net_worth.where(net_worth > 0)).where(~df["is_financial"])
    return out


def value(
    store: FundamentalsStore,
    price: pd.Series,
    sectors: Mapping[str, str],
    as_of: date,
) -> pd.Series:
    """Value score: mean sector-rank of cheapness across P/E, P/B, EV/EBITDA (low = cheap = high)."""
    tickers = list(price.index)
    latest = store.latest_for(tickers, as_of)
    if latest.empty:
        return pd.Series(dtype="float64", name="value")
    r = _ratios(latest, price)
    ranks = pd.DataFrame(
        {
            "pe": sector_percentile_ranks(r["pe"], sectors, higher_is_better=False),
            "pb": sector_percentile_ranks(r["pb"], sectors, higher_is_better=False),
            "ev_ebitda": sector_percentile_ranks(r["ev_ebitda"], sectors, higher_is_better=False),
        }
    )
    return ranks.mean(axis=1, skipna=True).rename("value")


def quality(
    store: FundamentalsStore,
    price: pd.Series,
    sectors: Mapping[str, str],
    as_of: date,
) -> pd.Series:
    """Quality score: mean sector-rank of ROE (high good) and D/E (low good)."""
    tickers = list(price.index)
    latest = store.latest_for(tickers, as_of)
    if latest.empty:
        return pd.Series(dtype="float64", name="quality")
    r = _ratios(latest, price)
    ranks = pd.DataFrame(
        {
            "roe": sector_percentile_ranks(r["roe"], sectors, higher_is_better=True),
            "de": sector_percentile_ranks(r["de"], sectors, higher_is_better=False),
        }
    )
    return ranks.mean(axis=1, skipna=True).rename("quality")


def dividend(
    store: FundamentalsStore,
    tickers: list[str],
    as_of: date,
) -> pd.Series:
    """Dividend score: consecutive years of dividend payment known by ``as_of`` (higher = better)."""
    values = {t: store.dividend_years(t, as_of) for t in tickers}
    series = pd.Series(values, dtype="float64", name="dividend")
    return series.replace(0, np.nan)  # no dividend history -> NaN (factor drops out for that name)
