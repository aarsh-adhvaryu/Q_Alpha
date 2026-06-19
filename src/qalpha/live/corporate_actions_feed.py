"""Detect corporate actions on held names and surface them for review (§14 criterion 5).

The tax-correct *application* lives in :mod:`qalpha.accounting.corporate_actions`; this is the
detection layer — it reads splits/dividends from yfinance and turns them into
:class:`~qalpha.accounting.corporate_actions.CorporateAction` candidates the user reviews before
recording them on the book.

**Honest caveat (load-bearing):** yfinance reports a **bonus** issue as a *split* (the price adjusts
either way), but their tax treatment differs sharply (a split preserves cost basis; a bonus is ₹0
cost). So a detected "split" is flagged **review-needed** — the user confirms split-vs-bonus from the
Zerodha/CDSL corporate-action notice, since only that distinguishes them. Detection never auto-applies.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction


def corporate_actions_from_series(
    ticker: str,
    splits: pd.Series,
    dividends: pd.Series,
    since: date,
) -> list[CorporateAction]:
    """Parse yfinance-style ``splits`` / ``dividends`` series into candidate actions on/after ``since``.

    ``splits`` is a date-indexed Series of split ratios (post/pre, e.g. 5.0); ``dividends`` is a
    date-indexed Series of ₹/share. A detected split is returned as a SPLIT candidate (the common
    case) — but see the module caveat: confirm it isn't a bonus before recording, as the tax differs.
    """
    out: list[CorporateAction] = []
    for d, ratio in zip(pd.DatetimeIndex(splits.index).date, splits.to_numpy(), strict=True):
        if d >= since and float(ratio) > 0:
            out.append(CorporateAction.split(ticker, d, Decimal(str(ratio))))
    for d, amount in zip(pd.DatetimeIndex(dividends.index).date, dividends.to_numpy(), strict=True):
        if d >= since and float(amount) > 0:
            out.append(CorporateAction.dividend(ticker, d, Decimal(str(amount))))
    return sorted(out, key=lambda a: a.ex_date)


def detect_corporate_actions(tickers: list[str], since: date) -> dict[str, list[CorporateAction]]:
    """Fetch splits/dividends for ``tickers`` from yfinance and return candidates per ticker.

    Network + yfinance are imported lazily so the pure parser above stays unit-testable offline. Any
    per-ticker fetch error is swallowed (the name simply yields no candidates) — detection is a
    best-effort advisory, never a hard dependency of the book.
    """
    import yfinance as yf  # lazy: only when actually polling the feed

    found: dict[str, list[CorporateAction]] = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            actions = corporate_actions_from_series(t, tk.splits, tk.dividends, since)
            if actions:
                found[t] = actions
        except Exception:
            continue
    return found
