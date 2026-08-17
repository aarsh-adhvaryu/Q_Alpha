"""Smoke test for the live Streamlit dashboard (scripts/dashboard_app.py).

The dashboard is UI behind the optional ``dashboard`` extra, so this skips when Streamlit is absent
(CI is dev-only — same pattern as the QAOA test) and when the paper book / price panel aren't on
disk. It uses Streamlit's in-process ``AppTest`` to confirm the page renders with no exception and
that an advisor button produces advice — the deterministic logic itself is covered by test_advisor.
"""

from __future__ import annotations

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


def test_buy_list_is_withheld_and_the_sell_side_still_renders() -> None:
    """PR-1 (PLAN_TRUST_REPAIR.md): no buy list on the real-money surface, sell/raise untouched."""
    at = AppTest.from_string(_ADVISOR_HARNESS, default_timeout=60).run()
    assert not at.exception
    # The withheld notice renders in place of the buy list.
    assert any("buy list is withheld" in w.value for w in at.warning)
    # Sell / Raise cash are unaffected — both advisor buttons are still on the page, and neither the
    # buy button nor the AI market read (which only ever framed the buy list) is rendered.
    labels = [b.label for b in at.button]
    assert any("Advise sell" in lbl for lbl in labels)
    assert any("Advise raise-cash" in lbl for lbl in labels)
    assert not any("Suggest what to buy" in lbl for lbl in labels)
    assert not any("AI leans" in i.value for i in at.info)


def test_the_sell_advisor_still_computes_on_the_real_money_surface() -> None:
    """Withholding the buy list must not have disturbed the validated FIFO/tax path beside it."""
    at = AppTest.from_string(_ADVISOR_HARNESS, default_timeout=60).run()
    at.button(key="sell_btn_live").click().run()
    assert not at.exception
    assert any("ITC.NS" in m.value for m in at.markdown)
