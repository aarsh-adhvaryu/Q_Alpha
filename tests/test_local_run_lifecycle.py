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


# --- the Windows launcher -------------------------------------------------------------------------
#
# Five tests used to live here, four of them about WSL: waking a distro, naming it, reaching a repo
# inside `\\\\wsl$\\...`, and an installer that copied the launcher OUT of WSL because a shortcut
# into it is unreachable exactly when it is needed ("Missing Shortcut", 2026-09-10).
#
# None of that was the launcher's problem — it was the cost of living in the wrong filesystem.
# Running natively from D:\\ removed the filesystem, the bridge, the installer and the drift between
# them. What survives is the part that was always about the launcher: it must find the repo without
# being told, and it must not open a browser at something that is not answering yet.
def test_the_launcher_sits_in_the_repo_and_needs_no_install_step() -> None:
    root = Path(__file__).resolve().parent.parent
    launcher = root / "Q-Alpha.bat"
    assert launcher.exists(), "the desktop shortcut points straight at this file"

    text = launcher.read_text(encoding="utf-8", errors="replace")
    assert 'cd /d "%~dp0"' in text, "it must locate the repo as its own folder, not a baked path"
    # THE EXECUTABLE LINES, not the prose. The header explains why the WSL bridge is gone and
    # names the `\\\\wsl$` path it used to live on, which is worth keeping — so the check reads
    # what actually runs. Asserting over the whole file failed on its own explanation.
    code = "\n".join(ln for ln in text.splitlines() if not ln.strip().upper().startswith("REM"))
    for command in ("wsl -d", "wsl --", "wsl.exe", "\\\\wsl$"):
        assert command not in code, f"{command!r} is back in the launcher"
    assert not (root / "deploy").exists(), "the WSL bridge is gone; do not reintroduce it"


def test_the_launcher_runs_the_same_entry_point_the_tests_drive() -> None:
    """If the desktop click ran something else, nothing above would describe what happens when he
    double-clicks it."""
    root = Path(__file__).resolve().parent.parent
    text = (root / "Q-Alpha.bat").read_text(encoding="utf-8", errors="replace")
    assert "scripts/local_run.py" in text
    assert "--app" in text


