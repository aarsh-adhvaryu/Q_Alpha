"""The launcher, end to end — the test that six defects survived a PR for want of.

Every previous test in this area exercised a *function* with prepared inputs. None established that
``main()`` supplies those inputs correctly or completes a decision lifecycle, and a 2026-09-10 review
reproduced six defects against the real entry point that all of those green tests missed:

    imported purchases did not update spending      → proposed another ₹49,738
    reservations could exceed available cash        → ₹12,000 cash, ₹21,882 reserved
    broker failure still saved a ₹0 balance         → last-known figure lost
    freshness checked the wrong file                → 90-day-old screening panel produced a basket
    different decisions shared a snapshot identity  → candidate prices changed, digest did not
    the page contradicted the decision it saved     → "₹50,000 available" beside a fresh reservation

This drives the real ``main()`` with injected broker responses, tradebooks and price panels, through
the cycle the review asked for: **propose once → restart → import fills → outage → recover.**
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("pandas")

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import local_run

from qalpha.accounting.costs import Side
from qalpha.live.commitments import allowance
from qalpha.live.commitments import load as load_commitments
from qalpha.live.tradebook import TradebookTrade

CASH = Decimal("201117")
TODAY = date.today()


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point every path at a temp dir and every feed at something controllable."""
    monkeypatch.setattr(local_run, "PAGE", tmp_path / "qalpha.html")
    monkeypatch.setattr(local_run, "SNAPSHOT", tmp_path / "snapshot.json")
    monkeypatch.setattr(local_run, "SNAPSHOT_ARCHIVE", tmp_path / "snapshots")
    monkeypatch.setattr(local_run, "COMMITMENTS", tmp_path / "commitments.jsonl")
    monkeypatch.setattr(local_run, "TRADEBOOK_DIR", tmp_path / "tradebooks")

    state: dict[str, object] = {
        "trades": [],
        "broker": ({"VBL.NS": Decimal("147")}, {"VBL.NS": Decimal("414.23")}, CASH, []),
        "price_as_of": TODAY - timedelta(days=1),
        "orders": [("INFY.NS", 20, Decimal("1043")), ("TCS.NS", 10, Decimal("2203"))],
    }

    monkeypatch.setattr(local_run, "_trades", lambda: (state["trades"], []))
    monkeypatch.setattr(local_run, "_broker", lambda cfg: state["broker"])
    monkeypatch.setattr(local_run, "_price_as_of", lambda: state["price_as_of"])
    monkeypatch.setattr(
        local_run,
        "_prices",
        lambda tickers, costs: ({t: Decimal("400") for t in tickers}, []),
    )
    monkeypatch.setattr(
        local_run, "_proposal", lambda account, budget, cfg: (_fit(state["orders"], budget), [])
    )
    state["tmp"] = tmp_path
    return state


def _fit(orders, budget):
    """Whatever the screen would return, truncated to the budget it was given — a stand-in that
    cannot itself overspend, so any overspend the test finds came from the caller."""
    out, spent = [], Decimal("0")
    for t, q, p in orders:
        cost = Decimal(q) * p
        if spent + cost <= budget:
            out.append((t, q, p))
            spent += cost
    return out


def _page(state) -> str:
    return (state["tmp"] / "qalpha.html").read_text(encoding="utf-8")


def _allowance(state):
    return allowance(
        Decimal("50000"), load_commitments(state["tmp"] / "commitments.jsonl"), period=TODAY
    )


def _buy(t: str, q: str, p: str) -> TradebookTrade:
    return TradebookTrade(TODAY, t, Side.BUY, Decimal(q), Decimal(p), "10:00", f"{t}{q}{p}")


