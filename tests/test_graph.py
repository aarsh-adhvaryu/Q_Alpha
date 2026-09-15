"""The knowledge graph keeps what was known when, separates facts from inferences, and shows its sources.

What these guard: a correction received today leaves yesterday's view exactly as it was; a view never
contains an assertion from after its knowledge time or outside its valid time; an inference is never
returned as a fact; a supplier edge runs supplier → customer and a traversal finds both suppliers of
one customer with their quotes; a connection whose quote is not in the filing never enters the graph.
"""

from __future__ import annotations

import gzip
import json
import random
import types
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from qalpha.live import graph as g
from qalpha.live import graph_ingest, graph_neo4j, graph_tools, relations
from qalpha.live.extraction import CORPUS_READER_DEFAULT, EXTRACTION_VERSION
from qalpha.live.financials import Quarter

T0 = datetime(2026, 5, 1, 12, tzinfo=UTC)
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64


def _supplier(
    frm: str, to: str, *, sha: str, passage: str, known: datetime, **over: Any
) -> g.Assertion:
    base: dict[str, Any] = {
        "kind": g.EDGE,
        "label": "SUPPLIER_TO",
        "subject": g.company_id(frm),
        "subject_label": "Company",
        "object": to,
        "object_label": "Company",
        "epistemic": g.DISCLOSED,
        "source": {"doc_sha256": sha, "passage": passage},
        "known_from": known,
    }
    base.update(over)
    return g.Assertion(**base)


def _quarter(revenue: str, filed: datetime, *, end: date = date(2026, 3, 31)) -> Quarter:
    return Quarter(
        ticker="INFY",
        period_start=end - timedelta(days=90),
        period_end=end,
        filed_at=filed,
        basis="Consolidated",
        audited="Audited",
        facts={
            "revenue": Decimal(revenue),
            "profit_after_tax": Decimal("10"),
            "eps_basic": Decimal("2"),
        },
        source_url="https://nsearchives.nseindia.com/x.xml",
        sha256=SHA_A,
    )


# ---- the rules an assertion must meet ----------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"source": {"doc_sha256": SHA_A, "passage": ""}}, "verbatim passage"),
        ({"source": {"passage": "a quote with no document"}}, "document"),
        ({"epistemic": g.INFERRED, "source": {"model": "m"}}, "confidence"),
        ({"epistemic": g.COMPUTED, "source": {"inputs": "x"}}, "code version"),
        ({"subject_label": "Person"}, "runs"),  # a person cannot be a supplier in this schema
        ({"label": "LIKES"}, "unknown relationship"),
        ({"known_from": datetime(2026, 5, 1)}, "timezone"),
    ],
)
def test_an_assertion_that_breaks_the_rules_is_refused(change: dict[str, Any], why: str) -> None:
    base = _supplier("TCS", "org:acme", sha=SHA_A, passage="TCS supplies Acme", known=T0)
    fields = {**base.__dict__, **change}
    fields.pop("known_to", None)
    with pytest.raises(g.GraphError, match=why):
        g.validate(g.Assertion(**fields))


# ---- time -------------------------------------------------------------------------------------


