"""Backtest runs are recorded with what produced them, or they are not evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from qalpha.backtest.runstore import RunRecord, drift_report, load_runs, save_run


def _record(label: str = "phase4", **kw: object) -> RunRecord:
    base = {
        "label": label,
        "params": {"universe": "pit_nifty50", "start": "2013-07-01", "null_draws": 60},
        "results": {"screen_final": 28_443_450.0, "noise_floor": 8_362_315.0},
        "caveats": ["one window", "screen developed with this data visible"],
    }
    base.update(kw)
    return RunRecord(**base)  # type: ignore[arg-type]


def test_a_run_records_its_commit(tmp_path: Path) -> None:
    """Without the commit a result can be re-obtained but never reproduced."""
    assert _record().commit


def test_a_run_without_caveats_is_refused() -> None:
    """Every backtest here has limits. Stored without them, they get quoted without them."""
    with pytest.raises(ValueError, match="quoted without them"):
        _record(caveats=[])


def test_runs_are_appended_never_overwritten(tmp_path: Path) -> None:
    """A changed answer must sit beside the old one, not replace it."""
    a = save_run(_record(), runs_dir=tmp_path)
    b = save_run(_record(), runs_dir=tmp_path)
    assert a != b
    assert len(load_runs(runs_dir=tmp_path)) == 2


def test_runs_round_trip(tmp_path: Path) -> None:
    save_run(_record(), runs_dir=tmp_path)
    (loaded,) = load_runs(runs_dir=tmp_path)
    assert loaded.params["null_draws"] == 60
    assert loaded.results["noise_floor"] == 8_362_315.0
    assert loaded.caveats


def test_runs_can_be_filtered_by_label(tmp_path: Path) -> None:
    save_run(_record("phase4"), runs_dir=tmp_path)
    save_run(_record("sip"), runs_dir=tmp_path)
    assert len(load_runs(label="sip", runs_dir=tmp_path)) == 1


def test_drift_between_runs_is_reported(tmp_path: Path) -> None:
    """The reason for keeping old runs: a number that moved when nothing should have."""
    save_run(_record(), runs_dir=tmp_path)
    save_run(_record(results={"screen_final": 30_000_000.0}), runs_dir=tmp_path)
    text = drift_report("phase4", "screen_final", runs_dir=tmp_path)
    assert "vs previous" in text
    assert "same commit produced different answers" in text


def test_a_missing_metric_says_so_rather_than_reporting_nothing(tmp_path: Path) -> None:
    save_run(_record(), runs_dir=tmp_path)
    assert "carry 'sharpe'" in drift_report("phase4", "sharpe", runs_dir=tmp_path)