def test_the_launcher_hard_codes_no_user_and_no_absolute_repo_path() -> None:
    """A baked username or drive letter launches for one person on one machine."""
    text = (Path(__file__).resolve().parent.parent / "Q-Alpha.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "dnaad" not in text
    assert "D:\\Q-Alpha" not in text, "%~dp0 already knows where it is"


def test_the_launcher_waits_for_the_server_before_opening_a_browser() -> None:
    """THE PROPERTY, NOT THE LINE.

    An earlier version asserted the literal ``start "" http://127.0.0.1:8787/`` appeared before the
    server call, which pinned a real defect in place: opening immediately meant a cold start showed
    a connection error, and "not up yet" and "broken" look identical in a browser.

    Two things must hold at once. The opener is LAUNCHED before the server call, because that call
    blocks until the window closes and nothing after it would ever run. And it opens nothing until
    the server actually answers.
    """
    text = (Path(__file__).resolve().parent.parent / "Q-Alpha.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    # The BLOCKING call specifically. `local_run.py` also appears in the "is this the repo?"
    # check near the top, and anchoring on that compared the waiter against the wrong line.
    blocker = text.index("run python scripts/local_run.py")
    assert text.index("Start-Process $u") < blocker, "the opener must precede the blocking call"
    waiter = text[text.index('start "" /b powershell') : blocker]
    assert "Invoke-WebRequest" in waiter, "it must wait for a real response, not guess at timing"
    assert "Start-Process" in waiter.split("Invoke-WebRequest", 1)[1], (
        "the browser must open only AFTER the request succeeds"
    )
    assert "Start-Sleep" in waiter, "and retry rather than give up on the first refusal"


def test_the_launcher_reports_its_two_real_failures_separately() -> None:
    """Missing uv and a launcher moved out of the repo are different problems with different fixes.
    A tool you double-click and walk away from has to say which one happened."""
    text = (Path(__file__).resolve().parent.parent / "Q-Alpha.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "astral.sh/uv/install" in text, "a missing uv must say how to install it"
    assert "local_run.py" in text and "must stay in the repo folder" in text
    assert "pause" in text, "a failing run must not close before it can be read"


def test_the_launcher_still_says_it_places_no_orders() -> None:
    text = (Path(__file__).resolve().parent.parent / "Q-Alpha.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "NOTHING HERE TRADES" in text


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


def test_the_launcher_does_not_fight_a_copy_of_itself() -> None:
    """A second double-click must open the running app, not try to bind its port again.

    Binding 8787 twice fails with a traceback about an address already in use, which says nothing
    about what is actually happening — the app is running and the user wants to look at it.
    """
    text = (Path(__file__).resolve().parent.parent / "Q-Alpha.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    head = text[: text.index("run python scripts/local_run.py")]
    assert "already running" in head.lower()
    assert head.lower().index("already running") < head.lower().index("where uv"), (
        "check before doing any setup work: there is nothing to prepare if it is already up"
    )


def test_the_launcher_pauses_with_something_that_works_under_redirection() -> None:
    """`timeout` refuses to run when stdin is redirected, printing an error over the last words the
    user reads. `ping -n` is the pause that always works.

    This survived the rewrite by catching it: the native launcher was written fresh and used
    `timeout /t`, reintroducing a bug that had already been fixed once. A test that outlives the
    file it was written about is doing its job.
    """
    text = (Path(__file__).resolve().parent.parent / "Q-Alpha.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "timeout /t" not in text
    assert "ping -n" in text


def test_the_launcher_says_it_places_no_orders_in_both_places() -> None:
    """The claim belongs on the thing the user double-clicks, not only on the page it opens."""
    text = (Path(__file__).resolve().parent.parent / "Q-Alpha.bat").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "NOTHING HERE TRADES" in text
    assert "you place every order in Kite" in text


# --- what the click actually does ------------------------------------------------------------------
#
# The launcher started a server and nothing else: `--app` returns from `main()` before a single line
# of the pipeline runs, so a double-click served whatever page the last run had left behind. On
# 2026-09-10 that was an empty account under a four-hour-old date, next to an OPERATING.md that said
# the click "runs on this machine, writes one page, and opens it". Reading that as broken was the
# correct reading of what was on the screen.
def _launcher() -> str:
    return (Path(__file__).resolve().parent.parent / "Q-Alpha.bat").read_text(
        encoding="utf-8", errors="replace"
    )


def _code_lines(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().upper().startswith("REM"))


def test_the_click_starts_the_evening_rather_than_only_a_server() -> None:
    text = _launcher()
    blocker = text[text.index("run python scripts/local_run.py") :].splitlines()[0]
    assert "--autorun" in blocker, "the click must run the evening, not serve yesterday's page"


def test_main_passes_autorun_through_to_the_server(monkeypatch) -> None:
    """THE COUPLING, not the flag. A flag parsed and dropped looks identical from the launcher."""
    from qalpha.live import server

    seen: dict[str, object] = {}
    monkeypatch.setattr(
        server, "serve", lambda port, **kw: seen.update({"port": port, **kw}), raising=True
    )
    assert local_run.main(["--app", "--autorun", "--no-open", "--port", "8791"]) == 0
    assert seen == {"port": 8791, "open_browser": False, "autorun": True}

    seen.clear()
    assert local_run.main(["--app", "--no-open"]) == 0
    assert seen["autorun"] is False, "without the flag the app must wait to be asked"


def test_the_launcher_is_crlf_because_cmd_is_what_reads_it() -> None:
    """`core.autocrlf` is false here, so nothing else keeps this true on a fresh checkout.

    cmd.exe reads a batch file in chunks as it executes it, and an LF-only file can lose a `goto`
    label that falls across a boundary — this file has three `goto :fail`s and the label at its tail.
    """
    root = Path(__file__).resolve().parent.parent
    raw = (root / "Q-Alpha.bat").read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n") > 0, "every line ending must be CRLF"
    attrs = (root / ".gitattributes").read_text(encoding="utf-8")
    assert "*.bat text eol=crlf" in attrs, "and git must keep it that way on the next checkout"


def test_the_launcher_does_not_uninstall_the_toolchain_on_every_click() -> None:
    """A bare `uv run` resolves against the base dependencies and removes the dev extra — 23
    packages out and back per click, inside the window the browser watcher is counting down."""
    code = _code_lines(_launcher())
    prepare = code[: code.index("run python scripts/local_run.py")]
    assert "sync" in prepare and "--extra dev" in prepare
    assert "UV_NO_SYNC=1" in prepare, "and `uv run` must not undo it a line later"


def test_the_watcher_says_so_when_it_gives_up() -> None:
    """Silence after two minutes is indistinguishable from a page that will never come."""
    text = _launcher()
    waiter = text[text.index('start "" /b powershell') : text.index("run python scripts/local")]
    assert "did not answer" in waiter
    bound = int(waiter.split("$i -lt ", 1)[1].split(";", 1)[0])
    assert bound >= 300, "a cold start that prepares an environment can exceed two minutes"


def test_the_watcher_does_not_hide_the_console_it_shares() -> None:
    """`start /b` shares this window, so hiding it hid the window the launcher says to leave open."""
    assert "-WindowStyle Hidden" not in _code_lines(_launcher())
