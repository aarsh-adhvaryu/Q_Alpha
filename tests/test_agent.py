"""AI-PM-3 through its real entry points, with a book that has holdings and cash, and a fake model.

The acceptance test the plan registered: two holdings in different sectors each supply the same
customer (a DISCLOSED connection read from their filings); the customer cuts spending (a new verified
event). The evening must find both suppliers through the graph, carry the quotes, take the size of the
exposure from the disclosed revenue share or record it MISSING, put both holdings under review, place
the chain in the packet, and record decisions that cite it.

Also: a holding with no trigger is not reviewed and gets no fresh HOLD; an unconfirmed exit is held;
an interruption at any step resumes without a second model call, a second queue or a second record;
the shadow book sizes the same intentions under the expanding rules.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from qalpha.accounting.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.live import agent, evidence_log, graph_ingest, manager, relations
from qalpha.live import attention as att
from qalpha.live import financials as company_facts
from qalpha.live import graph as g
from qalpha.live.extraction import EXTRACTION_VERSION, corpus_reader
from qalpha.live.market import Market
from qalpha.live.progress import IST
from qalpha.live.twin import TwinBook

HELD = ["AAA.NS", "BBB.NS", "CCC.NS"]
CANDIDATES = ["DDD.NS", "EEE.NS"]
CUSTOMER = "ZZZ.NS"
SECTORS = {
    "AAA.NS": "IT",
    "BBB.NS": "AUTO",
    "CCC.NS": "ENERGY",
    "DDD.NS": "FMCG",
    "EEE.NS": "POWER",
    CUSTOMER: "AUTO",
}
DAYS = pd.bdate_range(end="2026-09-16", periods=300)  # ends Wednesday
MON, TUE, WED = DAYS[-3].date(), DAYS[-2].date(), DAYS[-1].date()


def _evening(day: date) -> datetime:
    return datetime.combine(day, time(19, 0), IST)


def _panel() -> PriceData:
    rng = np.random.default_rng(11)
    names = [*HELD, *CANDIDATES, CUSTOMER]
    adj = {}
    for i, t in enumerate(names):
        path = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(DAYS))))
        if t in CANDIDATES:
            path[-60:] *= np.linspace(1.0, 0.7, 60)
        adj[t] = path * (1 + i / 10)
    frame = pd.DataFrame(adj, index=DAYS)
    for day in DAYS[-3:]:  # calm last sessions: no price trigger unless a test adds one
        frame.loc[day, :] = frame.loc[DAYS[-4], :]
    return PriceData(frame, frame.copy(), pd.DataFrame(100_000.0, index=DAYS, columns=names))


def _market(panel: PriceData, as_of: date) -> Market:
    upto = panel.adj_close.loc[: pd.Timestamp(as_of)]
    return Market(
        as_of=as_of,
        prices={t: Decimal(str(round(float(upto[t].iloc[-1]), 2))) for t in upto.columns},
        index_close=panel.adj_close[CUSTOMER],
        adj_close=panel.adj_close,
        rebase_from={},
        exclude=set(),
        watchlist=[*HELD, *CANDIDATES],
        sector_of=SECTORS,
        wl_prices=panel,
    )


def _book(panel: PriceData) -> TwinBook:
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("1000000"))
    bought = DAYS[-200].date()
    for t in HELD:
        pf.buy(
            bought,
            t,
            Decimal("150"),
            Decimal(str(round(float(panel.close_raw.at[pd.Timestamp(bought), t]), 2))),
        )
    pf.cash = Decimal("120000")
    return TwinBook(name="SYSTEM", portfolio=pf)


def _customer_event(day: date) -> dict[str, Any]:
    return {
        "_key": "cust:ZZZ:guidance_change:1",
        "ticker": "ZZZ",
        "as_of": day.isoformat(),
        "disseminated_at": f"{day.isoformat()}T09:00:00Z",
        "event_date": day.isoformat(),
        "event_type": "guidance_change",
        "materiality": "high",
        "summary": "cuts capital spending by 40%",
        "passage": "we will reduce capital expenditure by 40% this year",
        "doc_sha256": "e" * 64,
        "verified": True,
        "model": corpus_reader(),
        "extraction_version": EXTRACTION_VERSION,
    }


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    coverage = tmp_path / "coverage.jsonl"
    coverage.write_text(
        "".join(
            json.dumps(
                {
                    "_key": f"{d}:{t}",
                    "as_of": d.isoformat(),
                    "ticker": t.removesuffix(".NS"),
                    "complete": True,
                    "extraction_version": EXTRACTION_VERSION,
                    "reader": corpus_reader(),
                }
            )
            + "\n"
            for d in (MON, TUE, WED)
            for t in [*HELD, *CANDIDATES]
        ),
        encoding="utf-8",
    )
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    monkeypatch.setattr(evidence_log, "COVERAGE_LOG", coverage)
    monkeypatch.setattr(evidence_log, "EVENT_LOG", events)
    monkeypatch.setattr(evidence_log, "NEWS_EVENT_LOG", tmp_path / "news.jsonl")
    monkeypatch.setattr(company_facts, "FACTS_PATH", tmp_path / "financials.jsonl")
    monkeypatch.setattr("qalpha.live.evidence.load_archive", lambda day: ({}, None))
    panel = _panel()
    return {
        "panel": panel,
        "book": _book(panel),
        "store": manager.Store(tmp_path / "manager"),
        "files": agent.Files(tmp_path / "agent"),
        "log": g.GraphLog(tmp_path / "graph.jsonl"),
        "tmp": tmp_path,
        "calls": [],
    }


def _packet_of(prompt: str) -> dict[str, Any]:
    return dict(json.loads(prompt.split("PACKET:\n", 1)[1]))


def _intent(
    ticker: str,
    intent: str = "hold",
    *,
    share: float | None = None,
    cites: list[str] | None = None,
    **over: Any,
) -> dict[str, Any]:
    row = {
        "ticker": ticker,
        "intent": intent,
        "conviction": "standard",
        "desired_exposure_pct": share,
        "reason": "r",
        "thesis": "t",
        "invalidate_if": "i",
        "invalidate_drawdown_pct": None,
        "evidence_ids": cites or [f"price:{ticker}"],
        "note": f"note on {ticker}",
    }
    row.update(over)
    return row


def _brain(
    world: dict[str, Any],
    decide: Callable[[dict[str, Any]], list[dict[str, Any]]],
    confirm: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> agent.BrainFactory:
    def generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        world["calls"].append((model, prompt[:40]))
        if prompt.startswith(agent.CONFIRM_PROMPT):
            proposal = json.loads(prompt[len(agent.CONFIRM_PROMPT) :].split("\n\nPACKET:\n", 1)[0])
            body = {
                "confirmations": (
                    confirm or (lambda p: [{**x, "confirm": True, "reason": "ok"} for x in p])
                )(proposal)
            }
            return json.dumps(body), {"input": 1, "output": 1}
        return json.dumps({"portfolio_note": "steady", "intentions": decide(_packet_of(prompt))}), {
            "input": 1,
            "output": 1,
        }

    return lambda model: manager.Brain(model, generate)


def _hold_under_review(packet: dict[str, Any]) -> list[dict[str, Any]]:
    held = {h["ticker"] for h in packet["portfolio"]["holdings"]}
    return [_intent(t) for t in packet["under_review"] if t in held]


def _run(world: dict[str, Any], day: date, make_brain: agent.BrainFactory, **kw: Any) -> list[Any]:
    return agent.review(
        world["book"],
        _market(world["panel"], day),
        now=_evening(day),
        make_brain=make_brain,
        store=world["store"],
        files=world["files"],
        graph_log=world["log"],
        **kw,
    )


# ---- the acceptance test -----------------------------------------------------------------------


def _supply_chain_in_the_graph(world: dict[str, Any]) -> None:
    """Real ingestion: watchlist companies, two suppliers' own filings read for connections, the customer's event."""
    log: g.GraphLog = world["log"]
    watchlist = world["tmp"] / "watchlist.csv"
    watchlist.write_text(
        "ticker,sector\n" + "".join(f"{t},{s}\n" for t, s in SECTORS.items()), encoding="utf-8"
    )
    known = datetime.combine(MON, time(10), UTC) - timedelta(days=3)
    graph_ingest.companies(log, watchlist, now=known, counts=graph_ingest.Counts())
    resolver = relations.Resolver({CUSTOMER: ("Zeta Motors",)})
    filings = {
        "AAA": ("a" * 64, "Zeta Motors contributed 25% of our revenue in the year.", "pct=25"),
        "BBB": (
            "b" * 64,
            "We supply brake assemblies to Zeta Motors under a long-term contract.",
            "pct=-",
        ),
    }
    for filer, (sha, text, pct) in filings.items():
        reply = f'RELATION: from=SELF; type=SUPPLIER_TO; to=Zeta Motors; {pct}; amount_inr=-; since=-; passage="{text}"'
        result = relations.parse(
            reply,
            text=text,
            filer=filer,
            doc_sha256=sha,
            doc_url="u",
            known_from=known,
            resolver=resolver,
            reader="qwen3.5-9b-16k",
        )
        assert not result.dropped
        for a in result.assertions:
            log.add(a)
    graph_ingest.filing_events(
        log,
        [_customer_event(MON)],
        archive=graph_ingest.ArchiveText(world["tmp"]),
        counts=graph_ingest.Counts(),
    )
    log.flush()


def test_a_customer_in_trouble_reaches_both_suppliers_with_quotes_and_decisions_cite_the_chain(
    world: dict[str, Any],
) -> None:
    _supply_chain_in_the_graph(world)
    seen: dict[str, Any] = {}

    def decide(packet: dict[str, Any]) -> list[dict[str, Any]]:
        seen["packet"] = packet
        rows = []
        for t in packet["under_review"]:
            if t not in {h["ticker"] for h in packet["portfolio"]["holdings"]}:
                continue
            chain = [c for c in packet["attention"]["by_name"].get(t, []) if c["kind"] == "chain"]
            rows.append(_intent(t, cites=[chain[0]["cites"][0]] if chain else None))
        return rows

    _run(world, MON, _brain(world, decide))
    packet = seen["packet"]
    chains = {
        t: [c for c in packet["attention"]["by_name"].get(t, []) if c["kind"] == "chain"]
        for t in ("AAA.NS", "BBB.NS")
    }
    assert all(chains.values()), "both suppliers must be found through the graph"
    assert "CCC.NS" not in {
        t
        for t, cs in packet["attention"]["by_name"].items()
        if any(c["kind"] == "chain" for c in cs)
    }
    aaa, bbb = chains["AAA.NS"][0], chains["BBB.NS"][0]
    assert aaa["context"]["materiality"] == {
        "revenue_share_pct": 25.0,
        "basis": "DISCLOSED on the supply connection",
    }
    assert (
        bbb["context"]["materiality"]["status"] == g.MISSING
        and bbb["context"]["materiality"]["revenue_share_pct"] is None
    )
    assert (
        aaa["context"]["path"][0]["passage"]
        == "Zeta Motors contributed 25% of our revenue in the year."
    )
    assert (
        aaa["context"]["path"][1]["passage"]
        == "we will reduce capital expenditure by 40% this year"
    )
    assert {"AAA.NS", "BBB.NS"} <= set(packet["under_review"])

    recorded = {
        r["ticker"]: r
        for r in manager._jsonl(world["store"].decisions)
        if r["version"] == agent.VERSION
    }
    for t, chain in chains.items():
        assert chain[0]["cites"][0] in recorded[t]["evidence_ids"]
        assert any(tr["kind"] == "chain" for tr in recorded[t]["triggers"])


# ---- review scope ------------------------------------------------------------------------------


def test_a_holding_with_no_trigger_is_not_reviewed_and_gets_no_fresh_hold(
    world: dict[str, Any],
) -> None:
    files: agent.Files = world["files"]
    manager._append(
        files.scope, [{"as_of": (MON - timedelta(days=1)).isoformat(), "full_review": True}]
    )
    events = evidence_log.EVENT_LOG
    events.write_text(
        json.dumps(
            {
                **_customer_event(TUE),
                "_key": "aaa:1",
                "ticker": "AAA",
                "summary": "auditor resigned",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    decisions = _run(world, TUE, _brain(world, _hold_under_review))
    assert world["calls"], "a triggered name must be reviewed"
    scope = manager._jsonl(files.scope)[-1]
    assert scope["reviewed"] == ["AAA.NS"] and scope["full_review"] is False
    assert scope["not_reviewed"] == {
        "BBB.NS": "not reviewed tonight: no trigger",
        "CCC.NS": "not reviewed tonight: no trigger",
    }
    recorded = [
        r for r in manager._jsonl(world["store"].decisions) if r["version"] == agent.VERSION
    ]
    assert [r["ticker"] for r in recorded] == ["AAA.NS"]
    by = {d.ticker: d for d in decisions}
    assert (
        by["BBB.NS"].action == "NOT_REVIEWED"
        and by["BBB.NS"].reason == "not reviewed tonight: no trigger"
    )


def test_a_quiet_evening_calls_no_model_at_all(world: dict[str, Any]) -> None:
    manager._append(
        world["files"].scope,
        [{"as_of": (MON - timedelta(days=1)).isoformat(), "full_review": True}],
    )
    decisions = _run(world, TUE, _brain(world, _hold_under_review))
    assert world["calls"] == []
    assert {d.action for d in decisions} == {"NOT_REVIEWED"}


# ---- tiers -------------------------------------------------------------------------------------


def test_an_unconfirmed_exit_is_held_and_a_confirmed_open_is_sized_for_both_books(
    world: dict[str, Any],
) -> None:
    manager._append(
        world["files"].scope,
        [{"as_of": (MON - timedelta(days=1)).isoformat(), "full_review": True}],
    )
    evidence_log.EVENT_LOG.write_text(
        "".join(
            json.dumps(
                {
                    **_customer_event(TUE),
                    "_key": f"{t}:1",
                    "ticker": t.removesuffix(".NS"),
                    "summary": "news",
                }
            )
            + "\n"
            for t in ("AAA.NS", "DDD.NS")
        ),
        encoding="utf-8",
    )
    registration = replace(agent.REGISTRATION, decider="cheap-local")

    def decide(packet: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            _intent("AAA.NS", "exit", cites=["AAA.NS:1"], reason="the thesis is broken"),
            _intent("DDD.NS", "open", share=5.0, cites=["DDD.NS:1"], conviction="starter"),
        ]

    def confirm(proposal: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                **p,
                "confirm": p["intent"] == "open",
                "reason": "evidence is thin" if p["intent"] == "exit" else "supported",
            }
            for p in proposal
        ]

    _run(world, TUE, _brain(world, decide, confirm), registration=registration)
    models = [m for m, _ in world["calls"]]
    assert models == ["cheap-local", "claude-sonnet-5"]
    book = world["book"]
    orders = {o["ticker"]: o for o in book.manager["pending"]["orders"]}
    assert "AAA.NS" not in orders and orders["DDD.NS"]["action"] == "BUY"
    rows = {
        r["ticker"]: r
        for r in manager._jsonl(world["store"].decisions)
        if r["version"] == agent.VERSION
    }
    assert rows["AAA.NS"]["confirmation"].startswith("NOT confirmed: evidence is thin")
    shadow = json.loads(world["files"].shadow.read_text(encoding="utf-8"))
    shadow_orders = {o["ticker"]: o for p in shadow["pending"] for o in p["orders"]}
    assert shadow_orders["DDD.NS"]["action"] == "BUY"
    # the shadow's starter opens at the ₹15,000 minimum; the live book aims at the stated 5% (capped by allowance)
    assert Decimal(shadow_orders["DDD.NS"]["quantity"]) * Decimal(
        shadow_orders["DDD.NS"]["price"]
    ) >= Decimal("15000")


def test_citing_another_companys_evidence_makes_the_review_incomplete(
    world: dict[str, Any],
) -> None:
    def decide(packet: dict[str, Any]) -> list[dict[str, Any]]:
        rows = _hold_under_review(packet)
        rows[0]["evidence_ids"] = [
            "price:CCC.NS" if rows[0]["ticker"] != "CCC.NS" else "price:AAA.NS"
        ]
        return rows

    with pytest.raises(manager.IncompleteReviewError, match="not an id for"):
        _run(world, MON, _brain(world, decide))
    assert manager._jsonl(world["store"].decisions) == []


# ---- resumability ------------------------------------------------------------------------------


def test_an_interruption_at_confirmation_resumes_without_a_second_review_call_or_a_second_queue(
    world: dict[str, Any],
) -> None:
    manager._append(
        world["files"].scope,
        [{"as_of": (MON - timedelta(days=1)).isoformat(), "full_review": True}],
    )
    evidence_log.EVENT_LOG.write_text(
        json.dumps(
            {**_customer_event(TUE), "_key": "DDD:1", "ticker": "DDD", "summary": "order win"}
        )
        + "\n",
        encoding="utf-8",
    )
    registration = replace(agent.REGISTRATION, decider="cheap-local")
    decide = lambda p: [_intent("DDD.NS", "open", share=4.0, cites=["DDD:1"])]  # noqa: E731
    base = _brain(world, decide)

    def dies_at_confirmation(model: str) -> manager.Brain:
        if model == registration.confirmer:

            def boom(m: str, prompt: str) -> tuple[str, dict[str, int]]:
                from qalpha.live.spend import BudgetExceededError

                raise BudgetExceededError("the laptop lid closed")

            return manager.Brain(model, boom)
        return base(model)

    with pytest.raises(manager.IncompleteReviewError, match="not run"):
        _run(world, TUE, dies_at_confirmation, registration=registration)
    assert [m for m, _ in world["calls"]] == ["cheap-local"]
    _run(world, TUE, base, registration=registration)
    assert [m for m, _ in world["calls"]] == ["cheap-local", "claude-sonnet-5"], (
        "the review was answered; only confirmation runs again"
    )
    assert _run(world, TUE, base, registration=registration) == []
    rows = [r for r in manager._jsonl(world["store"].decisions) if r["version"] == agent.VERSION]
    assert len(rows) == 1 and len(world["book"].manager["pending"]["orders"]) == 1
    shadow = json.loads(world["files"].shadow.read_text(encoding="utf-8"))
    assert len(shadow["pending"]) == 1


def test_orders_fill_at_the_next_session_in_both_books(world: dict[str, Any]) -> None:
    manager._append(
        world["files"].scope,
        [{"as_of": (MON - timedelta(days=1)).isoformat(), "full_review": True}],
    )
    evidence_log.EVENT_LOG.write_text(
        json.dumps(
            {**_customer_event(TUE), "_key": "DDD:1", "ticker": "DDD", "summary": "order win"}
        )
        + "\n",
        encoding="utf-8",
    )
    _run(
        world, TUE, _brain(world, lambda p: [_intent("DDD.NS", "open", share=4.0, cites=["DDD:1"])])
    )
    before = world["book"].portfolio.positions().get("DDD.NS", Decimal("0"))
    agent.fill_live(
        world["book"],
        _market(world["panel"], WED),
        now=_evening(WED),
        store=world["store"],
        registration=agent.REGISTRATION,
    )
    shadow = agent.load_shadow(
        world["files"], world["book"], on=WED, registration=agent.REGISTRATION
    )
    agent.fill_shadow(shadow, _market(world["panel"], WED), now=_evening(WED))
    assert world["book"].portfolio.positions()["DDD.NS"] > before
    assert shadow.portfolio.positions()["DDD.NS"] > 0 and shadow.purchases


# ---- attention units ---------------------------------------------------------------------------


def test_a_drift_above_the_review_limit_is_flagged_and_the_address_limit_is_named() -> None:
    a = att.Attention(as_of=TUE)
    must = att.concentration_triggers(
        a,
        {"AAA.NS": Decimal("310"), "BBB.NS": Decimal("90")},
        Decimal("600"),
        SECTORS,
        agent.CURRENT_SIZING,
    )
    assert must == ["AAA.NS"] and a.by_name["AAA.NS"][0].kind == att.CONCENTRATION


def test_a_full_review_happens_on_friday_after_seven_days_and_on_a_portfolio_trigger() -> None:
    friday = date(2026, 9, 18)
    for as_of, last, portfolio, expected in [
        (friday, friday - timedelta(days=1), [], True),
        (date(2026, 9, 16), date(2026, 9, 9), [], True),
        (date(2026, 9, 16), date(2026, 9, 14), [], False),
        (date(2026, 9, 16), date(2026, 9, 14), [att.Trigger(att.FEED, "evidence failed")], True),
    ]:
        a = att.Attention(as_of=as_of, portfolio=list(portfolio))
        att.decide_full_review(a, last_full=last)
        assert a.full_review is expected


def test_idle_cash_needs_every_recent_month_above_the_limit_and_a_candidate() -> None:
    rules = agent.CURRENT_SIZING
    shares = {"2026-08": Decimal("0.40"), "2026-09": Decimal("0.35")}
    a = att.Attention(as_of=TUE)
    att.idle_cash_trigger(a, cash_share_by_month=shares, rules=rules, candidates_exist=True)
    assert [t.kind for t in a.portfolio] == [att.IDLE]
    b = att.Attention(as_of=TUE)
    att.idle_cash_trigger(
        b,
        cash_share_by_month={**shares, "2026-09": Decimal("0.10")},
        rules=rules,
        candidates_exist=True,
    )
    assert b.portfolio == []


def test_failed_steps_are_read_from_tonights_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rows = [
        {"task": "evidence", "state": "failed", "at": "2026-09-15T13:00:00+00:00"},
        {"task": "news", "state": "failed", "at": "2026-09-15T13:00:00+00:00"},
        {"task": "news", "state": "done", "at": "2026-09-15T13:30:00+00:00"},
        {"task": "financials", "state": "failed", "at": "2026-09-14T13:00:00+00:00"},
    ]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert agent.failed_steps_today(date(2026, 9, 15), ledger) == ["evidence"]


def test_ai_pm3_is_not_active_until_a_start_date_is_registered() -> None:
    assert agent.REGISTRATION.start is None and not agent.active(date(2030, 1, 1))
    assert agent.active(date(2026, 10, 1), replace(agent.REGISTRATION, start=date(2026, 10, 1)))


# ---- the evening run's caller ------------------------------------------------------------------


def _evening_step(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, start: date) -> Any:
    """``scripts/twin.py``'s step, with AI-PM-3 registered to start on ``start`` and its records in tmp."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import twin as twin_script

    real = agent.review
    brain = _brain(world, lambda p: [_intent("DDD.NS", "open", share=4.0, cites=["DDD:1"])])
    monkeypatch.setattr(
        agent,
        "review",
        lambda *a, **k: real(
            *a, **{**k, "files": world["files"], "graph_log": world["log"], "make_brain": brain}
        ),
    )
    monkeypatch.setattr(agent, "failed_steps_today", lambda today: [])
    monkeypatch.setattr(agent, "REGISTRATION", replace(agent.REGISTRATION, start=start))
    return twin_script


