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
        local_run,
        "_proposal",
        # `mandate` joined the signature when the sector and name caps were threaded through — the
        # stub follows the real one, or it stops testing the real one.
        lambda account, budget, cfg, mandate: (_fit(state["orders"], budget), []),
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
    assert local_run.main(["--no-open", "--no-pipeline"]) == 0

    left = _allowance(rig)
    assert left.reserved > 0, "the run must record what it proposed"
    page = _page(rig)
    assert f"₹{float(left.remaining):,.0f}" in page, (
        "the page must show the allowance AFTER reserving"
    )
    # And it must not simultaneously claim nothing cleared the screen while printing a basket.
    assert not ("nothing that cleared its bar" in page and "You place these yourself" in page)


def test_a_restart_does_not_propose_the_same_money_again(rig) -> None:
    local_run.main(["--no-open", "--no-pipeline"])
    first = _allowance(rig).reserved
    local_run.main(["--no-open", "--no-pipeline"])
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

    local_run.main(["--no-open", "--no-pipeline"])
    local_run.main(["--no-open", "--no-pipeline"])
    left = _allowance(rig)
    assert left.reserved <= Decimal("12000"), (
        f"reserved ₹{left.reserved:,.0f} against ₹12,000 of cash"
    )


def test_imported_purchases_move_the_allowance_from_reserved_to_spent(rig) -> None:
    """FINDING 1. Importing ₹49,766 of confirmed purchases left spending at ₹0 and offered another
    ₹49,738. Recording a proposal is only half the lifecycle."""
    local_run.main(["--no-open", "--no-pipeline"])
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
    local_run.main(["--no-open", "--no-pipeline"])

    left = _allowance(rig)
    assert left.spent > 0, "a confirmed fill must become SPENT, not stay reserved for ever"
    assert left.reserved == Decimal("0"), "and must not be double-counted"


def test_an_outage_keeps_the_last_known_balance_for_display(rig) -> None:
    """FINDING 3. Buying stopped, correctly — but the account, the saved snapshot and the displayed
    cash all became ₹0. A broker outage is not a confirmed empty account."""
    local_run.main(["--no-open", "--no-pipeline"])
    rig["broker"] = ({}, {}, None, ["Kite unreachable"])
    local_run.main(["--no-open", "--no-pipeline"])

    saved = json.loads((rig["tmp"] / "snapshot.json").read_text(encoding="utf-8"))
    assert Decimal(saved["cash"]) == CASH, (
        f"the outage overwrote a known ₹{CASH:,.0f} with ₹{saved['cash']}"
    )
    page = _page(rig)
    assert "₹0" not in page.split("Cash")[1][:120], "and the page must not display it as zero"


def test_a_candidate_price_change_changes_the_snapshot_identity(rig) -> None:
    """FINDING 5. Changing an unheld candidate's price changed its recommended quantity and left the
    digest identical — so a resumed run would inherit work done against different numbers."""
    local_run.main(["--no-open", "--no-pipeline"])
    first = json.loads((rig["tmp"] / "snapshot.json").read_text(encoding="utf-8"))["digest"]

    rig["orders"] = [("INFY.NS", 25, Decimal("900")), ("TCS.NS", 10, Decimal("2203"))]
    local_run.main(["--no-open", "--no-pipeline"])
    second = json.loads((rig["tmp"] / "snapshot.json").read_text(encoding="utf-8"))["digest"]
    assert first != second, "different candidate prices must not share one identity"