def test_a_restatement_leaves_yesterdays_view_reproducible(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    log = g.GraphLog(path)
    counts = graph_ingest.Counts()
    graph_ingest.financial_periods(log, [_quarter("100", T0)], counts=counts)
    log.flush()
    restated = T0 + timedelta(days=30)
    graph_ingest.financial_periods(log, [_quarter("90", restated)], counts=counts)
    log.flush()

    def revenue(known: datetime, fresh: bool) -> object:
        source = g.GraphLog(path) if fresh else log
        view = source.view(valid_at=date(2026, 9, 1), known_at=known)
        return view.periods("company:INFY", "revenue")[0]["value"]

    for fresh in (False, True):  # in memory, and reloaded from the file
        assert revenue(T0 + timedelta(days=10), fresh) == "100"
        assert revenue(restated + timedelta(days=1), fresh) == "90"
    assert counts.revised >= 1


def test_ingesting_out_of_order_gives_the_same_views(tmp_path: Path) -> None:
    early, late = _quarter("100", T0), _quarter("90", T0 + timedelta(days=30))
    in_order, reversed_ = g.GraphLog(tmp_path / "a.jsonl"), g.GraphLog(tmp_path / "b.jsonl")
    for q in (early, late):
        graph_ingest.financial_periods(in_order, [q], counts=graph_ingest.Counts())
    for q in (late, early):
        graph_ingest.financial_periods(reversed_, [q], counts=graph_ingest.Counts())
    for days in (-1, 5, 29, 31, 400):
        known = T0 + timedelta(days=days)
        a = in_order.view(valid_at=date(2026, 9, 1), known_at=known).periods(
            "company:INFY", "revenue"
        )
        b = reversed_.view(valid_at=date(2026, 9, 1), known_at=known).periods(
            "company:INFY", "revenue"
        )
        assert a == b


def test_reingesting_changes_nothing(tmp_path: Path) -> None:
    log = g.GraphLog(tmp_path / "log.jsonl")
    graph_ingest.financial_periods(log, [_quarter("100", T0)], counts=graph_ingest.Counts())
    assert log.flush() > 0
    again = g.GraphLog(tmp_path / "log.jsonl")
    counts = graph_ingest.Counts()
    graph_ingest.financial_periods(again, [_quarter("100", T0)], counts=counts)
    assert again.flush() == 0 and counts.new == counts.revised == 0


def test_no_view_holds_an_assertion_from_after_its_knowledge_time_or_outside_its_valid_time(
    tmp_path: Path,
) -> None:
    rng = random.Random(7)
    log = g.GraphLog(tmp_path / "log.jsonl")
    for i in range(80):
        start = date(2025, 1, 1) + timedelta(days=rng.randint(0, 500))
        end = None if rng.random() < 0.5 else start + timedelta(days=rng.randint(1, 200))
        log.add(
            _supplier(
                f"S{i % 9}",
                f"org:c{i % 5}",
                sha=SHA_A,
                passage=f"supplies number {rng.randint(0, 3)}",
                known=T0 + timedelta(days=rng.randint(-300, 300)),
                valid_from=start,
                valid_to=end,
            )
        )
    log.retract(next(iter(log._by_key)), at=T0, reason="found wrong")
    for _ in range(40):
        valid = date(2025, 1, 1) + timedelta(days=rng.randint(0, 800))
        known = T0 + timedelta(days=rng.randint(-400, 400))
        for e in log.view(valid_at=valid, known_at=known).edges:
            assert e.known_from <= known and (e.known_to is None or known < e.known_to)
            assert (e.valid_from is None or e.valid_from <= valid) and (
                e.valid_to is None or valid < e.valid_to
            )


def test_a_retracted_fact_is_gone_from_now_on_and_still_there_before(tmp_path: Path) -> None:
    log = g.GraphLog(tmp_path / "log.jsonl")
    edge = _supplier("TCS", "org:acme", sha=SHA_A, passage="TCS supplies Acme", known=T0)
    log.add(edge)
    log.retract(edge.key, at=T0 + timedelta(days=3), reason="the filing was withdrawn")
    log.flush()
    reloaded = g.GraphLog(tmp_path / "log.jsonl")
    assert reloaded.view(valid_at=date(2026, 9, 1), known_at=T0 + timedelta(days=1)).edges
    assert not reloaded.view(valid_at=date(2026, 9, 1), known_at=T0 + timedelta(days=4)).edges


# ---- what a query returns ----------------------------------------------------------------------


def test_an_inference_is_never_returned_as_a_fact(tmp_path: Path) -> None:
    log = g.GraphLog(tmp_path / "log.jsonl")
    log.add(_supplier("TCS", "org:acme", sha=SHA_A, passage="TCS supplies Acme", known=T0))
    log.add(
        _supplier(
            "INFY",
            "org:acme",
            sha=SHA_A,
            passage="",
            known=T0,
            epistemic=g.INFERRED,
            source={"model": "qwen3.5-9b-16k", "confidence": 0.7},
        )
    )
    view = log.view(valid_at=date(2026, 9, 1), known_at=T0 + timedelta(days=1))
    assert [e.subject for e in view.suppliers_of("org:acme")] == ["company:TCS"]
    assert view.exposure(["INFY"], "org:acme") == {}
    assert [e.subject for e in view.inferred("company:INFY")] == ["company:INFY"]


def test_two_suppliers_of_one_customer_are_found_with_their_quotes(tmp_path: Path) -> None:
    log = g.GraphLog(tmp_path / "log.jsonl")
    log.add(
        _supplier("TCS", "org:acme", sha=SHA_A, passage="TCS provides services to Acme", known=T0)
    )
    log.add(
        _supplier(
            "MOTHERSON", "org:acme", sha=SHA_B, passage="Acme is our largest customer", known=T0
        )
    )
    view = log.view(valid_at=date(2026, 9, 1), known_at=T0 + timedelta(days=1))
    exposure = view.exposure(["TCS", "MOTHERSON", "INFY"], "org:acme")
    assert set(exposure) == {"TCS", "MOTHERSON"}
    step = exposure["TCS"][0][0]
    assert step["relationship"] == "SUPPLIER_TO" and step["walked"] == "forward"
    assert step["passage"] == "TCS provides services to Acme" and step["doc_sha256"] == SHA_A


def test_coverage_tells_a_recorded_gap_from_nothing_known(tmp_path: Path) -> None:
    log = g.GraphLog(tmp_path / "log.jsonl")
    log.add(_supplier("TCS", "org:acme", sha=SHA_A, passage="TCS supplies Acme", known=T0))
    log.add(g.gap("company:TCS", "OWNS", reason="shareholding not ingested", known_from=T0))
    cov = log.view(valid_at=date(2026, 9, 1), known_at=T0 + timedelta(days=1)).coverage(
        "company:TCS"
    )
    assert (
        cov["SUPPLIER_TO"] == "known"
        and cov["OWNS"] == "MISSING"
        and cov["COMPETES_WITH"] == "unknown"
    )


# ---- ingestion from the logs -------------------------------------------------------------------


def _event_row(**over: Any) -> dict[str, Any]:
    row = {
        "_key": "k1:INFY:litigation:1",
        "as_of": "2026-09-12",
        "disseminated_at": "2026-03-02T10:00:00Z",
        "doc_sha256": SHA_C,
        "doc_url": "https://nsearchives.nseindia.com/x.pdf",
        "event_date": "2026-03-02",
        "event_type": "litigation",
        "extraction_version": EXTRACTION_VERSION,
        "materiality": "high",
        "model": CORPUS_READER_DEFAULT,
        "passage": "a penalty of Rs 10 crore was imposed",
        "summary": "penalty",
        "ticker": "INFY",
        "verified": True,
    }
    row.update(over)
    return row


def test_a_filing_event_is_known_from_when_the_corpus_read_it_not_when_it_was_filed(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "announcements" / "INFY"
    archive.mkdir(parents=True)
    (archive / "1.provenance.json").write_text(json.dumps({"sha256": SHA_C}), encoding="utf-8")
    with gzip.open(archive / "1.txt.gz", "wt", encoding="utf-8") as fh:
        fh.write("Notice. a penalty of Rs 10 crore was imposed on the company.")
    log = g.GraphLog(tmp_path / "log.jsonl")
    counts = graph_ingest.Counts()
    rows = [
        _event_row(),
        _event_row(_key="k2", verified=False),
        _event_row(_key="k3", model="other"),
    ]
    graph_ingest.filing_events(
        log, rows, archive=graph_ingest.ArchiveText(tmp_path / "announcements"), counts=counts
    )
    assert sum(counts.skipped.values()) == 2
    march = log.view(
        valid_at=date(2026, 9, 12), known_at=graph_ingest.end_of_day(date(2026, 3, 31))
    )
    september = log.view(
        valid_at=date(2026, 9, 12), known_at=graph_ingest.end_of_day(date(2026, 9, 12))
    )
    assert march.about("company:INFY") == []
    assert september.about("company:INFY") == ["event:k1:INFY:litigation:1"]
    passage = next(a for a in september.nodes.values() if a.label == "Passage")
    assert passage.source["offsets"] == "exact" and passage.source["offset_start"] == 8


def test_decisions_become_theses_revisions_and_citations(tmp_path: Path) -> None:
    log = g.GraphLog(tmp_path / "log.jsonl")
    graph_ingest.filing_events(
        log,
        [_event_row(as_of="2026-09-01")],
        archive=graph_ingest.ArchiveText(tmp_path),
        counts=graph_ingest.Counts(),
    )
    decided = [
        {
            "as_of": "2026-09-15",
            "ticker": "INFY.NS",
            "digest": "d1",
            "version": "AI-PM-2",
            "action": "HOLD",
            "thesis": "steady cash",
            "invalidate_if": "margins fall",
            "evidence_ids": ["k1:INFY:litigation:1", "price:INFY.NS"],
        },
        {
            "as_of": "2026-09-16",
            "ticker": "INFY.NS",
            "digest": "d2",
            "version": "AI-PM-2",
            "action": "HOLD",
            "thesis": "steady cash, penalty small",
            "invalidate_if": "margins fall",
            "evidence_ids": ["nope"],
        },
    ]
    counts = graph_ingest.Counts()
    graph_ingest.decisions(log, decided, counts=counts)
    view = log.view(valid_at=date(2026, 9, 20), known_at=graph_ingest.end_of_day(date(2026, 9, 20)))
    cites = {e.object for e in view.facts() if e.label == "CITES"}
    assert cites == {"event:k1:INFY:litigation:1", "company:INFY"}
    assert counts.skipped == {"decision cites an id the graph does not hold": 1}
    revised = [e for e in view.facts() if e.label == "REVISED_TO"]
    assert [(e.subject, e.object) for e in revised] == [
        ("thesis:INFY:2026-09-15", "thesis:INFY:2026-09-16")
    ]
    # a thesis is the investor's belief: never an event about the company
    assert view.about("company:INFY") == ["event:k1:INFY:litigation:1"]


# ---- reading connections -----------------------------------------------------------------------

FILING = (
    "Tata Consultancy Services Limited informs that it has entered into an agreement to provide cloud "
    "services to Acme Motors Inc, which contributed 12.5% of revenue last year. "
    "Infosys Limited holds 5% of Beta Ltd."
)


def _parse(reply: str) -> relations.Result:
    return relations.parse(
        reply,
        text=FILING,
        filer="TCS",
        doc_sha256=SHA_A,
        doc_url="u",
        known_from=T0,
        resolver=relations.Resolver(
            {"TCS.NS": ("Tata Consultancy Services",), "INFY.NS": ("Infosys",)}
        ),
        reader="qwen3.5-9b-16k",
    )


def test_a_connection_is_kept_only_with_its_verbatim_quote() -> None:
    reply = "\n".join(
        [
            "RELATION: from=SELF; type=SUPPLIER_TO; to=Acme Motors Inc; pct=12.5; amount_inr=-; since=-; "
            'passage="to provide cloud services to Acme Motors Inc, which contributed 12.5% of revenue"',
            "RELATION: from=SELF; type=SUPPLIER_TO; to=Acme Motors Inc; pct=-; amount_inr=-; since=-; "
            'passage="TCS is a key vendor for Acme"',  # a paraphrase
            "RELATION: from=Infosys; type=OWNS; to=Beta Ltd; pct=5; amount_inr=-; since=-; "
            'passage="Infosys Limited holds 5% of Beta Ltd."',  # neither end is the filer
            "RELATION: from=SELF; type=LOVES; to=Acme Motors Inc; pct=-; amount_inr=-; since=-; "
            'passage="to provide cloud services to Acme Motors Inc"',
            "RELATION: from=SELF; type=SUPPLIER_TO; to=Acme Motors Inc; pct=40; amount_inr=-; since=-; "
            'passage="to provide cloud services to Acme Motors Inc"',  # 40 is not in the quote
        ]
    )
    result = _parse(reply)
    edges = [a for a in result.assertions if a.kind == g.EDGE]
    assert len(edges) == 2
    first = edges[0]
    assert (first.subject, first.label, first.object) == (
        "company:TCS",
        "SUPPLIER_TO",
        "org:acme-motors-inc",
    )
    assert first.props["pct"] == 12.5 and first.epistemic == g.DISCLOSED
    assert "pct" not in edges[1].props
    assert result.dropped == {
        "quote not verbatim in the document": 1,
        "connection between two other parties": 1,
        "type not in the schema": 1,
        "percentage not in the quote (connection kept without it)": 1,
    }
    for a in result.assertions:
        g.validate(a)


def test_reading_connections_is_resumable_and_records_each_read(tmp_path: Path) -> None:
    from qalpha.live.announcements import Announcement, SourceDocument
    from qalpha.live.evidence import Provenance

    ann = Announcement(
        symbol="TCS",
        seq_id="1",
        subject="Updates",
        summary="",
        disseminated_at=T0,
        attachment_url="u",
    )
    prov = Provenance(
        source_url="u",
        retrieved_at_utc=T0,
        http_status=200,
        sha256=SHA_A,
        byte_length=10,
        document_date=date(2026, 5, 1),
    )
    doc = SourceDocument(announcement=ann, text=FILING, provenance=prov)
    reply = (
        "RELATION: from=SELF; type=SUPPLIER_TO; to=Acme Motors Inc; pct=-; amount_inr=-; since=-; "
        'passage="to provide cloud services to Acme Motors Inc"'
    )
    log = g.GraphLog(tmp_path / "log.jsonl")
    row = relations.read_document(
        doc,
        generate=lambda m, p: (reply, {"input": 1, "output": 1}),
        model="qwen3.5-9b-16k",
        resolver=relations.Resolver({}),
        log=log,
        max_chars=100_000,
    )
    assert row["kept"] == 1 and row["complete"]
    assert relations.already_read("qwen3.5-9b-16k") == {SHA_A}
    edge = next(a for a in log.versions.values() if a.kind == g.EDGE)
    assert edge.known_from >= datetime.now(UTC) - timedelta(
        minutes=5
    )  # known from when it was read


# ---- Neo4j -------------------------------------------------------------------------------------


def test_neo4j_sync_writes_every_edge_version_with_schema_types_only(tmp_path: Path) -> None:
    log = g.GraphLog(tmp_path / "log.jsonl")
    graph_ingest.financial_periods(log, [_quarter("100", T0)], counts=graph_ingest.Counts())
    passage = "Acme contributed 10% of revenue; later 12% of revenue"
    log.add(_supplier("TCS", "org:acme", sha=SHA_A, passage=passage, known=T0, props={"pct": 10}))
    log.add(
        _supplier(
            "TCS",
            "org:acme",
            sha=SHA_A,
            passage=passage,
            known=T0 + timedelta(days=30),
            props={"pct": 12},
        )
    )
    statements = graph_neo4j.sync_statements(log)
    texts = " ".join(t for t, _ in statements)
    assert "[r:REPORTED]" in texts and "[r:SUPPLIER_TO]" in texts
    supplied = [row for t, p in statements if "[r:SUPPLIER_TO]" in t for row in p["rows"]]
    assert len(supplied) == 2  # both versions, each with its own knowledge interval
    first = min(supplied, key=lambda r: r["known_from"])
    assert first["known_to"] == (T0 + timedelta(days=30)).isoformat()


def test_neo4j_templates_bind_every_value_as_a_parameter() -> None:
    captured: list[tuple[str, dict[str, Any]]] = []

    class Session:
        def __enter__(self) -> Session:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def run(self, text: str, params: dict[str, Any]) -> list[dict[str, Any]]:
            captured.append((text, params))
            return [{"supplier": "company:TCS"}]

    driver = types.SimpleNamespace(session=lambda **_: Session())
    rows = graph_neo4j.run(
        driver,
        "suppliers_of",
        {"customer": "org:acme'}) DETACH DELETE n //"},
        valid_at=date(2026, 9, 1),
        known_at=T0,
    )
    assert rows == [{"supplier": "company:TCS"}]
    text, params = captured[0]
    assert "DETACH" not in text and params["customer"].startswith("org:acme")
    assert params["classes"] == list(g.FACTS)
    for template in graph_neo4j.TEMPLATES.values():
        assert "$" in template and "{rel" not in template  # parameters only; no Python placeholders
    with pytest.raises(KeyError):
        graph_neo4j.run(driver, "MATCH (n) DELETE n", {}, valid_at=date(2026, 9, 1), known_at=T0)


def test_neo4j_without_a_password_is_said_to_be_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(graph_neo4j.PASSWORD_VAR, "")
    monkeypatch.setattr("qalpha.live.credentials.load_env", lambda *a, **k: None)
    with pytest.raises(graph_neo4j.Neo4jUnavailableError):
        graph_neo4j.connect()


# ---- the investor's graph tools ----------------------------------------------------------------


def test_graph_tools_answer_in_scope_with_quotes_and_refuse_outside_it(tmp_path: Path) -> None:
    log = g.GraphLog(tmp_path / "log.jsonl")
    log.add(_supplier("TCS", "org:acme", sha=SHA_A, passage="TCS supplies Acme", known=T0))
    view = log.view(valid_at=date(2026, 9, 1), known_at=T0 + timedelta(days=1))
    answers = graph_tools.answer(
        [
            {"tool": "connections", "ticker": "TCS"},
            {"tool": "exposure", "entity": "acme"},
            {"tool": "connections", "ticker": "RELIANCE"},
        ],
        view=view,
        names=["TCS", "INFY"],
        limit=6,
    )
    assert answers[0]["result"]["connections"][0]["path"][0]["passage"] == "TCS supplies Acme"
    assert set(answers[1]["result"]["paths"]) == {"TCS"}
    assert "not held or shown" in answers[2]["error"]
    assert graph_tools.cited_assertions(answers) == {log.current(next(iter(log._by_key))).id}  # type: ignore[union-attr]
