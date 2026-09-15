"""The replay — the investor over past sessions, on its own book, resumable, and blind to the future.

A synthetic world with **holdings and cash**: two names bought months before the window, two
pulled-back candidates, a deposit and a dividend inside the window, a trade the user made after the
start, a filing published mid-window, one read after the corpus date, a missing close, and a fake
model scripted per session to BUY, HOLD, research then SELL, and reply with garbage. Nothing touches
the network or the real records.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from qalpha.accounting.corporate_actions import CorporateAction, CorporateActionType
from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.live import evidence_log, manager, replay, spend
from qalpha.live import financials as company_facts
from qalpha.live.evidence_log import Corpus
from qalpha.live.extraction import EXTRACTION_VERSION, corpus_reader
from qalpha.live.flows import Flow
from qalpha.live.market import Market
from qalpha.live.progress import IST
from qalpha.live.tradebook import TradebookTrade

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

HELD = ["AAA.NS", "BBB.NS"]
CANDIDATES = ["DDD.NS", "EEE.NS"]
NAMES = HELD + CANDIDATES
SECTORS = {"AAA.NS": "IT", "BBB.NS": "Banks", "DDD.NS": "FMCG", "EEE.NS": "Energy"}
DAYS = pd.bdate_range(end="2026-09-11", periods=300)
S = [d.date() for d in DAYS[-6:]]  # the replay window: six sessions
BOUGHT = DAYS[-200].date()
RECORDED_BY = S[-1] + timedelta(days=2)
NOW = datetime.combine(S[-1] + timedelta(days=4), time(19, 0), IST)


def _panel() -> PriceData:
    rng = np.random.default_rng(11)
    raw = {}
    for i, t in enumerate(NAMES):
        path = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(DAYS)))) * (1 + i / 10)
        if t in CANDIDATES:
            path[-60:] *= np.linspace(1.0, 0.7, 60)
        raw[t] = path
    close = pd.DataFrame(raw, index=DAYS)
    # The vendor's adjusted series is scaled down before a dividend paid at the LAST session: a
    # number nobody had before then, which a replay must not show.
    adj = close.copy()
    adj.loc[DAYS[:-1], "AAA.NS"] *= 0.95
    close.loc[DAYS[-2], "BBB.NS"] = np.nan  # BBB has no close on S[4]: that review cannot happen
    volume = pd.DataFrame(100_000.0, index=DAYS, columns=NAMES)
    return PriceData(adj, close, volume)


def _full() -> Market:
    panel = _panel()
    return Market(
        as_of=S[-1],
        prices={},
        index_close=pd.Series(np.linspace(100.0, 130.0, len(DAYS)), index=DAYS),
        adj_close=panel.adj_close,
        rebase_from={},
        exclude=set(),
        watchlist=NAMES,
        sector_of=SECTORS,
        wl_prices=panel,
    )


def _trades(panel: PriceData) -> list[TradebookTrade]:
    def at(day: date, t: str) -> Decimal:
        return Decimal(str(round(float(panel.close_raw.at[pd.Timestamp(day), t]), 2)))

    return [
        TradebookTrade(
            BOUGHT, "AAA.NS", Side.BUY, Decimal(200), at(BOUGHT, "AAA.NS"), "10:00", "t1"
        ),
        TradebookTrade(
            BOUGHT, "BBB.NS", Side.BUY, Decimal(100), at(BOUGHT, "BBB.NS"), "10:01", "t2"
        ),
        # The user bought EEE after the start. The replayed book never learns of it.
        TradebookTrade(S[3], "EEE.NS", Side.BUY, Decimal(50), at(S[3], "EEE.NS"), "10:00", "t3"),
    ]


FLOWS = [Flow(on=BOUGHT - timedelta(days=1), amount=Decimal("60000")), Flow(S[2], Decimal("20000"))]
DIVIDEND = CorporateAction(
    ticker="AAA.NS",
    ex_date=S[1],
    action_type=CorporateActionType.DIVIDEND,
    amount_per_share=Decimal("5"),
)


def _event(key: str, ticker: str, *, public: date, read: date, **over: Any) -> dict[str, Any]:
    row = {
        "_key": key,
        "ticker": ticker,
        "as_of": read.isoformat(),
        "disseminated_at": f"{public.isoformat()}T10:00:00Z",
        "event_type": "order_win",
        "materiality": "high",
        "summary": key,
        "passage": "the company has won an order",
        "verified": True,
        "model": corpus_reader(),
        "extraction_version": EXTRACTION_VERSION,
    }
    row.update(over)
    return row


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    coverage = tmp_path / "coverage.jsonl"
    coverage.write_text(
        "".join(
            json.dumps(
                {
                    "_key": f"{S[0]}:{t}",
                    "as_of": (S[0] - timedelta(days=30)).isoformat(),
                    "ticker": t,
                    "complete": True,
                    "window_days": 365,
                    "extraction_version": EXTRACTION_VERSION,
                    "reader": corpus_reader(),
                }
            )
            + "\n"
            for t in NAMES
        ),
        encoding="utf-8",
    )
    events = tmp_path / "events.jsonl"
    events.write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in (
                # Published long before the window and read by a backfill later: no event date, so
                # the packet must date it by publication, not by the reading.
                _event("old:AAA", "AAA", public=S[0] - timedelta(days=90), read=S[-1]),
                _event("mid:AAA", "AAA", public=S[3], read=S[-1], event_date=S[3].isoformat()),
                _event("late-read:BBB", "BBB", public=S[0], read=RECORDED_BY + timedelta(days=1)),
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(evidence_log, "COVERAGE_LOG", coverage)
    monkeypatch.setattr(evidence_log, "EVENT_LOG", events)
    monkeypatch.setattr(evidence_log, "NEWS_EVENT_LOG", tmp_path / "news.jsonl")
    monkeypatch.setattr(evidence_log, "ANNOUNCEMENTS", tmp_path / "announcements")
    monkeypatch.setattr(evidence_log, "EXTRACTED_LOG", tmp_path / "extracted.jsonl")
    monkeypatch.setattr(evidence_log, "REFUSED_LOG", tmp_path / "refused.jsonl")
    monkeypatch.setattr(company_facts, "FACTS_PATH", tmp_path / "financials.jsonl")
    monkeypatch.setattr("qalpha.live.evidence.load_archive", lambda day: ({}, None))
    monkeypatch.setattr(replay, "REPLAY_ROOT", tmp_path / "replay")
    full = _full()
    assert full.wl_prices is not None
    return {"full": full, "trades": _trades(full.wl_prices), "tmp": tmp_path, "calls": []}


def _packet_of(prompt: str) -> dict[str, Any]:
    return dict(json.loads(prompt.split("PACKET:\n", 1)[1]))


def _row(ticker: str, action: str = "HOLD", qty: int = 0) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "action": action,
        "quantity": qty,
        "reason": "r",
        "thesis": "t",
        "invalidate_if": "i",
        "evidence_ids": [f"price:{ticker}"],
        "note": f"note on {ticker}",
    }


def _hold(packet: dict[str, Any]) -> list[dict[str, Any]]:
    return [_row(h["ticker"]) for h in packet["portfolio"]["holdings"]]


def _script(packet: dict[str, Any]) -> str:
    """The investor's reply for each session: BUY, HOLD, research-then-SELL, garbage, HOLD."""
    day = date.fromisoformat(packet["as_of"])
    body: dict[str, Any] = {"portfolio_note": f"note {day}"}
    if day == S[0]:
        body["decisions"] = [*_hold(packet), _row("DDD.NS", "BUY", 10)]
    elif day == S[2] and "research" not in packet:
        return json.dumps({"research": [{"tool": "filings", "ticker": "AAA.NS", "months": 12}]})
    elif day == S[2]:
        body["decisions"] = [
            _row(h["ticker"], "SELL", 50) if h["ticker"] == "AAA.NS" else _row(h["ticker"])
            for h in packet["portfolio"]["holdings"]
        ]
    elif day == S[3]:
        return "I think I would rather not answer in JSON today."
    else:
        body["decisions"] = _hold(packet)
    return json.dumps(body)


