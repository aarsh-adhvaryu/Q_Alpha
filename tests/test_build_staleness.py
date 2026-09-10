"""Is the running process still the code on disk? (:mod:`qalpha.live.build`)

The failure this prevents, in full: a fix was written at 12:15, the app had started at 12:10, the
user pressed the button and got the identical error — and concluded, reasonably, that the fix had
not worked. Nothing on the page distinguished the two situations. It cost a round trip to find that
the process was five minutes older than the file.

The asymmetry the design turns on: a **false alarm costs a restart; a false all-clear costs an
afternoon.** So "I do not know" resolves to not-stale (a permanent nag is a warning people learn to
ignore) while any evidence of newer code on disk is reported loudly.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from qalpha.live import build as build_mod
from qalpha.live.build import Build
from qalpha.live.progress import IST

START = build_mod.datetime(2026, 9, 10, 12, 10, tzinfo=IST)


def _build(*, minutes_after: int | None, rev: str = "abc1234") -> Build:
    code_at = None if minutes_after is None else START + timedelta(minutes=minutes_after)
    return Build(started=START, code_at=code_at, rev=rev)


# --- the comparison -------------------------------------------------------------------------------
def test_code_edited_after_the_process_started_is_stale() -> None:
    """The exact situation: process at 12:10, fix at 12:15."""
    build = _build(minutes_after=5)
    assert build.stale is True
    assert "old version" in build.sentence()
    assert "start it again" in build.sentence()


def test_code_older_than_the_process_is_not_stale() -> None:
    build = _build(minutes_after=-30)
    assert build.stale is False
    assert "has not changed since" in build.sentence()


def test_an_unknown_code_time_is_not_treated_as_stale() -> None:
    """Not knowing is not evidence. A permanent restart nag teaches people to ignore warnings."""
    assert _build(minutes_after=None).stale is False


def test_the_chip_says_restart_when_stale_and_the_start_time_otherwise() -> None:
    assert _build(minutes_after=5).chip_text() == "restart to pick up changes"
    quiet = _build(minutes_after=-1).chip_text()
    assert "12:10" in quiet and "abc1234" in quiet


def test_a_missing_revision_is_simply_omitted() -> None:
    """A commit id nobody can produce is worse than no commit id."""
    text = _build(minutes_after=-1, rev="").chip_text()
    assert "12:10" in text
    assert "·" not in text


# --- reading the disk -----------------------------------------------------------------------------
def test_the_newest_watched_file_wins(tmp_path: Path) -> None:
    live = tmp_path / "src/qalpha/live"
    live.mkdir(parents=True)
    (live / "old.py").write_text("x", encoding="utf-8")
    import os

    os.utime(live / "old.py", (1_000_000, 1_000_000))
    (live / "new.py").write_text("x", encoding="utf-8")
    os.utime(live / "new.py", (2_000_000, 2_000_000))

    found = build_mod.code_changed_at(tmp_path)
    assert found is not None
    assert found.timestamp() == 2_000_000


def test_the_entry_point_counts_as_well_as_the_package(tmp_path: Path) -> None:
    """Editing scripts/local_run.py must mark the process stale too — it is half the app."""
    import os

    (tmp_path / "src/qalpha/live").mkdir(parents=True)
    (tmp_path / "src/qalpha/live/a.py").write_text("x", encoding="utf-8")
    os.utime(tmp_path / "src/qalpha/live/a.py", (1_000_000, 1_000_000))
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/local_run.py").write_text("x", encoding="utf-8")
    os.utime(tmp_path / "scripts/local_run.py", (3_000_000, 3_000_000))

    found = build_mod.code_changed_at(tmp_path)
    assert found is not None and found.timestamp() == 3_000_000


def test_nothing_readable_is_none_rather_than_now(tmp_path: Path) -> None:
    """`None` flows to not-stale. Substituting `now` would make every process look current."""
    assert build_mod.code_changed_at(tmp_path) is None


def test_a_missing_git_is_an_empty_revision_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*a: object, **k: object) -> object:
        raise OSError("no git here")

    monkeypatch.setattr(build_mod.subprocess, "run", _boom)
    assert build_mod.revision(tmp_path) == ""


def test_the_real_checkout_reports_a_revision() -> None:
    """This repo is a git checkout; if this stops working the chip quietly loses information."""
    assert build_mod.revision() != ""


# --- on the page ----------------------------------------------------------------------------------
def test_a_stale_app_shows_a_banner_not_only_a_chip(monkeypatch: pytest.MonkeyPatch) -> None:
    """A chip is easy to miss, and missing it is the whole failure."""
    from qalpha.live import server

    monkeypatch.setattr(server.build_info, "current", lambda root=None: _build(minutes_after=5))
    banner = server._stale_banner()
    assert "running old code" in banner
    assert "qa-bad" in banner


def test_a_current_app_shows_no_banner_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    from qalpha.live import server

    monkeypatch.setattr(server.build_info, "current", lambda root=None: _build(minutes_after=-5))
    assert server._stale_banner() == ""


def test_the_app_shell_styles_the_classes_the_report_body_uses() -> None:
    """The report's body is inlined into the app and its own <style> is dropped with its <head>.

    Every class it writes must be defined in the shell too, or the same markup renders correctly as
    a file and unstyled inside the app — two visual languages from one module that exists so there
    is only ever one.
    """
    import inspect
    import re

    from qalpha.live import report, server

    shell = server._shell("", refresh=False).decode()
    # Every class name the report's own source writes into a class="..." attribute.
    emitted: set[str] = set()
    for match in re.findall(r'class="(qa-[^"]+)"', inspect.getsource(report)):
        emitted.update(match.split())
    assert emitted, "found no classes in report.py — this test has stopped testing anything"

    unstyled = sorted(name for name in emitted if f".{name}" not in shell)
    assert not unstyled, (
        f"the report writes {unstyled} and the app's shell styles none of them, so the same "
        "markup renders correctly as a file and unstyled inside the app"
    )
