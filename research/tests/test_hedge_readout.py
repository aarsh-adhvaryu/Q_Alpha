"""Tests for the plain-English hedge readout helpers (clarity follow-up)."""

from __future__ import annotations

from research.regime.hedge_readout import (
    hedge_gauge_read,
    hedge_glossary,
    hedge_plain_summary,
)


def test_gauge_read_on_off() -> None:
    on = hedge_gauge_read(0.74, 0.70, "elevated", hedge_on=True)
    assert "0.74" in on and "0.70" in on and "ON" in on and "elevated" in on
    off = hedge_gauge_read(0.46, 0.70, "calm", hedge_on=False)
    assert "OFF" in off and "calm" in off


def test_plain_summary_covers_state_and_reassures_on_quiet() -> None:
    md = hedge_plain_summary(
        level="calm", gauge=0.46, tau=0.70, hedge_on=False, days=12, episodes=0
    )
    assert "In plain English" in md
    assert "without selling your shares" in md  # the tax-free point, in plain words
    assert "12 trading days" in md and "fired **0**" in md
    assert "quiet chart good" in md.lower()  # reassures that a flat curve is expected


def test_glossary_defines_key_terms() -> None:
    md = hedge_glossary()
    for term in ("Systemic-stress gauge", "τ (tau)", "Hedge effect", "Coincident", "Tax-free"):
        assert term in md