def _brain(
    world: dict[str, Any], *, fail: Callable[[dict[str, Any]], None] | None = None
) -> Callable[[], manager.Brain]:
    def generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        packet = _packet_of(prompt)
        world["calls"].append(packet["as_of"])
        if fail is not None:
            fail(packet)
        return _script(packet), {"input": 10, "output": 5}

    return lambda: manager.Brain(manager.MODEL, generate)


def _register(world: dict[str, Any], run_id: str = "t") -> tuple[replay.Plan, replay.Paths]:
    plan = replay.new_plan(
        run_id,
        start=S[0],
        end=S[-1],
        recorded_by=RECORDED_BY,
        ceiling_usd=Decimal("1"),
        commit="abc",
        inputs="in",
    )
    paths = replay.paths_for(run_id)
    replay.save_plan(paths, plan, Corpus(RECORDED_BY, frozenset(), frozenset()))
    return plan, paths


def _run(
    world: dict[str, Any],
    plan: replay.Plan,
    paths: replay.Paths,
    make_brain: Callable[[], manager.Brain],
    headlines_from: date | None = None,
) -> replay.State:
    return replay.run(
        plan,
        paths,
        full=world["full"],
        now=NOW,
        make_brain=make_brain,
        trades=world["trades"],
        flows=FLOWS,
        actions=[DIVIDEND],
        off_market=[],
        cfg=Config(),
        headlines_from=headlines_from,
        log=lambda _: None,
    )


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _receipt(paths: replay.Paths, day: date) -> dict[str, Any]:
    found = [
        p
        for p in paths.store.receipts.glob(f"{day.isoformat()}-*.json")
        if ".failed-" not in p.name
    ]
    assert len(found) == 1, f"one receipt for {day}, found {found}"
    return dict(json.loads(found[0].read_text(encoding="utf-8")))


