"""AI-PM-1 — the model proposes, code disposes, and a review that did not happen is never a HOLD.

A synthetic world with **holdings and cash**: three held names bought months ago, three candidates,
a year of prices, filings read, and a fake model whose reply each test writes. Nothing touches the
network or the real records.
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

from qalpha.accounting.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.live import evidence_log, manager
from qalpha.live.extraction import EXTRACTION_VERSION, corpus_reader
from qalpha.live.market import Market
from qalpha.live.progress import IST
from qalpha.live.twin import TwinBook

HELD = ["AAA.NS", "BBB.NS", "CCC.NS"]
CANDIDATES = ["DDD.NS", "EEE.NS", "FFF.NS"]
SECTORS = {"AAA.NS": "IT", "BBB.NS": "Banks", "CCC.NS": "Energy", "DDD.NS": "IT", "EEE.NS": "FMCG"}
# FFF.NS deliberately has no sector.
DAYS = pd.bdate_range(end="2026-09-15", periods=300)
DECIDE = DAYS[-2].date()  # the review's close
NEXT = DAYS[-1].date()  # the session its orders fill on


def _evening(day: date) -> datetime:
    return datetime.combine(day, time(19, 0), IST)


def _panel() -> PriceData:
    rng = np.random.default_rng(3)
    names = HELD + CANDIDATES
    adj = {}
    for i, t in enumerate(names):
        path = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(DAYS))))
        if t in CANDIDATES:  # pulled back hard over the last quarter, so they are candidates
            path[-60:] *= np.linspace(1.0, 0.7, 60)
        adj[t] = path * (1 + i / 10)
    frame = pd.DataFrame(adj, index=DAYS)
    frame.loc[DAYS[-1], :] = frame.loc[DAYS[-2], :] * 1.02  # the fill session closes 2% higher
    volume = pd.DataFrame(100_000.0, index=DAYS, columns=names)
    return PriceData(frame, frame.copy(), volume)


def _market(panel: PriceData, as_of: date) -> Market:
    upto = panel.adj_close.loc[: pd.Timestamp(as_of)]
    return Market(
        as_of=as_of,
        prices={t: Decimal(str(round(float(upto[t].iloc[-1]), 2))) for t in upto.columns},
        index_close=pd.Series(100.0, index=DAYS),
        adj_close=panel.adj_close,
        rebase_from={},
        exclude=set(),
        watchlist=HELD + CANDIDATES,
        sector_of=SECTORS,
        wl_prices=panel,
    )


def _book(panel: PriceData) -> TwinBook:
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("1000000"))
    bought = DAYS[-200].date()
    for t in HELD:
        price = Decimal(str(round(float(panel.close_raw.at[pd.Timestamp(bought), t]), 2)))
        pf.buy(bought, t, Decimal("200"), price)
    pf.cash = Decimal("100000")  # holdings AND idle cash
    return TwinBook(name="SYSTEM", portfolio=pf)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    coverage = tmp_path / "coverage.jsonl"
    coverage.write_text(
        "".join(
            json.dumps(
                {
                    "_key": f"{DECIDE}:{t}",
                    "as_of": DECIDE.isoformat(),
                    "ticker": t,
                    "complete": True,
                    "extraction_version": EXTRACTION_VERSION,
                    "reader": corpus_reader(),
                }
            )
            + "\n"
            for t in HELD + CANDIDATES
        ),
        encoding="utf-8",
    )
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps(
            {
                "_key": "doc1:AAA:audit:1",
                "ticker": "AAA",
                "as_of": DECIDE.isoformat(),
                "event_date": DECIDE.isoformat(),
                "event_type": "auditor_change",
                "materiality": "high",
                "summary": "auditor resigned",
                "passage": "the statutory auditor has resigned with immediate effect",
                "verified": True,
                "model": corpus_reader(),
                "extraction_version": EXTRACTION_VERSION,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(evidence_log, "COVERAGE_LOG", coverage)
    monkeypatch.setattr(evidence_log, "EVENT_LOG", events)
    monkeypatch.setattr(evidence_log, "NEWS_EVENT_LOG", tmp_path / "news.jsonl")
    monkeypatch.setattr("qalpha.live.evidence.load_archive", lambda day: ({}, None))
    panel = _panel()
    return {
        "panel": panel,
        "book": _book(panel),
        "market": _market(panel, DECIDE),
        "store": manager.Store(tmp_path / "manager"),
        "calls": [],
    }


def _packet_of(prompt: str) -> dict[str, Any]:
    return dict(json.loads(prompt.split("PACKET:\n", 1)[1]))


def _decision(ticker: str, action: str = "HOLD", qty: int = 0, **over: Any) -> dict[str, Any]:
    row = {
        "ticker": ticker,
        "action": action,
        "quantity": qty,
        "reason": "r",
        "thesis": "t",
        "invalidate_if": "i",
        "evidence_ids": [f"price:{ticker}"],
        "note": f"note on {ticker}",
    }
    row.update(over)
    return row


def _brain(
    world: dict[str, Any],
    decide: Callable[[dict[str, Any]], list[dict[str, Any]]],
    usage: dict[str, int] | None = None,
    raw: str | None = None,
) -> Callable[[], manager.Brain]:
    def generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        world["calls"].append(prompt)
        if raw is not None:
            return raw, usage or {}
        body = {"portfolio_note": "steady", "decisions": decide(_packet_of(prompt))}
        return json.dumps(body), usage or {"input": 1, "output": 1}

    return lambda: manager.Brain(manager.MODEL, generate)


def _review(world: dict[str, Any], make_brain: Callable[[], manager.Brain]) -> list[Any]:
    return manager.review(
        world["book"],
        world["market"],
        now=_evening(DECIDE),
        make_brain=make_brain,
        store=world["store"],
    )


def _hold_all(packet: dict[str, Any]) -> list[dict[str, Any]]:
    return [_decision(h["ticker"]) for h in packet["portfolio"]["holdings"]]


# ---- a review that happens ---------------------------------------------------------------------


def test_a_review_queues_orders_and_fills_nothing(world: dict[str, Any]) -> None:
    book = world["book"]
    before = book.portfolio.positions()
    decisions = _review(
        world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 50)])
    )
    assert book.portfolio.positions() == before, "a decision must not fill at the close it saw"
    assert book.manager["pending"]["orders"] == [
        {"ticker": "EEE.NS", "action": "BUY", "quantity": 50}
    ]
    assert book.stepped_through == DECIDE
    assert {d.action for d in decisions} == {"HOLD", "QUEUED_BUY"}
    assert len(list(world["store"].receipts.glob("*.json"))) == 1, "the packet and reply are kept"


def test_the_packet_shows_holdings_candidates_evidence_and_nothing_unknowable(
    world: dict[str, Any],
) -> None:
    _review(world, _brain(world, _hold_all))
    packet = _packet_of(world["calls"][0])
    assert [h["ticker"] for h in packet["portfolio"]["holdings"]] == HELD
    assert {c["ticker"] for c in packet["candidates"]} <= set(CANDIDATES)
    assert packet["not_shown"].get("FFF.NS") == "sector unknown"
    assert packet["evidence"]["AAA"][0]["id"] == "doc1:AAA:audit:1"
    last_price_day = max(max(p["monthly_adjusted_closes"]) for p in packet["prices"].values())
    assert last_price_day <= DECIDE.isoformat(), "no price from after the decision date"


def test_a_retry_reuses_the_receipt_rather_than_asking_again(world: dict[str, Any]) -> None:
    make = _brain(world, _hold_all)
    _review(world, make)
    world["book"].stepped_through = None  # a retry of the same evening
    world["book"].manager = {}
    _review(world, make)
    assert len(world["calls"]) == 1
    decided = world["store"].decisions.read_text(encoding="utf-8").splitlines()
    assert len(decided) == len(HELD), "a retried evening must not record its decisions twice"


# ---- a review that does not happen is never a HOLD ------------------------------------------------


@pytest.mark.parametrize(
    ("make", "why"),
    [
        (lambda w: _brain(w, lambda p: _hold_all(p)[:-1]), "did not review CCC.NS"),
        (
            lambda w: _brain(
                w, lambda p: [*_hold_all(p)[1:], _decision("AAA.NS", evidence_ids=["price:BBB.NS"])]
            ),
            "not an id for AAA.NS",
        ),
        (lambda w: _brain(w, _hold_all, raw="Here is my answer: HOLD"), "not JSON"),
        (lambda w: _brain(w, _hold_all, usage={"truncated": 1}), "cut off"),
        (lambda w: _brain(w, _hold_all, usage={"refused": 1}), "refused"),
        (
            lambda w: _brain(w, lambda p: [*_hold_all(p), _decision("ZZZ.NS", "BUY", 1)]),
            "neither held nor a shown candidate",
        ),
        (
            lambda w: _brain(w, lambda p: [*_hold_all(p)[1:], _decision("AAA.NS", "SELL", 999)]),
            "sells 999",
        ),
    ],
)
def test_a_defective_reply_changes_nothing(
    world: dict[str, Any], make: Callable[[dict[str, Any]], Any], why: str
) -> None:
    book = world["book"]
    before = (book.portfolio.positions(), book.portfolio.cash)
    with pytest.raises(manager.IncompleteReviewError, match=why):
        _review(world, make(world))
    assert (book.portfolio.positions(), book.portfolio.cash) == before
    assert book.manager == {} and book.stepped_through is None
    assert not world["store"].decisions.exists() and not world["store"].logbook.exists()


def test_a_failed_reply_is_kept_but_does_not_answer_the_retry(world: dict[str, Any]) -> None:
    with pytest.raises(manager.IncompleteReviewError):
        _review(world, _brain(world, _hold_all, raw="nonsense"))
    _review(world, _brain(world, _hold_all))
    assert len(world["calls"]) == 2
    assert len(list(world["store"].receipts.glob("*.failed-*"))) == 1


def test_a_holding_nobody_opened_stops_the_review_before_the_model_is_asked(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No coverage row at all is a hole where the evidence should be, not a gap in it."""
    empty = tmp_path / "no-coverage.jsonl"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(evidence_log, "COVERAGE_LOG", empty)
    with pytest.raises(manager.IncompleteReviewError, match="nobody has read the filings"):
        _review(world, _brain(world, _hold_all))
    assert world["calls"] == []


