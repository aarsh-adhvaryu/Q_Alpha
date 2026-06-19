"""Paper-trading book tests: persistence + the plan/apply loop (no network).

The book must survive a save/load (cash, lots, LTCG tally), `plan` must never mutate it, and `apply`
must commit exactly the planned orders.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.dashboard import equity_csv, render_markdown
from qalpha.live.paper import PaperBook

SECTORS = ["FIN", "IT", "PHARMA", "ENERGY", "AUTO", "FMCG"]


def _market_panel(n_tickers: int = 12, n_days: int = 500, seed: int = 1) -> PriceData:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    rows = []
    for i in range(n_tickers):
        drift = rng.uniform(0.0001, 0.0009)
        vol = rng.uniform(0.010, 0.025)
        price = 200.0 * np.exp(np.cumsum(rng.normal(drift, vol, n_days)))
        volume = rng.integers(200_000, 600_000, n_days)
        for d, p, v in zip(dates, price, volume, strict=True):
            rows.append(
                {"date": d, "ticker": f"STK{i:02d}", "close": p, "adj_close": p, "volume": int(v)}
            )
    return PriceData.from_long(pd.DataFrame(rows))


def _setup(tmp_path: Path) -> tuple[PaperBook, PriceData, Universe, dict[str, str], date]:
    prices = _market_panel()
    universe = Universe.static(prices.tickers)
    sector_of = {t: SECTORS[i % len(SECTORS)] for i, t in enumerate(prices.tickers)}
    cfg = Config()
    book = PaperBook.init(
        tmp_path / "book.json",
        cfg,
        starting_capital=Decimal("200000"),
        start_date=prices.dates[-1].date(),
    )
    return book, prices, universe, sector_of, prices.dates[-1].date()


def test_init_load_round_trip(tmp_path: Path) -> None:
    book, *_ = _setup(tmp_path)
    reloaded = PaperBook.load(book.path, Config())
    assert reloaded.portfolio.cash == Decimal("200000")
    assert reloaded.start_date == book.start_date
    assert reloaded.params.weighting == "shrink"
    assert reloaded.history == []


def test_plan_does_not_mutate_book(tmp_path: Path) -> None:
    book, prices, universe, sector_of, as_of = _setup(tmp_path)
    cash_before = book.portfolio.cash
    plan = book.plan(prices, universe, sector_of, as_of)
    assert plan.has_orders  # first deployment of ₹2L → must propose buys
    assert book.portfolio.cash == cash_before  # plan() is read-only
    assert book.portfolio.positions() == {}


def test_apply_commits_and_persists(tmp_path: Path) -> None:
    book, prices, universe, sector_of, as_of = _setup(tmp_path)
    plan = book.plan(prices, universe, sector_of, as_of)
    records = book.apply(prices, plan)

    assert records and book.portfolio.positions()  # the book now holds stock
    assert book.portfolio.cash < Decimal("200000")  # cash was spent
    assert len(book.history) == 1

    # Persisted: a fresh load sees the same holdings and cash.
    reloaded = PaperBook.load(book.path, Config())
    assert reloaded.portfolio.positions() == book.portfolio.positions()
    assert reloaded.portfolio.cash == book.portfolio.cash
    assert len(reloaded.history) == 1


def test_second_plan_is_not_first_deployment(tmp_path: Path) -> None:
    """After capital is deployed, decide_rebalance must not relabel it as the first deployment."""
    book, prices, universe, sector_of, as_of = _setup(tmp_path)
    book.apply(prices, book.plan(prices, universe, sector_of, as_of))

    # last_target persists across a reload, so `first` is correctly False afterwards.
    reloaded = PaperBook.load(book.path, Config())
    assert reloaded.last_target is not None
    next_plan = reloaded.plan(prices, universe, sector_of, as_of)
    assert "first deployment" not in next_plan.decision.reason


def test_scheduled_rebalance_due_gates_by_period(tmp_path: Path) -> None:
    """The cadence gate: force_refresh must fire only when a new annual period begins, not daily."""
    book, prices, universe, sector_of, as_of = _setup(tmp_path)
    assert book.scheduled_rebalance_due(as_of) is True  # no history → first deployment is due
    book.apply(prices, book.plan(prices, universe, sector_of, as_of))
    # Same annual period as the deployment → NOT due (the bug fix: no daily churn).
    assert book.scheduled_rebalance_due(as_of) is False
    # A date in the next calendar year → a scheduled rebalance is due again.
    assert book.scheduled_rebalance_due(date(as_of.year + 1, 1, 2)) is True


def test_off_cadence_plan_holds_without_churn(tmp_path: Path) -> None:
    """Between scheduled dates the plan must HOLD — no proposed orders, no '41% drift' nag."""
    book, prices, universe, sector_of, as_of = _setup(tmp_path)
    book.apply(prices, book.plan(prices, universe, sector_of, as_of))
    held = book.plan(prices, universe, sector_of, as_of)  # same period → must hold
    assert not held.has_orders
    assert not held.decision.actionable
    assert "holding" in held.decision.reason


def test_rebalance_freq_persists_and_old_books_default_to_annual(tmp_path: Path) -> None:
    book, *_ = _setup(tmp_path)
    assert book.params.rebalance_freq == "Y"
    assert PaperBook.load(book.path, Config()).params.rebalance_freq == "Y"
    # A book.json written before the cadence gate (no rebalance_freq key) must load as annual.
    raw = json.loads(book.path.read_text())
    del raw["params"]["rebalance_freq"]
    book.path.write_text(json.dumps(raw))
    assert PaperBook.load(book.path, Config()).params.rebalance_freq == "Y"


def test_mark_records_equity_and_persists(tmp_path: Path) -> None:
    book, prices, universe, sector_of, as_of = _setup(tmp_path)
    book.apply(prices, book.plan(prices, universe, sector_of, as_of))

    eq = book.mark(prices, as_of)
    assert eq > 0
    assert len(book.equity_curve) == 1
    book.mark(prices, as_of)  # same date → overwrite, not duplicate
    assert len(book.equity_curve) == 1

    reloaded = PaperBook.load(book.path, Config())
    assert reloaded.equity_curve == book.equity_curve
    assert reloaded.starting_capital == Decimal("200000")


def test_dashboard_renders_committable_artifacts(tmp_path: Path) -> None:
    book, prices, universe, sector_of, as_of = _setup(tmp_path)
    book.apply(prices, book.plan(prices, universe, sector_of, as_of))
    book.mark(prices, as_of)
    plan = book.plan(prices, universe, sector_of, as_of)
    benchmark = pd.Series([100.0, 101.0], index=pd.DatetimeIndex([as_of, as_of]), name="nifty_tri")

    md = render_markdown(book, prices, benchmark, plan, as_of)
    assert "# Q-Alpha — Paper-Trading Dashboard" in md
    assert "Today's recommendation" in md
    assert "Holdings" in md

    csv = equity_csv(book)
    assert csv.startswith("date,equity,cash,return_pct")
    assert len(csv.strip().splitlines()) == 2  # header + one mark
