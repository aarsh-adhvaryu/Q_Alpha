"""The golden day: data → evidence → recommendation → governor → execution → costs → mark.

**Why this test shape.** Every defect this project has shipped was an *integration* failure — the
right function reached the wrong argument, a constant stood in for a measurement, a source
disagreed with the one the broker uses. Seven hundred unit tests caught none of them, because a
unit test asks whether a function works, never whether the right data got to it.

**It runs on real bytes where they exist.** Exchange verdicts come from
``data/evidence/reg_ind/REG1_IND270826.csv`` — the file NSE actually served, committed with its
SHA-256 — and the filing half from the four archived documents in
``data/evidence/announcements/VBL``. Prices are synthetic and explicit, because the watchlist panel
is gitignored and a golden day must assert an exact portfolio.

The final assertion is the point: **exact positions, exact cash, exact cost.**
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
from qalpha.live.evidence import BLOCK, PASS, WATCH, assess, load_archive
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
    "NIFTYBEES.NS": Decimal("276.00"),
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

#: Holdings and idle cash together, deliberately: a zeroed fixture hides a class of defect, and on
#: an empty book any two-name basket is 47/53 by sector so the governor fires on every clean day.
OPENING_HOLDINGS: dict[str, int] = {"INFY.NS": 45, "RELIANCE.NS": 40, "MARUTI.NS": 4}
FULL = AnnouncementCoverage(index_fetched=True, extraction_ran=True)


def _exchange(tickers: list[str]) -> dict[str, object]:
    rows, prov = load_archive(AS_OF)
    if prov is None:  # pragma: no cover - the archive ships with the repo
        pytest.skip("archived REG1_IND270826 not present")
    return {t: assess(t, rows, prov, as_of=AS_OF) for t in tickers}


def _ranked(*tickers: str) -> list[ProposedOrder]:
    """The screen's ranked, over-provisioned list — quantities as the screen would size them."""
    sizes = {CLEAN_A: 33, CLEAN_B: 5, CAUTIONED: 58, BLOCKED: 10}
    return [ProposedOrder(t, sizes.get(t, 10), PRICES[t], rank=i) for i, t in enumerate(tickers)]


def _propose(tickers: list[str], *, target: int = 2, **kw: object):
    defaults: dict[str, object] = {
        "as_of": AS_OF,
        "candidates": _ranked(*tickers),
        "target_names": target,
        "holdings": OPENING_HOLDINGS,
        "prices": PRICES,
        "sector_of": SECTORS,
        "exchange": _exchange(tickers),
        "coverage": dict.fromkeys(tickers, FULL),
    }
    defaults.update(kw)
    return propose(**defaults)  # type: ignore[arg-type]


# --- the exchange half runs on the bytes NSE actually served ------------------------------------


def test_the_archived_exchange_file_still_verifies_and_still_discriminates() -> None:
    rows, prov = load_archive(AS_OF)
    assert prov is not None and prov.document_date == AS_OF and len(rows) == 3140
    states = {t: assess(t, rows, prov, as_of=AS_OF).state for t in (CLEAN_A, CAUTIONED, BLOCKED)}
    assert states == {CLEAN_A: PASS, CAUTIONED: WATCH, BLOCKED: BLOCK}


# --- the golden day ------------------------------------------------------------------------------


def test_golden_day_end_to_end_asserts_the_exact_portfolio() -> None:
    cfg = Config()
    portfolio = Portfolio(cfg.cost, cfg.tax, cash=Decimal("120000"))
    proposal = _propose([CAUTIONED, CLEAN_A, CLEAN_B], target=2)

    # The cautioned name is skipped and REPLACED — the day still executes.
    assert proposal.outcome == EXECUTE
    assert [o.ticker for o in proposal.orders] == [CLEAN_A, CLEAN_B]
    assert [c.ticker for c in proposal.skipped] == [CAUTIONED]
    assert proposal.concentration is not None and proposal.concentration.clear

    for order in proposal.orders:
        portfolio.buy(AS_OF, order.ticker, Decimal(order.quantity), order.price)

    assert {t: int(q) for t, q in portfolio.positions().items() if q > 0} == {
        CLEAN_A: 33,
        CLEAN_B: 5,
    }
    gross = Decimal("33") * PRICES[CLEAN_A] + Decimal("5") * PRICES[CLEAN_B]
    assert gross == Decimal("29087.00")

    # THE EXACT PORTFOLIO. A paisa of drift fails this, which is the only way a replay pins an
    # integration: every defect here was arithmetically fine and wrong by a label.
    assert portfolio.cash == Decimal("90820.31")
    costs = Decimal("120000") - portfolio.cash - gross
    assert costs == Decimal("92.69")
    assert portfolio.holdings_value(PRICES) + portfolio.cash == Decimal("119907.31")
    assert portfolio.cash + gross + costs == Decimal("120000")


def test_the_golden_day_is_deterministic() -> None:
    runs = [_propose([CAUTIONED, CLEAN_A, CLEAN_B], target=2) for _ in range(3)]
    signatures = {
        (r.outcome, tuple((o.ticker, o.quantity, str(o.price)) for o in r.orders)) for r in runs
    }
    assert len(signatures) == 1


