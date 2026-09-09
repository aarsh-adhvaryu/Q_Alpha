"""Tests for the on-demand run control (``qalpha.live.workflow``).

The daily job's schedule is not a schedule — across 60 scheduled runs since 2026-06-15, none started
within fifteen minutes of its cron line. These cover the pieces that let it be started by hand, and
they assert the property that matters most on this surface: **a missing run is never reported as a
failure**, because this job has been ten hours late and still finished.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from qalpha.live import workflow


def _run(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "status": "completed",
        "conclusion": "success",
        "run_started_at": "2026-09-07T17:46:27Z",
        "event": "schedule",
        "html_url": "https://github.com/x/y/actions/runs/1",
    }
    base.update(kw)
    return base


def test_the_dispatch_targets_the_workflow_and_carries_the_branch() -> None:
    url, headers, body = workflow.dispatch_request("tok", ref="main")
    assert url.endswith("/actions/workflows/paper.yml/dispatches")
    assert headers["Authorization"] == "Bearer tok"
    assert b'"ref": "main"' in body


def test_every_refusal_names_the_thing_to_change() -> None:
    """GitHub's own 403 body reads "Resource not accessible by integration", which tells the user
    nothing. Each branch must name the actual fix."""
    assert "actions: write" in workflow.dispatch_error(403)
    assert "401" in workflow.dispatch_error(401)
    assert "404" in workflow.dispatch_error(404)
    assert "workflow_dispatch" in workflow.dispatch_error(422)
    for ok in (200, 201, 204):
        assert workflow.dispatch_error(ok) == "", "a success must not print an error"


def test_a_malformed_response_yields_no_runs_rather_than_an_exception() -> None:
    """This drives a status line in a sidebar. A status line must not be able to take the page down."""
    for junk in (None, {}, {"workflow_runs": None}, {"nope": 1}, "not json", 42):
        assert workflow.parse_runs(junk) == []


def test_a_run_that_has_not_happened_yet_is_not_reported_as_a_failure() -> None:
    """The single most important line on this control. This job has started as much as 10.1 hours
    after its cron time and finished green; calling that "failed" at noon would be a false alarm on
    a surface the user checks to decide whether something is wrong."""
    runs = workflow.parse_runs({"workflow_runs": [_run()]})
    text, tone = workflow.status_line(runs, datetime(2026, 9, 8, 12, 30, tzinfo=UTC))
    assert tone == "warn", "not yet run today is a warning, never a failure"
    assert "Nothing today yet" in text
    assert "never once fired on time" in text, "say why, or it reads as an incident"
    assert "fail" not in text.lower()


def test_a_run_today_reads_as_done() -> None:
    runs = workflow.parse_runs({"workflow_runs": [_run(run_started_at="2026-09-08T14:50:00Z")]})
    text, tone = workflow.status_line(runs, datetime(2026, 9, 8, 15, 30, tzinfo=UTC))
    assert tone == "good" and "Ran today" in text


def test_a_real_failure_reads_as_one() -> None:
    runs = workflow.parse_runs({"workflow_runs": [_run(conclusion="failure")]})
    _, tone = workflow.status_line(runs, datetime(2026, 9, 8, 18, 0, tzinfo=UTC))
    assert tone == "bad"


def test_a_run_in_flight_outranks_the_last_finished_one() -> None:
    """Right after the button is pressed the newest run has no conclusion yet. Falling through to
    the previous run would show "nothing today" one second after starting today's run."""
    runs = workflow.parse_runs(
        {
            "workflow_runs": [
                _run(status="queued", conclusion=None, event="workflow_dispatch"),
                _run(),
            ]
        }
    )
    text, tone = workflow.status_line(runs, datetime(2026, 9, 8, 12, 30, tzinfo=UTC))
    assert tone == "info" and "queued" in text and "workflow_dispatch" in text


def test_no_history_is_distinguished_from_no_run_today() -> None:
    text, tone = workflow.status_line([], datetime(2026, 9, 8, 12, 30, tzinfo=UTC))
    assert tone == "warn" and "No run history" in text


# --- the year-long-run failure mode -------------------------------------------------------------
def test_a_dormant_workflow_is_reported_before_github_switches_it_off() -> None:
    """GitHub disables a scheduled workflow after 60 days of repository inactivity and the failure
    mode is silence — the cron simply stops. Every other check here asks "did today's run succeed",
    which cannot see "no run has happened for two months"."""
    now = datetime(2026, 12, 1, tzinfo=UTC)
    quiet = workflow.parse_runs({"workflow_runs": [_run(run_started_at="2026-09-01T12:00:00Z")]})
    text, tone = workflow.status_line(quiet, now)
    assert tone == "bad"
    assert "60" in text and "disable" in text.lower()


def test_the_warning_arrives_with_time_to_act() -> None:
    """At 45 days there are still two weeks to press the button. A warning that fires on day 60 is
    a post-mortem."""
    base = datetime(2026, 9, 1, tzinfo=UTC)
    assert workflow.dormancy_warning(base, base + timedelta(days=44)) == ""
    assert workflow.dormancy_warning(base, base + timedelta(days=45)) != ""
    assert "worth one manual run" in workflow.dormancy_warning(base, base + timedelta(days=50))


def test_an_active_workflow_is_never_warned_about() -> None:
    base = datetime(2026, 9, 1, tzinfo=UTC)
    assert workflow.dormancy_warning(base, base + timedelta(days=1)) == ""
    assert workflow.dormancy_warning(None, base) == "", "no history is a different problem"


def test_the_cron_preflight_reports_every_secret_the_pipeline_depends_on() -> None:
    """An expired token degrades silently: the brief writes nothing, the spine archives filings it
    never reads, the twin's AI arm becomes its no-AI arm — and every step still reports success."""
    from pathlib import Path

    wf = (Path(__file__).resolve().parent.parent / ".github/workflows/paper.yml").read_text()
    assert "Preflight — which credentials are present" in wf
    for secret in ("ANTHROPIC_API_KEY", "GIST_TOKEN", "TELEGRAM_BOT_TOKEN"):
        assert wf.count(secret) >= 2, f"{secret} is used but not preflighted"
    assert "value never printed" in wf, "a preflight must never echo a secret"
