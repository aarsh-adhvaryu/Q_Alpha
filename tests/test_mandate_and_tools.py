"""The mandate, and the bounded research the investor may ask for.

The mandate's job is that a record can say which limits produced it. The tools' job is that the
investor can follow something up without the packet becoming unbounded, unrepeatable, or a way to
read the future.
"""

from __future__ import annotations

import json
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from qalpha.live import mandate
from qalpha.live import tools as research

# ---- the mandate ---------------------------------------------------------------------------------


def test_the_manager_reads_every_limit_from_the_mandate() -> None:
    """One place a number lives. A limit in three files is a limit that changes in one of them."""
    from qalpha.live import manager

    assert manager.MANDATE.version == manager.VERSION
    assert manager.MANDATE.max_names == manager.MAX_NAMES
    assert manager.MANDATE.name_cap == manager.NAME_CAP
    assert manager.MANDATE.sector_cap == manager.SECTOR_CAP
    assert manager.MANDATE.monthly_budget == manager.MONTHLY_BUDGET
    assert manager.MANDATE.drift_band == manager.DRIFT_BAND


def test_the_prompt_states_the_limits_that_are_actually_enforced() -> None:
    """A prompt that names different numbers from the code is a prompt that lies to the model."""
    from qalpha.live import manager

    assert f"at most {manager.MAX_NAMES} names" in manager.PROMPT
    assert f"{manager.NAME_CAP:.0%} per name" in manager.PROMPT
    assert f"{manager.SECTOR_CAP:.0%} per sector" in manager.PROMPT
    assert manager.VERSION in manager.PROMPT


def test_a_file_may_override_a_limit(tmp_path: Path) -> None:
    path = tmp_path / "mandate.json"
    path.write_text(json.dumps({"max_names": 5, "name_cap": "0.25", "evening": "18:30"}), "utf-8")
    m = mandate.load(path)
    assert m.max_names == 5
    assert m.name_cap == Decimal("0.25")
    assert m.evening == time(18, 30)
    assert m.monthly_budget == mandate.DEFAULT.monthly_budget, "untouched fields keep the default"


def test_a_mandate_file_that_sets_nothing_real_is_refused(tmp_path: Path) -> None:
    """A file that silently does nothing is worse than no file: it looks like it worked."""
    path = tmp_path / "mandate.json"
    path.write_text(json.dumps({"max_nmaes": 5}), encoding="utf-8")
    with pytest.raises(ValueError, match="not part of the mandate"):
        mandate.load(path)


def test_an_unreadable_mandate_is_refused_rather_than_defaulted(tmp_path: Path) -> None:
    path = tmp_path / "mandate.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not readable JSON"):
        mandate.load(path)


def test_no_mandate_file_is_the_registered_default(tmp_path: Path) -> None:
    assert mandate.load(tmp_path / "absent.json") == mandate.DEFAULT


def test_the_mandate_serialises_for_the_receipt() -> None:
    """Every receipt carries the limits in force, or a later reader cannot interpret the record."""
    payload = mandate.DEFAULT.to_dict()
    json.dumps(payload)  # must not raise
    assert payload["name_cap"] == "0.20"
    assert payload["evening"] == "17:00:00"
    assert payload["version"] == mandate.DEFAULT.version


# ---- the research tools ---------------------------------------------------------------------------


@pytest.fixture
def adj() -> pd.DataFrame:
    days = pd.bdate_range("2026-01-01", "2026-09-14")
    return pd.DataFrame({"A.NS": range(len(days))}, index=days, dtype=float)


def test_research_cannot_look_past_the_review_date(adj: pd.DataFrame) -> None:
    """A tool that could read tomorrow's price would be worse than no tool at all."""
    out = research.answer(
        [{"tool": "prices", "ticker": "A.NS", "months": 12}],
        known=date(2026, 6, 30),
        adj=adj,
        names=["A.NS"],
    )
    closes = out[0]["result"]["closes"]
    assert closes, "there should be prices before the cut-off"
    assert max(closes) <= "2026-06-30", "no price after the review's own date"


def test_research_cannot_reach_a_name_outside_the_review(adj: pd.DataFrame) -> None:
    """Scope is what it holds and what it was shown. Anything else is a packet nobody registered."""
    out = research.answer(
        [{"tool": "prices", "ticker": "SECRET.NS"}],
        known=date(2026, 6, 30),
        adj=adj,
        names=["A.NS"],
    )
    assert "not in this review's scope" in out[0]["error"]


def test_more_requests_than_allowed_are_refused_out_loud(adj: pd.DataFrame) -> None:
    """Silently dropping requests would let the investor believe it had looked at something."""
    asked = [{"tool": "prices", "ticker": "A.NS"} for _ in range(research.MAX_REQUESTS + 3)]
    out = research.answer(asked, known=date(2026, 6, 30), adj=adj, names=["A.NS"])
    answered = [o for o in out if "result" in o]
    assert len(answered) == research.MAX_REQUESTS
    assert any("were NOT run" in str(o.get("error", "")) for o in out)


def test_an_unknown_tool_is_an_answer_not_a_crash(adj: pd.DataFrame) -> None:
    out = research.answer(
        [{"tool": "buy", "ticker": "A.NS"}], known=date(2026, 6, 30), adj=adj, names=["A.NS"]
    )
    assert "no such tool" in out[0]["error"]
    assert "result" not in out[0]


def test_a_malformed_request_is_an_answer_not_a_crash(adj: pd.DataFrame) -> None:
    out = research.answer(["give me everything"], known=date(2026, 6, 30), adj=adj, names=["A.NS"])
    assert "not a request object" in out[0]["error"]


def test_compare_refuses_a_metric_it_cannot_compute(adj: pd.DataFrame) -> None:
    out = research.answer(
        [{"tool": "compare", "tickers": ["A.NS"], "metric": "vibes"}],
        known=date(2026, 6, 30),
        adj=adj,
        names=["A.NS"],
    )
    assert "metric must be one of" in out[0]["result"]["error"]


def test_a_first_pass_that_asks_for_research_is_read_as_asking() -> None:
    """A reply that asks AND decides decided without the answers. Those are not its decisions."""
    from qalpha.live.manager import _research_requests

    asked = _research_requests(
        json.dumps({"research": [{"tool": "filings", "ticker": "A.NS"}], "decisions": []})
    )
    assert asked == [{"tool": "filings", "ticker": "A.NS"}]
    assert _research_requests(json.dumps({"decisions": []})) == []
    assert _research_requests("not json at all") == []


def test_research_surfaces_ids_it_did_not_invent(adj: pd.DataFrame) -> None:
    """Citations earned by research are checked against the archive like any other."""
    out = research.answer(
        [{"tool": "filings", "ticker": "A.NS"}], known=date(2026, 6, 30), adj=adj, names=["A.NS"]
    )
    # No archive in this test, so no ids — the point is that it returns a set, never a licence.
    assert research.cited_ids(out) <= set()
