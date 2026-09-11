"""A currency symbol must not be able to kill a step.

Found on the first real run of the migrated system, 2026-09-11::

    mark failed after 0s — UnicodeEncodeError: 'charmap' codec can't encode
    character '\\u20b9' in position 268

``\\u20b9`` is ``₹``. Windows' default encoding is cp1252, which has no rupee sign, and Python falls
back to it whenever stdout is a pipe rather than a console — which is what ``uv run`` gives its
child. Nothing was wrong with the number, the book or the step.

The run behaved correctly around it: the failure was recorded, the evening continued, the page named
the step. That is the design working, and it is still a step that did not happen because of a glyph.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from qalpha.live.console import use_utf8

REPO = Path(__file__).resolve().parent.parent

#: Every entry point the evening runs, in-process or otherwise. Rule 1: the fix goes at every
#: caller of the thing that broke, not at the one that happened to break.
ENTRY_POINTS = (
    "local_run.py",
    "paper.py",
    "twin.py",
    "evidence.py",
    "news.py",
    "ai_brief.py",
)


def test_a_piped_stdout_can_carry_a_rupee_sign() -> None:
    """THE FAILURE, REPRODUCED. A fresh interpreter with a pipe for stdout, and no help from the
    environment: cp1252 before, utf-8 after, and the character that killed the step prints."""
    code = (
        "import sys;"
        "print('before', sys.stdout.encoding);"
        "sys.path.insert(0, r'" + str(REPO / "src") + "');"
        "from qalpha.live.console import use_utf8;"
        "use_utf8();"
        "print('after', sys.stdout.encoding);"
        "print('\\u20b9 1,14,045')"
    )
    env = {
        k: v
        for k, v in __import__("os").environ.items()
        if k not in ("PYTHONIOENCODING", "PYTHONUTF8")
    }
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, env=env, check=True
    ).stdout.decode("utf-8")
    assert "after utf-8" in out
    assert "₹ 1,14,045" in out


def test_use_utf8_reconfigures_both_streams() -> None:
    use_utf8()
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", "utf-8")
        assert encoding.lower().replace("-", "") == "utf8" or not hasattr(stream, "reconfigure")


def test_a_stream_that_cannot_be_reconfigured_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pytest replaces stdout, an embedder may too. Reaching into a stream that is not ours to
    reshape is how a helper becomes the thing that breaks a run."""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    use_utf8()  # must not raise


def test_a_closed_stream_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Angry:
        encoding = "cp1252"

        def reconfigure(self, **kw: object) -> None:
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(sys, "stdout", _Angry())
    use_utf8()  # must not raise


@pytest.mark.parametrize("script", ENTRY_POINTS)
def test_every_entry_point_sets_the_encoding_before_it_prints(script: str) -> None:
    """A rule that every print must remember to be ASCII is a rule the next print will break."""
    text = (REPO / "scripts" / script).read_text(encoding="utf-8")
    assert "use_utf8()" in text, f"{script} can still die on a rupee sign"
    body = text[text.index("def main(") :]
    first_print = body.find("print(")
    call = body.index("use_utf8()")
    assert first_print == -1 or call < first_print, f"{script} prints before it fixes the stream"


def test_the_launcher_asks_for_utf8_too() -> None:
    """Belt and braces: a traceback from a crash before `main()` runs should still be legible."""
    text = (REPO / "Q-Alpha.bat").read_text(encoding="utf-8", errors="replace")
    assert "PYTHONUTF8=1" in text


# --- a failed write must leave the old file, not none of it -----------------------------------------
#
# The step that died on the rupee sign died INSIDE `Path.write_text`, which truncates before it
# encodes. So `reports/paper_dashboard.md` was left zero bytes long: the failure did not leave
# yesterday's report standing, it left nothing. `save_parquet` learned this on 2026-09-07; the
# markdown and JSON writers had not.
def test_a_failed_write_leaves_the_previous_file_intact(tmp_path: Path) -> None:
    from qalpha.live import atomic

    target = tmp_path / "report.md"
    atomic.write_text(target, "yesterday's report")

    class _Unwritable:
        def __str__(self) -> str:
            raise RuntimeError("rendering blew up")

    with pytest.raises(TypeError):
        atomic.write_text(target, _Unwritable())  # type: ignore[arg-type]
    assert target.read_text(encoding="utf-8") == "yesterday's report"


def test_no_temp_file_is_left_behind(tmp_path: Path) -> None:
    from qalpha.live import atomic

    target = tmp_path / "report.md"
    with pytest.raises(TypeError):
        atomic.write_text(target, None)  # type: ignore[arg-type]
    assert list(tmp_path.iterdir()) == []


def test_it_writes_utf8_whatever_the_platform_prefers(tmp_path: Path) -> None:
    """`Path.write_text` with no encoding uses cp1252 here, which has no rupee sign. A program
    about rupees may not depend on the platform's preference."""
    from qalpha.live import atomic

    target = atomic.write_text(tmp_path / "money.md", "₹1,14,045 · ✓ · §4.7")
    assert target.read_text(encoding="utf-8") == "₹1,14,045 · ✓ · §4.7"
    assert "₹".encode() in target.read_bytes()


def test_it_creates_the_directory_rather_than_asking_every_caller_to(tmp_path: Path) -> None:
    from qalpha.live import atomic

    atomic.write_text(tmp_path / "deep" / "nested" / "x.md", "hello")
    assert (tmp_path / "deep" / "nested" / "x.md").read_text(encoding="utf-8") == "hello"


@pytest.mark.parametrize(
    "module,name",
    [
        ("src/qalpha/live/paper.py", "the paper book"),
        ("scripts/paper.py", "the dashboard"),
        ("scripts/twin.py", "the twin's report"),
        ("scripts/local_run.py", "the page"),
        ("scripts/evidence.py", "the pre-trade report"),
    ],
)
def test_every_surface_a_failing_step_could_destroy_is_written_atomically(
    module: str, name: str
) -> None:
    """Rule 1: the fix goes at every caller of the thing that broke. The book is the one that
    matters most — a failed write there destroys the paper portfolio, not a report of it."""
    text = (REPO / module).read_text(encoding="utf-8")
    assert "atomic.write_text" in text, f"{name} can still be truncated by a failed write"
