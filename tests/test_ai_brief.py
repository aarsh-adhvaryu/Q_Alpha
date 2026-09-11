"""Tests for the daily AI market brief — pure prompt/format logic + fail-soft generation (PR-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qalpha.live.ai_brief import (
    CONTEXT_PREAMBLE,
    build_prompt,
    format_for_telegram,
    generate_brief,
)


def test_build_prompt_includes_watchlist_and_context_preamble() -> None:
    prompt = build_prompt(["RELIANCE:ENERGY", "ITC:FMCG", "NTPC:POWER"])
    assert CONTEXT_PREAMBLE in prompt  # the disclaimer is baked into the instruction
    assert "RELIANCE:ENERGY" in prompt and "NTPC:POWER" in prompt
    assert "template only" in prompt.lower()
    assert "satellite sleeve" in prompt.lower()  # discretionary ideas are sleeve-framed


def test_build_prompt_asks_for_likely_reaction_framed_as_non_signal() -> None:
    prompt = build_prompt(["RELIANCE:ENERGY"])
    assert "likely reaction" in prompt.lower()
    assert "not a validated signal" in prompt.lower()  # forward read stays honestly framed
    assert "confidence" in prompt.lower()  # the light quantitative element


def test_build_prompt_requests_machine_readable_signal_line() -> None:
    # Book B of the forward study consumes a structured SIGNAL line deterministically.
    prompt = build_prompt(["RELIANCE:ENERGY"])
    assert "SIGNAL: lean=" in prompt and "confidence=" in prompt


def test_format_prepends_preamble_when_missing() -> None:
    out = format_for_telegram("Markets rose today on strong earnings.")
    assert out.startswith(CONTEXT_PREAMBLE)


def test_format_keeps_existing_preamble_once() -> None:
    text = f"{CONTEXT_PREAMBLE}\n\nSentiment 🟢 — calm."
    out = format_for_telegram(text)
    assert out.count(CONTEXT_PREAMBLE) == 1


def test_format_strips_pre_preamble_narration() -> None:
    # The web-search model sometimes narrates before the template — anchor drops it.
    text = f"I'll search for today's news.Let me dig deeper.{CONTEXT_PREAMBLE}\n\nSentiment 🟢."
    out = format_for_telegram(text)
    assert out.startswith(CONTEXT_PREAMBLE)
    assert "I'll search" not in out
    assert out.count(CONTEXT_PREAMBLE) == 1


def test_format_truncates_over_limit_on_word_boundary() -> None:
    long = CONTEXT_PREAMBLE + "\n\n" + ("word " * 2000)
    out = format_for_telegram(long, limit=200)
    assert len(out) <= 200
    assert out.endswith("…")


def test_generate_brief_with_canned_client() -> None:
    def fake(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        assert "RELIANCE:ENERGY" in prompt
        return "Sentiment 🟢 — steady.", {"input": 700, "output": 120}

    res = generate_brief(["RELIANCE:ENERGY"], generate=fake, model="claude-haiku-4-5")
    assert res is not None
    assert res.text.startswith(CONTEXT_PREAMBLE)  # preamble guaranteed even if the model omits it
    assert res.raw.startswith(CONTEXT_PREAMBLE) and "Sentiment 🟢 — steady." in res.raw
    assert res.usage["input"] == 700
    assert res.model == "claude-haiku-4-5"


def test_generate_brief_empty_response_is_skipped() -> None:
    res = generate_brief(["X:Y"], generate=lambda m, p: ("   ", {}))
    assert res is None


def test_generate_brief_api_error_is_fail_soft() -> None:
    def boom(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        raise RuntimeError("quota exceeded")

    assert generate_brief(["X:Y"], generate=boom) is None  # never raises


def test_generate_brief_missing_key_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # No injected generate + no key → skip (None), never attempts a network call.
    assert generate_brief(["X:Y"]) is None


def test_load_watchlist_lines(tmp_path: Path) -> None:
    from qalpha.live.ai_brief import load_watchlist_lines

    csv = tmp_path / "wl.csv"
    csv.write_text("ticker,sector\nRELIANCE.NS,ENERGY\nITC.NS,FMCG\n", encoding="utf-8")
    lines = load_watchlist_lines(str(csv))
    assert lines == ["RELIANCE:ENERGY", "ITC:FMCG"]  # .NS stripped, TICKER:SECTOR form


# --- the brief written here, from headlines this run archived (BRIEF-2-local) -----------------------
#
# The objection to a local brief was never the model: it was that a model with no retrieval, asked
# what happened today, answers from its training data — a fluent page with today's date on it, which
# is the worst thing this repo could ship and would look exactly like the feature working. The guard
# moves to where it belongs: no archived headlines, no brief.
from qalpha.live.ai_brief import (  # noqa: E402
    BRIEF_VERSION,
    Headline,
    IndexMove,
    build_local_prompt,
    check_local_brief,
    generate_local_brief,
    index_move,
    parse_citations,
)

HEADS = [
    Headline(id="a1b2c3d4", title="Sebi bars a promoter", source="ET", when="2026-09-10"),
    Headline(id="e5f6a7b8", title="Steel prices firm up", source="Mint", when="2026-09-10"),
]


def test_the_local_prompt_carries_every_headline_and_its_id() -> None:
    prompt = build_local_prompt(HEADS, ["TATASTEEL:METALS"])
    for head in HEADS:
        assert head.id in prompt and head.title in prompt
    assert "TATASTEEL:METALS" in prompt


def test_the_local_prompt_demands_a_citation_per_sentence() -> None:
    prompt = build_local_prompt(HEADS, [])
    assert "must end with the id" in prompt
    assert "A sentence you cannot cite is one you must not write" in prompt


def test_the_local_prompt_asks_for_no_forecast_and_no_signal_line() -> None:
    """The web-searched brief has a 'likely reaction' section, labelled as opinion. A model reading
    twenty headlines has no basis for one, and it would sit two inches from a real basket."""
    prompt = build_local_prompt(HEADS, [])
    assert "DO NOT forecast" in prompt
    assert "SIGNAL:" not in prompt
    assert "likely reaction" in prompt.lower(), "it must name the thing it is forbidding"


def test_a_brief_citing_an_id_it_was_never_given_is_rejected() -> None:
    problems = check_local_brief("Steel rallied [ffffffff].", [h.id for h in HEADS])
    assert problems and "never supplied" in problems[0]


def test_a_brief_that_cites_nothing_is_rejected() -> None:
    assert "cites nothing" in check_local_brief("It was a mixed day.", ["a1b2c3d4"])[0]


def test_a_brief_that_forecasts_is_rejected() -> None:
    problems = check_local_brief("Sebi acted [a1b2c3d4]. We expect a bounce.", ["a1b2c3d4"])
    assert any("forecast" in p for p in problems)


def test_a_clean_brief_passes() -> None:
    assert check_local_brief("Sebi acted against a promoter [a1b2c3d4].", ["a1b2c3d4"]) == []


def test_citations_are_parsed_from_the_body() -> None:
    assert parse_citations("one [a1b2c3d4] two [e5f6a7b8] three") == {"a1b2c3d4", "e5f6a7b8"}


def test_no_headlines_means_no_brief_rather_than_one_from_memory() -> None:
    """THE LOAD-BEARING ONE. A brief written with nothing to read is recalled training data."""
    called: list[str] = []
    result = generate_local_brief(
        [], [], generate=lambda m, p: (called.append(p), ("x", {}))[1], model="qwen"
    )
    assert result is None and called == []


def test_a_rejected_brief_is_not_returned() -> None:
    result = generate_local_brief(
        HEADS, [], generate=lambda m, p: ("Everything rallied.", {}), model="qwen"
    )
    assert result is None, "an uncitable brief must not reach the page"


def test_an_accepted_brief_carries_the_context_preamble() -> None:
    result = generate_local_brief(
        HEADS, [], generate=lambda m, p: ("Sebi acted [a1b2c3d4].", {"input": 9}), model="qwen"
    )
    assert result is not None
    assert result.raw.startswith(CONTEXT_PREAMBLE)
    assert result.model == "qwen"


def test_the_version_is_stamped_and_distinct() -> None:
    assert BRIEF_VERSION == "BRIEF-2-local"


# --- the index move is computed, never asked -------------------------------------------------------
def test_the_move_names_both_dates_because_a_session_can_be_missing() -> None:
    """The 2026 benchmark panel has 09-08 and 09-10 and no 09-09. 'Yesterday' would be wrong."""
    move = IndexMove("NIFTYBEES", "2026-09-08", 270.05, "2026-09-10", 267.17)
    sentence = move.sentence()
    assert "2026-09-08" in sentence and "2026-09-10" in sentence
    assert "-1.07%" in sentence
    assert "2 days apart" in sentence
    assert "ETF" in sentence, "it is a proxy, and the page has to say so"


def test_consecutive_sessions_say_so() -> None:
    assert "consecutive" in IndexMove("X", "2026-09-09", 100.0, "2026-09-10", 101.0).sentence()


def test_a_panel_with_one_close_is_none_rather_than_zero_percent(tmp_path) -> None:
    """A benchmark window with no data once reported 0.0%. Flat and unknown are not the same
    market — that row is in CLAUDE.md's table."""
    pd = pytest.importorskip("pandas")
    path = tmp_path / "bench.parquet"
    pd.DataFrame({"date": ["2026-09-10"], "close": [100.0]}).to_parquet(path)
    assert index_move(str(path)) is None


def test_a_missing_panel_is_none(tmp_path) -> None:
    assert index_move(str(tmp_path / "absent.parquet")) is None


def test_the_move_reads_the_last_two_closes(tmp_path) -> None:
    pd = pytest.importorskip("pandas")
    path = tmp_path / "bench.parquet"
    pd.DataFrame(
        {"date": ["2026-09-07", "2026-09-08", "2026-09-10"], "close": [271.21, 270.05, 267.17]}
    ).to_parquet(path)
    move = index_move(str(path))
    assert move is not None
    assert (move.prev_date, move.last_date) == ("2026-09-08", "2026-09-10")
    assert round(move.pct, 2) == -1.07