# --- company-level uncertainty never reaches the user ---------------------------------------------


def test_a_hard_exchange_block_is_skipped_and_replaced() -> None:
    proposal = _propose([BLOCKED, CLEAN_A, CLEAN_B], target=2)
    assert proposal.outcome == EXECUTE
    assert [o.ticker for o in proposal.orders] == [CLEAN_A, CLEAN_B]
    assert proposal.skipped[0].ticker == BLOCKED and BLOCK in proposal.skipped[0].reason


def test_an_unread_filing_list_skips_that_name_not_the_day() -> None:
    """The defect this replaced: nineteen names unread meant nineteen questions and no orders."""
    listed_only = AnnouncementCoverage(filings_in_window=8, documents_read=0, index_fetched=True)
    proposal = _propose(
        [CLEAN_A, CLEAN_B],
        target=1,
        coverage={CLEAN_A: listed_only, CLEAN_B: FULL},
    )
    assert proposal.outcome == EXECUTE
    assert [o.ticker for o in proposal.orders] == [CLEAN_B]
    assert proposal.skipped[0].ticker == CLEAN_A


def test_a_name_that_would_breach_a_cap_is_skipped_not_the_basket() -> None:
    """The governor filters. Refusing a whole basket over one name's sector kills the guard."""
    proposal = _propose([CLEAN_B, CAUTIONED, CLEAN_A], target=2)
    assert proposal.outcome == EXECUTE
    assert CLEAN_A in [o.ticker for o in proposal.orders]


# --- what IS a human's problem --------------------------------------------------------------------


def test_an_unpriced_holding_forces_a_human() -> None:
    """A missing price shrinks the denominator and flatters every other sector."""
    proposal = _propose([CLEAN_A], target=1, holdings={**OPENING_HOLDINGS, "MYSTERY.NS": 100})
    assert proposal.outcome == HUMAN_REQUIRED
    assert proposal.unpriced_holdings == ("MYSTERY.NS",)


def test_a_dead_evidence_feed_forces_a_human() -> None:
    """Nothing back for any candidate is a dead feed, not a clean bill of health."""
    proposal = _propose([CLEAN_A, CLEAN_B], target=2, exchange={})
    assert proposal.outcome == HUMAN_REQUIRED and "dead feed" in proposal.reason


def test_an_account_mismatch_forces_a_human() -> None:
    proposal = _propose(
        [CLEAN_A], target=1, account_ok=False, account_detail="Kite cash disagrees with the book"
    )
    assert proposal.outcome == HUMAN_REQUIRED and "Kite cash" in proposal.reason


def test_an_empty_screen_is_no_action_not_an_error() -> None:
    proposal = propose(
        as_of=AS_OF,
        candidates=[],
        target_names=2,
        holdings={},
        prices=PRICES,
        sector_of=SECTORS,
        exchange={},
    )
    assert proposal.outcome == NO_ACTION and proposal.orders == ()


# --- the filing half runs on the archived documents ------------------------------------------------


def _archived() -> list[Announcement]:
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
    docs = documents_for(_archived())
    if not docs:  # pragma: no cover
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

    covered = AnnouncementCoverage(
        filings_in_window=len(docs),
        documents_read=len(docs),
        extraction_ran=True,
        index_fetched=True,
    )
    proposal = _propose(
        [CLEAN_A],
        target=1,
        events={CLEAN_A: events},
        coverage={CLEAN_A: covered},
        unverified={CLEAN_A: discarded},
    )
    assert proposal.outcome == EXECUTE, "a quote that is not in the document changes nothing"
    assert [o.ticker for o in proposal.orders] == [CLEAN_A]


def test_a_verified_high_materiality_event_skips_that_name() -> None:
    docs = documents_for(_archived())
    if not docs:  # pragma: no cover
        pytest.skip("archived VBL filings not present")
    target = max(docs, key=lambda d: len(d.text))
    quote = " ".join(target.text.split())[200:320]
    line = (
        "EVENT: ticker=VBL; type=litigation; date=2026-08-25; materiality=high; "
        f'passage="{quote}"; summary=a real quote from the filing; uncertainty=-'
    )
    events, discarded, _raw, _usage = extract(docs, generate=lambda m, p: (line, {}), model="test")
    assert len(events) == 1 and events[0].verified

    covered = AnnouncementCoverage(
        filings_in_window=len(docs),
        documents_read=len(docs),
        extraction_ran=True,
        index_fetched=True,
    )
    proposal = _propose(
        [CLEAN_A, CLEAN_B],
        target=1,
        events={CLEAN_A: events},
        coverage={CLEAN_A: covered, CLEAN_B: FULL},
        unverified={CLEAN_A: discarded},
    )
    assert proposal.outcome == EXECUTE
    assert [o.ticker for o in proposal.orders] == [CLEAN_B], "skipped, and replaced"
    assert proposal.skipped[0].ticker == CLEAN_A
