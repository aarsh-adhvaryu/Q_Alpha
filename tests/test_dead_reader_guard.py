"""EXECUTE must not appear over a book nobody read.

### The report this came from

```
Coverage: **0 of 15** name(s) fully read

# 2026-09-09 — **EXECUTE**
0 name(s) cleared every check, 7 skipped, ₹67,574 to the anchor.
```

Every line is true. Together they say something false: that fifteen companies were considered and
rejected, and the money went to the index as a consequence. What actually happened is that no reader
was configured, so every candidate came back UNKNOWN on corporate announcements, every one was
skipped, and the entire budget went to the anchor — a decision made with the evidence layer switched
off, headed with the word EXECUTE.

### The distinction being restored

:mod:`qalpha.live.pipeline` is built on one: *"I could not read ONE filing about ONE candidate"* is
resolved by moving on, and *"an evidence feed that is wholly dead"* is a human's problem. There was
already a guard for the exchange's file returning nothing for anybody. There was none for the
filings reader, which is the other half of the same evidence.

### Why every existing test missed it

All of them supply `coverage=dict.fromkeys(tickers, FULL)`. Not one exercised a run where nothing
was read — which is CLAUDE.md's fourth rule word for word: *"Eleven tests passed while the scheduled
caller fed propose() alphabetically ordered one-share baskets, because every test supplied good
data."*
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from qalpha.live.evidence import PASS, Assessment
from qalpha.live.pipeline import EXECUTE, HUMAN_REQUIRED, ProposedOrder, propose
from qalpha.live.pretrade import AnnouncementCoverage

AS_OF = date(2026, 9, 10)
READ = AnnouncementCoverage(
    filings_in_window=2, documents_read=2, extraction_ran=True, index_fetched=True
)
#: The index was reached and the filings listed — and nothing read a word of them.
LISTED_NOT_READ = AnnouncementCoverage(filings_in_window=94, index_fetched=True)


def _propose(tickers: list[str], coverage: object, **kw: object):
    base: dict[str, object] = {
        "as_of": AS_OF,
        "candidates": [
            ProposedOrder(t, 10, Decimal("1000"), rank=i) for i, t in enumerate(tickers)
        ],
        "target_names": 4,
        "holdings": {},
        "prices": {},
        "sector_of": dict.fromkeys(tickers, "IT"),
        "exchange": {t: Assessment(t, PASS) for t in tickers},
        "budget": Decimal("50000"),
        "anchor_price": Decimal("268"),
        "coverage": coverage,
    }
    base.update(kw)
    return propose(**base)  # type: ignore[arg-type]


# --- the guard ------------------------------------------------------------------------------------
def test_nothing_read_for_anybody_is_a_human_problem_not_an_execute() -> None:
    """THE ONE THIS FILE EXISTS FOR."""
    proposal = _propose(
        ["A.NS", "B.NS", "C.NS"], dict.fromkeys(["A.NS", "B.NS", "C.NS"], LISTED_NOT_READ)
    )
    assert proposal.outcome == HUMAN_REQUIRED
    assert proposal.orders == (), "not even the anchor, matching the dead-exchange-feed guard"


def test_the_reason_names_the_cause_and_the_fix() -> None:
    proposal = _propose(["A.NS"], {"A.NS": LISTED_NOT_READ})
    assert "no extraction ran at all" in proposal.reason
    assert "QALPHA_LOCAL_MODEL" in proposal.reason, "say what would make it work"


def test_the_reason_distinguishes_an_off_layer_from_quiet_companies() -> None:
    """The two produce identical baskets, which is exactly why the words have to differ."""
    reason = _propose(["A.NS"], {"A.NS": LISTED_NOT_READ}).reason
    assert "1 candidates" in reason or "the 1 candidate" in reason
    assert "evidence layer that is off" in reason
    assert "companies had nothing to report" in reason


def test_no_coverage_argument_at_all_also_trips_it() -> None:
    """A caller that forgets to pass coverage must not read as a caller whose reader worked."""
    assert _propose(["A.NS"], None).outcome == HUMAN_REQUIRED


# --- and it must not over-fire ---------------------------------------------------------------------
#
# `evidence.py` warns what happens if "wholly dead feed" and "one unread filing" collapse into each
# other: every unbuilt feature starts producing HUMAN_REQUIRED and the gate becomes useless. So the
# guard asks for ONE assessed candidate, not all of them.
def test_one_name_actually_read_is_enough_to_leave_the_loop_alone() -> None:
    proposal = _propose(["A.NS", "B.NS"], {"A.NS": READ, "B.NS": LISTED_NOT_READ})
    assert proposal.outcome == EXECUTE
    assert [o.ticker for o in proposal.orders if not o.is_anchor] == ["A.NS"]
    assert [c.ticker for c in proposal.skipped] == ["B.NS"], "B moved on, as designed"


def test_everything_read_is_untouched() -> None:
    proposal = _propose(["A.NS", "B.NS"], {"A.NS": READ, "B.NS": READ})
    assert proposal.outcome == EXECUTE


def test_a_name_with_nothing_filed_counts_as_read() -> None:
    """`extraction_ran` is true when there was nothing to extract — that is complete, not blind."""
    nothing_filed = AnnouncementCoverage(
        filings_in_window=0, extraction_ran=True, index_fetched=True
    )
    assert _propose(["A.NS"], {"A.NS": nothing_filed}).outcome == EXECUTE


def test_no_candidates_at_all_is_not_a_dead_reader() -> None:
    """Nothing to deploy into is a quiet day, not an outage. The guard must not claim otherwise."""
    proposal = _propose([], {}, budget=Decimal("0"))
    assert proposal.outcome != HUMAN_REQUIRED


# --- the caller ------------------------------------------------------------------------------------
def test_the_scheduled_caller_hands_propose_the_coverage_it_needs() -> None:
    """The guard can only see what it is given, and every existing test gave it good data.

    Asserted on the call site because that is the layer eleven passing tests missed last time.
    """
    import inspect
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "scripts/evidence.py").read_text(
        encoding="utf-8"
    )
    call = src[src.index("proposal = propose(") :]
    call = call[: call.index(")\n")]
    assert "coverage=coverage" in call, (
        "evidence.py must pass real coverage into propose(), or the dead-reader guard is blind "
        "and silently never fires in production"
    )
    assert inspect.isfunction(propose)


def test_the_candidate_count_in_the_reason_is_the_real_one() -> None:
    """The first version of this message said "fifteen companies" as a literal, and the run that
    produced it had sixteen. A number written into a sentence is still a number on a money
    surface."""
    for size in (1, 3, 16):
        tickers = [f"T{i}.NS" for i in range(size)]
        reason = _propose(tickers, dict.fromkeys(tickers, LISTED_NOT_READ)).reason
        assert f"{size} candidate" in reason
        assert "fifteen" not in reason
