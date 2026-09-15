"""Quant cards compute what they say, from what was public on the date, and say why when they cannot."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from qalpha.live import quant
from qalpha.live.financials import Quarter


def _q(
    end: date, eps: str | None, *, filed: date | None = None, basis: str = "Consolidated"
) -> Quarter:
    return Quarter(
        ticker="INFY",
        period_start=end - timedelta(days=90),
        period_end=end,
        filed_at=datetime.combine(
            filed or end + timedelta(days=40), datetime.min.time(), tzinfo=UTC
        ),
        basis=basis,
        audited="Audited",
        facts={
            "revenue": Decimal("1000"),
            "profit_after_tax": Decimal("100"),
            "eps_basic": None if eps is None else Decimal(eps),
        },
        source_url="u",
        sha256="a" * 64,
    )


ENDS = [
    date(2026, 6, 30),
    date(2026, 3, 31),
    date(2025, 12, 31),
    date(2025, 9, 30),
    date(2025, 6, 30),
]


def test_trailing_eps_needs_four_consecutive_quarters_on_one_basis() -> None:
    four = [_q(e, "5") for e in ENDS[:4]]
    assert quant.trailing_eps(four).value == 20.0
    assert "four" in quant.trailing_eps(four[:3]).why
    assert (
        "not consecutive" in quant.trailing_eps([four[0], four[1], four[2], _q(ENDS[4], "5")]).why
    )
    assert "mix" in quant.trailing_eps([*four[:3], _q(ENDS[3], "5", basis="Standalone")]).why
    assert "not reported" in quant.trailing_eps([*four[:3], _q(ENDS[3], None)]).why


def test_pe_is_not_meaningful_on_losses() -> None:
    assert quant.pe_ratio(Decimal("100"), quant.Measured(20.0)).value == 5.0
    assert "losses" in quant.pe_ratio(Decimal("100"), quant.Measured(-3.0)).why
    assert quant.pe_ratio(None, quant.Measured(20.0)).value is None


def _panel(values: np.ndarray, start: str = "2023-01-02", name: str = "INFY") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({name: values}, index=idx)


def test_the_pe_range_uses_only_filings_public_on_each_month_end() -> None:
    """A result filed in 2026 must not rewrite the P/E the name had in 2024."""
    closes = _panel(np.full(900, 100.0))
    as_of = pd.Timestamp(closes.index[-1]).date()
    stored = []
    end = date(2022, 12, 31)
    while end < as_of:
        stored.append(_q(end, "5"))
        end = (pd.Timestamp(end) + pd.offsets.QuarterEnd(1)).date()
    # a much later filing for an OLD period, with a very different EPS
    stored.append(_q(date(2023, 12, 31), "50", filed=as_of - timedelta(days=5)))
    today = quant.pe_ratio(
        Decimal("100"),
        quant.trailing_eps(quant.company_facts.known_on(stored, "INFY", as_of, limit=4)),
    )
    result = quant.pe_percentile(
        "INFY", as_of=as_of, close_raw=closes, stored=stored, today_pe=today
    )
    assert result["points"] >= quant.MIN_PE_POINTS
    assert result["low"] == 5.0 == result["high"]  # every month-end saw EPS 5 × 4 = 20 → P/E 5


def test_volatility_beta_drawdown_and_sigma_move_match_their_formulas() -> None:
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 400)
    bench = 100 * np.exp(np.cumsum(r))
    frame = _panel(bench)
    frame["DOUBLE"] = 100 * np.exp(np.cumsum(2 * r))
    series = frame["INFY"]
    as_of = pd.Timestamp(frame.index[-1]).date()
    expected_vol = float(np.std(np.diff(np.log(bench))[-252:], ddof=1)) * math.sqrt(252) * 100
    assert quant.volatility(frame, "INFY", as_of).value == pytest.approx(expected_vol, abs=0.01)
    assert quant.beta(frame, "INFY", series, as_of).value == pytest.approx(1.0, abs=1e-3)
    assert quant.beta(frame, "DOUBLE", series, as_of).value == pytest.approx(2.0, abs=1e-3)
    tail = series.tail(252)
    assert quant.max_drawdown(frame, "INFY", as_of).value == pytest.approx(
        float((tail / tail.cummax() - 1).min()) * 100, abs=0.01
    )
    logret = np.diff(np.log(bench))
    assert quant.move_in_sigma(frame, "INFY", as_of).value == pytest.approx(
        logret[-1] / np.std(logret[:-1][-252:], ddof=1), abs=0.01
    )
    assert "no close today" in quant.move_in_sigma(frame, "INFY", as_of + timedelta(days=3)).why


def test_adding_a_risky_name_to_a_cash_book_raises_its_volatility_and_unaffordable_is_unknown() -> (
    None
):
    rng = np.random.default_rng(2)
    frame = _panel(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))))
    as_of = pd.Timestamp(frame.index[-1]).date()
    grew = quant.marginal_volatility(frame, "INFY", values={}, cash=Decimal("100000"), as_of=as_of)
    assert grew.value is not None and grew.value > 0
    assert (
        "not affordable"
        in quant.marginal_volatility(frame, "INFY", values={}, cash=Decimal("100"), as_of=as_of).why
    )


def test_the_card_labels_itself_computed_and_carries_reasons_for_gaps() -> None:
    rng = np.random.default_rng(3)
    adj = _panel(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))))
    as_of = pd.Timestamp(adj.index[-1]).date()
    card = quant.card(
        "INFY",
        as_of=as_of,
        known=as_of,
        close_raw=adj,
        adj=adj,
        benchmark=adj["INFY"],
        benchmark_name="NIFTYBEES",
        stored=[],
        values={"INFY": Decimal("20000")},
        cash=Decimal("80000"),
        sector_of={"INFY": "IT"},
    )
    assert card["epistemic"] == "COMPUTED" and card["id"] == "quant:INFY"
    assert card["valuation"]["pe"]["value"] is None and card["valuation"]["pe"]["why"]
    assert (
        card["weight"]["name_pct_of_book"] == 20.0 and card["weight"]["sector_pct_of_book"] == 20.0
    )
    assert card["risk"]["beta_to_NIFTYBEES"]["value"] == pytest.approx(1.0, abs=1e-3)
