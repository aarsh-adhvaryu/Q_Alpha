"""The three scripts the cron runs every day that no test imported.

`propose()` had eleven tests and passed while its scheduled caller handed it alphabetically ordered
one-share candidates. The lesson is not "test `propose` harder" — it is that a **caller** is code
too, and these three run daily with nothing exercising them.

These are not smoke tests. Each one pins a property whose failure would be silent: a benchmark that
lies about a crash, an as-of date that runs ahead of the data, a Telegram digest that says nothing
when there is something to say.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, "scripts")

import ai_brief
import paper
import scan_alerts

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
    series = paper._load_benchmark_series()
    assert len(series) > 500
    assert series.index.is_monotonic_increasing
    assert float(series.dropna().min()) > 0, "a zero or negative index level is not a price"


def test_as_of_never_runs_ahead_of_the_data() -> None:
    """A date past the panel would mark a book against prices that do not exist yet."""
    if not PANEL.exists():  # pragma: no cover
        pytest.skip("panel not present")
    prices, _u, _s = paper._load_market()
    last = pd.Timestamp(prices.dates[-1]).date()
    assert paper._as_of(prices, None) <= last
    assert paper._as_of(prices, "2099-01-01") <= last, "a future as-of must clamp, not extrapolate"


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


# --- scan_alerts.py: the daily Telegram digest ----------------------------------------------------


@pytest.mark.parametrize("level", ["deep", "elevated", "calm"])
def test_every_weakness_level_has_a_tranche_policy(level: str) -> None:
    """An unmapped level would print an empty instruction on a surface the user acts on."""
    policy = scan_alerts._tranche_policy(level)
    assert policy and policy.strip()


def test_the_benchmark_return_is_none_when_it_cannot_be_measured() -> None:
    """Not zero. A window with no data is unknown, and unknown is never a flat market."""
    idx = pd.bdate_range("2026-01-01", periods=5)
    series = pd.Series([100.0] * 5, index=idx)
    assert scan_alerts._benchmark_return_pct(series, date(2030, 1, 1), date(2030, 2, 1)) is None


def test_a_flat_benchmark_returns_zero_not_none() -> None:
    idx = pd.bdate_range("2026-01-01", periods=20)
    series = pd.Series([100.0] * 20, index=idx)
    out = scan_alerts._benchmark_return_pct(series, date(2026, 1, 2), date(2026, 1, 20))
    assert out is not None and abs(out) < 1e-9


# --- ai_brief.py ------------------------------------------------------------------------------------


def test_the_usage_footer_reports_truncation_rather_than_hiding_it() -> None:
    """A brief cut off at the token cap must say so, or it reads as a complete thought."""
    from qalpha.live.ai_brief import BriefResult

    cut = ai_brief._usage_footer(
        BriefResult(text="x", raw="x", model="m", usage={"input": 10, "output": 20, "truncated": 1})
    )
    whole = ai_brief._usage_footer(
        BriefResult(text="x", raw="x", model="m", usage={"input": 10, "output": 20, "truncated": 0})
    )
    # Assert the property, not a chosen word: a cut-off brief must warn, a whole one must not.
    assert cut != whole
    assert "⚠️" in cut and "cut off" in cut
    assert "⚠️" not in whole


def test_the_brief_never_reads_as_a_signal() -> None:
    """It is context only, and the preamble is the thing that stops it being read as advice."""
    from qalpha.live.ai_brief import CONTEXT_PREAMBLE

    assert "not a signal" in CONTEXT_PREAMBLE.lower()


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
