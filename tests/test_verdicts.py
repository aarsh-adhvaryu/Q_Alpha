"""The AI verdict path: what it asks about, and what it does when it cannot ask."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from qalpha.live.ai_brief import NameVerdict
from qalpha.live.verdicts import basket_verdicts, verdict_calls


def test_verdict_calls_flattens_to_what_the_runner_reads() -> None:
    """``Market.ai_verdicts`` is a ticker -> "keep"/"drop" map; anything else silently keeps."""
    calls = verdict_calls(
        {
            "A.NS": NameVerdict("A.NS", keep=True, confidence="high", reason="fine"),
            "B.NS": NameVerdict("B.NS", keep=False, confidence="medium", reason="demerger"),
        }
    )
    assert calls == {"A.NS": "keep", "B.NS": "drop"}


def test_an_empty_basket_never_calls_the_model() -> None:
    """No candidates means no question — and no token spend on a day with nothing to ask about."""
    assert basket_verdicts({}, {}, None, __import__("datetime").date(2026, 8, 30)) == ({}, "", {})


def test_a_book_below_the_cash_floor_is_never_asked_about() -> None:
    """The model is asked roughly when a SIP lands, not daily — the floor is the cost control.

    Also the fail-soft guarantee: ``_ai_verdicts`` returns an empty map rather than raising, so a
    twin cron can never go red because the AI was unavailable.
    """
    from decimal import Decimal

    from twin import _ai_verdicts

    from qalpha.backtest.portfolio import Portfolio
    from qalpha.config import Config
    from qalpha.live.twin import TWIN_FULL, TwinBook

    cfg = Config()
    book = TwinBook(TWIN_FULL, Portfolio(cfg.cost, cfg.tax, cash=Decimal("400")))
    assert _ai_verdicts({TWIN_FULL: book}, None, cfg) == {}
