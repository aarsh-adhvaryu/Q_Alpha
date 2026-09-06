"""The golden day: data → evidence → recommendation → governor → execution → costs → mark.

**Why this test shape and not more unit tests.** Every defect this project has shipped was an
*integration* failure — the right function reached the wrong argument, a constant stood in for a
measurement, a source disagreed with the one the broker uses. Seven hundred unit tests caught none
of them, because a unit test asks whether a function works, never whether the right data got to it.
Five of those defects were introduced and caught hours later by inspection, which is luck dressed
as process. This is the test shape that turns the luck into a gate.

**It runs on real bytes where they exist.** The exchange verdicts come from
``data/evidence/reg_ind/REG1_IND270826.csv`` — the actual file NSE served, committed with its
SHA-256 — and the filings from the four archived documents in ``data/evidence/announcements/VBL``.
Prices are synthetic and explicit, because the watchlist panel is gitignored and a golden day must
assert an exact portfolio.

The final assertion is the whole point: **exact positions, exact cash, exact cost.** A number that
drifts by a paisa fails it.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.announcements import Announcement, documents_for
from qalpha.live.evidence import BLOCK, PASS, UNKNOWN, WATCH, assess, load_archive
from qalpha.live.extraction import extract
from qalpha.live.pipeline import (
    EXECUTE,
    HUMAN_REQUIRED,
    NO_ACTION,
    ProposedOrder,
    propose,
)
from qalpha.live.pretrade import AnnouncementCoverage

AS_OF = date(2026, 8, 27)
ARCHIVE = Path("data/evidence/announcements/VBL")

#: Two names that clear the exchange file on 2026-08-27, one that is cautioned, one hard-blocked.
CLEAN_A, CLEAN_B = "VBL.NS", "MUTHOOTFIN.NS"
CAUTIONED = "JIOFIN.NS"
BLOCKED = "BLISSGVS"

PRICES: dict[str, Decimal] = {
    CLEAN_A: Decimal("414.00"),
    CLEAN_B: Decimal("3085.00"),
    CAUTIONED: Decimal("238.40"),
    BLOCKED: Decimal("100.00"),
    "INFY.NS": Decimal("1144.00"),
    "RELIANCE.NS": Decimal("1282.70"),
    "MARUTI.NS": Decimal("13376.00"),
}
SECTORS = {
    CLEAN_A: "FMCG",
    CLEAN_B: "NBFC",
    CAUTIONED: "NBFC",
    BLOCKED: "PHARMA",
    "INFY.NS": "IT",
    "RELIANCE.NS": "ENERGY",
    "MARUTI.NS": "AUTO",
}

#: The book the day starts from. **Holdings and idle cash together, deliberately** — a zeroed
#: fixture hides an entire class of defect, and on an empty book *any* two-name basket is 47/53 by
#: sector, so the governor would fire on every clean day and the test would prove nothing.
OPENING_HOLDINGS: dict[str, int] = {"INFY.NS": 45, "RELIANCE.NS": 40, "MARUTI.NS": 4}
OPENING_VALUE = Decimal("156292.00")  # 45×1144 + 40×1282.70 + 4×13376

FULL_COVERAGE = AnnouncementCoverage(index_fetched=True, extraction_ran=True)


def _exchange(tickers: list[str]) -> dict[str, object]:
    rows, prov = load_archive(AS_OF)
    if prov is None:  # pragma: no cover - the archive ships with the repo
        pytest.skip("archived REG1_IND270826 not present")
    return {t: assess(t, rows, prov, as_of=AS_OF) for t in tickers}


def _candidates() -> list[ProposedOrder]:
    return [
        ProposedOrder(CLEAN_A, 33, PRICES[CLEAN_A]),
        ProposedOrder(CLEAN_B, 5, PRICES[CLEAN_B]),
        ProposedOrder(CAUTIONED, 58, PRICES[CAUTIONED]),
    ]


# --- the exchange half runs on the bytes NSE actually served ------------------------------------


def test_the_archived_exchange_file_still_verifies_and_still_discriminates() -> None:
    """If this fails the golden day is measuring something other than what NSE published."""
    rows, prov = load_archive(AS_OF)
    assert prov is not None and prov.document_date == AS_OF
    assert len(rows) == 3140
    states = {t: assess(t, rows, prov, as_of=AS_OF).state for t in (CLEAN_A, CAUTIONED, BLOCKED)}
    assert states == {CLEAN_A: PASS, CAUTIONED: WATCH, BLOCKED: BLOCK}


# --- the golden day ------------------------------------------------------------------------------


def test_golden_day_end_to_end_asserts_the_exact_portfolio() -> None:
    """One full day, and the portfolio it produces to the paisa."""
    cfg = Config()
    tickers = [CLEAN_A, CLEAN_B, CAUTIONED]
    portfolio = Portfolio(cfg.cost, cfg.tax, cash=Decimal("120000"))

    proposal = propose(
        as_of=AS_OF,
        candidates=_candidates(),
        holdings=OPENING_HOLDINGS,
        prices=PRICES,
        sector_of=SECTORS,
        exchange=_exchange(tickers),  # type: ignore[arg-type]
        coverage=dict.fromkeys(tickers, FULL_COVERAGE),
    )

    # The cautioned name is set aside, not bought, and not silently dropped either.
    assert proposal.outcome == HUMAN_REQUIRED
    assert [o.ticker for o in proposal.orders] == [CLEAN_A, CLEAN_B]
    assert CAUTIONED in proposal.excluded and "WATCH" in proposal.excluded[CAUTIONED]
    assert proposal.concentration is not None and proposal.concentration.clear

    # Execution: whole shares, real Zerodha costs, the same engine the backtest uses.
    for order in proposal.orders:
        portfolio.buy(AS_OF, order.ticker, Decimal(order.quantity), order.price)

    positions = {t: int(q) for t, q in portfolio.positions().items() if q > 0}
    assert positions == {CLEAN_A: 33, CLEAN_B: 5}

    gross = Decimal("33") * PRICES[CLEAN_A] + Decimal("5") * PRICES[CLEAN_B]
    assert gross == Decimal("29087.00")

    # THE EXACT PORTFOLIO. Not a tolerance, not a range. A paisa of drift fails this, which is the
    # only way a replay can pin an integration: every intermediate defect this project shipped was
    # arithmetically fine and wrong by a label, and a loose assertion would have passed all of them.
    assert portfolio.cash == Decimal("90820.31")
    costs = Decimal("120000") - portfolio.cash - gross
    assert costs == Decimal("92.69"), "Zerodha delivery costs on this exact fill"

    # Mark: holdings at the same prices the orders were placed at, plus the untouched cash.
    marked = portfolio.holdings_value(PRICES) + portfolio.cash
    assert marked == Decimal("119907.31")
    assert marked == gross + portfolio.cash

    # Reconciliation: nothing appeared and nothing vanished.
    assert portfolio.cash + gross + costs == Decimal("120000")


def test_the_golden_day_is_deterministic() -> None:
    """Same inputs, same answer. A replay that drifts cannot pin anything."""
    tickers = [CLEAN_A, CLEAN_B, CAUTIONED]
    exchange = _exchange(tickers)
    runs = [
        propose(
            as_of=AS_OF,
            candidates=_candidates(),
            holdings=OPENING_HOLDINGS,
            prices=PRICES,
            sector_of=SECTORS,
            exchange=exchange,  # type: ignore[arg-type]
            coverage=dict.fromkeys(tickers, FULL_COVERAGE),
        )
        for _ in range(3)
    ]
    signatures = {
        (r.outcome, tuple((o.ticker, o.quantity, str(o.price)) for o in r.orders)) for r in runs
    }
    assert len(signatures) == 1


# --- each gate can stop the day, and only the exchange can BLOCK ---------------------------------


def test_a_hard_exchange_condition_removes_the_name() -> None:
    tickers = [CLEAN_A, BLOCKED]
    proposal = propose(
        as_of=AS_OF,
        candidates=[
            ProposedOrder(CLEAN_A, 10, PRICES[CLEAN_A]),
            ProposedOrder(BLOCKED, 10, PRICES[BLOCKED]),
        ],
        holdings={},
        prices=PRICES,
        sector_of=SECTORS,
        exchange=_exchange(tickers),  # type: ignore[arg-type]
        coverage=dict.fromkeys(tickers, FULL_COVERAGE),
    )
    assert BLOCKED in proposal.excluded and proposal.excluded[BLOCKED].startswith("BLOCK")
    assert [o.ticker for o in proposal.orders] == [CLEAN_A]


def test_an_unread_filing_list_stops_the_buy() -> None:
    """Coverage that is merely listed is not coverage, and an unassessed name is not bought."""
    tickers = [CLEAN_A]
    listed_only = AnnouncementCoverage(filings_in_window=8, documents_read=0, index_fetched=True)
    proposal = propose(
        as_of=AS_OF,
        candidates=[ProposedOrder(CLEAN_A, 33, PRICES[CLEAN_A])],
        holdings=OPENING_HOLDINGS,
        prices=PRICES,
        sector_of=SECTORS,
        exchange=_exchange(tickers),  # type: ignore[arg-type]
        coverage={CLEAN_A: listed_only},
    )
    assert proposal.outcome == HUMAN_REQUIRED and proposal.orders == ()
    assert UNKNOWN in proposal.excluded[CLEAN_A]


def test_an_unpriced_holding_cannot_be_assessed_and_forces_a_human() -> None:
    """A missing price is not a zero: it shrinks the denominator and flatters every other sector."""
    tickers = [CLEAN_A]
    proposal = propose(
        as_of=AS_OF,
        candidates=[ProposedOrder(CLEAN_A, 33, PRICES[CLEAN_A])],
        holdings={"MYSTERY.NS": 100},
        prices=PRICES,
        sector_of=SECTORS,
        exchange=_exchange(tickers),  # type: ignore[arg-type]
        coverage={CLEAN_A: FULL_COVERAGE},
    )
    assert proposal.outcome == HUMAN_REQUIRED
    assert proposal.unpriced_holdings == ("MYSTERY.NS",)
    assert "not a zero" in proposal.reason


def test_the_governor_stops_a_basket_that_concentrates_the_book() -> None:
    """The cap is measured on the resulting BOOK, which is the denominator that matters."""
    tickers = [CLEAN_B]
    proposal = propose(
        as_of=AS_OF,
        candidates=[ProposedOrder(CLEAN_B, 30, PRICES[CLEAN_B])],
        holdings=OPENING_HOLDINGS,
        prices=PRICES,
        sector_of=SECTORS,
        exchange=_exchange(tickers),  # type: ignore[arg-type]
        coverage=dict.fromkeys(tickers, FULL_COVERAGE),
    )
    assert proposal.outcome == HUMAN_REQUIRED
    assert proposal.concentration is not None and not proposal.concentration.clear
    assert "NBFC" in proposal.reason


def test_a_clean_day_executes() -> None:
    tickers = [CLEAN_A, CLEAN_B]
    proposal = propose(
        as_of=AS_OF,
        candidates=[
            ProposedOrder(CLEAN_A, 33, PRICES[CLEAN_A]),
            ProposedOrder(CLEAN_B, 5, PRICES[CLEAN_B]),
        ],
        holdings=OPENING_HOLDINGS,
        prices=PRICES,
        sector_of=SECTORS,
        exchange=_exchange(tickers),  # type: ignore[arg-type]
        coverage=dict.fromkeys(tickers, FULL_COVERAGE),
    )
    assert proposal.outcome == EXECUTE and proposal.excluded == {}
    assert proposal.value == Decimal("29087.00")


def test_an_empty_screen_is_no_action_not_an_error() -> None:
    proposal = propose(
        as_of=AS_OF,
        candidates=[],
        holdings={},
        prices=PRICES,
        sector_of=SECTORS,
        exchange={},
        coverage={},
    )
    assert proposal.outcome == NO_ACTION and proposal.orders == ()


# --- the filing half runs on the archived documents ----------------------------------------------


def _archived_announcements() -> list[Announcement]:
    out = []
    for meta_path in sorted(ARCHIVE.glob("*.provenance.json")):
        meta = json.loads(meta_path.read_text())
        out.append(
            Announcement(
                symbol="VBL",
                seq_id=meta["seq_id"],
                subject=meta["subject"],
                summary="",
                disseminated_at=datetime.fromisoformat(meta["document_date"]).replace(tzinfo=UTC),
                attachment_url=meta["source_url"],
            )
        )
    return out


def test_a_fabricated_event_cannot_reach_the_proposal() -> None:
    """End to end, on real filings: an unverifiable quote never becomes a WATCH."""
    docs = documents_for(_archived_announcements())
    if not docs:  # pragma: no cover - the archive ships with the repo
        pytest.skip("archived VBL filings not present")

    fabricated = (
        "EVENT: ticker=VBL; type=regulatory_action; date=2026-08-25; materiality=high; "
        'passage="SEBI has initiated adjudication proceedings against the company and its board"; '
        "summary=invented; uncertainty=-"
    )
    events, discarded, _raw, usage = extract(
        docs, generate=lambda m, p: (fabricated, {}), model="test"
    )
    assert events == [] and discarded > 0 and usage["failed_batches"] == 0

    proposal = propose(
        as_of=AS_OF,
        candidates=[ProposedOrder(CLEAN_A, 33, PRICES[CLEAN_A])],
        holdings=OPENING_HOLDINGS,
        prices=PRICES,
        sector_of=SECTORS,
        exchange=_exchange([CLEAN_A]),  # type: ignore[arg-type]
        events={CLEAN_A: events},
        coverage={
            CLEAN_A: AnnouncementCoverage(
                filings_in_window=len(docs),
                documents_read=len(docs),
                extraction_ran=True,
                index_fetched=True,
            )
        },
        unverified={CLEAN_A: discarded},
    )
    assert proposal.outcome == EXECUTE, "a quote that is not in the document changes nothing"
    assert proposal.assessments[CLEAN_A].unverified_events == discarded


def test_a_verified_high_materiality_event_stops_the_buy() -> None:
    """The mirror of the test above, on the same real documents."""
    docs = documents_for(_archived_announcements())
    if not docs:  # pragma: no cover
        pytest.skip("archived VBL filings not present")
    target = max(docs, key=lambda d: len(d.text))
    quote = " ".join(target.text.split())[200:320]

    line = (
        f"EVENT: ticker=VBL; type=litigation; date=2026-08-25; materiality=high; "
        f'passage="{quote}"; summary=a real quote from the filing; uncertainty=-'
    )
    events, discarded, _raw, _usage = extract(docs, generate=lambda m, p: (line, {}), model="test")
    assert len(events) == 1 and events[0].verified

    proposal = propose(
        as_of=AS_OF,
        candidates=[ProposedOrder(CLEAN_A, 33, PRICES[CLEAN_A])],
        holdings=OPENING_HOLDINGS,
        prices=PRICES,
        sector_of=SECTORS,
        exchange=_exchange([CLEAN_A]),  # type: ignore[arg-type]
        events={CLEAN_A: events},
        coverage={
            CLEAN_A: AnnouncementCoverage(
                filings_in_window=len(docs),
                documents_read=len(docs),
                extraction_ran=True,
                index_fetched=True,
            )
        },
        unverified={CLEAN_A: discarded},
    )
    assert proposal.outcome == HUMAN_REQUIRED and proposal.orders == ()
    assert WATCH in proposal.excluded[CLEAN_A]
