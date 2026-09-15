"""Release checks at process boundaries: saved books, durable records and actual fill costs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from qalpha.accounting.corporate_actions import CorporateAction, CorporateActionType
from qalpha.config import Config
from qalpha.live import actions, agent, evidence_log, manager
from qalpha.live.twin import load_books, save_books
from tests.test_agent import (
    MON,
    TUE,
    WED,
    _brain,
    _customer_event,
    _evening,
    _evening_step,
    _hold_under_review,
    _intent,
    _market,
    _run,
)
from tests.test_agent import (
    world as world,
)


def _open_candidate(world: dict[str, Any]) -> None:
    manager._append(
        world["files"].scope,
        [{"as_of": (MON - timedelta(days=1)).isoformat(), "full_review": True}],
    )
    evidence_log.EVENT_LOG.write_text(
        json.dumps({**_customer_event(TUE), "_key": "DDD:1", "ticker": "DDD"}) + "\n",
        encoding="utf-8",
    )


def _pending_buy(world: dict[str, Any]) -> None:
    book = world["book"]
    book.portfolio.cash = Decimal("1000000")
    world["panel"].close_raw.loc[pd.Timestamp(WED), "DDD.NS"] = 100.0
    book.manager["pending"] = {
        "as_of": TUE.isoformat(),
        "digest": "release-buy",
        "orders": [{"ticker": "DDD.NS", "action": "BUY", "quantity": 1000}],
        "sectors": {"AAA.NS": "IT", "BBB.NS": "AUTO", "CCC.NS": "ENERGY", "DDD.NS": "FMCG"},
    }


def _fill(world: dict[str, Any]) -> list[dict[str, Any]]:
    return agent.fill_live(
        world["book"],
        _market(world["panel"], WED),
        now=_evening(WED),
        store=world["store"],
        registration=agent.REGISTRATION,
    )


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_recovered_fill_matches_the_uninterrupted_portfolio_exactly(
    world: dict[str, Any], side: str
) -> None:
    _pending_buy(world)
    if side == "SELL":
        world["book"].manager["pending"]["orders"] = [
            {"ticker": "AAA.NS", "action": "SELL", "quantity": 150}
        ]
        world["panel"].close_raw.loc[pd.Timestamp(WED), "AAA.NS"] = 1000.0
    saved = world["tmp"] / "books.json"
    save_books({"SYSTEM": world["book"]}, saved)
    _fill(world)
    expected = world["book"].portfolio.to_state()
    recorded = world["store"].fills.read_bytes()

    # The fill log survived, but the process died before save_books.
    world["book"] = load_books(Config(), saved)["SYSTEM"]
    _fill(world)
    assert world["book"].portfolio.to_state() == expected
    assert world["store"].fills.read_bytes() == recorded


def test_fill_month_allowance_includes_charges(world: dict[str, Any]) -> None:
    _pending_buy(world)
    _fill(world)
    spent = agent.purchases_by_month(world["store"])[WED.isoformat()[:7]]
    assert Decimal("49000") < spent <= agent.REGISTRATION.live_sizing.monthly_allowance


@pytest.mark.parametrize("volume", [0.0, float("nan")])
def test_no_fill_on_a_session_without_traded_volume(world: dict[str, Any], volume: float) -> None:
    _pending_buy(world)
    world["panel"].volume.loc[pd.Timestamp(WED), "DDD.NS"] = volume
    before = world["book"].portfolio.to_state()
    assert _fill(world) == []
    assert world["book"].portfolio.to_state() == before
    assert world["book"].manager["pending"] is not None


def test_daily_caller_recovers_queued_orders_from_the_saved_book(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _open_candidate(world)
    caller = _evening_step(world, monkeypatch, start=TUE)
    saved = world["tmp"] / "books.json"
    save_books({"SYSTEM": world["book"]}, saved)
    market = _market(world["panel"], TUE)
    assert (
        caller.step_system(world["book"], market, now=_evening(TUE), store=world["store"]) is None
    )
    expected = json.loads(json.dumps(world["book"].manager))
    calls = len(world["calls"])
    world["book"] = load_books(Config(), saved)["SYSTEM"]
    assert (
        caller.step_system(world["book"], market, now=_evening(TUE), store=world["store"]) is None
    )
    assert world["book"].manager == expected
    assert world["book"].stepped_through == TUE
    assert len(world["calls"]) == calls


@pytest.mark.parametrize("destination", ["logbook", "intentions", "scope"])
def test_partial_review_records_are_completed_on_retry(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    _open_candidate(world)
    owner = world["store"] if destination == "logbook" else world["files"]
    target = getattr(owner, destination)
    append = manager._append

    def interrupted(path: Any, rows: Any) -> None:
        if path == target:
            raise OSError("simulated process interruption")
        append(path, rows)

    brain = _brain(world, lambda p: [_intent("DDD.NS", "open", share=4.0, cites=["DDD:1"])])
    with monkeypatch.context() as patch:
        patch.setattr(manager, "_append", interrupted)
        with pytest.raises(OSError, match="simulated process interruption"):
            _run(world, TUE, brain)
    calls = len(world["calls"])
    _run(world, TUE, brain)
    for path in (
        world["store"].decisions,
        world["store"].logbook,
        world["files"].intentions,
        world["files"].scope,
    ):
        rows = [r for r in manager._jsonl(path) if r.get("as_of") == TUE.isoformat()]
        assert rows, f"retry lost {path.name}"
    assert len(world["calls"]) == calls


@pytest.mark.parametrize("flag", ["refused", "truncated"])
def test_cached_failed_reply_cannot_become_a_success(world: dict[str, Any], flag: str) -> None:
    def generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        return '{"portfolio_note":"partial","intentions":[]}', {flag: 1}

    for _ in range(2):
        with pytest.raises(agent.IncompleteReviewError):
            agent._call(
                world["files"],
                TUE,
                "review",
                agent.REGISTRATION.decider,
                "test packet",
                lambda model: manager.Brain(model, generate),
                {},
            )


def test_shadow_holdings_can_diverge_without_aborting_the_investor(world: dict[str, Any]) -> None:
    _open_candidate(world)
    shadow = agent.load_shadow(
        world["files"], world["book"], on=TUE, registration=agent.REGISTRATION
    )
    shadow.portfolio.buy(MON, "DDD.NS", Decimal("250"), Decimal("100"))
    agent.save_shadow(world["files"], shadow)
    _run(
        world, TUE, _brain(world, lambda p: [_intent("DDD.NS", "open", share=4.0, cites=["DDD:1"])])
    )
    assert world["book"].manager["pending"]["orders"]


def test_shadow_receives_a_later_deposit_once(world: dict[str, Any]) -> None:
    from qalpha.live.flows import Flow

    book = world["book"]
    shadow = agent.load_shadow(world["files"], book, on=TUE, registration=agent.REGISTRATION)
    agent.save_shadow(world["files"], shadow)
    original = shadow.portfolio.cash
    book.flows.append(Flow(on=WED, amount=Decimal("50000")))
    book.portfolio.cash += Decimal("50000")
    shadow = agent.load_shadow(world["files"], book, on=WED, registration=agent.REGISTRATION)
    assert shadow.portfolio.cash == original + Decimal("50000")
    agent.save_shadow(world["files"], shadow)
    again = agent.load_shadow(world["files"], book, on=WED, registration=agent.REGISTRATION)
    assert again.portfolio.cash == shadow.portfolio.cash


@pytest.mark.parametrize("volume", [0.0, float("nan"), 100000.0])
def test_shadow_fill_checks_volume_and_all_in_monthly_spend(
    world: dict[str, Any], volume: float
) -> None:
    _pending_buy(world)
    shadow = agent.load_shadow(
        world["files"], world["book"], on=TUE, registration=agent.REGISTRATION
    )
    shadow.pending = [world["book"].manager["pending"]]
    world["panel"].volume.loc[pd.Timestamp(WED), "DDD.NS"] = volume
    fills = agent.fill_shadow(shadow, _market(world["panel"], WED), now=_evening(WED))
    if volume == 100000.0:
        assert fills and Decimal("49000") < shadow.purchases[WED.isoformat()[:7]] <= Decimal(
            "50000"
        )
    else:
        assert not fills and shadow.pending


def test_fill_recovery_preserves_a_later_deposit(world: dict[str, Any]) -> None:
    _pending_buy(world)
    saved = world["tmp"] / "books.json"
    save_books({"SYSTEM": world["book"]}, saved)
    _fill(world)
    expected = world["book"].portfolio.to_state()
    world["book"] = load_books(Config(), saved)["SYSTEM"]
    world["book"].portfolio.cash += Decimal("50000")
    _fill(world)
    expected["cash"] = str(Decimal(str(expected["cash"])) + Decimal("50000"))
    assert world["book"].portfolio.to_state() == expected


def test_recovery_replays_every_queued_evening_after_repeated_save_failures(
    world: dict[str, Any],
) -> None:
    _pending_buy(world)
    book = world["book"]
    pending = book.manager.pop("pending")
    saved = world["tmp"] / "books.json"
    save_books({"SYSTEM": book}, saved)
    pending["as_of"] = MON.isoformat()
    book.manager["pending"] = pending
    agent._mark(world["files"], MON, "queued", manager=book.manager)
    agent.fill_live(
        book,
        _market(world["panel"], TUE),
        now=_evening(TUE),
        store=world["store"],
        registration=agent.REGISTRATION,
    )
    book.manager["pending"] = {
        **pending,
        "as_of": TUE.isoformat(),
        "digest": "second-evening",
        "orders": [{"ticker": "AAA.NS", "action": "SELL", "quantity": 150}],
    }
    agent._mark(world["files"], TUE, "queued", manager=book.manager)
    _fill(world)
    agent._mark(world["files"], WED, "queued", manager=book.manager)
    expected = book.portfolio.to_state()
    recorded = world["store"].fills.read_bytes()
    world["book"] = load_books(Config(), saved)["SYSTEM"]
    _run(world, WED, _brain(world, _hold_under_review))
    assert world["book"].portfolio.to_state() == expected
    assert world["store"].fills.read_bytes() == recorded
    assert not world["calls"]


def _dividend(ticker: str, on: Any, amount: str) -> actions.Record:
    value = Decimal(amount)
    return actions.Record(
        actions=(
            actions.Recorded(
                CorporateAction(
                    ticker=ticker,
                    ex_date=on,
                    action_type=CorporateActionType.DIVIDEND,
                    amount_per_share=value,
                ),
                implied=value,
                note="test record reconciles",
            ),
        ),
        source="test",
        fetched_at=_evening(on).isoformat(),
    )


def test_catch_up_credits_a_dividend_after_the_pending_purchase(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _pending_buy(world)
    book = world["book"]
    book.actions_through = MON
    book.manager["pending"]["as_of"] = MON.isoformat()
    world["panel"].close_raw.loc[pd.Timestamp(TUE), "DDD.NS"] = 100.0
    monkeypatch.setattr(actions, "load", lambda: _dividend("DDD.NS", WED, "1"))
    cash = book.portfolio.cash
    _run(world, WED, _brain(world, _hold_under_review))
    purchases = agent.purchases_by_month(world["store"])[WED.isoformat()[:7]]
    quantity = book.portfolio.positions()["DDD.NS"]
    assert quantity > 0
    assert book.portfolio.cash == cash - purchases + quantity
    assert book.actions_through == WED


def test_shadow_receives_dividends_once_through_the_evening_runner(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    book = world["book"]
    book.actions_through = MON
    shadow = agent.load_shadow(world["files"], book, on=MON, registration=agent.REGISTRATION)
    agent.save_shadow(world["files"], shadow)
    cash = shadow.portfolio.cash
    quantity = shadow.portfolio.positions()["AAA.NS"]
    monkeypatch.setattr(actions, "load", lambda: _dividend("AAA.NS", TUE, "2"))
    brain = _brain(world, _hold_under_review)
    for _ in range(2):
        _run(world, TUE, brain)
        shadow = agent.load_shadow(world["files"], book, on=TUE, registration=agent.REGISTRATION)
        assert shadow.portfolio.cash == cash + quantity * 2
        assert shadow.actions_through == TUE


def test_action_import_includes_ai_holdings_and_keeps_previously_recorded_actions(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import corporate_actions as command

    from qalpha.live.flows import Flow

    monkeypatch.setattr(command.twin_script, "_tradebook", lambda: ([], []))
    world["book"].flows = [Flow(on=MON, amount=Decimal("500000"))]
    monkeypatch.setattr(command, "load_books", lambda cfg: {"REAL": world["book"]})
    monkeypatch.setattr(manager, "STORE", world["store"])
    monkeypatch.setattr(agent, "FILES", world["files"])
    shadow = agent.load_shadow(
        world["files"], world["book"], on=MON, registration=agent.REGISTRATION
    )
    shadow.portfolio.buy(MON, "DDD.NS", Decimal("1"), Decimal("100"))
    agent.save_shadow(world["files"], shadow)
    _, names = command._trades_and_names(Config())
    assert set(names) == {"AAA.NS", "BBB.NS", "CCC.NS", "DDD.NS"}
    record = _dividend("AAA.NS", TUE, "2")
    monkeypatch.setattr(actions, "load", lambda: record)
    saved: list[actions.Record] = []
    monkeypatch.setattr(actions, "save", saved.append)
    monkeypatch.setattr(command, "_fetch", lambda names, since: [])
    monkeypatch.setattr(command.pd, "read_parquet", lambda path: pd.DataFrame())
    assert command.main(["--import"]) == 0
    assert saved[0].actions == record.actions
    # The read-only display used to reference the import-only local variable.
    assert command.main([]) == 0


def test_launch_shadow_review_does_not_credit_inherited_dividends_again(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent as command

    class Evening(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return _evening(TUE)

    monkeypatch.setattr(command, "datetime", Evening)
    book = world["book"]
    book.actions_through = MON
    monkeypatch.setattr(actions, "load", lambda: _dividend("AAA.NS", MON, "2"))
    monkeypatch.setattr(command, "_system", lambda: (book, _market(world["panel"], TUE)))
    monkeypatch.setattr(agent, "AGENT_DIR", world["tmp"] / "launch")
    monkeypatch.setattr(manager, "STORE", world["store"])
    review = agent.review
    captured: list[Decimal] = []

    def real_review(copy: Any, market: Any, **kwargs: Any) -> Any:
        decisions = review(
            copy,
            market,
            **kwargs,
            make_brain=_brain(world, _hold_under_review),
            graph_log=world["log"],
        )
        captured.append(copy.portfolio.cash)
        return decisions

    monkeypatch.setattr(agent, "review", real_review)
    before = book.portfolio.to_state()
    assert command.main(["shadow-review"]) == 0
    assert captured == [book.portfolio.cash]
    assert book.portfolio.to_state() == before
