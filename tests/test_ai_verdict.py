"""The AI name-verdict experiment (PLAN_TRUST_REPAIR.md PR-8).

⚠️ **This is the one place the LLM selects a security.** Everywhere else it is context-only (locked
discipline #3). That makes the *guards* the important thing to test, not the prompt: these assert
that the model cannot add a name, cannot change a size, and cannot fail closed. Each guard is
enforced in code, so each is testable without a network, an API key, or the `ai` extra installed.

The load-bearing test is the last one: stubbed to "keep everything", the System basket must be
byte-identical to the Shadow's. That is what makes System − Shadow an ablation of the verdict rather
than a comparison of two differently-built portfolios.
"""

from __future__ import annotations

from qalpha.live.ai_brief import (
    Candidate,
    NameVerdict,
    build_verdict_prompt,
    parse_verdicts,
    survivors,
    verdicts_note,
)

_UNIVERSE = {"VEDL.NS", "TCS.NS", "ITC.NS"}
_BASKET = {"VEDL.NS": 69, "TCS.NS": 7, "ITC.NS": 27}


def _candidates() -> list[Candidate]:
    return [
        Candidate("VEDL.NS", "METAL", 0.231, "breaking", -0.554),
        Candidate("TCS.NS", "IT", 0.367, "breaking", -0.350),
        Candidate("ITC.NS", "FMCG", 0.305, "breaking", -0.135),
    ]


# ---- guard 1: the model cannot add a name -------------------------------------------------------


def test_a_ticker_outside_the_universe_is_discarded() -> None:
    """The opportunity set is fixed by the deterministic screen before the model is ever asked."""
    text = (
        "VERDICT: ticker=VEDL; call=drop; confidence=high; reason=demerger unresolved\n"
        "VERDICT: ticker=RELIANCE; call=keep; confidence=high; reason=great company\n"
        "VERDICT: ticker=NVDA; call=keep; confidence=high; reason=not even indian\n"
    )
    out = parse_verdicts(text, _UNIVERSE)
    assert set(out) == {"VEDL.NS"}  # the two names it invented are gone


def test_an_invented_name_cannot_reach_the_basket() -> None:
    """End-to-end of guard 1: survivors only ever filters the deterministic basket."""
    verdicts = parse_verdicts(
        "VERDICT: ticker=RELIANCE; call=keep; confidence=high; reason=x", _UNIVERSE
    )
    assert survivors(_BASKET, verdicts) == _BASKET
    assert "RELIANCE.NS" not in survivors(_BASKET, verdicts)


# ---- guard 2: the model cannot change a size ----------------------------------------------------


def test_surviving_names_keep_their_deterministic_quantities_exactly() -> None:
    """The model's lever is presence, not weight — quantities come from the fixed-notional basket."""
    verdicts = parse_verdicts(
        "VERDICT: ticker=VEDL; call=drop; confidence=medium; reason=demerger", _UNIVERSE
    )
    kept = survivors(_BASKET, verdicts)
    assert kept == {"TCS.NS": 7, "ITC.NS": 27}  # untouched quantities, one name removed
    assert all(kept[t] == _BASKET[t] for t in kept)


# ---- guard 3: the model cannot fail closed -----------------------------------------------------


def test_no_verdicts_at_all_keeps_every_name() -> None:
    """No API key, a refused call, an exception, an empty body — all arrive here as {}."""
    assert survivors(_BASKET, {}) == _BASKET


def test_a_name_the_model_ignored_is_kept() -> None:
    """Absence is keep. A silent model degrades to the deterministic screen, never to an empty book."""
    verdicts = parse_verdicts(
        "VERDICT: ticker=VEDL; call=drop; confidence=low; reason=x", _UNIVERSE
    )
    assert set(survivors(_BASKET, verdicts)) == {"TCS.NS", "ITC.NS"}  # TCS/ITC had no line


def test_an_unreadable_line_is_kept_not_guessed() -> None:
    """A line we cannot parse is a name with no verdict — we never infer intent from a malformed row."""
    text = (
        "VERDICT: ticker=TCS; call=maybe; confidence=high; reason=unclear\n"
        "VERDICT: garbled nonsense\n"
        "VERDICT: ticker=ITC\n"
    )
    assert parse_verdicts(text, _UNIVERSE) == {}
    assert survivors(_BASKET, parse_verdicts(text, _UNIVERSE)) == _BASKET


