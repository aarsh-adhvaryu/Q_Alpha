"""The scenario suite passes a careful model and names every rule a careless one breaks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from qalpha.live import agent, scenarios


def _held(packet: dict[str, Any]) -> list[str]:
    return [h["ticker"] for h in packet["portfolio"]["holdings"]]


def _row(ticker: str, intent: str, cites: list[str], **over: Any) -> dict[str, Any]:
    row = {
        "ticker": ticker,
        "intent": intent,
        "conviction": "standard",
        "desired_exposure_pct": None,
        "reason": "r",
        "thesis": "t",
        "invalidate_if": "i",
        "evidence_ids": cites,
        "note": "n",
    }
    row.update(over)
    return row


def _careful(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for t in _held(packet):
        triggers = packet["attention"]["by_name"].get(t, [])
        cites = [c for trig in triggers for c in trig.get("cites", [])][:1] or [f"price:{t}"]
        intent = "reduce" if any(trig["kind"] == "thesis" for trig in triggers) else "hold"
        rows.append(
            _row(
                t,
                intent,
                cites,
                desired_exposure_pct=5.0 if intent == "reduce" else None,
                reason="exposure unknown; watching",
            )
        )
    return rows


def _careless(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        _row(
            t,
            "add",
            [f"price:{t}"],
            desired_exposure_pct=30.0,
            reason="about 12% of revenue comes from this customer",
        )
        for t in _held(packet)
    ]
    rows += [
        _row(c["ticker"], "open", [f"price:{c['ticker']}"], desired_exposure_pct=5.0)
        for c in packet["candidates"]
    ]
    return rows


def _generate(decide: Any) -> scenarios.GenerateFn:
    def generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        packet = json.loads(prompt.split("PACKET:\n", 1)[1])
        return json.dumps({"portfolio_note": "note", "intentions": decide(packet)}), {
            "input": 1,
            "output": 1,
        }

    return generate


def test_a_careful_model_passes_every_scenario() -> None:
    results = scenarios.run_suite(_generate(_careful), "careful")
    assert [(r.scenario, r.problems) for r in results if not r.passed] == []


def test_a_careless_model_fails_each_scenario_for_the_right_reason() -> None:
    failed = {
        r.scenario: " ".join(r.problems)
        for r in scenarios.run_suite(_generate(_careless), "careless")
    }
    assert "added to a holding whose thesis" in failed["contradicted_thesis"]
    assert "price data alone" in failed["no_buy_without_evidence"]
    assert (
        "customer cuts spending" in failed["supply_chain"] and "MISSING" in failed["supply_chain"]
    )
    assert "not read tonight" in failed["missing_feed"]
    assert "above the 20% limit" in failed["limits"]


def test_an_unusable_reply_fails_and_is_not_guessed_at() -> None:
    result = scenarios.run_one(scenarios.suite()[0], lambda m, p: ("HOLD everything", {}), "broken")
    assert not result.passed and "unusable reply" in result.problems[0]


def test_agreement_is_measured_between_saved_runs(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(agent, "AGENT_DIR", tmp_path)
    a = scenarios.save("a", scenarios.run_suite(_generate(_careful), "a"))
    b = scenarios.save("b", scenarios.run_suite(_generate(_careless), "b"))
    same = scenarios.agreement(a, a)
    assert same["rate"] == 1.0 and same["compared"] > 0
    assert scenarios.agreement(a, b)["rate"] < 1.0
