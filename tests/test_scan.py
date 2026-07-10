"""Tests for the pure scan decision logic — every dedupe/hysteresis rule, no I/O."""

from __future__ import annotations

from datetime import date

from qalpha.live.scan import AlertState, ScanFacts, evaluate


def _facts(
    *,
    weakness: str = "normal",
    go: str = "NOT YET",
    rebalance_applied: bool = False,
    rebalance_pending: bool = False,
    rebalance_date: str = "",
    stale: bool = False,
    as_of: date = date(2026, 7, 8),
) -> ScanFacts:
    return ScanFacts(
        as_of=as_of,
        weakness_level=weakness,
        weakness_note="note",
        deploy_lines="policy",
        go_verdict=go,
        rebalance_applied=rebalance_applied,
        rebalance_pending=rebalance_pending,
        rebalance_date=rebalance_date,
        rebalance_summary="BUY X 1",
        freshness_stale=stale,
        freshness_note="stale note",
        digest_body="digest",
    )


def _kinds(alerts: list) -> list[str]:  # type: ignore[type-arg]
    return [a.kind for a in alerts]


# --- weakness escalation / easing ---------------------------------------------------------------


def test_escalation_fires_once_then_silent() -> None:
    st = AlertState()  # baseline normal
    alerts, st = evaluate(_facts(weakness="elevated"), st, date(2026, 7, 8))
    assert _kinds(alerts) == ["weakness-escalation"]
    assert st.weakness_level == "elevated"
    # repeat scan at the same level → silent
    alerts, st = evaluate(_facts(weakness="elevated"), st, date(2026, 7, 9))
    assert _kinds(alerts) == []


def test_deep_fires_even_if_elevated_never_notified() -> None:
    st = AlertState()  # normal
    alerts, st = evaluate(_facts(weakness="deep"), st, date(2026, 7, 8))
    assert _kinds(alerts) == ["weakness-escalation"]
    assert st.weakness_level == "deep"


def test_easing_only_on_third_consecutive_lower_scan() -> None:
    st = AlertState(weakness_level="deep")
    # 1st + 2nd lower scan: build hysteresis, no alert
    alerts, st = evaluate(_facts(weakness="normal"), st, date(2026, 7, 8))
    assert _kinds(alerts) == []
    assert st.weakness_level == "deep"  # not yet eased
    alerts, st = evaluate(_facts(weakness="normal"), st, date(2026, 7, 9))
    assert _kinds(alerts) == []
    # 3rd consecutive lower scan → easing fires
    alerts, st = evaluate(_facts(weakness="normal"), st, date(2026, 7, 10))
    assert _kinds(alerts) == ["weakness-easing"]
    assert st.weakness_level == "normal"


def test_easing_hysteresis_resets_on_bounce_back() -> None:
    st = AlertState(weakness_level="deep")
    _, st = evaluate(_facts(weakness="normal"), st, date(2026, 7, 8))  # pending count 1
    _, st = evaluate(_facts(weakness="normal"), st, date(2026, 7, 9))  # pending count 2
    # bounces back to deep (the notified level) → pending cleared, no alert
    alerts, st = evaluate(_facts(weakness="deep"), st, date(2026, 7, 10))
    assert _kinds(alerts) == []
    assert st.weakness_pending == "" and st.weakness_pending_count == 0
    # a fresh single normal scan starts the count over → still silent (Tue, no digest)
    alerts, st = evaluate(_facts(weakness="normal"), st, date(2026, 7, 14))
    assert _kinds(alerts) == []
    assert st.weakness_pending_count == 1


# --- GO flip ------------------------------------------------------------------------------------


def test_go_flip_both_directions_first_obs_silent() -> None:
    st = AlertState()  # go_verdict "" → first observation is a silent baseline
    alerts, st = evaluate(_facts(go="NOT YET"), st, date(2026, 7, 8))
    assert "go-flip" not in _kinds(alerts)
    assert st.go_verdict == "NOT YET"
    # NOT YET → READY fires
    alerts, st = evaluate(_facts(go="READY"), st, date(2026, 7, 9))
    assert "go-flip" in _kinds(alerts)
    # READY → NO-GO fires the other direction
    alerts, st = evaluate(_facts(go="NO-GO"), st, date(2026, 7, 10))
    assert "go-flip" in _kinds(alerts)
    assert st.go_verdict == "NO-GO"


