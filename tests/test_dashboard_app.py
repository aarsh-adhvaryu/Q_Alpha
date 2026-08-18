"""Smoke test for the live Streamlit dashboard (scripts/dashboard_app.py).

The dashboard is UI behind the optional ``dashboard`` extra, so this skips when Streamlit is absent
(CI is dev-only — same pattern as the QAOA test) and when the paper book / price panel aren't on
disk. It uses Streamlit's in-process ``AppTest`` to confirm the page renders with no exception and
that an advisor button produces advice — the deterministic logic itself is covered by test_advisor.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

_ROOT = Path(__file__).resolve().parent.parent
_APP = _ROOT / "scripts" / "dashboard_app.py"
_BOOK = _ROOT / "data" / "paper" / "book.json"
_PRICES = _ROOT / "data" / "historical" / "prices_pit_2026.parquet"

pytestmark = pytest.mark.skipif(
    not (_BOOK.exists() and _PRICES.exists()),
    reason="paper book / price panel not on disk (gitignored data)",
)


def test_dashboard_renders_the_system_view() -> None:
    at = AppTest.from_file(str(_APP), default_timeout=60).run()
    assert not at.exception
    assert any("Q-Alpha" in t.value for t in at.title)
    # Two top-level tabs now: 🧠 The system + 🔴 Live (Zerodha).
    labels = [t.label for t in at.tabs]
    assert any("system" in lbl.lower() for lbl in labels)
    assert any(("Live" in lbl) or ("Zerodha" in lbl) for lbl in labels)
    # The wallet metric renders (the fundable dry-powder view).
    assert len(at.metric) >= 1
    # The core-GO expander carries the validated book's "Today" brief (unchanged underneath).
    assert any("Today — what to do" in m.value for m in at.markdown)


# The advisor lives behind the Kite login gate on the 🔴 Live tab, which ``AppTest`` cannot pass
# without broker credentials — so render ``_advisor_tabs`` directly on a synthetic book instead. This
# is the real-money surface's code path, minus only the login.
_ADVISOR_HARNESS = """
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path("scripts").resolve()))
from dashboard_app import _advisor_tabs

from qalpha.accounting.tax_lots import TaxLot
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config

cfg = Config()
pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("50000"))
pf.ledger.add_lot(
    TaxLot(
        ticker="ITC.NS",
        acquisition_date=date(2024, 1, 2),
        quantity_original=Decimal("10"),
        buy_price=Decimal("400"),
    )
)
idx = pd.bdate_range("2025-01-01", periods=400)
_advisor_tabs(
    pf,
    {"ITC.NS": Decimal("420")},
    pd.Series(range(len(idx)), index=idx, dtype=float) + 20000.0,
    date(2026, 8, 17),
    default_add_amount=50000,
    namespace="live",
)
"""


def test_the_buy_list_renders_with_its_scope_note() -> None:
    """PR-3 restored the surface — and the honest framing rides *with* it, on every render."""
    at = AppTest.from_string(_ADVISOR_HARNESS, default_timeout=60).run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any("Suggest what to buy" in lbl for lbl in labels)  # back on the page
    # The scope note is not optional decoration: T1.5 must be on screen whenever the list is.
    infos = " ".join(i.value for i in at.info)
    assert "never been backtested" in infos
    assert "18.2%" in infos
    # Sell / Raise cash are untouched throughout.
    assert any("Advise sell" in lbl for lbl in labels)
    assert any("Advise raise-cash" in lbl for lbl in labels)


def test_the_kill_switch_still_withholds_every_buy_surface() -> None:
    """The flag must remain a working one-constant off switch, not a historical artifact.

    ``dashboard_app`` caches in ``sys.modules`` across AppTest runs, so flipping the flag leaks into
    every later test unless it is put back — restore it in ``finally``, not at the end of the body.
    """
    sys.path.insert(0, str(_ROOT / "scripts"))
    import dashboard_app

    try:
        dashboard_app.BUY_ADVICE_ON_REAL_MONEY = False
        at = AppTest.from_string(_ADVISOR_HARNESS, default_timeout=60).run()
        assert not at.exception
        assert any("switched off" in w.value for w in at.warning)
        labels = [b.label for b in at.button]
        assert not any("Suggest what to buy" in lbl for lbl in labels)
        assert any("Advise sell" in lbl for lbl in labels)  # sell side never gated on the flag
    finally:
        dashboard_app.BUY_ADVICE_ON_REAL_MONEY = True


def test_stale_watchlist_prices_withhold_the_buy_list_but_not_the_sell_side() -> None:
    """PR-2's data guard, seen end-to-end on the surface it protects."""
    at = AppTest.from_string(
        _ADVISOR_HARNESS.replace(
            '    namespace="live",',
            '    namespace="live",\n'
            '    buy_blocked_reasons=["latest watchlist price is 2026-07-10 — 27 weekdays stale"],',
        ),
        default_timeout=60,
    ).run()
    assert not at.exception
    warnings = " ".join(w.value for w in at.warning)
    assert "2026-07-10" in warnings
    labels = [b.label for b in at.button]
    assert not any("Suggest what to buy" in lbl for lbl in labels)
    assert any("Advise raise-cash" in lbl for lbl in labels)


def test_the_sell_advisor_still_computes_on_the_real_money_surface() -> None:
    """Restoring the buy list must not have disturbed the validated FIFO/tax path beside it."""
    at = AppTest.from_string(_ADVISOR_HARNESS, default_timeout=60).run()
    at.button(key="sell_btn_live").click().run()
    assert not at.exception
    assert any("ITC.NS" in m.value for m in at.markdown)


# ---- one book, one number (PLAN_TRUST_REPAIR.md PR-4 — fixes T2.2, T2.3) -------------------------


def test_the_headline_tile_reads_the_same_source_as_the_chart_beneath_it() -> None:
    """T2.3: the tile re-marked equity live while the chart read the committed curve.

    One book, two numbers, one screen. This asserts the tile's value is the committed curve's last
    mark — the same series the chart, the GO scorecard and the freshness panel all read.
    """
    import json

    raw = json.loads(_BOOK.read_text(encoding="utf-8"))
    committed = float(raw["equity_curve"][-1]["equity"])

    at = AppTest.from_file(str(_APP), default_timeout=90).run()
    assert not at.exception
    values = [m.value for m in at.metric]
    assert any(f"₹{committed:,.0f}" == v for v in values), (
        f"no tile shows the committed mark ₹{committed:,.0f}; tiles were {values}"
    )
    # And the tile is named for what it contains — it is inclusive of cash, beside a cash tile.
    labels = [m.label for m in at.metric]
    assert any("Book value" in lbl and "cash" in lbl for lbl in labels)


def test_every_headline_return_arrives_with_a_window() -> None:
    """T2.1/T2.2: a bare percentage with no window is what made two honest numbers look wrong."""
    at = AppTest.from_file(str(_APP), default_timeout=90).run()
    assert not at.exception
    text = " ".join(c.value for c in at.caption) + " ".join(m.value for m in at.markdown)
    assert "→" in text  # a window is printed
    assert "measured against" in text or "Window:" in text