# --- the cycle ----------------------------------------------------------------------------------
def test_a_healthy_run_proposes_once_and_the_page_agrees_with_what_it_reserved(rig) -> None:
    """FINDING 6. The page showed "₹50,000 available" and "nothing cleared the screen" on the very
    run that had just reserved ₹49,766 and printed a basket. Three statements, one screen."""
    assert local_run.main(["--no-open"]) == 0

    left = _allowance(rig)
    assert left.reserved > 0, "the run must record what it proposed"
    page = _page(rig)
    assert f"₹{float(left.remaining):,.0f}" in page, (
        "the page must show the allowance AFTER reserving"
    )
    # And it must not simultaneously claim nothing cleared the screen while printing a basket.
    assert not ("nothing that cleared its bar" in page and "You place these yourself" in page)


def test_a_restart_does_not_propose_the_same_money_again(rig) -> None:
    local_run.main(["--no-open"])
    first = _allowance(rig).reserved
    local_run.main(["--no-open"])
    assert _allowance(rig).reserved == first, "a second run must not re-reserve the same names"


def test_reservations_can_never_exceed_the_cash_that_exists(rig) -> None:
    """FINDING 2. ₹12,000 of cash and ₹10,000 already reserved produced another ₹11,882 — total
    reservations of ₹21,882 against ₹12,000."""
    rig["broker"] = (
        {"VBL.NS": Decimal("147")},
        {"VBL.NS": Decimal("414.23")},
        Decimal("12000"),
        [],
    )
    rig["orders"] = [("A.NS", 10, Decimal("1000")), ("B.NS", 10, Decimal("1000"))]

    local_run.main(["--no-open"])
    local_run.main(["--no-open"])
    left = _allowance(rig)
    assert left.reserved <= Decimal("12000"), (
        f"reserved ₹{left.reserved:,.0f} against ₹12,000 of cash"
    )


def test_imported_purchases_move_the_allowance_from_reserved_to_spent(rig) -> None:
    """FINDING 1. Importing ₹49,766 of confirmed purchases left spending at ₹0 and offered another
    ₹49,738. Recording a proposal is only half the lifecycle."""
    local_run.main(["--no-open"])
    proposed = _allowance(rig).reserved
    assert proposed > 0

    # The user placed them; the Console export now shows the fills.
    rig["trades"] = [_buy(t, str(q), str(p)) for t, q, p in rig["orders"]]
    rig["broker"] = (
        {t: Decimal(q) for t, q, _ in rig["orders"]},
        {t: p for t, _, p in rig["orders"]},
        CASH - proposed,
        [],
    )
    local_run.main(["--no-open"])

    left = _allowance(rig)
    assert left.spent > 0, "a confirmed fill must become SPENT, not stay reserved for ever"
    assert left.reserved == Decimal("0"), "and must not be double-counted"


def test_an_outage_keeps_the_last_known_balance_for_display(rig) -> None:
    """FINDING 3. Buying stopped, correctly — but the account, the saved snapshot and the displayed
    cash all became ₹0. A broker outage is not a confirmed empty account."""
    local_run.main(["--no-open"])
    rig["broker"] = ({}, {}, None, ["Kite unreachable"])
    local_run.main(["--no-open"])

    saved = json.loads((rig["tmp"] / "snapshot.json").read_text(encoding="utf-8"))
    assert Decimal(saved["cash"]) == CASH, (
        f"the outage overwrote a known ₹{CASH:,.0f} with ₹{saved['cash']}"
    )
    page = _page(rig)
    assert "₹0" not in page.split("Cash")[1][:120], "and the page must not display it as zero"


def test_a_candidate_price_change_changes_the_snapshot_identity(rig) -> None:
    """FINDING 5. Changing an unheld candidate's price changed its recommended quantity and left the
    digest identical — so a resumed run would inherit work done against different numbers."""
    local_run.main(["--no-open"])
    first = json.loads((rig["tmp"] / "snapshot.json").read_text(encoding="utf-8"))["digest"]

    rig["orders"] = [("INFY.NS", 25, Decimal("900")), ("TCS.NS", 10, Decimal("2203"))]
    local_run.main(["--no-open"])
    second = json.loads((rig["tmp"] / "snapshot.json").read_text(encoding="utf-8"))["digest"]
    assert first != second, "different candidate prices must not share one identity"


