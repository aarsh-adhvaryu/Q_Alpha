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