def test_the_evening_run_is_ai_pm3_from_its_start_and_nothing_before_it(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 4: the scheduled caller, with holdings and cash. AI-PM-3 is the only investor."""
    manager._append(
        world["files"].scope,
        [{"as_of": (MON - timedelta(days=1)).isoformat(), "full_review": True}],
    )
    evidence_log.EVENT_LOG.write_text(
        json.dumps(
            {**_customer_event(MON), "_key": "DDD:1", "ticker": "DDD", "summary": "order win"}
        )
        + "\n",
        encoding="utf-8",
    )
    twin_script = _evening_step(world, monkeypatch, start=TUE)
    book, store = world["book"], world["store"]
    before = book.portfolio.positions()

    assert (
        twin_script.step_system(book, _market(world["panel"], MON), now=_evening(MON), store=store)
        is None
    )
    assert world["calls"] == [] and book.portfolio.positions() == before, (
        "before its start: nothing"
    )

    assert (
        twin_script.step_system(book, _market(world["panel"], TUE), now=_evening(TUE), store=store)
        is None
    )
    assert world["calls"] and book.manager["pending"]["orders"][0]["ticker"] == "DDD.NS"
    assert book.portfolio.positions() == before, "never filled at the close it decided on"

    twin_script.step_system(book, _market(world["panel"], WED), now=_evening(WED), store=store)
    assert book.portfolio.positions()["DDD.NS"] > 0, "the next evening fills first"


def test_a_fill_cut_before_the_book_is_saved_is_not_written_twice(world: dict[str, Any]) -> None:
    manager._append(
        world["files"].scope,
        [{"as_of": (MON - timedelta(days=1)).isoformat(), "full_review": True}],
    )
    evidence_log.EVENT_LOG.write_text(
        json.dumps(
            {**_customer_event(TUE), "_key": "DDD:1", "ticker": "DDD", "summary": "order win"}
        )
        + "\n",
        encoding="utf-8",
    )
    _run(
        world, TUE, _brain(world, lambda p: [_intent("DDD.NS", "open", share=4.0, cites=["DDD:1"])])
    )
    saved = world["book"].portfolio.clone(), dict(world["book"].manager)
    for _ in range(2):  # the second pass is the retry from the book as it was saved
        world["book"].portfolio, world["book"].manager = (
            saved[0].clone(),
            json.loads(json.dumps(saved[1])),
        )
        agent.fill_live(
            world["book"],
            _market(world["panel"], WED),
            now=_evening(WED),
            store=world["store"],
            registration=agent.REGISTRATION,
        )
    fills = [f for f in manager._jsonl(world["store"].fills) if f["on"] == WED.isoformat()]
    assert len(fills) == 1 and world["book"].portfolio.positions()["DDD.NS"] > 0


def test_the_scorecard_shows_ai_pm3_its_own_decisions(world: dict[str, Any]) -> None:
    manager._append(
        world["store"].decisions,
        [
            {
                "version": agent.VERSION,
                "as_of": MON.isoformat(),
                "ticker": "AAA.NS",
                "action": "HOLD",
                "price_at_decision": "100",
            }
        ],
    )
    card = manager.update_scorecard(_market(world["panel"], TUE), world["store"])
    assert [(r["ticker"], r["version"]) for r in card["decisions"]] == [("AAA.NS", agent.VERSION)]
