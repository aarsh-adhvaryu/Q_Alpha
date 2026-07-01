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


def test_dashboard_renders_and_advises() -> None:
    at = AppTest.from_file(str(_APP), default_timeout=60).run()
    assert not at.exception
    assert any("Q-Alpha" in t.value for t in at.title)
    assert len(at.metric) >= 4
    # Two top-level tabs now: Paper book + Live (Zerodha).
    labels = [t.label for t in at.tabs]
    assert any("Paper" in lbl for lbl in labels)
    assert any(("Live" in lbl) or ("Zerodha" in lbl) for lbl in labels)
    # The one-screen "Today" brief renders on the paper tab.
    assert any("Today — what to do" in m.value for m in at.markdown)

    # Clicking the "Add money" advisor (button: "Suggest what to buy") must render without error.
    at.number_input(key="add_amt").set_value(50000).run()
    next(b for b in at.button if "buy" in b.label.lower()).click().run()
    assert not at.exception
    # It renders the deploy advice ("Tax saved …") when the watchlist panel is on disk, or a graceful
    # "not ready" notice when that gitignored panel is absent — either is a clean render.
    texts = [m.value for m in at.markdown] + [e.value for e in at.error]
    assert any(("Tax saved" in t) or ("not ready" in t.lower()) for t in texts)
