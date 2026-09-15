"""EX-5: readers are judged against a reference that is itself checked, under a rule set in advance.

What these guard: a triage rule that would hide a material filing is caught; a research job cannot
spend past its own ceiling or touch the operating cap; a batch that fails or never reports releases
its money; a reference the user found incomplete selects nobody; and the cheapest reader that meets
every threshold wins — not the one with the best headline number.
"""

from __future__ import annotations

import csv
import gzip
import json
import types
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from qalpha.live import reader_scoring, readers, reference, spend, triage
from qalpha.live.announcements import Announcement, SourceDocument
from qalpha.live.evidence import Provenance

TEXT = (
    "Sub: Disclosure under Regulation 30.\n\n"
    "The Board of Directors has approved the acquisition of a 51% stake in Acme Bottling Private "
    "Limited for a consideration of INR 4,200 million, subject to regulatory approvals.\n"
    "The statutory auditor has resigned with immediate effect citing pre-occupation."
)
ACQUISITION = "approved the acquisition of a 51% stake in Acme Bottling Private Limited"
AUDITOR = "The statutory auditor has resigned with immediate effect"


def _doc(sha: str = "a" * 64, symbol: str = "VBL", text: str = TEXT) -> SourceDocument:
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


def _sample_doc(sha: str, group: str = "ordinary", **over: Any) -> readers.SampleDoc:
    base = readers.SampleDoc(
        sha256=sha,
        symbol="VBL",
        seq_id=sha[-6:],
        subject="General Updates",
        chars=2_000,
        sector="FMCG",
        group=group,
        triage_rule="",
    )
    return replace(base, **over)


# ---- triage -------------------------------------------------------------------------------------


def test_triage_skips_short_routine_notices_and_reads_everything_else() -> None:
    assert triage.classify("Trading Window-XBRL", 1_200).routine
    # the same subject over its ceiling is read: a transcript can hide behind an intimation subject
    long = triage.classify("Analysts/Institutional Investor Meet/Con. Call Updates", 90_000)
    assert not long.routine and "ceiling" in long.rule
    # ambiguous subjects are always read, however short
    assert not triage.classify("General Updates", 300).routine
    # unknown is read, never skipped
    assert not triage.classify("", 100).routine
    assert triage.classify("Trading Window", 10).status == triage.ROUTINE != triage.READ


def test_a_failed_rule_is_removed_and_its_filings_are_read_again() -> None:
    rules = triage.without({"trading-window"})
    assert not triage.classify("Trading Window", 100, rules=rules).routine
    assert triage.classify("Copy of Newspaper Publication", 100, rules=rules).routine


# ---- the sample ---------------------------------------------------------------------------------


def _archive(tmp_path: Path) -> tuple[Path, Path]:
    archive = tmp_path / "announcements"
    specs = [("ITC", "Trading Window", 800)] * 40 + [
        ("HDFCBANK", "Investor Presentation", 45_000)
    ] * 40
    specs += [("IOC" if i % 2 else "ITC", "Updates", 3_000) for i in range(120)]
    for i, (sym, subject, chars) in enumerate(specs):
        folder = archive / sym
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{i}.provenance.json").write_text(
            json.dumps(
                {"symbol": sym, "subject": subject, "seq_id": str(i), "sha256": f"{i:064d}"}
            ),
            encoding="utf-8",
        )
        with gzip.open(folder / f"{i}.txt.gz", "wt", encoding="utf-8") as fh:
            fh.write("x" * chars)
    # a scan with no text layer is not a fair test of a text reader
    (archive / "ITC" / "999.provenance.json").write_text(
        json.dumps({"symbol": "ITC", "sha256": "f" * 64}), encoding="utf-8"
    )
    watchlist = tmp_path / "watchlist.csv"
    watchlist.write_text(
        "ticker,sector\nITC.NS,FMCG\nHDFCBANK.NS,BANK\nIOC.NS,ENERGY\n", encoding="utf-8"
    )
    return archive, watchlist


