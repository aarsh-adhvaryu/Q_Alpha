"""Shared test fixtures: synthetic price panels (no network), and a runnable dashboard sandbox."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qalpha.data.prices import PriceData


@pytest.fixture
def synthetic_long() -> pd.DataFrame:
    """Three tickers, 300 business days, deterministic geometric random walks."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2022-01-03", periods=300)
    tickers = ["AAA", "BBB", "CCC"]
    rows = []
    for t_i, ticker in enumerate(tickers):
        # Different drifts so factor ranks are non-degenerate.
        drift = 0.0003 * (t_i + 1)
        shocks = rng.normal(drift, 0.012, size=len(dates))
        price = 100.0 * np.exp(np.cumsum(shocks))
        volume = rng.integers(50_000, 200_000, size=len(dates))
        for d, p, v in zip(dates, price, volume, strict=True):
            rows.append({"date": d, "ticker": ticker, "close": p, "adj_close": p, "volume": int(v)})
    return pd.DataFrame(rows)


@pytest.fixture
def synthetic_prices(synthetic_long: pd.DataFrame) -> PriceData:
    return PriceData.from_long(synthetic_long)


# ---- the dashboard sandbox (PLAN_TRUST_REPAIR.md PR-5 — fixes T3.3) ------------------------------
#
# ``test_dashboard_app.py`` was ``skipif``'d on ``data/historical/prices_pit_2026.parquet``, which is
# gitignored market data. It therefore **never ran in CI** — the dashboard, the surface every one of
# the plan's defects reached the user through, was the least-tested code in the repo.
#
# The plan called for committing a small fixture panel. Generating one instead is strictly better: no
# market data enters the repo, the panel cannot go stale relative to "today", and the prices are
# deterministic so a test asserting a rendered number is asserting something stable. What the tests
# need from a price panel is *shape* — the right tickers over a recent window — not real quotes.


def _synthetic_panel(
    tickers: list[str], *, end: pd.Timestamp, periods: int, seed: int
) -> pd.DataFrame:
    """A deterministic long-form OHLC panel: right shape, arbitrary levels, no network."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end, periods=periods)
    rows = []
    for i, ticker in enumerate(sorted(tickers)):
        shocks = rng.normal(0.0002, 0.011, size=len(dates))
        price = (100.0 + 5.0 * i) * np.exp(np.cumsum(shocks))
        volume = rng.integers(50_000, 200_000, size=len(dates))
        for d, px, v in zip(dates, price, volume, strict=True):
            rows.append(
                {"date": d, "ticker": ticker, "close": px, "adj_close": px, "volume": int(v)}
            )
    return pd.DataFrame(rows)


@pytest.fixture
def dashboard_sandbox(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """A working directory the Streamlit app can run in with **no gitignored data and no network**.

    Copies the committed state (the books, the universes, the reports) and generates the price panels
    the app would otherwise download. Panels end on the most recent weekday so the app's own staleness
    guards see fresh data and never shell out to a downloader mid-test.
    """
    import shutil
    from datetime import date as _date

    root = Path(__file__).resolve().parent.parent
    for rel in ("data/paper", "data/autopilot", "data/universes", "reports"):
        src = root / rel
        if src.exists():
            shutil.copytree(src, tmp_path / rel, dirs_exist_ok=True)
    (tmp_path / "data" / "historical").mkdir(parents=True, exist_ok=True)

    end = pd.Timestamp(_date.today())
    end = end if end.weekday() < 5 else end - pd.Timedelta(days=end.weekday() - 4)

    universe = pd.read_csv(root / "data/universes/nifty50_membership_2026.csv")
    watchlist = pd.read_csv(root / "data/universes/nifty100_watchlist.csv")
    # The GO book's own holdings must be priceable or it cannot be marked at all.
    held = ["APOLLOHOSP.NS", "ASIANPAINT.NS", "BEL.NS", "NTPC.NS", "SUNPHARMA.NS"]
    core = sorted({str(t) for t in universe["ticker"]} | set(held))
    names = sorted({str(t) for t in watchlist["ticker"]} | set(held))

    _synthetic_panel(core, end=end, periods=400, seed=7).to_parquet(
        tmp_path / "data/historical/prices_pit_2026.parquet", index=False
    )
    _synthetic_panel(names, end=end, periods=400, seed=8).to_parquet(
        tmp_path / "data/historical/prices_watchlist.parquet", index=False
    )
    _synthetic_panel(["NIFTYBEES.NS"], end=end, periods=400, seed=9).to_parquet(
        tmp_path / "data/historical/benchmark_NIFTYBEESNS_2026.parquet", index=False
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    return tmp_path