# ---- the whole sequence ------------------------------------------------------------------------


def test_the_investor_researches_decides_fills_remembers_and_says_what_did_not_happen(
    world: dict[str, Any],
) -> None:
    plan, paths = _register(world)
    state = _run(world, plan, paths, _brain(world))
    rows = {r["as_of"]: r for r in state.sessions}
    assert [r["as_of"] for r in state.sessions] == [d.isoformat() for d in S]

    # The starting book is the one that existed then: two names, no EEE bought after the start.
    assert set(state.boundary["holdings"]) == {"AAA.NS", "BBB.NS"}

    # S0 decides a BUY; nothing fills at the close it saw.
    assert rows[S[0].isoformat()]["status"] == "reviewed"
    assert rows[S[0].isoformat()]["queued"] == [
        {"ticker": "DDD.NS", "action": "BUY", "quantity": 10}
    ]
    assert rows[S[0].isoformat()]["fills"] == []

    # S1 fills it at S1's close, credits the dividend, and the review carries its earlier notes.
    fill = rows[S[1].isoformat()]["fills"][0]
    panel = world["full"].wl_prices
    assert fill["ticker"] == "DDD.NS" and fill["filled"] == 10
    assert Decimal(fill["price"]) == Decimal(
        str(float(panel.close_raw.at[pd.Timestamp(S[1]), "DDD.NS"]))
    )
    assert rows[S[1].isoformat()]["corporate_actions"], "the dividend on its ex-date"
    assert rows[S[1].isoformat()]["packet"]["memory_notes"] > 0, "it remembers S0"

    # S2: the deposit arrives before the review; the investor researches, then sells.
    assert rows[S[2].isoformat()]["flows"] == [{"on": S[2].isoformat(), "amount": "20000"}]
    assert rows[S[2].isoformat()]["packet"]["research_requests"] == 1
    research = _receipt(paths, S[2])["packet"]["research"][0]["result"]
    assert [e["id"] for e in research["events"]] == ["old:AAA"], "research sees what was public"
    assert rows[S[2].isoformat()]["queued"] == [
        {"ticker": "AAA.NS", "action": "SELL", "quantity": 50}
    ]

    # S3 fills the sale, then the reply is garbage: INCOMPLETE, never a HOLD.
    assert rows[S[3].isoformat()]["fills"][0]["action"] == "SELL"
    assert rows[S[3].isoformat()]["status"] == "incomplete"
    assert "not JSON" in rows[S[3].isoformat()]["reason"]
    # S4: a held name has no close. The review cannot happen and the value is unknown, not guessed.
    assert rows[S[4].isoformat()]["status"] == "incomplete"
    assert "no close for held BBB.NS" in rows[S[4].isoformat()]["reason"]
    assert rows[S[4].isoformat()]["value"] is None
    assert rows[S[5].isoformat()]["status"] == "reviewed"

    book = state.book.portfolio.positions()
    assert book == {"AAA.NS": Decimal(150), "BBB.NS": Decimal(100), "DDD.NS": Decimal(10)}
    assert state.book.portfolio.cash > 0
    assert state.book.net_invested == Decimal("80000")


