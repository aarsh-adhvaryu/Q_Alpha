"""Properties of the evening's callers whose failure would be silent.

A caller is code too: eleven tests once passed while the scheduled caller fed the function they
tested alphabetically ordered one-share baskets. Each test here pins a property of what the evening
actually runs — a benchmark that lies about a crash, a writer that destroys a good panel, a
first-sighting read that a failed run silently spends.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, "scripts")

import twin

BENCHMARK = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")
PANEL = Path("data/historical/prices_pit_2026.parquet")


# --- paper.py: the first step in the chain -------------------------------------------------------


def test_the_benchmark_repairs_a_spike_but_never_a_real_crash() -> None:
    """It carried two prints of ₹13.02 against a true ~₹129, which reads as a 90% collapse.

    The repair must undo a round trip and leave a fall that persists, because a persistent fall is
    exactly the signal this system must never be blind to.
    """
    from qalpha.live.price_integrity import repair_price_spikes

    idx = pd.bdate_range("2026-01-01", periods=10)
    spike = pd.Series([100.0] * 10, index=idx)
    spike.iloc[5] = 13.0  # one bad print, recovers next day
    repaired, fixed = repair_price_spikes(spike)
    assert fixed and float(repaired.iloc[5]) > 90, "a round trip is a bad print"

    crash = pd.Series([100.0] * 5 + [60.0] * 5, index=idx)
    held, fixed2 = repair_price_spikes(crash)
    assert not fixed2 and float(held.iloc[-1]) == 60.0, "a fall that persists is real"


def test_the_benchmark_series_loads_and_is_monotonic_in_time() -> None:
    if not BENCHMARK.exists():  # pragma: no cover - gitignored, refreshed in CI
        pytest.skip("benchmark panel not present")
    series = twin._benchmark_series()
    assert len(series) > 500
    assert series.index.is_monotonic_increasing
    assert float(series.dropna().min()) > 0, "a zero or negative index level is not a price"


def test_the_price_writer_refuses_to_destroy_a_good_panel(tmp_path: Path) -> None:
    """The defect: a direct `to_parquet` left a truncated file when the step was killed."""
    from qalpha.data.ingest import save_parquet

    good = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"]),
            "ticker": ["A.NS"],
            "close": [1.0],
            "adj_close": [1.0],
            "volume": [1],
        }
    )
    target = tmp_path / "p.parquet"
    save_parquet(good, target)
    with pytest.raises(ValueError, match="empty panel"):
        save_parquet(good.iloc[0:0], target)
    assert len(pd.read_parquet(target)) == 1, "the good panel survived the failed write"
    assert [f.name for f in tmp_path.iterdir()] == ["p.parquet"], "no temp file left behind"


# --- a name is "seen" only when it was actually covered ---------------------------------------------


def _cov_row(tmp_path: Path, **over: object) -> Path:
    import json

    from qalpha.live.extraction import EXTRACTION_VERSION, corpus_reader

    row: dict[str, object] = {
        "as_of": "2026-09-07",
        "ticker": "VBL.NS",
        "complete": True,
        "extraction_version": EXTRACTION_VERSION,
        "reader": corpus_reader(),
    }
    row.update(over)
    p = tmp_path / "coverage.jsonl"
    p.write_text(json.dumps(row) + "\n")
    return p


def test_an_incomplete_coverage_row_does_not_burn_the_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A name gets ONE chance at a year of history. A failed run must not spend it.

    Sixteen incomplete rows written during local testing on 2026-09-08 would otherwise have sent
    sixteen names down the ten-day path permanently.
    """
    import evidence

    monkeypatch.setattr(evidence, "COVERAGE_LOG", _cov_row(tmp_path, complete=False))
    assert evidence._seen_before("VBL.NS") is False
    assert evidence._window_days("VBL.NS") == evidence.BOOTSTRAP_DAYS


def test_a_superseded_extractor_does_not_burn_the_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evidence

    monkeypatch.setattr(evidence, "COVERAGE_LOG", _cov_row(tmp_path, extraction_version="EX-1"))
    assert evidence._seen_before("VBL.NS") is False


def test_a_complete_current_row_does_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import evidence

    monkeypatch.setattr(evidence, "COVERAGE_LOG", _cov_row(tmp_path))
    assert evidence._seen_before("VBL.NS") is True
    assert evidence._window_days("VBL.NS") == evidence.LOOKBACK_DAYS
