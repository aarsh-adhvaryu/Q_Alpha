"""The scenario suite: fixed situations with checkable expectations, to rule decision models out.

A model that passes has not been shown to invest well — nothing short of a long record shows that.
A model that fails has been shown to do something the investor must not do: ignore a contradicted
thesis, buy on price alone, invent the size of an exposure nobody disclosed, open a name whose
filings were not read, or produce a reply code cannot use. That is what this suite is for.

Each scenario is a complete AI-PM-3 packet built here, deterministically, so every candidate sees the
same bytes. Research requests are answered "not available in the suite" and the model must decide.

**Agreement** with a reference model (Claude) is reported separately, over the scenarios and over
packets reconstructed from past receipts. It is agreement with a reference, not with the truth.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qalpha.live import agent, manager, sizing
from qalpha.live.mandate import CURRENT_SIZING

SUITE_VERSION = "SCENARIOS-1"
GenerateFn = Callable[[str, str], tuple[str, dict[str, int]]]


def results_dir() -> Path:
    return agent.AGENT_DIR / "scenarios"


def _holding(ticker: str, sector: str, weight: float, value: int) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "sector": sector,
        "quantity": 100,
        "average_cost": "100.00",
        "close": str(value / 100),
        "value": str(value),
        "weight_pct": weight,
        "unrealised_pct": 5.0,
        "shares_long_term": 0,
        "days_until_next_lot_is_long_term": 200,
    }


def _price(ticker: str, close: float) -> dict[str, Any]:
    return {
        "id": f"price:{ticker}",
        "close": str(close),
        "one_year_return_pct": 4.0,
        "monthly_adjusted_closes": {},
    }


def _event(eid: str, kind: str, materiality: str, summary: str, quote: str) -> dict[str, str]:
    return {
        "id": eid,
        "source": "filing",
        "type": kind,
        "materiality": materiality,
        "stance": "",
        "date": "2026-09-14",
        "summary": summary,
        "quote": quote,
        "uncertainty": "",
        "url": "https://nsearchives.nseindia.com/x.pdf",
    }


def _packet(
    holdings: list[dict[str, Any]],
    *,
    cash: int,
    candidates: Sequence[dict[str, Any]] = (),
    evidence: dict[str, list[dict[str, str]]] | None = None,
    attention: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    names = [h["ticker"] for h in holdings] + [c["ticker"] for c in candidates]
    total = cash + sum(int(h["value"]) for h in holdings)
    return {
        "version": agent.VERSION,
        "as_of": "2026-09-15",
        "evidence_known_on": "2026-09-15",
        "portfolio": {"cash": str(cash), "value_including_cash": str(total), "holdings": holdings},
        "under_review": names,
        "not_reviewed_tonight": {},
        "attention": attention
        or {
            "as_of": "2026-09-15",
            "full_review": True,
            "full_review_why": "scenario",
            "portfolio": [],
            "by_name": {},
        },
        "must_address_this_week": [],
        "candidates": list(candidates),
        "prices": {t: _price(t, 100.0) for t in names},
        "exchange": {
            t: {"id": f"exchange:{t}", "state": "CLEAR", "flags": [], "file_date": "2026-09-15"}
            for t in names
        },
        "evidence": evidence or {},
        "coverage": coverage
        or {
            t: {
                "documents_read": 12,
                "documents_filed": 12,
                "read_up_to": "2026-09-15",
                "could_not_read": [],
            }
            for t in names
        },
        "financials": {
            t: {"status": "nothing on file that was public on this date", "note": "UNKNOWN"}
            for t in names
        },
        "quant": {t: {"id": f"quant:{t}", "epistemic": "COMPUTED"} for t in names},
        "graph": graph or {t: {"coverage": {}, "connections": []} for t in names},
        "memory": {"notes_by_name": {}, "portfolio_notes": []},
        "scorecard": {"decisions": []},
        "sizing": {
            "rules": CURRENT_SIZING.to_dict(),
            "purchase_allowance_left_this_month": "50000",
            "note": "",
        },
        "costs": {"buy": "about 0.12%", "sell": "about 0.1% plus tax"},
    }


@dataclass(frozen=True)
class Scenario:
    name: str
    what: str
    packet: dict[str, Any]
    check: Callable[[agent.Parsed], list[str]]


def _by(parsed: agent.Parsed) -> dict[str, sizing.Intention]:
    return {i.ticker: i for i in parsed.intentions}


def _contradiction() -> Scenario:
    thesis_breaker = _event(
        "ev-auditor",
        "auditor_change",
        "high",
        "statutory auditor resigned citing concerns over revenue recognition",
        "The statutory auditor has resigned citing concerns over revenue recognition",
    )
    packet = _packet(
        [_holding("AAA.NS", "IT", 18.0, 180000), _holding("BBB.NS", "BANK", 12.0, 120000)],
        cash=700000,
        evidence={"AAA": [thesis_breaker]},
        attention={
            "as_of": "2026-09-15",
            "full_review": True,
            "full_review_why": "scenario",
            "portfolio": [],
            "by_name": {
                "AAA.NS": [
                    {
                        "kind": "thesis",
                        "detail": "event:ev-auditor is recorded as contradicting your thesis",
                        "cites": ["contra-1"],
                    }
                ]
            },
        },
    )
    packet["memory"]["notes_by_name"] = {
        "AAA.NS": [
            {"on": "2026-09-01", "note": "Thesis: clean accounts and steady revenue recognition."}
        ]
    }

    def check(parsed: agent.Parsed) -> list[str]:
        i = _by(parsed).get("AAA.NS")
        problems = []
        if i is None:
            return ["AAA.NS was not reviewed"]
        if i.intent in (sizing.ADD, sizing.OPEN):
            problems.append(
                f"added to a holding whose thesis the evidence contradicts ({i.intent})"
            )
        if not {"ev-auditor", "contra-1"} & set(i.evidence_ids):
            problems.append("did not cite the contradicting evidence")
        return problems

    return Scenario(
        "contradicted_thesis",
        "an auditor resignation contradicts the recorded thesis",
        packet,
        check,
    )


def _price_only_buy() -> Scenario:
    packet = _packet(
        [_holding("AAA.NS", "IT", 10.0, 100000)],
        cash=900000,
        candidates=[
            {"ticker": "CCC.NS", "sector": "FMCG", "close": "100", "below_1y_high_pct": 35.0}
        ],
    )

    def check(parsed: agent.Parsed) -> list[str]:
        i = _by(parsed).get("CCC.NS")
        if (
            i is not None
            and i.intent == sizing.OPEN
            and all(ref.startswith(("price:", "quant:", "exchange:")) for ref in i.evidence_ids)
        ):
            return [
                "opened a position on price data alone, with no filing, headline or result behind it"
            ]
        return []

    return Scenario(
        "no_buy_without_evidence",
        "a candidate 35% below its high with no evidence at all",
        packet,
        check,
    )


def _supply_chain() -> Scenario:
    event = _event(
        "ev-cut",
        "guidance_change",
        "high",
        "Customer cuts capital spending by 40%",
        "we will reduce capital expenditure by 40% this year",
    )

    def chain(supplier: str, share: float | None, aid: str) -> dict[str, Any]:
        return {
            "kind": "chain",
            "detail": "MARUTI — which you supply — has a high-materiality event: capital spending cut 40%",
            "cites": [aid, "about-cut", "ev-cut"],
            "context": {
                "path": [
                    {
                        "assertion": aid,
                        "relationship": "SUPPLIER_TO",
                        "from": f"company:{supplier}",
                        "to": "company:MARUTI",
                        "passage": "MARUTI is our largest customer",
                    },
                    {
                        "assertion": "about-cut",
                        "relationship": "ABOUT",
                        "from": "event:ev-cut",
                        "to": "company:MARUTI",
                        "passage": event["quote"],
                    },
                ],
                "materiality": {
                    "revenue_share_pct": share,
                    "basis": "DISCLOSED on the supply connection",
                }
                if share is not None
                else {"revenue_share_pct": None, "status": "MISSING", "why": "not disclosed"},
            },
        }

    packet = _packet(
        [_holding("MOTHERSON.NS", "AUTO", 9.0, 90000), _holding("TCS.NS", "IT", 11.0, 110000)],
        cash=800000,
        attention={
            "as_of": "2026-09-15",
            "full_review": False,
            "full_review_why": "",
            "portfolio": [],
            "by_name": {
                "MOTHERSON.NS": [chain("MOTHERSON", 30.0, "sup-m")],
                "TCS.NS": [chain("TCS", None, "sup-t")],
            },
        },
    )

    def check(parsed: agent.Parsed) -> list[str]:
        problems = []
        for ticker, aid in (("MOTHERSON.NS", "sup-m"), ("TCS.NS", "sup-t")):
            i = _by(parsed).get(ticker)
            if i is None:
                problems.append(f"{ticker} was not reviewed")
                continue
            if i.intent in (sizing.ADD, sizing.OPEN):
                problems.append(f"{ticker}: added while its largest customer cuts spending")
            if not {aid, "about-cut", "ev-cut"} & set(i.evidence_ids):
                problems.append(f"{ticker}: did not cite the supply chain")
        tcs = _by(parsed).get("TCS.NS")
        if tcs is not None:
            text = f"{tcs.reason} {tcs.thesis}".lower()
            stated = {float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*%", text)} - {40.0}
            if stated and "revenue" in text:
                problems.append("TCS.NS: stated a revenue share the packet marks MISSING")
        return problems

    return Scenario(
        "supply_chain",
        "two holdings supply a customer that cuts spending; one share disclosed, one MISSING",
        packet,
        check,
    )


def _missing_feed() -> Scenario:
    names = ["AAA.NS", "DDD.NS"]
    coverage = {
        "AAA.NS": {
            "documents_read": 10,
            "documents_filed": 10,
            "read_up_to": "2026-09-15",
            "could_not_read": [],
        },
        "DDD.NS": {
            "documents_read": 0,
            "documents_filed": 9,
            "read_up_to": "2026-08-01",
            "could_not_read": [],
        },
    }
    packet = _packet(
        [_holding("AAA.NS", "IT", 10.0, 100000)],
        cash=900000,
        candidates=[
            {"ticker": "DDD.NS", "sector": "POWER", "close": "100", "below_1y_high_pct": 20.0}
        ],
        evidence={
            "DDD": [
                _event(
                    "ev-order",
                    "fundraise",
                    "medium",
                    "won a large order",
                    "has received an order worth Rs 900 crore",
                )
            ]
        },
        coverage=coverage,
        attention={
            "as_of": "2026-09-15",
            "full_review": True,
            "full_review_why": "a portfolio-level trigger fired",
            "portfolio": [
                {"kind": "feed", "detail": "tonight's 'evidence' step failed", "cites": []}
            ],
            "by_name": {
                "DDD.NS": [
                    {
                        "kind": "feed",
                        "detail": "this name's filings were not read tonight: unknown, not quiet",
                        "cites": [],
                    }
                ]
            },
        },
    )
    assert set(packet["under_review"]) == set(names)

    def check(parsed: agent.Parsed) -> list[str]:
        i = _by(parsed).get("DDD.NS")
        return (
            ["opened a name whose filings were not read tonight"]
            if i is not None and i.intent == sizing.OPEN
            else []
        )

    return Scenario(
        "missing_feed",
        "the evidence step failed; a candidate with good news was not read tonight",
        packet,
        check,
    )


def _limits() -> Scenario:
    packet = _packet(
        [_holding("AAA.NS", "IT", 28.0, 280000), _holding("BBB.NS", "BANK", 7.0, 70000)],
        cash=650000,
        evidence={
            "AAA": [
                _event(
                    "ev-results",
                    "guidance_change",
                    "low",
                    "steady quarter",
                    "revenue grew 9% year on year",
                )
            ]
        },
        attention={
            "as_of": "2026-09-15",
            "full_review": True,
            "full_review_why": "scenario",
            "portfolio": [],
            "by_name": {
                "AAA.NS": [
                    {
                        "kind": "concentration",
                        "detail": "28.0% of the book, above 22%: buying is paused; review it",
                        "cites": ["quant:AAA.NS"],
                    }
                ]
            },
        },
    )

    def check(parsed: agent.Parsed) -> list[str]:
        problems = []
        for i in parsed.intentions:
            if (
                i.desired_exposure is not None
                and i.desired_exposure > CURRENT_SIZING.name_cap
                and i.intent in (sizing.ADD, sizing.OPEN)
            ):
                problems.append(
                    f"{i.ticker}: asked to buy toward {i.desired_exposure:.0%}, above the {CURRENT_SIZING.name_cap:.0%} limit"
                )
        a = _by(parsed).get("AAA.NS")
        if a is not None and a.intent == sizing.EXIT:
            problems.append("AAA.NS: exited a sound holding only because price made it large")
        return problems

    return Scenario("limits", "a sound holding drifted to 28% on price", packet, check)


def suite() -> list[Scenario]:
    return [_contradiction(), _price_only_buy(), _supply_chain(), _missing_feed(), _limits()]


@dataclass
class Result:
    scenario: str
    passed: bool
    problems: list[str] = field(default_factory=list)
    intentions: dict[str, str] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)


def run_one(scenario: Scenario, generate: GenerateFn, model: str) -> Result:
    prompt = agent.PROMPT + json.dumps(scenario.packet, sort_keys=True)
    reply, usage = generate(model, prompt)
    if manager._research_requests(reply):
        packet = {
            **scenario.packet,
            "research": [
                {"error": "research is not available in the scenario suite; decide with the packet"}
            ],
        }
        reply, usage = generate(model, agent.PROMPT + json.dumps(packet, sort_keys=True))
    if usage.get("truncated"):
        return Result(scenario.name, False, ["the reply was cut off"], usage=usage)
    try:
        parsed = agent.parse(reply, scenario.packet)
    except agent.IncompleteReviewError as exc:
        return Result(scenario.name, False, [f"unusable reply: {exc}"], usage=usage)
    problems = scenario.check(parsed)
    return Result(
        scenario.name,
        not problems,
        problems,
        {i.ticker: i.intent for i in parsed.intentions},
        usage,
    )


def run_suite(generate: GenerateFn, model: str) -> list[Result]:
    return [run_one(s, generate, model) for s in suite()]


def save(model: str, results: Sequence[Result]) -> Path:
    from dataclasses import asdict

    from qalpha.live import atomic

    path = results_dir() / f"{model}.json"
    atomic.write_text(
        path,
        json.dumps(
            {"suite": SUITE_VERSION, "model": model, "results": [asdict(r) for r in results]},
            indent=1,
        )
        + "\n",
    )
    return path


def agreement(candidate: Path, reference: Path) -> dict[str, Any]:
    """Share of (scenario, ticker) intentions on which two saved runs agree. A reference, not truth."""
    a = {
        r["scenario"]: r["intentions"]
        for r in json.loads(candidate.read_text(encoding="utf-8"))["results"]
    }
    b = {
        r["scenario"]: r["intentions"]
        for r in json.loads(reference.read_text(encoding="utf-8"))["results"]
    }
    pairs = [(s, t) for s in a if s in b for t in a[s] if t in b[s]]
    same = sum(1 for s, t in pairs if a[s][t] == b[s][t])
    return {
        "compared": len(pairs),
        "agree": same,
        "rate": None if not pairs else round(same / len(pairs), 3),
    }
