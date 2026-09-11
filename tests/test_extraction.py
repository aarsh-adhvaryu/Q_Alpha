"""The AI reports what a document says. It does not decide, and its quotes are checked.

The guard under test is the one a hostname allowlist could never provide: it tests whether the
source **supports the claim**, not whether the URL looks respectable. The first real veto cited a
stock quote page and passed, because "a URL is present" was the whole rule.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from qalpha.live.announcements import Announcement, SourceDocument
from qalpha.live.evidence import Provenance
from qalpha.live.extraction import (
    EVENT_TYPES,
    EXTRACTION_VERSION,
    build_prompt,
    chunks_for,
    event_rows,
    extract,
    normalise,
    parse_events,
    verify_passage,
)

TEXT = (
    "Sub: Disclosure under Regulation 30 of the SEBI (Listing Obligations and Disclosure\n"
    "Requirements) Regulations, 2015\n\n"
    "The Board of Directors has approved the acquisition of a 51% stake in Acme Bottling\n"
    "Private Limited for a consideration of INR 4,200 million, subject to regulatory approvals."
)
OTHER_TEXT = "The Company informs the Exchange of a change in its registered office address."


def _doc(symbol: str = "VBL", text: str = TEXT, sha: str = "a" * 64) -> SourceDocument:
    ann = Announcement(
        symbol=symbol,
        seq_id="1",
        subject="General Updates",
        summary="",
        disseminated_at=datetime(2026, 8, 25, 16, 21, tzinfo=UTC),
        attachment_url=f"https://nsearchives.nseindia.com/corporate/{symbol}_x.pdf",
    )
    prov = Provenance(
        source_url=ann.attachment_url,
        retrieved_at_utc=datetime(2026, 9, 5, tzinfo=UTC),
        http_status=200,
        sha256=sha,
        byte_length=len(text),
        document_date=date(2026, 8, 25),
    )
    return SourceDocument(announcement=ann, text=text, provenance=prov)


def _line(**over: str) -> str:
    f = {
        "ticker": "VBL",
        "type": "acquisition",
        "date": "2026-08-25",
        "materiality": "high",
        "passage": "approved the acquisition of a 51% stake in Acme Bottling",
        "summary": "51% stake acquisition",
        "uncertainty": "-",
    }
    f.update(over)
    return (
        f"EVENT: ticker={f['ticker']}; type={f['type']}; date={f['date']}; "
        f'materiality={f["materiality"]}; passage="{f["passage"]}"; '
        f"summary={f['summary']}; uncertainty={f['uncertainty']}"
    )


# --- the quote guard --------------------------------------------------------------------------


def test_a_verbatim_quote_verifies() -> None:
    assert verify_passage("approved the acquisition of a 51% stake", TEXT)


def test_a_line_wrapped_quote_still_verifies() -> None:
    """PDF extraction inserts newlines wherever the layout had them; words are what matter."""
    assert verify_passage("Disclosure under\n  Regulation 30 of\tthe SEBI", TEXT)


def test_a_fabricated_quote_does_not_verify() -> None:
    assert not verify_passage(
        "SEBI has initiated adjudication proceedings against the company", TEXT
    )


def test_a_paraphrase_does_not_verify() -> None:
    assert not verify_passage("The board agreed to buy a majority holding in Acme", TEXT)


def test_a_trivially_short_quote_does_not_verify() -> None:
    """Two words appear in almost any filing and evidence nothing."""
    assert not verify_passage("the Board", TEXT)


def test_normalise_is_applied_to_both_sides() -> None:
    assert normalise("  A   B \n C ") == "a b c"


# --- parsing ----------------------------------------------------------------------------------


def test_a_verified_event_is_kept_with_its_document_hash() -> None:
    events, discarded = parse_events(_line(), [_doc()], model="m")
    assert discarded == 0 and len(events) == 1
    e = events[0]
    assert e.verified and e.ticker == "VBL" and e.event_type == "acquisition"
    assert e.doc_sha256 == "a" * 64 and e.event_date == date(2026, 8, 25)
    assert e.extraction_version == EXTRACTION_VERSION


def test_a_hallucinated_quote_is_discarded() -> None:
    events, discarded = parse_events(
        _line(passage="SEBI has initiated adjudication proceedings against the company"),
        [_doc()],
        model="m",
    )
    assert events == [] and discarded == 1


def test_the_model_cannot_introduce_a_name_it_was_not_given() -> None:
    events, discarded = parse_events(_line(ticker="RELIANCE"), [_doc()], model="m")
    assert events == [] and discarded == 1


def test_a_real_quote_cannot_be_attributed_to_the_wrong_company() -> None:
    """The quote exists, but not in any document supplied for that ticker."""
    events, discarded = parse_events(
        _line(ticker="INFY"), [_doc(), _doc("INFY", OTHER_TEXT, "b" * 64)], model="m"
    )
    assert events == [] and discarded == 1


def test_an_unknown_event_type_falls_back_rather_than_inventing_a_category() -> None:
    events, _ = parse_events(_line(type="hostile_takeover_rumour"), [_doc()], model="m")
    assert events[0].event_type == "other"


def test_an_unreadable_materiality_falls_back_to_low() -> None:
    events, _ = parse_events(_line(materiality="catastrophic"), [_doc()], model="m")
    assert events[0].materiality == "low"


def test_an_undated_event_is_kept_but_stays_undated() -> None:
    events, _ = parse_events(_line(date="-"), [_doc()], model="m")
    assert events[0].event_date is None


def test_a_passage_containing_semicolons_survives_the_parser() -> None:
    text = "the Board approved; subject to approvals; the acquisition of Acme Bottling Limited"
    events, discarded = parse_events(
        _line(passage="approved; subject to approvals; the acquisition"),
        [_doc(text=text)],
        model="m",
    )
    assert discarded == 0 and len(events) == 1


def test_prose_around_the_event_lines_is_ignored() -> None:
    raw = f"Here is what I found.\n\n{_line()}\n\nLet me know if you need more."
    events, _ = parse_events(raw, [_doc()], model="m")
    assert len(events) == 1


# --- the prompt -------------------------------------------------------------------------------


def test_the_prompt_forbids_recommendation() -> None:
    prompt = build_prompt(chunks_for(_doc()))
    assert "DO NOT recommend" in prompt
    assert "should be bought, held or sold" in prompt


def test_the_prompt_carries_the_document_text_and_its_hash() -> None:
    prompt = build_prompt(chunks_for(_doc()))
    assert "Acme Bottling" in prompt and "a" * 64 in prompt


def test_the_prompt_offers_silence_as_a_valid_answer() -> None:
    assert "Silence is a valid answer" in build_prompt(chunks_for(_doc()))


def test_every_event_type_is_named_in_the_prompt() -> None:
    prompt = build_prompt(chunks_for(_doc()))
    assert all(t in prompt for t in EVENT_TYPES)


def test_a_long_document_is_chunked_rather_than_truncated() -> None:
    """Truncation meant the tail was never read while coverage counted it as read."""
    doc = _doc(text="x" * 30_000)
    parts = chunks_for(doc)
    assert len(parts) > 1
    assert "".join(p.text for p in parts).count("x") >= 30_000, "every character reaches a prompt"
    assert all(p.total == len(parts) for p in parts)


def test_chunks_overlap_so_a_boundary_fact_survives_whole() -> None:
    from qalpha.live.extraction import CHUNK_OVERLAP

    parts = chunks_for(_doc(text="y" * 30_000))
    assert parts[0].text[-CHUNK_OVERLAP:] == parts[1].text[:CHUNK_OVERLAP]


def test_a_short_document_is_one_whole_chunk() -> None:
    parts = chunks_for(_doc())
    assert len(parts) == 1 and parts[0].label == "whole" and parts[0].text == TEXT


def test_batches_never_split_a_chunk() -> None:
    from qalpha.live.extraction import batch_chunks

    parts = chunks_for(_doc(text="z" * 60_000))
    batches = batch_chunks(parts)
    assert sum(len(b) for b in batches) == len(parts)
    assert all(b for b in batches)


def test_every_chunk_of_a_long_filing_reaches_the_model() -> None:
    doc = _doc(text="q" * 40_000)
    seen: list[str] = []

    def _gen(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        seen.append(prompt)
        return "", {}

    extract([doc], generate=_gen, model="m")
    total = sum(p.count("q") for p in seen)
    assert total >= 40_000, "the tail must not be dropped"


# --- the run ----------------------------------------------------------------------------------


def test_extract_returns_nothing_when_there_is_nothing_to_read() -> None:
    events, discarded, raw, usage, _unread = extract([], generate=lambda m, p: ("", {}), model="m")
    assert (events, discarded, raw) == ([], 0, "")
    assert usage["calls"] == 0 and usage["failed_batches"] == 0


def test_a_failed_call_yields_no_events_and_says_why() -> None:
    """An extraction that did not happen must not look like one that found nothing."""

    def _boom(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        raise RuntimeError("quota exceeded")

    events, discarded, raw, usage, _unread = extract([_doc()], generate=_boom, model="m")
    assert events == [] and discarded == 0 and "quota exceeded" in raw
    assert usage["failed_batches"] == 1, "a caller must be able to refuse to claim coverage"


def test_one_failed_batch_does_not_lose_the_others() -> None:
    calls = {"n": 0}

    def _flaky(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return _line(), {}

    doc = _doc(text=TEXT + "w" * 40_000)
    events, _, _, usage, _unread = extract([doc], generate=_flaky, model="m")
    assert usage["failed_batches"] == 1 and usage["calls"] >= 1
    assert len(events) == 1


def test_the_same_event_found_in_overlapping_chunks_is_recorded_once() -> None:
    doc = _doc(text=TEXT + "p" * 30_000)
    events, _, _, _, _ = extract([doc], generate=lambda m, p: (_line(), {}), model="m")
    assert len(events) == 1


def test_extract_verifies_end_to_end() -> None:
    canned = _line() + "\n" + _line(passage="an entirely invented sentence about a regulator")
    events, discarded, _, _, _ = extract([_doc()], generate=lambda m, p: (canned, {}), model="m")
    assert len(events) == 1 and discarded == 1


def test_two_events_of_one_type_in_one_document_do_not_collide() -> None:
    """Keyed on (document, ticker, type) alone the second silently superseded the first."""
    text = (
        "The company reports a first proceeding before the tribunal in Mumbai concerning tax. "
        "The company reports a second proceeding before the tribunal in Delhi concerning duty."
    )
    raw = "\n".join(
        _line(type="litigation", passage=p)
        for p in (
            "a first proceeding before the tribunal in Mumbai concerning tax",
            "a second proceeding before the tribunal in Delhi concerning duty",
        )
    )
    events, discarded = parse_events(raw, [_doc(text=text)], model="m")
    assert discarded == 0 and len(events) == 2
    keys = {r["_key"] for r in event_rows(events, as_of=date(2026, 9, 5))}
    assert len(keys) == 2, "same document, same type, different passages — two rows, not one"


def test_event_rows_key_on_the_document_so_a_rerun_corrects(tmp_path: object) -> None:
    events, _ = parse_events(_line(), [_doc()], model="m")
    (row,) = event_rows(events, as_of=date(2026, 9, 5))
    assert row["_key"].startswith(f"{'a' * 16}:VBL:acquisition:")
    assert row["verified"] is True and row["kind"] == "event"


# --- a reply that ran out of room is not a reading -------------------------------------------------
#
# `failed_batches` covered the call that RAISED. A call that answered, and was cut off at max_tokens
# halfway down its list of events, looked identical to one that had read everything and found what
# it found — and coverage counted every document in that batch as read. That is the "25 of 30
# filings, reported as 25 of 25" defect with a new cause, and a local model with thinking on walks
# straight into it.
def test_a_truncated_single_document_is_not_counted_as_read() -> None:
    def _cut_off(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        return _line(), {"truncated": 1}

    events, _discarded, _raw, usage, _unread = extract([_doc()], generate=_cut_off, model="m")
    assert usage["truncated_batches"] == 1
    assert usage["failed_batches"] == 1, "a caller must be able to refuse to claim coverage"
    assert len(events) == 1, "what it did verify is still evidence; the count is what stops it"


def test_a_truncated_multi_document_batch_is_retried_one_document_at_a_time() -> None:
    """Temperature is zero, so asking again unchanged truncates in the same place. Splitting is the
    only thing worth trying, and usually it is enough."""
    seen: list[int] = []

    def _cut_off_when_crowded(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        documents = prompt.count("--- DOCUMENT ")
        seen.append(documents)
        return (_line(), {"truncated": 1}) if documents > 1 else (_line(), {})

    docs = [_doc(sha="a" * 64), _doc(symbol="TCS", text=OTHER_TEXT, sha="b" * 64)]
    _events, _discarded, raw, usage, _unread = extract(
        docs, generate=_cut_off_when_crowded, model="m"
    )
    assert seen == [2, 1, 1], "the crowded call, then each document alone"
    assert usage["retried_batches"] == 1
    assert usage["failed_batches"] == 0, "the retry succeeded, so nothing was left unread"
    assert "[TRUNCATED]" in raw


def test_the_empty_run_carries_the_same_counters_as_a_busy_one() -> None:
    _events, _discarded, _raw, usage, _unread = extract(
        [], generate=lambda m, p: ("", {}), model="m"
    )
    assert usage["truncated_batches"] == 0 and usage["retried_batches"] == 0


def test_the_cloud_reader_reports_the_same_fact(monkeypatch) -> None:
    """Rule 1: fix it at the thing, not at one call site. Both readers say when they were cut off."""
    import sys
    import types

    class _Usage:
        input_tokens = 10
        output_tokens = 3000

    class _Block:
        type = "text"
        text = "EVENT: one"

    class _Resp:
        stop_reason = "max_tokens"
        usage = _Usage()

        def __init__(self) -> None:
            self.content = [_Block()]

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **_kw: types.SimpleNamespace(  # type: ignore[attr-defined]
        messages=types.SimpleNamespace(create=lambda **kw: _Resp())
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    from qalpha.live.extraction import default_generate

    _text, usage = default_generate("sk-test")("claude-haiku-4-5", "read this")
    assert usage["truncated"] == 1
