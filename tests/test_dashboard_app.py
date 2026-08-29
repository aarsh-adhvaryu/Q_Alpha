"""Smoke + cross-surface tests for the live Streamlit dashboard (scripts/dashboard_app.py).

**This module used to skip in CI** (PLAN_TRUST_REPAIR.md T3.3): it was ``skipif``'d on a gitignored
price panel, so the dashboard — the surface every defect in the plan reached the user through — was
the least-tested code in the repo. It now runs against the ``dashboard_sandbox`` fixture, which
copies the committed books and generates the price panels, so it needs no market data and no network.

Streamlit itself is still an optional extra, so the import skip remains — that one is honest.
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

pytestmark = pytest.mark.usefixtures("dashboard_sandbox")


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
    # The property, not the sentence — see test_dashboard_status for why.
    assert "not:** the validated strategy" in infos
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


def test_the_daily_sources_are_freshness_gated_on_the_page() -> None:
    """T3.3: the System tab rendered three cron-written files with no freshness check at all.

    The sandbox copies the committed reports, whose mtimes are checkout time, so the panel renders
    one way or the other — what matters is that a verdict is *reached and shown* rather than the
    files being trusted silently.
    """
    at = AppTest.from_file(str(_APP), default_timeout=90).run()
    assert not at.exception
    shown = " ".join(c.value for c in at.caption) + " ".join(w.value for w in at.warning)
    # Branch-agnostic on purpose. The panel renders one of two shapes — a one-line "all up to date"
    # summary, or a block naming each stale source. An earlier version of this test asserted the
    # source names, which only appear in the stale branch, so it passed only while the cron was
    # behind and broke the moment it caught up. What must hold either way is that a freshness
    # verdict is *reached and shown* rather than the files being trusted silently.
    assert "daily sources are up to date" in shown or "daily sources are stale" in shown


def test_the_track_record_is_on_the_real_money_page() -> None:
    """The Live tab must carry the forward comparison, not just today's snapshot (PR-71).

    The tab reported equity, cash, holdings and tax paid — every one of them a *state*, none of them
    a *result*. Asserted at the source because the Live tab is behind a Kite login that AppTest
    cannot pass; the panel's own behaviour is covered in ``tests/test_track_record.py``.
    """
    import inspect

    import dashboard_app

    live_view = inspect.getsource(dashboard_app.main)
    assert "_track_record_panel(" in live_view, "the track record is not wired into the live view"
    panel = inspect.getsource(dashboard_app._track_record_panel)
    # It must mark against the prices the page is actually showing, and against the same benchmark
    # every other "vs Nifty" number on the dashboard uses — not a second, privately-loaded series.
    assert "benchmark, as_of)" in panel
    # SHARES ONLY. The benchmark leg is built from the traded rupees alone, so passing market_value
    # (cash + holdings) compares a column containing next month's parked SIP instalment against one
    # that cannot contain it: ₹4L parked against a ₹1L basket rendered "+444.2%, ahead by ₹4,01,677"
    # where the truth was +1.2% and ₹1,677. This assertion previously pinned that exact expression in
    # place, which is why 503 passing tests did not catch it — so it now forbids that call.
    assert "portfolio.holdings_value(prices)" in panel
    assert "market_value(" not in panel, (
        "the track record must not count idle cash as investment performance"
    )


def test_the_track_record_never_takes_the_page_down_with_it() -> None:
    """A missing tradebook, a short benchmark or a bad replay must not break the account view."""
    import inspect

    import dashboard_app

    panel = inspect.getsource(dashboard_app._track_record_panel)
    assert "except Exception" in panel
    assert "if not trades:\n        return" in panel


# ---- final audit, 2026-08-28: idle cash must not leak into a portfolio-weight column -------------


def test_holdings_weights_are_of_equity_and_are_unmoved_by_idle_cash() -> None:
    """The column read 3.3% for a position that was 17.8% of the portfolio, and summed to 18.6%.

    ``Portfolio.current_weights`` divides by cash + holdings, which is right for the paper book's NAV
    and wrong for a real account where the cash is next month's SIP instalment, not an allocation.
    That column is how concentration is read by eye against the advisor's own 20% max-name and 30%
    sector caps, so a 5.4× understatement is load-bearing. ``current_weights`` itself is untouched —
    the validated decision layer depends on the NAV basis.
    """
    from datetime import date
    from decimal import Decimal

    import dashboard_app

    from qalpha.accounting.tax_lots import TaxLot
    from qalpha.backtest.portfolio import Portfolio
    from qalpha.config import Config

    cfg = Config()
    prices = {"A.NS": Decimal("100"), "B.NS": Decimal("100")}

    def _book(cash: str) -> Portfolio:
        pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal(cash))
        for t, q in (("A.NS", "80"), ("B.NS", "20")):
            pf.ledger.add_lot(
                TaxLot(
                    ticker=t,
                    acquisition_date=date(2026, 1, 1),
                    quantity_original=Decimal(q),
                    buy_price=Decimal("100"),
                )
            )
        return pf

    as_of = date(2026, 8, 28)
    lean = dashboard_app._holdings_frame(_book("0"), prices, as_of)
    parked = dashboard_app._holdings_frame(_book("400000"), prices, as_of)

    assert list(lean["% of equity"]) == ["80.0%", "20.0%"]
    # The identical book with ₹4L of SIP money parked beside it must read identically.
    assert list(parked["% of equity"]) == list(lean["% of equity"])
    assert sum(float(x.rstrip("%")) for x in parked["% of equity"]) == pytest.approx(100.0)


def test_lots_frame_reveals_a_name_bought_on_two_dates() -> None:
    """One row per name hides split long-term dates — the live book's INFY, found 2026-08-29.

    The holdings table shows one LTCG-safe date per name: the *latest* lot's, since that is when the
    whole line qualifies. INFY held 5 shares from 2026-06-15 and 15 from 2026-08-28, so a fifth of
    the position reaches the 12.5% rate 74 days earlier than the row implies — invisible until now.
    """
    from datetime import date
    from decimal import Decimal

    import dashboard_app

    from qalpha.accounting.tax_lots import TaxLot
    from qalpha.backtest.portfolio import Portfolio
    from qalpha.config import Config

    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    for on, qty, px in [
        (date(2026, 6, 15), "5", "1136.31"),
        (date(2026, 8, 28), "15", "1140.21"),
    ]:
        pf.ledger.add_lot(
            TaxLot(
                ticker="INFY.NS",
                acquisition_date=on,
                quantity_original=Decimal(qty),
                buy_price=Decimal(px),
            )
        )
    pf.ledger.add_lot(
        TaxLot(
            ticker="TCS.NS",
            acquisition_date=date(2026, 8, 28),
            quantity_original=Decimal("10"),
            buy_price=Decimal("2340.03"),
        )
    )

    frame, split = dashboard_app._lots_frame(
        pf, {"INFY.NS": Decimal("1140"), "TCS.NS": Decimal("2334")}, date(2026, 8, 29)
    )
    assert len(frame) == 3, "one row per LOT, not per name"
    # Only the twice-bought name is flagged; a single-lot holding must not be.
    assert split == ["INFY.NS"]
    infy = frame[frame["Ticker"] == "INFY"]
    assert len(infy) == 2
    # The two lots must carry DIFFERENT long-term dates — the whole point of the panel.
    assert infy["Long-term from"].nunique() == 2


def test_the_harvest_tab_is_on_the_live_advisor() -> None:
    """Tax-loss harvesting graduated onto the real-money surface without the §2a ablation bar.

    Deliberate, and worth stating: that bar exists to stop an unproven *strategy claim* reaching real
    money. Harvesting makes no such claim — it converts a paper loss into a §74 carry-forward asset
    and realises ₹0 capital-gains tax by construction, which is exactly why it has no ablation.
    It also has a deadline the twin cannot wait out: 31 March.
    """
    import inspect

    import dashboard_app

    src = inspect.getsource(dashboard_app._advisor_tabs)
    assert "Harvest losses" in src
    assert "advise_harvest(" in src
    # A harvest is still a sale, so it must carry the same unreconciled-branch warning as Sell.
    assert "_harvest_branch_warning(" in src
    # And it must say the quantities are FIFO prefixes — picking by eye is the defect it prevents.
    assert "FIFO **prefixes**" in src


def test_the_harvest_warning_always_flags_the_set_off_branch() -> None:
    """Every harvest realises a loss, so §70 — never confirmed against a Zerodha statement — is
    always exercised. A sale that looks free of tax risk is the one worth reconciling."""
    import inspect

    import dashboard_app

    src = inspect.getsource(dashboard_app._harvest_branch_warning)
    assert "has_loss_lot=True" in src
    assert "Reconcile it afterwards" in src


def test_the_twin_panel_is_on_the_system_tab() -> None:
    """The twin is the instrument; without a surface it is markdown nobody opens."""
    import inspect

    import dashboard_app

    assert "_twin_panel(as_of)" in inspect.getsource(dashboard_app._system_tab)
    src = inspect.getsource(dashboard_app._twin_panel)
    # An unseeded twin must say so, not render an empty table that reads like a tie.
    assert "not seeded" in src
    # Freshness must come from the runner's own stamp, not the file's mtime: Streamlit Cloud
    # redeploys from a fresh git checkout, which resets every mtime to the deploy time — so an
    # mtime check reports a two-week-old book as current on exactly the surface where it matters.
    assert "saved_at" in src
    assert "_mtime_date" not in src


def test_the_archived_autopilot_panel_says_it_is_archived() -> None:
    """A superseded panel that silently vanishes is worse than one labelled frozen."""
    import inspect

    import dashboard_app

    src = inspect.getsource(dashboard_app._system_tab)
    assert "Superseded 2026-08-29" in src
    assert "will not move" in src