def test_a_replayed_evening_holds_nothing_after_it(world: dict[str, Any]) -> None:
    full = world["full"]
    market = replay.world_on(full, S[2])
    assert market is not None
    assert market.adj_close.index.max().date() == S[2]
    assert market.index_close.index.max().date() == S[2]
    assert market.wl_prices is not None and market.wl_prices.volume.index.max().date() == S[2]
    # The vendor scaled AAA's adjusted history by a dividend paid later. On S2 nobody had that.
    stamp = pd.Timestamp(S[2])
    assert float(market.adj_close.at[stamp, "AAA.NS"]) == pytest.approx(
        float(market.wl_prices.close_raw.at[stamp, "AAA.NS"])
    )
    assert replay.world_on(full, S[-1] + timedelta(days=1)) is None


def test_the_packet_shows_filings_public_by_the_session_and_names_missing_headlines(
    world: dict[str, Any],
) -> None:
    plan, paths = _register(world)
    _run(world, plan, paths, _brain(world))
    early = _receipt(paths, S[0])["packet"]
    late = _receipt(paths, S[5])["packet"]
    early_ids = {e["id"] for items in early["evidence"].values() for e in items}
    late_ids = {e["id"] for items in late["evidence"].values() for e in items}
    assert early_ids == {"old:AAA"}, "published on S3, so unknowable on S0"
    assert late_ids == {"old:AAA", "mid:AAA"}
    assert "late-read:BBB" not in late_ids, "read after the corpus date: not in this corpus"
    old = next(e for e in early["evidence"]["AAA"] if e["id"] == "old:AAA")
    assert old["date"] == (S[0] - timedelta(days=90)).isoformat(), (
        "dated by publication, not reading"
    )
    assert "headlines" in early["data_gaps"] and "UNKNOWN" in early["data_gaps"]["headlines"]


def test_headlines_that_exist_are_not_called_missing(world: dict[str, Any]) -> None:
    plan, paths = _register(world)
    _run(world, plan, paths, _brain(world), headlines_from=S[0] - timedelta(days=30))
    assert "data_gaps" not in _receipt(paths, S[0])["packet"]


# ---- resuming ----------------------------------------------------------------------------------


def _outputs(paths: replay.Paths) -> dict[str, Any]:
    state = json.loads(paths.state.read_text(encoding="utf-8"))
    # A lot's id is a fresh uuid per purchase: two runs that bought the same shares on the same day
    # at the same price differ in nothing else.
    for lot in state["book"]["portfolio"]["lots"]:
        lot.pop("lot_id")
    return {
        "book": state["book"],
        "sessions": state["sessions"],
        "fills": _jsonl(paths.store.fills),
        "decisions": _jsonl(paths.store.decisions),
        "logbook": _jsonl(paths.store.logbook),
    }


