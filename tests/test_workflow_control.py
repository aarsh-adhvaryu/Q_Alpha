"""Tests for the on-demand run control (``qalpha.live.workflow``).

The daily job's schedule is not a schedule — across 60 scheduled runs since 2026-06-15, none started
within fifteen minutes of its cron line. These cover the pieces that let it be started by hand, and
they assert the property that matters most on this surface: **a missing run is never reported as a
failure**, because this job has been ten hours late and still finished.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
