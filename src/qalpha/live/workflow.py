"""Firing the daily job on demand, because its schedule is not a schedule.

``paper.yml`` asks GitHub for 12:23 UTC on weekdays. Across the 60 scheduled runs since the cron
line was written on 2026-06-15, **not one started within fifteen minutes of it**: the median delay
is 2.4 hours and the worst was 10.1. GitHub queues scheduled workflows behind paid load and is
explicit that it may drop them entirely. Nothing in this repo can fix that, so the answer is to stop
depending on it — ``workflow_dispatch`` is already enabled on the workflow, and a dispatch runs
immediately.

Everything here is **pure**: it builds requests and reads responses, and performs no I/O. The
caller owns the network, so a dead token or a rate limit degrades to a message on the page instead
of a traceback, and every branch is testable without a GitHub account.

The token needs the **actions: write** scope. A classic PAT needs `workflow`; a fine-grained one
needs *Actions: read and write* on this repository. Contents-only tokens return 403, which
:func:`dispatch_error` translates rather than showing the raw body.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

API = "https://api.github.com"
DEFAULT_REPO = "aarsh-adhvaryu/Q_Alpha"
DEFAULT_WORKFLOW = "paper.yml"

#: What the workflow's cron line asks for. Kept here only to measure the gap against it.
SCHEDULED_UTC = "12:23"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "qalpha-dashboard",
    }


def dispatch_request(
    token: str, *, repo: str = DEFAULT_REPO, workflow: str = DEFAULT_WORKFLOW, ref: str = "main"
) -> tuple[str, dict[str, str], bytes]:
    """The POST that starts a run now. Returns ``(url, headers, body)`` for the caller to send."""
    url = f"{API}/repos/{repo}/actions/workflows/{workflow}/dispatches"
    body = json.dumps({"ref": ref}).encode()
    return url, {**_headers(token), "Content-Type": "application/json"}, body


def runs_request(
    token: str, *, repo: str = DEFAULT_REPO, workflow: str = DEFAULT_WORKFLOW, limit: int = 5
) -> tuple[str, dict[str, str]]:
    """The GET that lists recent runs, so the page can show whether the dispatch took."""
    return f"{API}/repos/{repo}/actions/workflows/{workflow}/runs?per_page={limit}", _headers(token)


def dispatch_error(status: int) -> str:
    """Turn an HTTP status into something worth reading on a page.

    A raw 403 body says "Resource not accessible by integration", which tells the user nothing about
    what to change. Every branch here names the actual fix.
    """
    if status in (200, 201, 204):
        return ""
    if status == 401:
        return "GITHUB_TOKEN is not valid (401). Regenerate it and update the app's secrets."
    if status == 403:
        return (
            "The token cannot start workflows (403). It needs the **actions: write** scope — a "
            "classic token needs `workflow`; a fine-grained one needs *Actions: read and write* on "
            "this repository. A contents-only token can commit but cannot dispatch."
        )
    if status == 404:
        return (
            "No such workflow, or the token cannot see this repository (404). Check the repo name "
            "and that `paper.yml` is on the branch you asked for."
        )
    if status == 422:
        return (
            "GitHub refused the dispatch (422). `workflow_dispatch` must exist on the workflow **on "
            "that branch** — a run cannot be dispatched against a branch whose copy lacks the "
            "trigger."
        )
    return f"GitHub returned {status}."


@dataclass(frozen=True)
class RunSummary:
    """One workflow run, reduced to what is worth putting on a screen."""

    status: str  # queued | in_progress | completed
    conclusion: str | None  # success | failure | cancelled | None while running
    started: datetime | None
    event: str  # schedule | workflow_dispatch | push
    url: str

    @property
    def finished(self) -> bool:
        return self.status == "completed"

    @property
    def ok(self) -> bool:
        return self.conclusion == "success"


def parse_runs(payload: Any) -> list[RunSummary]:
    """Read GitHub's runs response. Anything malformed yields an empty list, never an exception —
    this drives a status line, and a status line must not be able to take the page down."""
    out: list[RunSummary] = []
    try:
        runs = payload["workflow_runs"]
    except (KeyError, TypeError, IndexError):
        return out
    if not isinstance(runs, list):  # `{"workflow_runs": null}` is a valid JSON body and not a list
        return out
    for run in runs:
        if not isinstance(run, dict):
            continue
        try:
            started_raw = run.get("run_started_at") or run.get("created_at")
            started = (
                datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
                if started_raw
                else None
            )
            out.append(
                RunSummary(
                    status=str(run.get("status", "")),
                    conclusion=(None if run.get("conclusion") is None else str(run["conclusion"])),
                    started=started,
                    event=str(run.get("event", "")),
                    url=str(run.get("html_url", "")),
                )
            )
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def _ago(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() // 60)} min ago"
    if hours < 48:
        return f"{hours:.0f}h ago"
    return f"{hours / 24:.0f}d ago"


def status_line(runs: list[RunSummary], now: datetime) -> tuple[str, str]:
    """``(text, tone)`` for the sidebar. Says what the job did, when, and whether one is running.

    "No run today" is stated as a fact about the record, never as a failure: this job has been late
    by up to ten hours and still finished, so a missing run at noon means nothing at all.
    """
    if not runs:
        return "No run history — check the token, or the workflow has never run.", "warn"
    live = next((r for r in runs if not r.finished), None)
    if live is not None:
        return f"A run is {live.status.replace('_', ' ')} now ({live.event}).", "info"
    last = runs[0]
    when = "" if last.started is None else f" · {last.started:%d %b %H:%M} UTC"
    age = "" if last.started is None else f" ({_ago(now - last.started)})"
    if not last.ok:
        return f"Last run **{last.conclusion}**{when}{age}.", "bad"
    today = last.started is not None and last.started.date() == now.date()
    if today:
        return f"Ran today{when}{age} — success.", "good"
    return (
        f"Nothing today yet. Last success{when}{age}. "
        f"The {SCHEDULED_UTC} UTC schedule has never once fired on time — median delay 2.4h.",
        "warn",
    )