def test_a_stale_screening_panel_blocks_even_when_another_panel_is_fresh(rig) -> None:
    """FINDING 4. Freshness took the NEWEST date across two files while the screen reads one
    specific file, so a fresh secondary panel licensed a 90-day-old screening panel."""
    rig["price_as_of"] = TODAY - timedelta(days=90)
    local_run.main(["--no-open", "--no-pipeline"])
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
    # THE PROPERTY, NOT THE LINE. This used to assert the literal
    # `start "" http://127.0.0.1:8787/` appeared before the server call — which pinned a real
    # defect in place: opening the browser *immediately* meant a cold start (WSL waking, uv
    # resolving, pandas importing) showed a connection error, and "not up yet" and "broken" look
    # identical in a browser.
    #
    # Two things have to hold at once, and both still do. The opener must be LAUNCHED before the
    # server call, because that call blocks until the window closes and nothing after it would ever
    # run. And it must not actually open anything until the server answers.
    opener = bat.index("Start-Process $u")
    assert opener < bat.index("qalpha.sh --app"), "the opener must be launched before the blocker"
    waiter = bat[bat.index('start "" /b powershell') : bat.index("qalpha.sh --app")]
    assert "Invoke-WebRequest" in waiter, "it must wait for a real response, not a guess at timing"
    assert "Start-Process" in waiter.split("Invoke-WebRequest", 1)[1], (
        "the browser must open only AFTER the request succeeds"
    )
    assert "Start-Sleep" in waiter, "and retry rather than giving up on the first refusal"
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