def test_a_filing_that_could_not_be_read_is_named_rather_than_freezing_the_name(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scanned newspaper page nobody can transcribe must not remove a company from consideration.

    The review runs, and the packet says what could not be read and what the exchange called it, so
    the investor decides with the gap in front of it instead of the name silently disappearing.
    """
    gap = [
        {"on": "2026-09-10", "subject": "Copy of Newspaper Publication", "url": "http://x/ad.pdf"}
    ]
    monkeypatch.setattr(
        evidence_log,
        "unread_documents",
        lambda ticker, **kw: gap if ticker.removesuffix(".NS") == "AAA" else [],
    )
    monkeypatch.setattr(
        manager,
        "evidence_coverage",
        lambda names, as_of: {
            t.removesuffix(".NS"): evidence_log.Coverage(
                ticker=t.removesuffix(".NS"),
                opened=True,
                read=9,
                filed=10 if t == "AAA.NS" else 9,
                unread=tuple(gap) if t == "AAA.NS" else (),
                as_of=DECIDE.isoformat(),
            )
            for t in names
        },
    )
    _review(world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 10)]))
    packet = _packet_of(world["calls"][0])
    assert packet["coverage"]["AAA.NS"]["could_not_read"] == gap
    assert packet["coverage"]["AAA.NS"]["documents_read"] == 9
    assert "could NOT be read" in world["calls"][0], "the prompt must say what that means"
    assert world["book"].manager["pending"], "a buy is still allowed while a gap is named"


def test_no_key_is_an_incomplete_review(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("qalpha.live.credentials.load_env", lambda: None)
    with pytest.raises(manager.IncompleteReviewError, match="ANTHROPIC_API_KEY"):
        _review(world, manager.brain)


def test_before_the_evening_the_close_is_not_final(world: dict[str, Any]) -> None:
    with pytest.raises(manager.IncompleteReviewError, match="not final"):
        manager.review(
            world["book"],
            world["market"],
            now=datetime.combine(DECIDE, time(14, 0), IST),
            make_brain=_brain(world, _hold_all),
            store=world["store"],
        )


def test_a_different_model_on_the_book_is_a_new_version(world: dict[str, Any]) -> None:
    world["book"].manager = {"model": "claude-haiku-4-5"}
    with pytest.raises(manager.IncompleteReviewError, match="new version"):
        _review(world, _brain(world, _hold_all))


# ---- code disposes -----------------------------------------------------------------------------


def test_a_buy_over_twenty_percent_of_the_book_is_cut_to_the_cap(world: dict[str, Any]) -> None:
    _review(world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 100_000)]))
    order = world["book"].manager["pending"]["orders"][0]
    assert 0 < order["quantity"] < 100_000
    row = json.loads(world["store"].decisions.read_text(encoding="utf-8").splitlines()[-1])
    assert row["ticker"] == "EEE.NS" and row["status"].startswith("cut from 100000")


def test_a_ninth_name_is_cancelled(world: dict[str, Any]) -> None:
    pf = world["book"].portfolio
    extra = {"G1.NS": "A", "G2.NS": "B", "G3.NS": "C", "G4.NS": "D", "G5.NS": "E"}
    prices = {t: Decimal("10") for t in extra}
    for t in extra:
        pf.buy(DECIDE, t, Decimal("1"), Decimal("10"))
    results = manager.apply_orders(
        pf.clone(),
        [{"ticker": "EEE.NS", "action": "BUY", "quantity": 1}],
        {**prices, "EEE.NS": Decimal("100")},
        {**SECTORS, **extra},
        DECIDE,
    )
    assert results[0]["filled"] == 0 and "already 8 names" in results[0]["status"]


# ---- the fill ----------------------------------------------------------------------------------


def test_orders_fill_at_the_next_session_close_not_the_decision_close(
    world: dict[str, Any],
) -> None:
    _review(world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 50)]))
    book, panel = world["book"], world["panel"]
    next_market = _market(panel, NEXT)
    fills = manager.fill_pending(book, next_market, now=_evening(NEXT), store=world["store"])
    assert fills[0]["filled"] == 50
    assert Decimal(fills[0]["price"]) == Decimal(
        str(float(panel.close_raw.at[pd.Timestamp(NEXT), "EEE.NS"]))
    )
    assert book.portfolio.positions()["EEE.NS"] == 50
    assert book.manager["pending"] is None


def test_an_order_waits_while_its_session_is_not_final_or_has_no_volume(
    world: dict[str, Any],
) -> None:
    _review(world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 50)]))
    book, panel = world["book"], world["panel"]
    afternoon = datetime.combine(NEXT, time(14, 0), IST)
    assert (
        manager.fill_pending(book, _market(panel, NEXT), now=afternoon, store=world["store"]) == []
    )
    panel.volume.at[pd.Timestamp(NEXT), "EEE.NS"] = 0
    assert (
        manager.fill_pending(book, _market(panel, NEXT), now=_evening(NEXT), store=world["store"])
        == []
    )
    assert "EEE.NS" not in book.portfolio.positions()
    assert "no volume" in book.manager["pending"]["waiting"]


def test_waiting_orders_block_the_next_review_and_say_why(world: dict[str, Any]) -> None:
    _review(world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 50)]))
    world["book"].stepped_through = None
    with pytest.raises(manager.IncompleteReviewError, match="have not filled yet"):
        _review(world, _brain(world, _hold_all))


# ---- memory ------------------------------------------------------------------------------------


def test_the_next_review_sees_its_own_notes_and_how_its_decisions_went(
    world: dict[str, Any],
) -> None:
    _review(world, _brain(world, _hold_all))
    book, panel = world["book"], world["panel"]
    world["market"] = _market(panel, NEXT)
    manager.review(
        book,
        world["market"],
        now=_evening(NEXT),
        make_brain=_brain(world, _hold_all),
        store=world["store"],
    )
    packet = _packet_of(world["calls"][1])
    assert packet["memory"]["notes_by_name"]["AAA.NS"][-1]["note"] == "note on AAA.NS"
    assert packet["memory"]["portfolio_notes"][-1]["note"] == "steady"
    card = {r["ticker"]: r for r in packet["scorecard"]["decisions"]}
    assert card["AAA.NS"]["change_pct"] == pytest.approx(2.0, abs=0.01)


# ---- the caller ---------------------------------------------------------------------------------


def test_the_evening_step_fills_then_reviews_and_reports_an_incomplete_review(
    world: dict[str, Any],
) -> None:
    """Rule 4: the scheduled caller, with holdings and cash — not only the functions."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import twin as twin_script

    book = world["book"]
    ok = twin_script.step_system(
        book,
        world["market"],
        now=_evening(DECIDE),
        make_brain=_brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 50)]),
        store=world["store"],
    )
    assert ok is None and book.manager["pending"]

    next_market = _market(world["panel"], NEXT)
    failure = twin_script.step_system(
        book,
        next_market,
        now=_evening(NEXT),
        make_brain=_brain(world, lambda p: _hold_all(p)[:-1]),
        store=world["store"],
    )
    assert book.portfolio.positions()["EEE.NS"] == 50, "yesterday's order filled first"
    assert failure is not None and "did not review" in failure