# --- rebalance ----------------------------------------------------------------------------------


def test_rebalance_once_per_event_date() -> None:
    st = AlertState()
    f = _facts(rebalance_applied=True, rebalance_date="2026-07-08")
    alerts, st = evaluate(f, st, date(2026, 7, 8))
    assert _kinds(alerts) == ["rebalance"]
    # same event date next scan → silent
    alerts, st = evaluate(f, st, date(2026, 7, 9))
    assert _kinds(alerts) == []
    # a new event date → fires again (Tue, no digest)
    f2 = _facts(rebalance_pending=True, rebalance_date="2027-01-05")
    alerts, st = evaluate(f2, st, date(2027, 1, 5))
    assert _kinds(alerts) == ["rebalance"]


# --- guard / pipeline ---------------------------------------------------------------------------


def test_stale_edge_once_per_streak() -> None:
    st = AlertState()
    alerts, st = evaluate(_facts(stale=True), st, date(2026, 7, 8))
    assert _kinds(alerts) == ["guard-failure"]
    # still stale → no repeat
    alerts, st = evaluate(_facts(stale=True), st, date(2026, 7, 9))
    assert _kinds(alerts) == []
    # recovers, then goes stale again → new streak fires (Tue, no digest)
    _, st = evaluate(_facts(stale=False), st, date(2026, 7, 10))
    alerts, st = evaluate(_facts(stale=True), st, date(2026, 7, 14))
    assert _kinds(alerts) == ["guard-failure"]


def test_pipeline_failed_via_facts() -> None:
    st = AlertState(go_verdict="NOT YET")  # baseline so no go-flip noise
    f = ScanFacts(
        as_of=date(2026, 7, 8),
        weakness_level="normal",
        weakness_note="n",
        deploy_lines="",
        go_verdict="NOT YET",
        rebalance_applied=False,
        rebalance_pending=False,
        rebalance_date="",
        rebalance_summary="",
        freshness_stale=False,
        freshness_note="",
        digest_body="d",
        pipeline_failed="run url",
    )
    alerts, _ = evaluate(f, st, date(2026, 7, 8))
    assert "pipeline-failed" in _kinds(alerts)


# --- weekly digest ------------------------------------------------------------------------------


def test_digest_monday_once_per_iso_week() -> None:
    st = AlertState(go_verdict="NOT YET")
    monday = date(2026, 7, 6)  # a Monday
    alerts, st = evaluate(_facts(go="NOT YET"), st, monday)
    assert "weekly-digest" in _kinds(alerts)
    # same week, later day → no repeat
    alerts, st = evaluate(_facts(go="NOT YET"), st, date(2026, 7, 6))
    assert "weekly-digest" not in _kinds(alerts)
    # a non-Monday → no digest
    alerts, st = evaluate(_facts(go="NOT YET"), st, date(2026, 7, 8))
    assert "weekly-digest" not in _kinds(alerts)
    # next Monday → fires again
    alerts, st = evaluate(_facts(go="NOT YET"), st, date(2026, 7, 13))
    assert "weekly-digest" in _kinds(alerts)


def test_force_digest_does_not_burn_the_week_slot() -> None:
    st = AlertState(go_verdict="NOT YET")
    # forced on a non-Monday → emits, but must NOT record the week (Monday still gets its digest)
    alerts, st = evaluate(_facts(go="NOT YET"), st, date(2026, 7, 8), force_digest=True)
    assert "weekly-digest" in _kinds(alerts)
    assert st.last_digest_week == ""
    alerts, st = evaluate(_facts(go="NOT YET"), st, date(2026, 7, 13))  # Monday
    assert "weekly-digest" in _kinds(alerts)


# --- persistence --------------------------------------------------------------------------------


def test_state_json_round_trip() -> None:
    st = AlertState(
        weakness_level="elevated",
        weakness_pending="normal",
        weakness_pending_count=2,
        go_verdict="READY",
        was_stale=True,
        last_rebalance_alert="2026-07-08",
        last_digest_week="2026-W28",
    )
    assert AlertState.from_dict(st.to_dict()) == st
