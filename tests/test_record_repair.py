"""The append-only record actually appends, and the numbers on it say what they are.

Three defects, all of the same shape the codebase keeps producing — a value labelled as something
it is not, on a surface a later reader will trust:

1. ``_append_jsonl`` **replaced** a same-key row. A re-run after a rule change silently substituted
   the new rule's answer for the old rule's, on the same date, leaving nothing to say so.
2. ``undeployed_cash`` summed share *quantities* into a field named cash. The live record holds
   ``"11"`` where rupees were meant.
3. ``runner._hedge`` read the NIFTYBEES ETF price (~₹276) as the Nifty index level (~27,574) and
   multiplied it by a futures lot size.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.hedge import NIFTY_LOT_SIZE, hedge_availability
from qalpha.live.policy import HEDGE_ON, POLICIES
from qalpha.live.runner import Market, TwinBook, step
from qalpha.live.twin import (
    _append_jsonl,
    append_ai_attempt,
    latest_by_key,
    load_history,
)

_AS_OF = date(2026, 9, 5)


# --- 1. a correction never deletes what it corrects ----------------------------------------------


def test_a_repeat_key_appends_a_revision_and_keeps_the_original(tmp_path: Path) -> None:
    p = tmp_path / "r.jsonl"
    _append_jsonl(p, [{"_key": "d1", "verdict": "drop", "rule": "url-present"}], key="_key")
    total = _append_jsonl(p, [{"_key": "d1", "verdict": "keep", "rule": "primary-source"}], key="_key")
    assert total == 2, "the earlier belief must still be on file"
    lines = [line for line in p.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert "url-present" in p.read_text() and "primary-source" in p.read_text()


def test_revisions_number_upward_from_zero(tmp_path: Path) -> None:
    p = tmp_path / "r.jsonl"
    for _ in range(3):
        _append_jsonl(p, [{"_key": "d1"}], key="_key")
    import json

    revs = [json.loads(x)["revision"] for x in p.read_text().splitlines() if x.strip()]
    assert revs == [0, 1, 2]


def test_a_different_key_is_untouched_by_a_correction(tmp_path: Path) -> None:
    p = tmp_path / "r.jsonl"
    _append_jsonl(p, [{"_key": "d1", "v": 1}, {"_key": "d2", "v": 2}], key="_key")
    _append_jsonl(p, [{"_key": "d1", "v": 99}], key="_key")
    current = latest_by_key(
        [__import__("json").loads(x) for x in p.read_text().splitlines() if x.strip()], key="_key"
    )
    assert {r["_key"]: r["v"] for r in current} == {"d1": 99, "d2": 2}


def test_latest_by_key_takes_the_highest_revision_not_the_last_line() -> None:
    rows = [
        {"k": "a", "revision": 2, "v": "current"},
        {"k": "a", "revision": 1, "v": "older"},
        {"k": "b", "v": "no-revision-field"},
    ]
    assert [r["v"] for r in latest_by_key(rows, key="k")] == ["current", "no-revision-field"]


def test_load_history_returns_the_current_view(tmp_path: Path) -> None:
    p = tmp_path / "h.jsonl"
    _append_jsonl(p, [{"as_of": "2026-09-01", "gate": "NOT YET"}], key="as_of")
    _append_jsonl(p, [{"as_of": "2026-09-01", "gate": "CORRECTED"}], key="as_of")
    rows = load_history(p)
    assert len(rows) == 1 and rows[0]["gate"] == "CORRECTED"
    assert len(p.read_text().strip().splitlines()) == 2, "both revisions stay on disk"


def test_a_shrink_is_still_refused(tmp_path: Path) -> None:
    p = tmp_path / "r.jsonl"
    _append_jsonl(p, [{"_key": f"d{i}"} for i in range(5)], key="_key")
    before = p.read_text()
    _append_jsonl(p, [{"_key": "d0"}], key="_key")
    assert p.read_text().startswith(before), "existing rows are a prefix; nothing was rewritten"


# --- 2. the cash field is labelled --------------------------------------------------------------


def test_attempt_rows_carry_the_unit_of_the_cash_field(tmp_path: Path) -> None:
    """Rows before 2026-09-05 hold a share count. The tag is how a reader tells them apart."""
    p = tmp_path / "v.jsonl"
    append_ai_attempt(
        as_of=_AS_OF, status="verdicts_recorded", undeployed_cash="33165.60", cash_unit="INR", path=p
    )
    import json

    row = json.loads(p.read_text().splitlines()[0])
    assert row["undeployed_cash"] == "33165.60" and row["cash_unit"] == "INR"


def test_an_untagged_cash_field_is_the_legacy_share_count(tmp_path: Path) -> None:
    p = tmp_path / "v.jsonl"
    append_ai_attempt(as_of=_AS_OF, status="x", undeployed_cash="11", path=p)
    import json

    assert json.loads(p.read_text().splitlines()[0])["cash_unit"] == ""


# --- 3. the hedge is not told an ETF price is the index -------------------------------------------

_DATES = pd.bdate_range("2026-01-01", periods=60)


def _falling_index() -> pd.Series:
    level = [140.0] * (len(_DATES) - 3) + [120.0, 120.0, 120.0]
    return pd.Series(level, index=_DATES)


def _book() -> TwinBook:
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("300000"))
    return TwinBook(name="TWIN_FULL", portfolio=pf)


def _market(index_level: float | None) -> Market:
    flat = [100.0] * len(_DATES)
    return Market(
        as_of=_DATES[-1].date(),
        prices={},
        index_close=_falling_index(),
        adj_close=pd.DataFrame({"A.NS": flat}, index=_DATES),
        index_level=index_level,
    )


def test_without_an_index_level_availability_cannot_be_assessed() -> None:
    """Missing input produces CANNOT ASSESS, never an invented number."""
    decisions = step(_book(), POLICIES["TWIN_FULL"], _market(None))
    hedges = [d for d in decisions if d.action == HEDGE_ON]
    assert hedges, "the gauge must still trip"
    assert "CANNOT BE ASSESSED" in hedges[0].reason


def test_the_etf_price_would_have_understated_a_lot_by_a_hundredfold() -> None:
    """The defect, pinned as arithmetic so it cannot come back quietly.

    NIFTYBEES tracks roughly a hundredth of the index, so feeding its price into a lot-size
    multiplication reported a ₹3L book as able to hold eight contracts.
    """
    etf_price, index_level = 275.74, 27574.0
    wrong = hedge_availability(300_000.0, etf_price)
    right = hedge_availability(300_000.0, index_level)
    assert wrong.available and not right.available
    assert round(right.lot_notional / wrong.lot_notional) == 100
    assert right.lot_notional == NIFTY_LOT_SIZE * index_level


def test_a_real_index_level_reports_the_shortfall() -> None:
    decisions = step(_book(), POLICIES["TWIN_FULL"], _market(27574.0))
    hedges = [d for d in decisions if d.action == HEDGE_ON]
    assert hedges and "hedge UNAVAILABLE" in hedges[0].reason


def test_stress_gauge_is_unaffected_because_it_reads_a_ratio() -> None:
    """``index_close`` staying an ETF series is correct for the gauge — drawdown is scale-free."""
    from qalpha.live.hedge import stress_gauge

    etf = _falling_index()
    as_index = etf * 100.0
    assert np.allclose(stress_gauge(etf).to_numpy(), stress_gauge(as_index).to_numpy(), equal_nan=True)