def test_a_decision_date_is_never_the_fill_date(world: dict[str, Any]) -> None:
    """The fills log must never record a fill on the day the decision was made."""
    _review(world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 5)]))
    manager.fill_pending(
        world["book"], _market(world["panel"], NEXT), now=_evening(NEXT), store=world["store"]
    )
    fills = [json.loads(line) for line in world["store"].fills.read_text().splitlines()]
    decided = {
        json.loads(line)["as_of"] for line in world["store"].decisions.read_text().splitlines()
    }
    assert all(f["on"] not in decided for f in fills)
    assert all(date.fromisoformat(f["on"]) - DECIDE > timedelta(0) for f in fills)


def test_a_queued_order_carries_only_the_sectors_its_fill_needs(world: dict[str, Any]) -> None:
    """The whole watchlist's sector map was being written into the book beside three orders."""
    _review(world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 10)]))
    kept = set(world["book"].manager["pending"]["sectors"])
    assert kept == {*HELD, "EEE.NS"}, "only the order's names and what is held"
    assert "DDD.NS" not in kept


# ---- the caps, and the difference between buying and drifting -------------------------------------


def test_drift_above_the_cap_is_shown_not_forced(world: dict[str, Any]) -> None:
    """A holding that appreciated past 20% must not become a compulsory, tax-paying sale.

    Selling to manage risk has been measured here as losing to the tax. The buy limit stays 20%; the
    investor is only told when a position has drifted past the band, and decides for itself.
    """
    book = world["book"]
    # Make AAA about a quarter of the book by price alone: no buy, no decision, just the market.
    world["panel"].close_raw.loc[pd.Timestamp(DECIDE), "AAA.NS"] *= 3
    world["panel"].adj_close.loc[pd.Timestamp(DECIDE), "AAA.NS"] *= 3
    world["market"] = _market(world["panel"], DECIDE)
    _review(world, _brain(world, _hold_all))

    packet = _packet_of(world["calls"][0])
    weights = {h["ticker"]: h["weight_pct"] for h in packet["portfolio"]["holdings"]}
    assert weights["AAA.NS"] > 22, "the fixture must actually breach the band"
    assert packet["limits"]["a_purchase_may_take_a_name_to_pct"] == 20
    assert packet["limits"]["drift_tolerated_to_name_pct"] == 22
    assert "AAA.NS" in packet["limits"]["over_the_drift_band"]
    assert book.manager["pending"] is None, "no sale was forced"


def test_a_position_inside_the_band_is_not_flagged(world: dict[str, Any]) -> None:
    _review(world, _brain(world, _hold_all))
    packet = _packet_of(world["calls"][0])
    assert packet["limits"]["over_the_drift_band"] == []


def test_a_buy_is_still_capped_at_twenty_percent(world: dict[str, Any]) -> None:
    """The band tolerates drift; it does not let the investor BUY past the cap."""
    _review(world, _brain(world, lambda p: [*_hold_all(p), _decision("EEE.NS", "BUY", 100_000)]))
    order = world["book"].manager["pending"]["orders"][0]
    book = world["book"]
    nav = book.portfolio.cash + sum(
        (q * world["market"].prices[t] for t, q in book.portfolio.positions().items()),
        Decimal("0"),
    )
    bought = Decimal(order["quantity"]) * world["market"].prices["EEE.NS"]
    assert bought <= nav * manager.NAME_CAP, "a purchase may not exceed the 20% cap"