def test_a_run_cut_after_a_fill_resumes_to_the_same_record_without_filling_twice(
    world: dict[str, Any],
) -> None:
    plan, whole = _register(world, "whole")
    _run(world, plan, whole, _brain(world))

    plan_cut, cut = _register(world, "cut")

    def power_cut(packet: dict[str, Any]) -> None:
        if packet["as_of"] == S[3].isoformat():  # after S3's fill of the sale, before its review
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run(world, plan_cut, cut, _brain(world, fail=power_cut))
    assert [r["as_of"] for r in _outputs(cut)["sessions"]][-1] == S[2].isoformat()
    assert sum(1 for f in _jsonl(cut.store.fills) if f["on"] == S[3].isoformat()) == 1

    _run(world, plan_cut, cut, _brain(world))
    assert _outputs(cut) == _outputs(whole)


def test_a_session_cut_after_its_decisions_is_neither_decided_nor_paid_for_twice(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, whole = _register(world, "whole")
    _run(world, plan, whole, _brain(world))
    world["calls"].clear()

    plan_cut, cut = _register(world, "cut")
    real_save = replay.save_state
    tripped: list[bool] = []

    def crash_at_s2(paths: replay.Paths, state: replay.State) -> None:
        if state.through == S[2] and not tripped:
            tripped.append(True)
            raise OSError("disk went away")  # S2 decided and recorded; its checkpoint never lands
        real_save(paths, state)

    monkeypatch.setattr(replay, "save_state", crash_at_s2)
    with pytest.raises(OSError):
        _run(world, plan_cut, cut, _brain(world))
    _run(world, plan_cut, cut, _brain(world))

    assert world["calls"].count(S[2].isoformat()) == 2, "one research round, paid once, not again"
    assert _outputs(cut) == _outputs(whole)


def test_a_spend_stop_records_nothing_and_resuming_retries_that_session(
    world: dict[str, Any],
) -> None:
    plan, paths = _register(world)

    def broke(packet: dict[str, Any]) -> None:
        if packet["as_of"] == S[1].isoformat():
            raise spend.BudgetExceededError("replay job would pass its ceiling")

    with pytest.raises(replay.ReplayStoppedError, match="ceiling"):
        _run(world, plan, paths, _brain(world, fail=broke))
    state = replay.load_state(paths, Config())
    assert state is not None and state.through == S[0], "S1 did not happen and is not recorded"

    state = _run(world, plan, paths, _brain(world))
    assert state.sessions[1]["as_of"] == S[1].isoformat()
    assert state.sessions[1]["status"] == "reviewed"


# ---- boundaries --------------------------------------------------------------------------------


def test_a_replay_refuses_the_evening_runs_records(world: dict[str, Any]) -> None:
    plan, _ = _register(world)
    live = replay.Paths(manager.STORE.root.parent)
    with pytest.raises(replay.ReplayStoppedError, match="evening run"):
        _run(world, plan, live, _brain(world))
    assert not (manager.STORE.root.parent / "state.json").exists()


def test_a_registered_run_names_the_investor_and_notices_it_change(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, paths = _register(world)
    assert replay.changed_since(plan, commit="abc", inputs="in") == []
    assert replay.changed_since(plan, commit="def", inputs="in") == ["code commit abc → def"]
    assert "prices, tradebook" in replay.changed_since(plan, commit="abc", inputs="out")[0]
    monkeypatch.setattr(manager, "PROMPT", manager.PROMPT + "\nBe bolder.")
    assert "the mandate or the prompt changed" in replay.changed_since(
        plan, commit="abc", inputs="in"
    )
    with pytest.raises(ValueError, match="never rewritten"):
        replay.save_plan(paths, plan, Corpus(RECORDED_BY, frozenset(), frozenset()))
    with pytest.raises(ValueError, match="corpus date"):
        replay.new_plan(
            "x",
            start=S[0],
            end=S[-1],
            recorded_by=S[2],
            ceiling_usd=Decimal(1),
            commit="abc",
            inputs="in",
        )


def test_the_replay_counts_filings_over_the_evening_runs_window() -> None:
    import evidence as evidence_script

    assert evidence_log.DAILY_WINDOW_DAYS == evidence_script.LOOKBACK_DAYS


def test_descriptive_figures_do_not_count_a_deposit_as_a_return(world: dict[str, Any]) -> None:
    plan, paths = _register(world)
    state = _run(world, plan, paths, _brain(world))
    figures = replay.outcome(
        state, paths.store, index_close=world["full"].index_close, ew_series=None
    )
    assert figures["value_unknown_on"] == [S[4].isoformat()]
    bench = figures["baseline_niftybees"]
    index = world["full"].index_close
    moved = float(index.loc[pd.Timestamp(S[-1])] / index.loc[pd.Timestamp(S[0])] - 1) * 100
    # The benchmark leg got ₹20,000 on S2. Unitized, its return is the index's move, nothing more.
    assert bench["return_pct"] == pytest.approx(moved, abs=0.05)
    assert "baseline_equal_weight_fund" not in figures, "no series: unavailable, not zero"
    assert Decimal(figures["costs"]) > 0


# ---- the command -------------------------------------------------------------------------------


def test_the_command_registers_runs_refuses_changes_and_reports(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import replay as replay_script

    full, trades = world["full"], world["trades"]
    monkeypatch.setattr(replay_script, "_inputs", lambda: (full, trades, FLOWS, [DIVIDEND], []))
    monkeypatch.setattr(replay_script, "_commit", lambda: ("abc", False))
    monkeypatch.setattr(replay_script.manager, "brain", lambda **kw: _brain(world)())
    monkeypatch.setattr(replay_script.twin_script, "_benchmark_series", lambda: full.index_close)
    monkeypatch.setattr(replay_script.twin_script, "_ew_fund_series", lambda: None)
    monkeypatch.setattr(replay_script, "NEWS_DIR", world["tmp"] / "news")
    monkeypatch.setattr(replay, "LIVE_RECORDS", (world["tmp"] / "live",))

    args = ["run", "c1", "--start", S[0].isoformat(), "--end", S[-1].isoformat(), "--ceiling", "1"]
    monkeypatch.setattr(replay_script, "datetime", _Clock)
    assert replay_script.main([*args, "--recorded-by", RECORDED_BY.isoformat()]) == 0
    assert replay_script.main(["run", "c1", "--ceiling", "2"]) == replay_script.ABORTED
    monkeypatch.setattr(replay_script, "_commit", lambda: ("def", False))
    assert replay_script.main(["run", "c1"]) == replay_script.ABORTED
    monkeypatch.setattr(replay_script, "_commit", lambda: ("abc", True))
    assert replay_script.main(["run", "c1"]) == replay_script.ABORTED
    monkeypatch.setattr(replay_script, "_commit", lambda: ("abc", False))
    assert replay_script.main(["run", "c1"]) == 0, "unchanged: resumes, nothing left to do"
    # A re-downloaded close for a session inside the window is a different world.
    refetched = _full()
    assert refetched.wl_prices is not None
    refetched.wl_prices.close_raw.loc[DAYS[-2], "BBB.NS"] = 101.0
    monkeypatch.setattr(
        replay_script, "_inputs", lambda: (refetched, trades, FLOWS, [DIVIDEND], [])
    )
    assert replay_script.main(["run", "c1"]) == replay_script.ABORTED

    capsys.readouterr()
    assert replay_script.main(["report", "c1"]) == 0
    text = capsys.readouterr().out
    assert "not a performance record" in text
    assert "reviewed **4**" in text and "incomplete **2**" in text
    assert "unchanged." in text


class _Clock(datetime):
    """The command's clock, fixed after the window so every replayed close is final."""

    @classmethod
    def now(cls, tz: Any = None) -> _Clock:  # type: ignore[override]
        moment = NOW if tz is None else NOW.astimezone(tz)
        return cls.fromtimestamp(moment.timestamp(), tz)