def test_a_stale_screening_panel_blocks_even_when_another_panel_is_fresh(rig) -> None:
    """FINDING 4. Freshness took the NEWEST date across two files while the screen reads one
    specific file, so a fresh secondary panel licensed a 90-day-old screening panel."""
    rig["price_as_of"] = TODAY - timedelta(days=90)
    local_run.main(["--no-open"])
    assert _allowance(rig).reserved == Decimal("0"), "nothing may be proposed on 90-day-old prices"


# --- the Windows launcher -----------------------------------------------------------------------
def test_the_windows_launcher_checks_each_failure_separately() -> None:
    """A missing WSL feature, a stopped distro and a wrong repo path are three different problems,
    and only one of them is fixed by waiting. A launcher that reports them as one failure sends the
    user to the wrong place, which for a double-click-and-walk-away tool is most of its job."""
    bat = (Path(__file__).resolve().parent.parent / "deploy/Q-Alpha.bat").read_text(
        encoding="utf-8"
    )
    assert "wsl --install" in bat, "a missing WSL must say how to install it"
    assert "wsl --list --verbose" in bat, "a wrong distro name must say how to find the right one"
    assert "Edit REPO" in bat, "a wrong path must say which line to edit"
    # The browser is opened BEFORE the server starts: the app runs in the foreground
    # until the window closes, so opening it afterwards would never happen.
    assert bat.index('start "" http://127.0.0.1:8787/') < bat.index("qalpha.sh --app")
    assert "pause" in bat, "a failing run must not close before it can be read"
    assert "NOTHING HERE TRADES" in bat


def test_the_launcher_runs_the_same_entry_point_the_tests_drive() -> None:
    """If the desktop click ran something else, none of the tests above would say anything about
    what actually happens when he double-clicks it."""
    root = Path(__file__).resolve().parent.parent
    bat = (root / "deploy/Q-Alpha.bat").read_text(encoding="utf-8")
    sh = (root / "qalpha.sh").read_text(encoding="utf-8")
    assert "qalpha.sh" in bat
    assert "scripts/local_run.py" in sh


def test_the_launcher_is_installed_to_windows_not_shortcut_inside_wsl() -> None:
    """ "Missing Shortcut", 2026-09-10, and it was a chicken-and-egg of my own making.

    The first instruction shortcut ``deploy/Q-Alpha.bat`` where it sits — inside WSL's filesystem at
    ``\\\\wsl$\\<distro>\\...``. **That path only exists while WSL is running**, and starting WSL is
    the launcher's entire job, so Windows could not reach the file it needed in order to wake the
    thing the file lives on. It failed on exactly the occasions it was needed.

    The installer copies the launcher to the Windows side, where it is always reachable, and writes
    this machine's real distro and repo into the copy.
    """
    root = Path(__file__).resolve().parent.parent
    installer = (root / "deploy/install-windows.sh").read_text(encoding="utf-8")
    assert "WSL_DISTRO_NAME" in installer, "the distro must be read, never assumed"
    assert "%USERNAME%" in installer, "the Windows user must be read, never assumed"
    assert "OneDrive/Desktop" in installer, (
        "a redirected Desktop is the common case, not the odd one"
    )
    # The shortcut must target the Windows copy. A .lnk whose TargetPath is a \\wsl$ path is the
    # exact failure being fixed, so no TargetPath line may mention it.
    targets = [ln for ln in installer.splitlines() if "TargetPath" in ln]
    assert targets, "the installer must set a shortcut target"
    for line in targets:
        assert "USERPROFILE" in line, line
        assert "wsl$" not in line, f"a shortcut into WSL is unreachable when WSL is asleep: {line}"

    bat = (root / "deploy/Q-Alpha.bat").read_text(encoding="utf-8")
    assert "DO NOT shortcut this file where it sits" in bat, (
        "the file must warn against the thing that failed"
    )
