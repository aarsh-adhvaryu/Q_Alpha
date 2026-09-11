"""The market brief on the page — and the labels that keep it from becoming a signal.

:mod:`qalpha.live.ai_brief` is explicit that this is a language model's *narrative*, including a
directional "likely reaction" that is its own non-validated opinion. Putting it on a page beside a
real account is the highest-risk rendering in this repo, so the tests here are almost entirely
about labelling: its age, its status, and the fact that nothing downstream reads it.

The specific trap: the markdown carries no date and a file's mtime is reset by a fresh checkout, so
a brief about a market three weeks gone would render as this morning's with nothing to contradict
it. An undated brief is reported as undated.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from qalpha.live.report import _brief_age, _brief_panel, _markdownish

TODAY = date(2026, 9, 10)
SAMPLE = """🧠 AI market brief — context only, not a signal.

**Sentiment**: 🔴 Indian market fell 0.53% on September 9, 2026.

**Drivers**:
1. **Crude surges past $100** — Brent rose 3%. Compresses refiner margins.
2. **Foreign outflows persist** — Dampens bank and IT sentiment.

SIGNAL: lean=down; band=-0.4..-0.9; confidence=medium
"""


def _files(tmp_path: Path, *, text: str = SAMPLE, as_of: str | None = "2026-09-10"):
    md = tmp_path / "ai_brief.md"
    md.write_text(text, encoding="utf-8")
    stamp = tmp_path / "ai_brief.json"
    if as_of is not None:
        stamp.write_text(json.dumps({"as_of": as_of}), encoding="utf-8")
    return md, stamp


# --- age ------------------------------------------------------------------------------------------
def test_a_stamped_brief_reports_its_real_age(tmp_path: Path) -> None:
    _md, stamp = _files(tmp_path, as_of="2026-09-07")
    assert _brief_age(TODAY, stamp) == 3


def test_an_unstamped_brief_is_undated_rather_than_assumed_fresh(tmp_path: Path) -> None:
    """THE ONE THAT MATTERS. No stamp must not silently become 'today'."""
    _md, stamp = _files(tmp_path, as_of=None)
    assert _brief_age(TODAY, stamp) is None
    panel = _brief_panel(TODAY, path=_md, stamp=stamp)
    assert "undated" in panel
    assert "written today" not in panel


def test_an_unreadable_stamp_is_undated_not_a_crash(tmp_path: Path) -> None:
    md, stamp = _files(tmp_path)
    stamp.write_text("{ not json", encoding="utf-8")
    assert _brief_age(TODAY, stamp) is None
    assert "undated" in _brief_panel(TODAY, path=md, stamp=stamp)


def test_a_stale_brief_is_shown_and_called_history(tmp_path: Path) -> None:
    """Hiding it would leave the page silent about a market it has an opinion on."""
    md, stamp = _files(tmp_path, as_of="2026-08-20")
    panel = _brief_panel(TODAY, path=md, stamp=stamp)
    assert "history, not news" in panel
    assert "Crude surges" in panel, "a stale brief is still shown, just dated"


def test_todays_brief_says_written_today(tmp_path: Path) -> None:
    md, stamp = _files(tmp_path)
    assert "written today" in _brief_panel(TODAY, path=md, stamp=stamp)


# --- what it is, said on the surface --------------------------------------------------------------
def test_the_panel_always_says_it_is_an_opinion_and_that_nothing_acts_on_it(
    tmp_path: Path,
) -> None:
    md, stamp = _files(tmp_path)
    panel = _brief_panel(TODAY, path=md, stamp=stamp)
    assert "non-validated opinion" in panel
    assert "Nothing on this page acts on it" in panel
    assert "never add one" in panel


def test_the_machine_signal_line_is_not_shown_to_a_person(tmp_path: Path) -> None:
    """`SIGNAL: lean=down` is for the twin's AI arm. On a page it reads as an instruction."""
    md, stamp = _files(tmp_path)
    panel = _brief_panel(TODAY, path=md, stamp=stamp)
    assert "SIGNAL:" not in panel
    assert "lean=down" not in panel


def test_a_missing_brief_says_nobody_wrote_one(tmp_path: Path) -> None:
    """Absence of a brief is not a quiet day."""
    panel = _brief_panel(TODAY, path=tmp_path / "gone.md", stamp=tmp_path / "gone.json")
    assert "No brief on file" in panel
    assert "not that the day was quiet" in panel
    assert "needs a reader and something to read" in panel, "say what is missing, not just that"


# --- rendering ------------------------------------------------------------------------------------
def test_model_output_cannot_become_markup(tmp_path: Path) -> None:
    """The brief is model text on a page showing an account. It is escaped before anything else."""
    md, stamp = _files(tmp_path, text="**Sentiment**: <script>alert(1)</script> & co")
    panel = _brief_panel(TODAY, path=md, stamp=stamp)
    assert "<script>" not in panel
    assert "&lt;script&gt;" in panel
    assert "&amp; co" in panel


def test_bold_and_numbered_drivers_survive_as_structure() -> None:
    html = _markdownish(SAMPLE)
    assert "<b>Sentiment</b>" in html
    assert "<ol>" in html and html.count("<li>") == 2


def test_an_empty_brief_renders_nothing_rather_than_a_stray_paragraph() -> None:
    assert _markdownish("   \n\n  ") == ""


# --- which model wrote it, and from what ----------------------------------------------------------
#
# "The market, in words" means something different depending on where the words came from: a model
# that searched the web, or a model on this desk reading twenty archived headlines. A page that
# showed both the same way would be making the same claim for two different things.
def test_a_local_brief_says_the_model_and_the_headline_count(tmp_path: Path) -> None:
    import json

    md = tmp_path / "brief.md"
    md.write_text("Steel names dominated the day [a1b2c3d4].", encoding="utf-8")
    stamp = tmp_path / "brief.json"
    stamp.write_text(
        json.dumps(
            {
                "as_of": TODAY.isoformat(),
                "model": "qwen3-8b-32k",
                "source": "local-rss",
                "headlines": 42,
                "brief_version": "BRIEF-2-local",
            }
        ),
        encoding="utf-8",
    )
    panel = _brief_panel(TODAY, path=md, stamp=stamp)
    assert "qwen3-8b-32k" in panel and "42 archived headlines" in panel
    assert "cites an item id you can open" in panel
    assert "likely reaction" not in panel, "the local brief has no forecast section to disclaim"


def test_a_web_searched_brief_still_carries_its_own_disclaimer(tmp_path: Path) -> None:
    import json

    md = tmp_path / "brief.md"
    md.write_text("**Sentiment**: steady.", encoding="utf-8")
    stamp = tmp_path / "brief.json"
    stamp.write_text(
        json.dumps(
            {"as_of": TODAY.isoformat(), "model": "claude-haiku-4-5", "source": "web-search"}
        ),
        encoding="utf-8",
    )
    panel = _brief_panel(TODAY, path=md, stamp=stamp)
    assert "claude-haiku-4-5" in panel
    assert "non-validated opinion" in panel


def test_an_unstamped_brief_makes_no_claim_about_who_wrote_it(tmp_path: Path) -> None:
    md = tmp_path / "brief.md"
    md.write_text("Something happened.", encoding="utf-8")
    panel = _brief_panel(TODAY, path=md, stamp=tmp_path / "absent.json")
    assert "local-rss" not in panel and "archived headline" not in panel
    assert "undated" in panel