# --- the pipeline, driven by the real main() -----------------------------------------------------
#
# Every test above passes `--no-pipeline`, which is right for testing the decision layer and wrong
# as the only thing that reaches `main()`. The first version of this file did exactly that, and
# `main()` then shipped `run_pipeline(snapshot.digest)` — a bound METHOD where a digest string was
# wanted, so every ledger row would have been unwritable. Nothing caught it until a test ran the
# caller with the pipeline switched on. That is rule 4, again, in the same file that exists because
# of rule 4.
def test_main_runs_the_pipeline_and_keys_it_to_a_real_digest(rig, monkeypatch) -> None:
    from qalpha.live import daily

    seen: list[tuple[str, str]] = []

    def _spy(name: str):
        def run() -> None:
            seen.append(("ran", name))

        return daily.Step(name, f"doing {name}", run)

    monkeypatch.setattr(local_run, "LEDGER", rig["tmp"] / "ledger.jsonl")
    monkeypatch.setattr(daily, "refresh_steps", lambda: [_spy("prices")])
    monkeypatch.setattr(daily, "research_steps", lambda: [_spy("evidence")])
    monkeypatch.setattr(local_run, "refresh_steps", lambda: [_spy("prices")])
    monkeypatch.setattr(local_run, "research_steps", lambda: [_spy("evidence")])

    real = daily.run_pipeline
    keys: list[str] = []

    def _record(digest: str, **kw: object):
        keys.append(digest)
        return real(digest, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(local_run, "run_pipeline", _record)

    assert local_run.main(["--no-open"]) == 0
    assert seen == [("ran", "prices"), ("ran", "evidence")], "refresh must precede research"
    assert len(keys) == 2
    assert keys[0].startswith("day:"), "the refresh phase is scoped to the calendar day"
    # The research phase is keyed to the INPUTS. A bound method stringifies to something starting
    # with "<bound method", which is why this asserts the shape rather than merely that it is a str.
    assert keys[1].isalnum() and "method" not in keys[1], keys[1]


def test_a_second_run_does_not_redo_finished_research(rig, monkeypatch) -> None:
    """'Stop for two days and it continues' — asserted against the real entry point."""
    from qalpha.live import daily

    ran: list[str] = []
    ledger = rig["tmp"] / "ledger.jsonl"

    def _plan():
        return [daily.Step("evidence", "reading", lambda: ran.append("evidence"))]

    monkeypatch.setattr(local_run, "LEDGER", ledger)
    monkeypatch.setattr(local_run, "refresh_steps", list)
    monkeypatch.setattr(local_run, "research_steps", _plan)

    local_run.main(["--no-open"])
    local_run.main(["--no-open"])
    assert ran == ["evidence"], "the same inputs must not be researched twice"


def test_a_failed_step_does_not_stop_the_page_being_written(rig, monkeypatch) -> None:
    """A dead filings step must still leave a page, with the failure named on it."""
    from qalpha.live import daily

    def _boom() -> None:
        raise RuntimeError("NSE refused the connection")

    monkeypatch.setattr(local_run, "LEDGER", rig["tmp"] / "ledger.jsonl")
    monkeypatch.setattr(local_run, "refresh_steps", list)
    monkeypatch.setattr(
        local_run, "research_steps", lambda: [daily.Step("evidence", "reading", _boom)]
    )

    assert local_run.main(["--no-open"]) == 0
    page = _page(rig)
    assert "evidence FAILED" in page
    assert "NSE refused the connection" in page


def test_the_windows_launcher_does_not_fight_a_copy_of_itself() -> None:
    """A second double-click must open the running app, not try to bind its port again.

    Binding 8787 twice fails with a traceback about an address already in use, which says nothing
    about what is actually happening — the app is running and the user wants to look at it.
    """
    bat = (Path(__file__).resolve().parent.parent / "deploy/Q-Alpha.bat").read_text(
        encoding="utf-8"
    )
    head = bat[: bat.index("qalpha.sh --app")]
    assert "already running" in head.lower()
    assert head.index("already running") < head.index("waking"), (
        "check before waking the distro: there is nothing to wake if it is already up"
    )


def test_the_windows_launcher_pauses_with_something_that_works_under_redirection() -> None:
    """`timeout` refuses to run when stdin is redirected, printing an error over the last words the
    user reads. `ping -n` is the pause that always works."""
    bat = (Path(__file__).resolve().parent.parent / "deploy/Q-Alpha.bat").read_text(
        encoding="utf-8"
    )
    assert "timeout /t" not in bat
    assert "ping -n" in bat


def test_the_windows_launcher_still_says_it_places_no_orders() -> None:
    """The claim belongs on the thing the user double-clicks, not only on the page it opens."""
    bat = (Path(__file__).resolve().parent.parent / "deploy/Q-Alpha.bat").read_text(
        encoding="utf-8"
    )
    assert "NOTHING HERE TRADES" in bat
    assert "you place every order in Kite" in bat


def test_the_installer_can_actually_rewrite_the_lines_it_targets() -> None:
    """The installer edits the launcher with `sed`. If those two drift, it silently edits nothing.

    `deploy/Q-Alpha.bat` in the repo is a TEMPLATE: it carries whichever machine's distro and path
    were last committed, and `install-windows.sh` overwrites both when it copies the file to the
    Windows side. The failure mode is quiet — sed that matches no line exits 0 and writes the file
    through unchanged, so the shortcut ends up launching somebody else's checkout with no error
    anywhere. Reformatting either line is all it takes.

    The first version of this test asserted the template's own path existed on disk, which passed
    on the machine that wrote it and failed in CI, where that path is nobody's checkout. That was
    the test asserting a machine rather than a property.
    """
    import re

    root = Path(__file__).resolve().parent.parent
    installer = (root / "deploy/install-windows.sh").read_text(encoding="utf-8")
    patterns = re.findall(r'-e "s\|(\^set [A-Z]+=)\.\*\|', installer)
    assert {"^set DISTRO=", "^set REPO="} <= set(patterns), (
        f"the installer rewrites {patterns}; it must rewrite both DISTRO and REPO"
    )

    for name in ("Q-Alpha", "Q-Alpha-dev"):
        bat = (root / f"deploy/{name}.bat").read_text(encoding="utf-8")
        for anchor in patterns:
            line = anchor.lstrip("^")
            assert any(ln.startswith(line) for ln in bat.splitlines()), (
                f"{name}.bat has no line starting `{line}`, so the installer's sed for it "
                f"matches nothing and the launcher ships with whatever was committed."
            )


def test_the_launchers_never_hard_code_a_windows_username() -> None:
    """The installer reads %USERNAME% at install time. A baked-in one launches for one person."""
    root = Path(__file__).resolve().parent.parent
    for name in ("Q-Alpha", "Q-Alpha-dev"):
        bat = (root / f"deploy/{name}.bat").read_text(encoding="utf-8")
        assert "dnaad" not in bat, f"{name}.bat carries a specific Windows user"
        assert "C:\\Users\\" not in bat, f"{name}.bat hard-codes a Users path"
