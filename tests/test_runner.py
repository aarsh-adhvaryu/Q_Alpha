"""One autonomous day: the step that turns a policy into decisions (PLAN_REDESIGN §1, Phase 3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from qalpha.accounting.tax_lots import TaxLot
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.policy import DEPLOY, EXIT, HARVEST, HEDGE_ON, HOLD, POLICIES
from qalpha.live.runner import Market, step
from qalpha.live.twin import TWIN_FULL, TWIN_NO_EXITS, TWIN_NO_HEDGE, TwinBook

_AS_OF = date(2026, 8, 28)
_DATES = pd.bdate_range(end=pd.Timestamp(_AS_OF), periods=400)


def _book(name: str = TWIN_FULL, cash: str = "0", lots: tuple = ()) -> TwinBook:
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal(cash))
    for ticker, on, qty, px in lots:
        pf.ledger.add_lot(
            TaxLot(
                ticker=ticker,
                acquisition_date=on,
                quantity_original=Decimal(qty),
                buy_price=Decimal(px),
            )
        )
    return TwinBook(name=name, portfolio=pf)


def _calm_index() -> pd.Series:
    return pd.Series(np.linspace(100.0, 112.0, len(_DATES)), index=_DATES)


def _index_crossing_today() -> pd.Series:
    """Flat, then a fall whose 3-scan persistence completes **exactly on ``as_of``**.

    The overlay is edge-triggered: it fires when the state *changes*. A crash that began weeks ago
    produces no decision today — correctly, because nothing changed — so a test asserting HEDGE_ON
    has to place the edge on the day being stepped.
    """
    level = [140.0] * (len(_DATES) - 3) + [120.0, 120.0, 120.0]  # 14.3% down → gauge 0.95 ≥ τ
    return pd.Series(level, index=_DATES)


def _frame(**paths: list[float]) -> pd.DataFrame:
    return pd.DataFrame(paths, index=_DATES)


def _market(index: pd.Series | None = None, **kw: object) -> Market:
    flat = [100.0] * len(_DATES)
    return Market(
        as_of=_AS_OF,
        prices=kw.pop("prices", {}),  # type: ignore[arg-type]
        index_close=index if index is not None else _calm_index(),
        adj_close=kw.pop("adj_close", _frame(A=flat, B=flat)),  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


# ---- doing nothing is still a decision ------------------------------------------------------------


def test_a_quiet_day_records_a_hold() -> None:
    """Silence and a dead runner must not look alike — the failure that hid for 38 days."""
    (d,) = step(_book(), POLICIES[TWIN_FULL], _market())
    assert d.action == HOLD
    assert d.reason


def test_every_decision_carries_a_reason() -> None:
    decisions = step(
        _book(lots=(("CRATER.NS", date(2026, 1, 5), "100", "500"),)),
        POLICIES[TWIN_FULL],
        _market(
            prices={"CRATER.NS": Decimal("200")},
            adj_close=_frame(
                **{
                    "CRATER.NS": list(np.linspace(500.0, 200.0, len(_DATES))),
                    "A.NS": [100.0] * len(_DATES),
                    "B.NS": [101.0] * len(_DATES),
                }
            ),
        ),
    )
    assert decisions
    assert all(d.reason.strip() for d in decisions)


# ---- harvesting is never ablated -------------------------------------------------------------------


def test_harvest_runs_in_every_configuration() -> None:
    """It is not a strategy bet, so ablating it would test nothing (policy.Policy)."""
    lots = (("A.NS", date(2026, 1, 5), "100", "500"),)
    for name, policy in POLICIES.items():
        decisions = step(_book(name, lots=lots), policy, _market(prices={"A.NS": Decimal("400")}))
        assert any(d.action == HARVEST for d in decisions), name


def test_a_harvest_decision_states_the_loss_and_the_round_trip() -> None:
    (d,) = [
        x
        for x in step(
            _book(lots=(("A.NS", date(2026, 1, 5), "100", "500"),)),
            POLICIES[TWIN_FULL],
            _market(prices={"A.NS": Decimal("400")}),
        )
        if x.action == HARVEST
    ]
    assert "banks ₹10,000" in d.reason
    assert "round trip" in d.reason
    assert "31 March" in d.reason


# ---- the ablations actually remove their factor -----------------------------------------------------


def test_removing_exits_removes_exit_decisions() -> None:
    lots = (("CRATER.NS", date(2026, 1, 5), "100", "100"),)
    adj = _frame(
        **{
            "CRATER.NS": list(np.linspace(100.0, 40.0, len(_DATES))),
            "A.NS": [100.0] * len(_DATES),
            "B.NS": [101.0] * len(_DATES),
        }
    )
    market = _market(prices={"CRATER.NS": Decimal("40")}, adj_close=adj)
    full = step(_book(TWIN_FULL, lots=lots), POLICIES[TWIN_FULL], market)
    none = step(_book(TWIN_NO_EXITS, lots=lots), POLICIES[TWIN_NO_EXITS], market)
    assert any(d.action == EXIT for d in full)
    assert not any(d.action == EXIT for d in none)


def test_removing_the_hedge_removes_hedge_decisions() -> None:
    market = _market(index=_index_crossing_today())
    full = step(_book(TWIN_FULL), POLICIES[TWIN_FULL], market)
    none = step(_book(TWIN_NO_HEDGE), POLICIES[TWIN_NO_HEDGE], market)
    assert any(d.action == HEDGE_ON for d in full), "a 25% fall must trip the gauge"
    assert not any(d.action == HEDGE_ON for d in none)


def test_the_hedge_fires_on_the_edge_not_every_day() -> None:
    """Edge-triggered: an ON that repeats daily is noise, not a decision."""
    decisions = step(_book(), POLICIES[TWIN_FULL], _market(index=_index_crossing_today()))
    assert len([d for d in decisions if d.action == HEDGE_ON]) <= 1


# ---- deploy, and the AI ablation --------------------------------------------------------------------


def test_idle_cash_below_the_floor_is_not_deployed() -> None:
    """Below the pre-committed floor a deploy is charges wearing a strategy costume."""
    assert all(d.action != DEPLOY for d in step(_book(cash="1000"), POLICIES[TWIN_FULL], _market()))


def test_cash_with_no_watchlist_says_so_instead_of_silently_holding() -> None:
    (d,) = [
        x for x in step(_book(cash="100000"), POLICIES[TWIN_FULL], _market()) if x.action == HOLD
    ]
    assert "no watchlist panel" in d.reason
    assert "100,000" in d.reason
