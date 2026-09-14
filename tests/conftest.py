"""Shared test fixtures: synthetic price panels, no network — and no writes to the live record."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qalpha.data.prices import PriceData

_ROOT = Path(__file__).resolve().parent.parent

#: The files that ARE the record: the books, their history, the investor's own records, the evidence
#: logs and the financials. A test that writes to any of them is a test that can destroy something a
#: re-run cannot recreate. One did — a refunding test emptied data/twin/history.jsonl — and nothing
#: in 600 tests noticed, because every test checked its own outputs and none checked the real files.
_LIVE = (
    "data/twin",
    "data/facts/financials.jsonl",
    "data/evidence",
    "data/spend",
    "data/models",
    "data/readers",
)


def _fingerprint() -> dict[str, str]:
    prints: dict[str, str] = {}
    for entry in _LIVE:
        base = _ROOT / entry
        files = [base] if base.is_file() else sorted(base.rglob("*.json*")) if base.is_dir() else []
        for path in files:
            if path.is_file():
                prints[str(path.relative_to(_ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return prints


@pytest.fixture(scope="session", autouse=True)
def the_live_record_is_untouched() -> Iterator[None]:
    """Fail the session if any test changed the live record. Checked once, around everything."""
    before = _fingerprint()
    yield
    after = _fingerprint()
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    assert not changed, f"the test suite wrote to the live record: {changed}"


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


@pytest.fixture(autouse=True)
def _private_spend_and_pins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets its own spend ledger, model pins and reader-comparison store.

    A priced call reserves in the ledger before it is made. Without this, any test that exercises a
    real backend with a fake client would write reservations into ``data/spend/ledger.jsonl`` — and
    count test calls against the user's real monthly budget.
    """
    from qalpha.live import model_identity, readers, spend

    monkeypatch.setattr(spend, "LEDGER_PATH", tmp_path / "spend" / "ledger.jsonl")
    monkeypatch.setattr(model_identity, "PINS_PATH", tmp_path / "models" / "pins.json")
    monkeypatch.setattr(readers, "READERS_DIR", tmp_path / "readers")