def test_prose_around_the_verdict_lines_is_ignored() -> None:
    """The model writes a short rationale first; only the contract lines are machine-read."""
    text = (
        "I searched for news on these names. VEDL's demerger is still unresolved.\n\n"
        "VERDICT: ticker=VEDL; call=drop; confidence=high; reason=demerger unresolved\n"
        "VERDICT: ticker=TCS; call=keep; confidence=medium; reason=IT cycle trough\n"
    )
    out = parse_verdicts(text, _UNIVERSE)
    assert out["VEDL.NS"].keep is False
    assert out["TCS.NS"].keep is True
    assert out["VEDL.NS"].reason == "demerger unresolved"


def test_an_unrecognised_confidence_degrades_to_low() -> None:
    out = parse_verdicts("VERDICT: ticker=TCS; call=keep; confidence=certain; reason=x", _UNIVERSE)
    assert out["TCS.NS"].confidence == "low"


# ---- the prompt asks the right question ---------------------------------------------------------


def test_the_prompt_asks_for_a_one_year_view_not_tomorrow() -> None:
    """The horizon is the point — the old brief asked about the next 1–2 sessions, i.e. noise."""
    prompt = build_verdict_prompt(_candidates())
    assert "~1-YEAR hold" in prompt
    assert "Ignore short-term price moves" in prompt
    assert "next 1-2 sessions" not in prompt


def test_the_prompt_states_the_model_may_only_remove() -> None:
    prompt = build_verdict_prompt(_candidates())
    assert "cannot add names, change weights" in prompt
    assert "Default to KEEP" in prompt
    # "it fell a lot" is the screen's own selection criterion, so it cannot also be a drop reason.
    assert "'It has fallen a lot' is not a reason" in prompt


def test_the_prompt_carries_the_deterministic_facts_per_name() -> None:
    """The model reasons about news; it never re-derives numbers the engine already owns."""
    prompt = build_verdict_prompt(_candidates())
    assert (
        "VEDL (METAL): 23% below its 1y high, 6-month return -55%, breakdown test says breaking"
        in prompt
    )


# ---- the audit trail ----------------------------------------------------------------------------


def test_the_note_reports_what_was_dropped_and_why() -> None:
    verdicts = {
        "VEDL.NS": NameVerdict("VEDL.NS", False, "high", "demerger unresolved"),
        "TCS.NS": NameVerdict("TCS.NS", True, "medium", "cycle trough"),
    }
    note = verdicts_note(verdicts, _BASKET)
    assert "dropped 1 of 3" in note
    assert "VEDL.NS: demerger unresolved (high confidence)" in note
    assert "never add a name, never change a size" in note


def test_the_note_says_so_when_nothing_was_dropped() -> None:
    verdicts = {"TCS.NS": NameVerdict("TCS.NS", True, "high", "fine")}
    assert "kept all 3" in verdicts_note(verdicts, _BASKET)


# ---- the acceptance criterion -------------------------------------------------------------------


def test_stubbed_to_keep_everything_the_two_baskets_are_identical() -> None:
    """**The plan's acceptance criterion for PR-8.**

    With the AI stubbed to keep everything, the System basket must equal the Shadow's exactly — same
    tickers, same quantities. If this ever fails, some second difference has crept between the books
    and System − Shadow is no longer measuring the verdict alone.
    """
    keep_all = "\n".join(
        f"VERDICT: ticker={t.removesuffix('.NS')}; call=keep; confidence=high; reason=fine"
        for t in sorted(_UNIVERSE)
    )
    verdicts = parse_verdicts(keep_all, _UNIVERSE)
    assert len(verdicts) == len(_UNIVERSE)  # the stub really did speak for every name

    shadow_basket = dict(_BASKET)
    system_basket = survivors(dict(_BASKET), verdicts)
    assert system_basket == shadow_basket
    assert list(system_basket.items()) == list(shadow_basket.items())
