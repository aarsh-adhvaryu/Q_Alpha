"""The valuation check — the gap VBL exposed: a big fall is not a low price."""

from __future__ import annotations

from datetime import UTC, date, datetime

from qalpha.live.valuation import (
    MIN_MARKET_CAP,
    PE_CAUTION,
    Valuation,
    check_basket,
    fetch_valuations,
    load_snapshot,
    save_snapshot,
)

_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _v(ticker: str, pe: float | None, mcap: float | None = 5e11) -> Valuation:
    return Valuation(ticker, pe, None, mcap, retrieved_at=_NOW)


def test_a_name_that_fell_hard_and_is_still_expensive_is_flagged() -> None:
    """VBL, in one assertion.

    It fell ₹669 → ₹412, which the screen scores as 23.8% "cheap" and ranks it UP for. The exchange
    was simultaneously showing "Scrip PE is greater than 50". Both statements are true; only one of
    them is about value. The screen reads prices and only prices, so it could not tell that a −38%
    fall from a P/E-80 valuation leaves a name that is still expensive.
    """
    report = check_basket(["VBL.NS"], {"VBL.NS": _v("VBL.NS", 62.0)}, as_of=date(2026, 8, 31))
    assert not report.clear
    assert "P/E 62.0" in report.cautioned[0].caution() or ""
    assert "not the same as a low price" in report.render()


def test_a_reasonably_priced_name_passes() -> None:
    report = check_basket(["ITC.NS"], {"ITC.NS": _v("ITC.NS", 16.9)}, as_of=date(2026, 8, 31))
    assert report.clear
    assert "passed" in report.render()


def test_a_missing_pe_is_unknown_and_never_reads_as_cheap() -> None:
    """A loss-making company has no meaningful P/E. Silence there is the +444% defect's shape.

    "No data" must surface as CANNOT ASSESS, never as an implicit pass — a name with no earnings is
    the *last* thing a screen that buys falling prices should wave through.
    """
    for pe in (None, 0.0, -12.0):
        report = check_basket(["X.NS"], {"X.NS": _v("X.NS", pe)}, as_of=date(2026, 8, 31))
        assert not report.clear, f"pe={pe} must not pass silently"
        assert "cannot be assessed" in (report.cautioned[0].caution() or "")


def test_a_name_absent_from_the_snapshot_is_unknown_not_skipped() -> None:
    """Dropping an unpriced name would let the basket look cleaner than it is."""
    report = check_basket(["GONE.NS"], {}, as_of=date(2026, 8, 31))
    assert not report.clear
    assert report.cautioned[0].source == "missing"


def test_a_microcap_is_flagged_before_its_pe_is_even_considered() -> None:
    """Kite nudges under ₹100 cr as illiquid and pump-and-dump-prone. That outranks valuation."""
    report = check_basket(
        ["TINY.NS"],
        {"TINY.NS": _v("TINY.NS", 12.0, mcap=MIN_MARKET_CAP - 1)},
        as_of=date(2026, 8, 31),
    )
    assert "below ₹100 cr" in (report.cautioned[0].caution() or "")


def test_the_threshold_is_the_exchange_s_own() -> None:
    """Mirroring a published regulatory caution invents no factor and needs no validation."""
    assert PE_CAUTION == 50.0


def test_a_fetch_failure_yields_unknown_rather_than_stopping_the_basket() -> None:
    def boom(ticker: str) -> dict[str, object]:
        raise RuntimeError("network down")

    out = fetch_valuations(["A.NS"], fetch=boom, now=_NOW)
    assert out["A.NS"].pe is None and out["A.NS"].unknown


def test_nan_is_not_a_number_we_act_on() -> None:
    out = fetch_valuations(["A.NS"], fetch=lambda t: {"trailingPE": float("nan")}, now=_NOW)
    assert out["A.NS"].pe is None


def test_the_snapshot_round_trips_with_its_provenance(tmp_path) -> None:
    """A decision must be replayable against the facts that were actually visible when it was made."""
    path = tmp_path / "snapshot.json"
    assert save_snapshot({"A.NS": _v("A.NS", 41.0)}, path=path) == 1
    back = load_snapshot(path)
    assert back["A.NS"].pe == 41.0
    assert back["A.NS"].retrieved_at == _NOW


def test_a_missing_snapshot_reads_as_unknown_not_as_empty_approval(tmp_path) -> None:
    assert load_snapshot(tmp_path / "nope.json") == {}