def test_the_sample_is_stratified_fixed_and_leaves_out_scans(tmp_path: Path) -> None:
    archive, watchlist = _archive(tmp_path)
    pool = readers.candidates_in_archive(archive, watchlist)
    assert len(pool) == 200 and "f" * 64 not in {d.sha256 for d in pool}
    chosen = readers.select_sample(pool)
    groups = {g: sum(1 for d in chosen if d.group == g) for g in ("routine", "long", "ordinary")}
    assert groups == {"routine": readers.QUOTA_ROUTINE, "long": readers.QUOTA_LONG, "ordinary": 95}
    ordinary_sectors = {d.sector for d in chosen if d.group == "ordinary"}
    assert ordinary_sectors == {"FMCG", "ENERGY"}  # sectors taken in turn, not one filer's pile
    assert [d.sha256 for d in readers.select_sample(pool)] == [d.sha256 for d in chosen]
    readers.save_sample(chosen)
    assert readers.load_sample() == chosen


# ---- research money -----------------------------------------------------------------------------


def test_a_research_job_is_capped_by_its_own_budget_and_never_by_the_operating_cap(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ledger.jsonl"
    limits = spend.Limits(cap_usd=Decimal("1"), decisions_reserve_usd=Decimal("1"))
    # The operating reading partition has $0 here, and research still proceeds within its own job.
    job = spend.Ledger(path, limits=limits, job="ex5-reference", job_limit_usd=Decimal("3"))
    one = job.reserve(
        partition=spend.RESEARCH, model="claude-opus-5", input_ceiling=400_000, max_output=0
    )
    assert one.usd == Decimal("2")  # $5/M, 400k tokens
    with pytest.raises(spend.BudgetExceededError):
        job.reserve(
            partition=spend.RESEARCH, model="claude-opus-5", input_ceiling=400_000, max_output=0
        )
    # Batch is half price, so the same request now fits.
    two = job.reserve(
        partition=spend.RESEARCH,
        model="claude-opus-5",
        input_ceiling=400_000,
        max_output=0,
        batch=True,
    )
    assert two.usd == Decimal("1") and job.reservation(two.id) == two
    # Research is not counted against the month's operating partitions.
    assert job.state(one.month).committed() == Decimal("0")
    # A later process sees the same total, and a release frees it.
    again = spend.Ledger(path, limits=limits, job="ex5-reference", job_limit_usd=Decimal("3"))
    assert again.job_committed("ex5-reference") == Decimal("3")
    again.release(one, "test")
    assert again.job_committed("ex5-reference") == Decimal("1")


def test_research_without_a_named_budget_is_refused(tmp_path: Path) -> None:
    ledger = spend.Ledger(tmp_path / "ledger.jsonl")
    with pytest.raises(spend.BudgetExceededError):
        ledger.reserve(
            partition=spend.RESEARCH, model="claude-opus-5", input_ceiling=10, max_output=10
        )


def test_a_provider_with_no_batch_price_cannot_be_reserved_as_batch(tmp_path: Path) -> None:
    ledger = spend.Ledger(tmp_path / "ledger.jsonl", job="j", job_limit_usd=Decimal("5"))
    with pytest.raises(spend.NoBatchPriceError):
        ledger.reserve(
            partition=spend.RESEARCH,
            model="deepseek-flash",
            input_ceiling=10,
            max_output=10,
            batch=True,
        )


# ---- reference batches --------------------------------------------------------------------------


class FakeBatches:
    """Records what was submitted; returns scripted results."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.results_by_id: dict[str, list[Any]] = {}

    def create(self, *, requests: list[dict[str, Any]]) -> Any:
        self.created.append({"requests": requests})
        return types.SimpleNamespace(id=f"batch-{len(self.created)}")

    def retrieve(self, batch_id: str) -> Any:
        return types.SimpleNamespace(processing_status="ended")

    def results(self, batch_id: str) -> list[Any]:
        return self.results_by_id.get(batch_id, [])


def _client() -> Any:
    batches = FakeBatches()
    return types.SimpleNamespace(messages=types.SimpleNamespace(batches=batches)), batches


def _succeeded(
    custom_id: str, text: str, model: str = "claude-opus-5", stop: str = "end_turn"
) -> Any:
    message = types.SimpleNamespace(
        model=model,
        stop_reason=stop,
        usage=types.SimpleNamespace(input_tokens=1_000, output_tokens=500),
        content=[types.SimpleNamespace(type="text", text=text)],
    )
    return types.SimpleNamespace(
        custom_id=custom_id, result=types.SimpleNamespace(type="succeeded", message=message)
    )


def _event_line(passage: str, kind: str = "acquisition", materiality: str = "high") -> str:
    return (
        f"EVENT: ticker=VBL; type={kind}; date=2026-08-25; materiality={materiality}; "
        f'passage="{passage}"; summary=s; uncertainty=none'
    )


def test_reference_batches_settle_what_succeeded_and_release_what_did_not() -> None:
    docs = [_doc("a" * 64), _doc("b" * 64)]
    ledger = spend.Ledger(job=reference.REFERENCE_JOB, job_limit_usd=Decimal("5"))
    client, batches = _client()
    items = [
        (
            f"ref-{d.provenance.sha256[:48]}",
            reference.reference_prompt(d),
            {"doc_sha256": d.provenance.sha256},
        )
        for d in reference.pending_reference(docs)
    ]
    record = reference.submit("reference", items, client=client, ledger=ledger)
    assert record is not None and len(record["requests"]) == 2
    params = batches.created[0]["requests"][0]["params"]
    assert params["model"] == "claude-opus-5" and params["thinking"] == {"type": "adaptive"}
    # in flight: not offered again
    assert reference.pending_reference(docs) == []

    first, second = sorted(record["requests"])
    batches.results_by_id[record["batch_id"]] = [
        _succeeded(first, _event_line(ACQUISITION) + "\n" + _event_line("an invented quote here")),
        # the second request never reports: its money must not be held for ever
    ]
    lines = reference.collect(client=client, ledger=ledger, documents=docs)
    assert "1 succeeded, 1 failed" in lines[0]
    rows = reference._jsonl(reference.events_path())
    assert len(rows) == 1 and rows[0]["complete"] and rows[0]["discarded"] == 1
    assert [e["passage"] for e in rows[0]["events"]] == [ACQUISITION]
    # settled at the batch price of the actual tokens; the unreported one released
    expected = spend.cost("claude-opus-5", 1_000, 500, batch=True)
    assert ledger.job_committed(reference.REFERENCE_JOB) == expected
    # the unreported document goes back to the queue
    assert [d.provenance.sha256 for d in reference.pending_reference(docs)] == [
        second[4:] + "b" * 16
    ]


def test_a_truncated_reading_is_kept_but_not_complete() -> None:
    doc = _doc()
    ledger = spend.Ledger(job=reference.REFERENCE_JOB, job_limit_usd=Decimal("5"))
    client, batches = _client()
    record = reference.submit(
        "reference",
        [("ref-x", reference.reference_prompt(doc), {"doc_sha256": doc.provenance.sha256})],
        client=client,
        ledger=ledger,
    )
    assert record is not None
    batches.results_by_id[record["batch_id"]] = [
        _succeeded("ref-x", _event_line(ACQUISITION), stop="max_tokens")
    ]
    reference.collect(client=client, ledger=ledger, documents=[doc])
    assert reference.pending_reference([doc]) == [doc]


def test_submit_stops_at_the_budget_and_a_failed_create_releases_everything() -> None:
    doc = _doc()
    prompt = reference.reference_prompt(doc)
    worst = spend.worst_case(
        "claude-opus-5",
        spend.text_input_ceiling(prompt),
        reference.REFERENCE_MAX_TOKENS,
        batch=True,
    )
    ledger = spend.Ledger(job=reference.REFERENCE_JOB, job_limit_usd=worst * Decimal("1.5"))
    client, batches = _client()
    items = [(f"ref-{i}", prompt, {"doc_sha256": doc.provenance.sha256}) for i in range(3)]
    record = reference.submit("reference", items, client=client, ledger=ledger)
    assert record is not None and list(record["requests"]) == ["ref-0"]

    def boom(**_: Any) -> Any:
        raise RuntimeError("network")

    batches.create = boom  # type: ignore[method-assign]
    before = ledger.job_committed(reference.REFERENCE_JOB)
    fresh = spend.Ledger(job="other", job_limit_usd=worst * 3)
    with pytest.raises(RuntimeError):
        reference.submit("reference", items, client=client, ledger=fresh)
    assert fresh.job_committed("other") == Decimal("0")
    assert ledger.job_committed(reference.REFERENCE_JOB) == before


def test_a_different_returned_model_stops_collection() -> None:
    from qalpha.live.model_identity import ModelChangedError

    doc = _doc()
    ledger = spend.Ledger(job=reference.REFERENCE_JOB, job_limit_usd=Decimal("5"))
    client, batches = _client()
    record = reference.submit(
        "reference",
        [("ref-x", reference.reference_prompt(doc), {"doc_sha256": doc.provenance.sha256})],
        client=client,
        ledger=ledger,
    )
    assert record is not None
    batches.results_by_id[record["batch_id"]] = [_succeeded("ref-x", "", model="claude-opus-4-8")]
    with pytest.raises(ModelChangedError):
        reference.collect(client=client, ledger=ledger, documents=[doc])


def test_verdict_lines_are_parsed_and_a_malformed_true_is_a_gap_not_a_false() -> None:
    claims = [{"passage": "p"}] * 4
    text = (
        "CLAIM 1: verdict=TRUE; type=acquisition; materiality=high; reason=disclosed\n"
        "CLAIM 2: verdict=FALSE; type=other; materiality=-; reason=not in the document\n"
        "CLAIM 3: verdict=TRUE; type=made_up; materiality=high; reason=bad type\n"
        "CLAIM 9: verdict=TRUE; type=acquisition; materiality=high; reason=no such claim\n"
    )
    verdicts = reference.parse_verdicts(text, claims)
    assert set(verdicts) == {1, 2}
    assert verdicts[1]["materiality"] == "high" and verdicts[2]["verdict"] == "FALSE"


# ---- scoring and the rule -----------------------------------------------------------------------


def _adj(
    sha: str,
    passage: str,
    verdict: str,
    sources: list[str],
    materiality: str = "high",
    kind: str = "acquisition",
) -> dict[str, Any]:
    return {
        "claim_id": reference.claim_id(sha, kind, passage),
        "doc_sha256": sha,
        "event_type": kind,
        "passage": passage,
        "sources": sources,
        "adjudicated": {
            "verdict": verdict,
            "event_type": kind,
            "materiality": materiality,
            "reason": "r",
        },
    }


def _run(
    slug: str,
    kind: str,
    events: list[tuple[str, str, str]],
    done: int,
    usd: str = "0",
    discarded: int = 0,
) -> dict[str, Any]:
    return {
        "reader": slug,
        "kind": kind,
        "done": [f"{i:064d}" for i in range(done)],
        "events": [
            {
                "doc_sha256": sha,
                "event_type": k,
                "passage": p,
                "materiality": "high",
                "verified": True,
            }
            for sha, k, p in events
        ],
        "segments": [
            {
                "usage": {"calls": 3, "failed_batches": 0},
                "usd": usd,
                "seconds": 10,
                "discarded": discarded,
                "tokens_per_second": 40.0,
                "peak_vram_mb": 9000,
            }
        ],
    }


def test_the_same_event_quoted_differently_is_one_event() -> None:
    sha = "a" * 64
    a = {"doc_sha256": sha, "event_type": "acquisition", "passage": ACQUISITION}
    b = {**a, "passage": "The Board of Directors has " + ACQUISITION + " for a consideration"}
    assert reader_scoring.same_event(a, b)
    assert not reader_scoring.same_event(a, {**a, "event_type": "divestment"})
    assert not reader_scoring.same_event(a, {**a, "passage": AUDITOR})


def test_scores_count_false_and_unverifiable_claims_against_the_reader() -> None:
    sha = "a" * 64
    adjudications = [
        _adj(sha, ACQUISITION, "TRUE", ["claude-opus-5", "cheap"]),
        _adj(sha, AUDITOR, "TRUE", ["claude-opus-5"], kind="auditor_change"),
        _adj(sha, "a quote that is in the text but no event", "FALSE", ["cheap"], kind="other"),
    ]
    refs = reader_scoring.build_reference(adjudications)
    assert len(refs) == 2
    run = _run(
        "cheap",
        "deepseek",
        [
            (sha, "acquisition", ACQUISITION),
            (sha, "other", "a quote that is in the text but no event"),
        ],
        done=150,
        usd="0.30",
        discarded=2,
    )
    s = reader_scoring.score_reader(run, refs, adjudications)
    assert s.claims == 4 and s.verified == 2 and s.true_claims == 1
    assert s.precision == 0.25 and s.verbatim == 0.5
    assert s.recall_high == 0.5
    assert s.usd_per_filing(150) == Decimal("0.002")


def _score(
    slug: str,
    *,
    recall: float,
    precision: float = 0.95,
    verbatim: float = 0.95,
    usd: str = "0",
    kind: str = "deepseek",
    done: int = 150,
) -> reader_scoring.Score:
    claims = 100
    return reader_scoring.Score(
        reader=slug,
        kind=kind,
        documents_done=done,
        claims=claims,
        verified=int(verbatim * claims),
        true_claims=int(precision * claims),
        unadjudicated=0,
        recall_high=recall,
        recall_medium=0.8,
        failed_batches=0,
        calls=10,
        usd=Decimal(usd),
        seconds=1.0,
        tokens_per_second=None,
        peak_vram_mb=None,
        peak_ram_mb=None,
    )


GOOD = reader_scoring.Validation(
    human_documents=20, human_events=30, omitted=1, claim_checks=25, disagreements=1
)


def test_the_cheapest_reader_meeting_every_threshold_wins() -> None:
    scores = [
        _score("sonnet", recall=0.97, usd="3.00", kind="anthropic"),
        _score("flash", recall=0.90, usd="0.20"),
        _score("qwen", recall=0.80, usd="0", kind="local"),  # free, but below the absolute floor
        _score("gemma", recall=0.95, precision=0.70, kind="local"),  # free, but imprecise
    ]
    sel = reader_scoring.select(scores, GOOD, 150)
    assert sel.decided and sel.winner == "flash"
    assert set(sel.qualified) == {"sonnet", "flash"}
    assert sel.reasons["qwen"] and sel.reasons["gemma"]


def test_a_reader_far_behind_the_best_does_not_qualify_even_above_the_floor() -> None:
    scores = [_score("best", recall=1.0, usd="3"), _score("cheap", recall=0.86, usd="0.1")]
    sel = reader_scoring.select(scores, GOOD, 150)
    assert sel.winner == "best" and "x best" in sel.reasons["cheap"][0]


def test_an_unfinished_run_cannot_win() -> None:
    sel = reader_scoring.select(
        [_score("half", recall=1.0, done=70), _score("full", recall=0.9, usd="1")], GOOD, 150
    )
    assert sel.winner == "full"


def test_when_nobody_qualifies_the_best_recall_is_named_and_the_shortfall_recorded() -> None:
    sel = reader_scoring.select(
        [_score("a", recall=0.6), _score("b", recall=0.7, usd="2")], GOOD, 150
    )
    assert sel.decided and sel.qualified == [] and sel.winner == "b"


@pytest.mark.parametrize(
    "validation",
    [
        replace(GOOD, omitted=6),  # 20% of the events you found were missing from the reference
        replace(GOOD, disagreements=5),  # the judge was wrong on 20% of the checks
        replace(GOOD, human_documents=12),  # the checks were not done
        replace(GOOD, claim_checks=0, disagreements=0),
    ],
)
def test_a_reference_that_fails_the_users_checks_selects_nobody(
    validation: reader_scoring.Validation,
) -> None:
    sel = reader_scoring.select([_score("flash", recall=0.95)], validation, 150)
    assert not sel.decided and sel.winner is None and sel.why_not_decided


def test_the_users_omissions_are_measured_against_the_model_built_reference() -> None:
    sha = "a" * 64
    model_ref = reader_scoring.build_reference([_adj(sha, ACQUISITION, "TRUE", ["claude-opus-5"])])
    human = [
        {
            "doc_sha256": sha,
            "event_type": "acquisition",
            "materiality": "high",
            "passage": ACQUISITION,
        },
        {
            "doc_sha256": sha,
            "event_type": "auditor_change",
            "materiality": "high",
            "passage": AUDITOR,
        },
        {"doc_sha256": sha, "event_type": "other", "materiality": "low", "passage": "not counted"},
    ]
    v = reader_scoring.validate(model_ref, human, {sha}, [{"your_verdict": "agree"}])
    assert v.human_events == 2 and v.omitted == 1 and v.omission_rate == 0.5
    # the event every model missed still enters the reference, so readers are judged on it too
    full = reader_scoring.build_reference(
        [_adj(sha, ACQUISITION, "TRUE", ["claude-opus-5"])], human
    )
    assert any(c.event_type == "auditor_change" and c.sources == {"human"} for c in full)


def test_worksheets_record_what_the_user_read_and_checked() -> None:
    sample = [_sample_doc(f"{i:064d}", group="long" if i < 6 else "ordinary") for i in range(30)]
    chosen = reader_scoring.choose_human_documents(sample)
    assert len(chosen) == 20  # no routine documents here: the shortfall comes from the rest
    assert sum(1 for d in chosen if d.group == "long") >= 5
    docs = [_doc(d.sha256) for d in chosen]
    reader_scoring.write_omission_worksheet(docs, chosen)
    assert len(list((reader_scoring.human_dir() / "documents").glob("*.txt"))) == 20
    assert reader_scoring.read_human_documents() == set()  # nothing marked read yet

    with reader_scoring.documents_path().open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows[0]["read_by_you"] = "yes"
    with reader_scoring.documents_path().open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert reader_scoring.read_human_documents() == {rows[0]["sha256"]}

    with reader_scoring.omissions_path().open("a", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerow([rows[0]["sha256"], "auditor_change", "High", AUDITOR, ""])
    assert reader_scoring.read_human_events()[0]["materiality"] == "high"

    reference._append(reference.adjudications_path(), [_adj("a" * 64, ACQUISITION, "TRUE", ["x"])])
    path = reader_scoring.write_claim_worksheet()
    assert path is not None and reader_scoring.read_claim_checks() == []


def test_a_triage_rule_hiding_a_material_event_fails() -> None:
    routine = _sample_doc("1" * 64, group="routine", subject="Trading Window", chars=900)
    notice = _sample_doc(
        "2" * 64, group="routine", subject="Copy of Newspaper Publication", chars=900
    )
    clusters = reader_scoring.build_reference(
        [
            _adj("1" * 64, "the trading window closes and the auditor resigned", "TRUE", ["x"]),
            _adj(
                "2" * 64,
                "a routine notice of the results date",
                "TRUE",
                ["x"],
                materiality="low",
                kind="other",
            ),
        ]
    )
    check = reader_scoring.triage_check([routine, notice], clusters)
    assert check["trading-window"] == {"documents": 1, "high": 1, "medium": 0}
    assert reader_scoring.failed_triage_rules(check) == {"trading-window"}


def test_the_report_says_not_decided_when_the_reference_is_unchecked() -> None:
    bad = replace(GOOD, human_documents=0)
    scores = [_score("flash", recall=0.95)]
    sel = reader_scoring.select(scores, bad, 150)
    text = reader_scoring.render_report(
        scores,
        sel,
        bad,
        {"trading-window": {"documents": 0, "high": 0, "medium": 0}},
        sample_size=150,
        reference_events=10,
    )
    assert "NOT DECIDED" in text and "Selected" not in text
    assert "untested" in text


# ---- the command line ---------------------------------------------------------------------------


def test_paid_steps_refuse_without_a_budget(capsys: pytest.CaptureFixture[str]) -> None:
    import importlib.util

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("readers_cli", root / "scripts" / "readers.py")
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    readers.save_sample([_sample_doc("a" * 64)])
    assert cli.main(["read", "--reader", "deepseek-flash"]) == 2
    assert "--budget-usd" in capsys.readouterr().err
    assert cli.main(["reference", "submit"]) == 2
    assert cli.main(["sample"]) == 1  # a sample is never silently redrawn


def test_one_pdf_filed_under_two_announcements_is_one_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read once, counted once: a reader that read it is not marked short of the sample."""
    from qalpha.live import announcements

    doc = _doc("a" * 64)
    monkeypatch.setattr(announcements, "load_document", lambda ann: (doc.text, doc.provenance))
    sample = [
        _sample_doc("a" * 64, seq_id="106517358", subject="Change in Director(s)"),
        _sample_doc("a" * 64, seq_id="106517331", subject="Updates"),
    ]
    documents, problems = readers.load_documents(sample)
    assert len(documents) == 1 and problems == []
    assert readers.unique_documents(sample) == 1
    sel = reader_scoring.select(
        [_score("r", recall=0.95, done=1)], GOOD, readers.unique_documents(sample)
    )
    assert sel.winner == "r" and sel.qualified == ["r"]
