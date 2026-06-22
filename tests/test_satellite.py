"""Tests for the satellite (IPO/discretionary) sleeve bookkeeping (live/satellite.py).

Pure-module tests: no engine internals touched, so these lock the math (the withdrawn-cash split,
the funnel-window graduation gate, the (cap-f)/c sector-bound transform) without any backtest risk.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from qalpha.accounting.tax_lots import TaxLot
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import DEFAULT_CONFIG, Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.satellite import (
    SatelliteRegistry,
    classify_positions,
    concentration_alerts,
    core_decision_inputs,
    core_fraction,
    core_value,
    core_view,
    funnel_window,
    has_sufficient_history,
    history_guard,
    is_graduated,
    register_ipo,
    satellite_report,
    satellite_sector_footprint,
    satellite_value,
    tighten_sector_bounds,
)


def _panel_with_late_listing() -> PriceData:
    """400 business days: CORE listed throughout; IPO listed only in the last 100 days (NaN before)."""
    dates = pd.bdate_range("2024-01-01", periods=400)
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {"date": d, "ticker": "CORE", "close": 100.0, "adj_close": 100.0, "volume": 10_000}
        )
        if i >= 300:  # IPO lists at row 300 → 100 days of history at the end
            rows.append(
                {"date": d, "ticker": "IPO", "close": 50.0, "adj_close": 50.0, "volume": 5_000}
            )
    return PriceData.from_long(pd.DataFrame(rows))


def _book(cfg: Config) -> Portfolio:
    """A book: cash + a CORE lot + a satellite IPO lot (priced below for valuation tests)."""
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("10000"))
    pf.ledger.add_lot(TaxLot("CORE", date(2024, 1, 1), Decimal("100"), Decimal("100"), pool="core"))
    pf.ledger.add_lot(
        TaxLot("IPO", date(2026, 6, 20), Decimal("10"), Decimal("500"), pool="satellite")
    )
    return pf


# ---- funnel window ------------------------------------------------------------------------------


def test_funnel_window_is_momentum_lookback_plus_buffer() -> None:
    cfg = DEFAULT_CONFIG
    assert funnel_window(cfg) == cfg.factor.momentum_lookback_days + 90 == 342


# ---- registry -----------------------------------------------------------------------------------


def test_registry_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    reg = SatelliteRegistry()
    reg.add("IPO.NS", date(2026, 6, 20))
    reg.add("NSE.NS", date(2026, 5, 1))
    path = tmp_path / "satellite.json"
    reg.save(path)

    loaded = SatelliteRegistry.load(path)
    assert loaded.listed_on == {"IPO.NS": date(2026, 6, 20), "NSE.NS": date(2026, 5, 1)}
    assert loaded.is_satellite("IPO.NS") and not loaded.is_satellite("RELIANCE.NS")
    assert loaded.tickers == {"IPO.NS", "NSE.NS"}


def test_registry_load_missing_file_is_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert SatelliteRegistry.load(tmp_path / "nope.json").listed_on == {}


def test_classify_positions_splits_by_registry() -> None:
    reg = SatelliteRegistry({"IPO": date(2026, 6, 20)})
    core, sat = classify_positions(["CORE", "IPO", "OTHER"], reg)
    assert core == ["CORE", "OTHER"]
    assert sat == ["IPO"]


# ---- withdrawn-cash value split -----------------------------------------------------------------


def test_value_split_treats_satellite_as_withdrawn() -> None:
    cfg = DEFAULT_CONFIG
    pf = _book(cfg)
    reg = SatelliteRegistry({"IPO": date(2026, 6, 20)})
    prices = {"CORE": Decimal("100"), "IPO": Decimal("500")}
    # total = 10000 cash + 100*100 core + 10*500 satellite = 25000; satellite = 5000.
    assert pf.market_value(prices) == Decimal("25000")
    assert satellite_value(pf, reg, prices) == Decimal("5000")
    assert core_value(pf, reg, prices) == Decimal("20000")  # cash + core only
    assert core_fraction(pf, reg, prices) == pytest.approx(0.8)


def test_core_fraction_is_one_without_satellite() -> None:
    cfg = DEFAULT_CONFIG
    pf = _book(cfg)
    empty = SatelliteRegistry()
    prices = {"CORE": Decimal("100"), "IPO": Decimal("500")}
    assert core_fraction(pf, empty, prices) == 1.0


def test_core_view_drops_satellite_keeps_cash() -> None:
    cfg = DEFAULT_CONFIG
    pf = _book(cfg)
    reg = SatelliteRegistry({"IPO": date(2026, 6, 20)})
    prices = {"CORE": Decimal("100"), "IPO": Decimal("500")}
    view = core_view(pf, reg)
    # Satellite gone, core kept, cash identical → the optimizer sizes over cash + core only.
    assert set(view.positions()) == {"CORE"}
    assert view.cash == pf.cash
    assert view.market_value(prices) == core_value(pf, reg, prices) == Decimal("20000")
    # The real book is untouched.
    assert set(pf.positions()) == {"CORE", "IPO"}


def test_core_view_is_full_book_without_satellite() -> None:
    cfg = DEFAULT_CONFIG
    pf = _book(cfg)
    empty = SatelliteRegistry()
    prices = {"CORE": Decimal("100"), "IPO": Decimal("500")}
    view = core_view(pf, empty)
    assert view.market_value(prices) == pf.market_value(prices)


# ---- insufficient-history guard / graduation ----------------------------------------------------


def test_has_sufficient_history_full_vs_short() -> None:
    panel = _panel_with_late_listing()
    as_of = date(2025, 7, 1)  # within the panel, IPO already listed for a while by the end
    last = panel.dates[-1].date()
    # CORE has full history; over a 342-day window it is sufficient, the 100-day IPO is not.
    assert has_sufficient_history(panel, "CORE", last, 342)
    assert not has_sufficient_history(panel, "IPO", last, 342)
    # but the IPO IS sufficient over a short 50-day window (graduation with a smaller gate).
    assert has_sufficient_history(panel, "IPO", last, 50)
    assert not has_sufficient_history(panel, "MISSING", last, 50)
    _ = as_of


def test_history_no_look_ahead() -> None:
    panel = _panel_with_late_listing()
    before_listing = date(2024, 6, 1)  # IPO has not listed yet as of this date
    assert not has_sufficient_history(panel, "IPO", before_listing, 50)


def test_history_guard_partitions() -> None:
    panel = _panel_with_late_listing()
    last = panel.dates[-1].date()
    guard = history_guard(panel, ["CORE", "IPO"], last, 342)
    assert guard.eligible == ["CORE"]
    assert guard.flagged == ["IPO"]


def test_graduation_flips_once_history_is_long_enough() -> None:
    panel = _panel_with_late_listing()
    last = panel.dates[-1].date()
    assert not is_graduated(panel, "IPO", last, 342)  # only 100 days listed
    assert is_graduated(panel, "IPO", last, 50)  # would have graduated under a 50-day gate


# ---- concentration alerts (live value, surface only) --------------------------------------------


def test_concentration_alert_fires_on_appreciation() -> None:
    cfg = DEFAULT_CONFIG
    pf = _book(cfg)
    reg = SatelliteRegistry({"IPO": date(2026, 6, 20)})
    # IPO triples: 10 * 1500 = 15000 of a (10000 + 10000 + 15000 = 35000) book ≈ 42.9% sleeve.
    prices = {"CORE": Decimal("100"), "IPO": Decimal("1500")}
    alerts = concentration_alerts(pf, reg, prices, sleeve_cap=0.08, name_cap=0.025)
    scopes = {a.scope for a in alerts}
    assert "sleeve" in scopes and "IPO" in scopes
    sleeve = next(a for a in alerts if a.scope == "sleeve")
    assert sleeve.weight == pytest.approx(15000 / 35000)


def test_no_alert_within_caps() -> None:
    cfg = DEFAULT_CONFIG
    pf = _book(cfg)
    reg = SatelliteRegistry({"IPO": date(2026, 6, 20)})
    # Make the satellite tiny: a huge core so IPO is well under both caps.
    prices = {"CORE": Decimal("100000"), "IPO": Decimal("1")}
    assert concentration_alerts(pf, reg, prices) == []


# ---- sector footprint + bound transform ---------------------------------------------------------


def test_sector_footprint_by_live_value() -> None:
    cfg = DEFAULT_CONFIG
    pf = _book(cfg)
    reg = SatelliteRegistry({"IPO": date(2026, 6, 20)})
    sector_of = {"CORE": "IT", "IPO": "TELECOM"}
    prices = {"CORE": Decimal("100"), "IPO": Decimal("500")}
    fp = satellite_sector_footprint(pf, reg, sector_of, prices)
    # only the satellite counts; 5000 / 25000 = 0.2 telecom of the total book.
    assert fp == pytest.approx({"TELECOM": 0.2})


def test_tighten_sector_bounds_exact_transform() -> None:
    # f = 0.08 telecom footprint, core fraction c = 0.92, box [0.05, 0.30].
    bounds = tighten_sector_bounds({"TELECOM": 0.08}, 0.92, floor=0.05, cap=0.30)
    lo, hi = bounds["TELECOM"]
    assert hi == pytest.approx((0.30 - 0.08) / 0.92)  # ≈ 0.2391, NOT 0.22
    assert lo == 0.0  # (0.05 - 0.08)/0.92 < 0 → floored
    # round-trip: core hi * c + footprint lands exactly on the 30% total-book cap.
    assert hi * 0.92 + 0.08 == pytest.approx(0.30)


def test_tighten_sector_bounds_over_cap_collapses_to_zero() -> None:
    # satellite alone exceeds the 30% cap → core room is zero (never negative); alert handles the rest.
    bounds = tighten_sector_bounds({"TELECOM": 0.35}, 0.65, floor=0.05, cap=0.30)
    assert bounds["TELECOM"] == (0.0, 0.0)


def test_tighten_sector_bounds_floor_carries_when_footprint_small() -> None:
    # tiny footprint: both bounds stay positive and scale by 1/c.
    bounds = tighten_sector_bounds({"IT": 0.01}, 0.9, floor=0.05, cap=0.30)
    lo, hi = bounds["IT"]
    assert lo == pytest.approx((0.05 - 0.01) / 0.9)
    assert hi == pytest.approx((0.30 - 0.01) / 0.9)


# ---- slice 4: live wiring (register / core_decision_inputs / report) ----------------------------


def test_register_ipo_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "satellite.json"
    register_ipo("JIO.NS", date(2026, 6, 20), path=path)
    register_ipo("NSE.NS", date(2026, 5, 1), path=path)
    loaded = SatelliteRegistry.load(path)
    assert loaded.listed_on == {"JIO.NS": date(2026, 6, 20), "NSE.NS": date(2026, 5, 1)}


def test_core_decision_inputs_assembles_view_blacklist_overrides() -> None:
    cfg = DEFAULT_CONFIG
    # Panel: CORE full history, YOUNG only the last 100 days (insufficient for the funnel window).
    dates = pd.bdate_range("2024-01-01", periods=400)
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {"date": d, "ticker": "CORE", "close": 100.0, "adj_close": 100.0, "volume": 10_000}
        )
        if i >= 300:
            rows.append(
                {"date": d, "ticker": "YOUNG", "close": 20.0, "adj_close": 20.0, "volume": 5_000}
            )
    panel = PriceData.from_long(pd.DataFrame(rows))
    last = panel.dates[-1].date()

    pf = _book(cfg)  # holds CORE (core) + IPO (satellite)
    reg = SatelliteRegistry({"IPO": date(2026, 6, 20)})
    universe = Universe.static(["CORE", "YOUNG"])
    sector_of = {"CORE": "IT", "IPO": "TELECOM"}
    prices_dec = {"CORE": Decimal("100"), "IPO": Decimal("500")}

    view, blacklist, overrides = core_decision_inputs(
        pf, reg, panel, universe, sector_of, prices_dec, last, cfg
    )
    # satellite excluded from the optimizer's portfolio view; core kept.
    assert set(view.positions()) == {"CORE"}
    # blacklist = satellite (registry) ∪ young universe name (history net) — but not CORE.
    assert "IPO" in blacklist and "YOUNG" in blacklist and "CORE" not in blacklist
    # telecom box tightened by the satellite footprint: f=5000/25000=0.2, c=0.8 → (0, (0.30-0.2)/0.8).
    assert overrides["TELECOM"][0] == 0.0
    assert overrides["TELECOM"][1] == pytest.approx((0.30 - 0.2) / 0.8)


def test_core_decision_inputs_empty_registry_is_full_book() -> None:
    cfg = DEFAULT_CONFIG
    dates = pd.bdate_range("2024-01-01", periods=400)
    rows = [
        {"date": d, "ticker": "CORE", "close": 100.0, "adj_close": 100.0, "volume": 10_000}
        for d in dates
    ]
    panel = PriceData.from_long(pd.DataFrame(rows))
    last = panel.dates[-1].date()
    pf = _book(cfg)
    empty = SatelliteRegistry()
    universe = Universe.static(["CORE"])
    view, blacklist, overrides = core_decision_inputs(
        pf, empty, panel, universe, {"CORE": "IT"}, {"CORE": Decimal("100")}, last, cfg
    )
    # No satellite → full book, no overrides, and CORE (full history) is not blacklisted.
    assert set(view.positions()) == {"CORE", "IPO"}
    assert overrides == {}
    assert "CORE" not in blacklist


def test_satellite_report_has_exit_tax_and_countdown() -> None:
    cfg = DEFAULT_CONFIG
    pf = _book(cfg)  # IPO lot: 10 sh @500 bought 2026-06-20
    reg = SatelliteRegistry({"IPO": date(2026, 6, 20)})
    as_of = date(2026, 7, 20)
    prices_dec = {"CORE": Decimal("100"), "IPO": Decimal("600")}  # IPO up 20% → a short-term gain
    report = satellite_report(pf, reg, prices_dec, as_of, cfg)

    assert len(report.holdings) == 1
    h = report.holdings[0]
    assert h.ticker == "IPO"
    assert h.value == Decimal("6000")
    assert not h.ready_to_graduate  # ~1 month listed vs the 342-day window
    assert h.graduates_on is not None and h.graduates_on > as_of
    assert h.window == cfg.factor.funnel_window()
    # exact exit tax comes from the validated advisor (a short-term gain here → tax > 0).
    assert h.sell_advice.total_tax > 0
    assert "Discretionary" in report.render()
