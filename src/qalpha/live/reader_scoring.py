"""Score the readers against a validated reference, and apply the rule registered before any run.

**The reference is three things combined.** Opus 5's complete readings; every candidate's claim that
Opus adjudicated TRUE (so events Opus missed are included); and the material events the user found
reading complete documents end to end (so events *every* model missed are included for those
documents).

**The reference is validated before it judges anyone.** Two numbers, both from the user's own checks:

* **omission rate** — of the high and medium events the user found in complete documents, the share
  the model-built reference had no match for. It bounds every recall figure: a reference that misses
  a fifth of what is there cannot certify a reader at 85% recall.
* **adjudicator disagreement** — of the random adjudications the user checked, the share the user
  judged wrong.

Either above its ceiling and **nothing is selected**: the reference is rebuilt, not the readers judged.

**Matching events.** Two claims are the same event when they are about the same document, have the
same (adjudicated) type, and their passages overlap — one contains the other, or they share at least
:data:`OVERLAP` of their words. Readers quote the same disclosure differently, and demanding identical
quotes would score a correct reader as blind.

**Per reader:** precision = TRUE claims / all claims (a quote not in the document counts as a false
claim — it is the one unambiguous error); verbatim rate; recall against reference events of high and
of medium materiality separately; failed-batch rate; cost per filing; and, locally, tokens per second
and peak memory. Unadjudicated claims are excluded from precision and reported, never assumed true.

**Triage** is checked on the same reference: any rule whose routine documents contain a high event,
or more than :data:`TRIAGE_MAX_MEDIUM` medium events, is removed from the rule set.
"""

from __future__ import annotations

import csv
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from qalpha.live import readers, reference, triage

# ---- the pre-registered thresholds (reports/PREREGISTRATION_EX5_READERS.md) ---------------------

MIN_RECALL_HIGH = 0.85
RELATIVE_RECALL_HIGH = 0.90
MIN_PRECISION = 0.85
MIN_VERBATIM = 0.90
MAX_REFERENCE_OMISSION = 0.10
MAX_ADJUDICATOR_DISAGREEMENT = 0.10
MIN_HUMAN_DOCUMENTS = 20
MIN_CLAIM_CHECKS = 25
TRIAGE_MAX_MEDIUM = 1
OVERLAP = 0.30

HUMAN_SEED = 20260915


def human_dir() -> Path:
    return readers.READERS_DIR / "human"


def omissions_path() -> Path:
    return human_dir() / "omissions.csv"


def claim_checks_path() -> Path:
    return human_dir() / "claim_checks.csv"


def documents_path() -> Path:
    return human_dir() / "documents.csv"


# ---- matching -----------------------------------------------------------------------------------


def _words(text: str) -> set[str]:
    from qalpha.live.extraction import normalise

    return {w for w in normalise(text).split() if len(w) > 2}


def same_event(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Same document, same type, overlapping passages."""
    from qalpha.live.extraction import normalise

    if a["doc_sha256"] != b["doc_sha256"] or a["event_type"] != b["event_type"]:
        return False
    pa, pb = normalise(a["passage"]), normalise(b["passage"])
    if pa and pb and (pa in pb or pb in pa):
        return True
    wa, wb = _words(a["passage"]), _words(b["passage"])
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= OVERLAP


@dataclass
class Cluster:
    """One reference event: the claims that describe it, and the most severe materiality given."""

    doc_sha256: str
    event_type: str
    materiality: str
    members: list[dict[str, Any]] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)

    def as_claim(self) -> dict[str, Any]:
        return self.members[0]


_RANK = {"high": 0, "medium": 1, "low": 2}


def build_reference(
    adjudications: Sequence[dict[str, Any]], human_events: Sequence[dict[str, Any]] = ()
) -> list[Cluster]:
    """TRUE adjudicated claims plus human-found events, clustered into distinct events."""
    items: list[tuple[dict[str, Any], str, list[str]]] = []
    for row in adjudications:
        verdict = row.get("adjudicated", {})
        if verdict.get("verdict") != reference.VERDICT_TRUE:
            continue
        claim = {
            "doc_sha256": row["doc_sha256"],
            "event_type": verdict["event_type"],
            "passage": row["passage"],
            "claim_id": row["claim_id"],
        }
        items.append((claim, verdict["materiality"], list(row.get("sources", []))))
    for event in human_events:
        items.append((event, str(event["materiality"]), ["human"]))

    clusters: list[Cluster] = []
    for claim, materiality, sources in items:
        home = next((c for c in clusters if same_event(c.as_claim(), claim)), None)
        if home is None:
            home = Cluster(claim["doc_sha256"], claim["event_type"], materiality)
            clusters.append(home)
        home.members.append(claim)
        home.sources.update(sources)
        if _RANK.get(materiality, 3) < _RANK.get(home.materiality, 3):
            home.materiality = materiality
    return clusters


# ---- the user's checks --------------------------------------------------------------------------


def choose_human_documents(
    sample: Sequence[readers.SampleDoc], n: int = MIN_HUMAN_DOCUMENTS
) -> list[readers.SampleDoc]:
    """Documents for the user to read end to end: long ones and routine-looking ones included."""
    rng = random.Random(HUMAN_SEED)
    by_group: dict[str, list[readers.SampleDoc]] = {}
    for doc in sorted(sample, key=lambda d: d.sha256):
        by_group.setdefault(doc.group, []).append(doc)
    for docs in by_group.values():
        rng.shuffle(docs)
    want = {"long": 5, "routine": 4}
    want["ordinary"] = n - sum(want.values())
    out: list[readers.SampleDoc] = []
    for group, k in want.items():
        out.extend(by_group.get(group, [])[:k])
    # A group too small for its share is topped up from the rest, so the check is never short.
    rest = [d for group in want for d in by_group.get(group, [])[want[group] :]]
    out.extend(rest[: max(0, n - len(out))])
    return out


def write_omission_worksheet(documents: Sequence[Any], chosen: Sequence[readers.SampleDoc]) -> Path:
    """The documents as plain text, and an empty CSV for the events the user finds in them."""
    from qalpha.live.extraction import EVENT_TYPES, MATERIALITY_RUBRIC

    folder = human_dir() / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    by_sha = {d.provenance.sha256: d for d in documents}
    rows = []
    for item in chosen:
        doc = by_sha.get(item.sha256)
        if doc is None:
            continue
        name = f"{item.symbol}-{item.seq_id}.txt"
        (folder / name).write_text(doc.text, encoding="utf-8")
        rows.append((item.sha256, item.symbol, item.seq_id, name, item.subject))
    if not documents_path().exists():
        # ``read_by_you`` is how a document with no material event is told apart from an unread one:
        # neither has a row in omissions.csv.
        with documents_path().open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["sha256", "symbol", "seq_id", "file", "subject", "read_by_you"])
            writer.writerows([*r, ""] for r in rows)
    if not omissions_path().exists():
        omissions_path().write_text(
            "sha256,event_type,materiality,passage,notes\n", encoding="utf-8"
        )
    (human_dir() / "HOW_TO_CHECK.md").write_text(
        "# Reading complete documents for events\n\n"
        "Read every file in `documents/` from start to end. For each event that should worry "
        "someone who owns the shares, add one row to `omissions.csv`:\n\n"
        "- `sha256` — copy it from `documents.csv`\n"
        f"- `event_type` — one of: {', '.join(EVENT_TYPES)}\n"
        "- `materiality` — high, medium or low, by the rubric below\n"
        "- `passage` — copy the sentence from the document exactly\n\n"
        "A document with no material event needs no row. When you finish a document, put `yes` in "
        "its `read_by_you` column in `documents.csv` — that is how a document with nothing material "
        "is told apart from one not yet read. Do not look at any model's output first.\n\n"
        + MATERIALITY_RUBRIC,
        encoding="utf-8",
    )
    return human_dir()


def write_claim_worksheet(n: int = MIN_CLAIM_CHECKS) -> Path | None:
    """A random set of adjudicated claims for the user to agree or disagree with."""
    adjudicated = reference._jsonl(reference.adjudications_path())
    if not adjudicated:
        return None
    rng = random.Random(HUMAN_SEED + 1)
    rows = sorted(adjudicated, key=lambda r: r["claim_id"])
    rng.shuffle(rows)
    human_dir().mkdir(parents=True, exist_ok=True)
    if claim_checks_path().exists():
        return claim_checks_path()
    with claim_checks_path().open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "claim_id",
                "doc_sha256",
                "event_type",
                "passage",
                "judge_verdict",
                "judge_type",
                "judge_materiality",
                "judge_reason",
                "your_verdict",
            ]
        )
        for row in rows[:n]:
            v = row["adjudicated"]
            writer.writerow(
                [
                    row["claim_id"],
                    row["doc_sha256"],
                    row["event_type"],
                    row["passage"],
                    v["verdict"],
                    v["event_type"],
                    v["materiality"],
                    v["reason"],
                    "",
                ]
            )
    return claim_checks_path()


def read_human_events() -> list[dict[str, Any]]:
    if not omissions_path().exists():
        return []
    with omissions_path().open(encoding="utf-8", newline="") as fh:
        return [
            {
                "doc_sha256": r["sha256"].strip(),
                "event_type": r["event_type"].strip(),
                "materiality": r["materiality"].strip().lower(),
                "passage": r["passage"].strip(),
            }
            for r in csv.DictReader(fh)
            if r.get("sha256", "").strip() and r.get("passage", "").strip()
        ]


def read_human_documents() -> set[str]:
    """The documents the user has marked as read end to end."""
    if not documents_path().exists():
        return set()
    with documents_path().open(encoding="utf-8", newline="") as fh:
        return {
            r["sha256"].strip()
            for r in csv.DictReader(fh)
            if r.get("read_by_you", "").strip().lower() in ("yes", "y")
        }


def read_claim_checks() -> list[dict[str, str]]:
    if not claim_checks_path().exists():
        return []
    with claim_checks_path().open(encoding="utf-8", newline="") as fh:
        return [r for r in csv.DictReader(fh) if r.get("your_verdict", "").strip()]


@dataclass(frozen=True)
class Validation:
    human_documents: int
    human_events: int
    omitted: int
    claim_checks: int
    disagreements: int

    @property
    def omission_rate(self) -> float | None:
        return None if self.human_events == 0 else self.omitted / self.human_events

    @property
    def disagreement_rate(self) -> float | None:
        return None if self.claim_checks == 0 else self.disagreements / self.claim_checks

    def problems(self) -> list[str]:
        out = []
        if self.human_documents < MIN_HUMAN_DOCUMENTS:
            out.append(
                f"only {self.human_documents} of {MIN_HUMAN_DOCUMENTS} complete documents checked"
            )
        if self.claim_checks < MIN_CLAIM_CHECKS:
            out.append(f"only {self.claim_checks} of {MIN_CLAIM_CHECKS} adjudications checked")
        if self.omission_rate is not None and self.omission_rate > MAX_REFERENCE_OMISSION:
            out.append(
                f"the reference missed {self.omission_rate:.0%} of the events found by reading "
                f"complete documents (ceiling {MAX_REFERENCE_OMISSION:.0%}) — rebuild it"
            )
        if (
            self.disagreement_rate is not None
            and self.disagreement_rate > MAX_ADJUDICATOR_DISAGREEMENT
        ):
            out.append(
                f"the adjudicator was judged wrong on {self.disagreement_rate:.0%} of checked claims "
                f"(ceiling {MAX_ADJUDICATOR_DISAGREEMENT:.0%}) — rebuild it"
            )
        return out


def validate(
    model_reference: Sequence[Cluster],
    human_events: Sequence[dict[str, Any]],
    human_doc_shas: set[str],
    checks: Sequence[dict[str, str]],
) -> Validation:
    material = [e for e in human_events if e["materiality"] in ("high", "medium")]
    omitted = sum(
        1
        for e in material
        if not any(
            same_event(c.as_claim(), e) for c in model_reference if c.doc_sha256 == e["doc_sha256"]
        )
    )
    disagreements = sum(1 for r in checks if r["your_verdict"].strip().lower().startswith("dis"))
    return Validation(
        human_documents=len(human_doc_shas),
        human_events=len(material),
        omitted=omitted,
        claim_checks=len(checks),
        disagreements=disagreements,
    )


# ---- scoring the readers ------------------------------------------------------------------------


@dataclass
class Score:
    reader: str
    kind: str
    documents_done: int
    claims: int
    verified: int
    true_claims: int
    unadjudicated: int
    recall_high: float | None
    recall_medium: float | None
    failed_batches: int
    calls: int
    usd: Decimal | None
    seconds: float
    tokens_per_second: float | None
    peak_vram_mb: int | None
    peak_ram_mb: int | None

    @property
    def precision(self) -> float | None:
        judged = self.claims - self.unadjudicated
        return None if judged <= 0 else self.true_claims / judged

    @property
    def verbatim(self) -> float | None:
        return None if self.claims == 0 else self.verified / self.claims

    def usd_per_filing(self, n: int) -> Decimal | None:
        if self.kind == "local":
            return Decimal("0")
        return None if self.usd is None or n == 0 else self.usd / n


def score_reader(
    run: dict[str, Any], clusters: Sequence[Cluster], adjudications: Sequence[dict[str, Any]]
) -> Score:
    slug = str(run["reader"])
    verdicts = {r["claim_id"]: r["adjudicated"]["verdict"] for r in adjudications}
    segments = run.get("segments", [])
    discarded = sum(int(s.get("discarded", 0)) for s in segments)
    seen: set[str] = set()
    verified = true_claims = unadjudicated = 0
    for event in run.get("events", []):
        cid = reference.claim_id(event["doc_sha256"], event["event_type"], event["passage"])
        if cid in seen:
            continue  # a document re-read after an interruption must not count its claims twice
        seen.add(cid)
        verified += 1
        v = verdicts.get(cid)
        if v is None:
            unadjudicated += 1
        elif v == reference.VERDICT_TRUE:
            true_claims += 1

    def recall(level: str) -> float | None:
        targets = [c for c in clusters if c.materiality == level]
        if not targets:
            return None
        return sum(1 for c in targets if slug in c.sources) / len(targets)

    usage_calls = sum(int(s.get("usage", {}).get("calls", 0)) for s in segments)
    failed = sum(int(s.get("usage", {}).get("failed_batches", 0)) for s in segments)
    usd_total: Decimal | None = Decimal("0")
    for s in segments:
        try:
            usd_total = (usd_total or Decimal("0")) + Decimal(str(s.get("usd", "0")))
        except ArithmeticError:
            usd_total = None
            break
    tps = [s["tokens_per_second"] for s in segments if s.get("tokens_per_second")]
    vram = [s["peak_vram_mb"] for s in segments if s.get("peak_vram_mb") is not None]
    ram = [s["peak_ram_mb"] for s in segments if s.get("peak_ram_mb") is not None]
    return Score(
        reader=slug,
        kind=str(run.get("kind", "")),
        documents_done=len(run.get("done", [])),
        claims=verified + discarded,
        verified=verified,
        true_claims=true_claims,
        unadjudicated=unadjudicated,
        recall_high=recall("high"),
        recall_medium=recall("medium"),
        failed_batches=failed,
        calls=usage_calls,
        usd=usd_total,
        seconds=sum(float(s.get("seconds", 0)) for s in segments),
        tokens_per_second=round(sum(tps) / len(tps), 2) if tps else None,
        peak_vram_mb=max(vram) if vram else None,
        peak_ram_mb=max(ram) if ram else None,
    )


@dataclass(frozen=True)
class Selection:
    winner: str | None
    qualified: list[str]
    reasons: dict[str, list[str]]
    decided: bool
    why_not_decided: list[str]


def select(scores: Sequence[Score], validation: Validation, sample_size: int) -> Selection:
    """The rule registered before any run. Cheapest qualifier wins; none qualifies → best recall."""
    blockers = validation.problems()
    reasons: dict[str, list[str]] = {}
    complete = [s for s in scores if s.documents_done >= sample_size]
    for s in scores:
        if s not in complete:
            reasons[s.reader] = [f"read {s.documents_done} of {sample_size} documents"]
    best = max((s.recall_high or 0.0 for s in complete), default=0.0)
    qualified: list[Score] = []
    for s in complete:
        why: list[str] = []
        if s.recall_high is None or s.recall_high < MIN_RECALL_HIGH:
            why.append(f"high recall {s.recall_high} below {MIN_RECALL_HIGH}")
        elif s.recall_high < RELATIVE_RECALL_HIGH * best:
            why.append(
                f"high recall {s.recall_high:.2f} below {RELATIVE_RECALL_HIGH} x best {best:.2f}"
            )
        if s.precision is None or s.precision < MIN_PRECISION:
            why.append(f"precision {s.precision} below {MIN_PRECISION}")
        if s.verbatim is None or s.verbatim < MIN_VERBATIM:
            why.append(f"verbatim rate {s.verbatim} below {MIN_VERBATIM}")
        reasons[s.reader] = why
        if not why:
            qualified.append(s)
    if blockers:
        return Selection(None, [q.reader for q in qualified], reasons, False, blockers)

    def price(s: Score) -> Decimal:
        per = s.usd_per_filing(sample_size)
        return per if per is not None else Decimal("Infinity")

    winner: str | None
    if qualified:
        winner = min(qualified, key=lambda s: (price(s), -(s.recall_high or 0.0))).reader
    else:
        winner = max(complete, key=lambda s: s.recall_high or 0.0).reader if complete else None
    return Selection(winner, [q.reader for q in qualified], reasons, True, [])


def triage_check(
    sample: Sequence[readers.SampleDoc], clusters: Sequence[Cluster]
) -> dict[str, dict[str, int]]:
    """Per routine rule: documents it would skip, and the reference events inside them."""
    by_sha = {d.sha256: d for d in sample}
    out: dict[str, dict[str, int]] = {
        r.name: {"documents": 0, "high": 0, "medium": 0} for r in triage.RULES
    }
    for doc in sample:
        verdict = triage.classify(doc.subject, doc.chars)
        if verdict.routine:
            out[verdict.rule]["documents"] += 1
    for c in clusters:
        home = by_sha.get(c.doc_sha256)
        if home is None:
            continue
        verdict = triage.classify(home.subject, home.chars)
        if verdict.routine and c.materiality in ("high", "medium"):
            out[verdict.rule][c.materiality] += 1
    return out


def failed_triage_rules(check: dict[str, dict[str, int]]) -> set[str]:
    return {name for name, n in check.items() if n["high"] > 0 or n["medium"] > TRIAGE_MAX_MEDIUM}


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.0%}"


def render_report(
    scores: Sequence[Score],
    selection: Selection,
    validation: Validation,
    triage_result: dict[str, dict[str, int]],
    *,
    sample_size: int,
    reference_events: int,
) -> str:
    lines = [
        "# Reader comparison — EX-5",
        "",
        "Decided under `reports/PREREGISTRATION_EX5_READERS.md`, registered before any reader ran.",
        "",
        f"**Sample:** {sample_size} archived filings. **Reference:** {reference_events} distinct events "
        "(Opus 5 readings + claims adjudicated true + events found by reading complete documents).",
        "",
        "## Is the reference fit to judge?",
        f"- Complete documents read by the user: {validation.human_documents}; material events found: "
        f"{validation.human_events}; missed by the model-built reference: {validation.omitted} "
        f"(**{_pct(validation.omission_rate)}**, ceiling {MAX_REFERENCE_OMISSION:.0%})",
        f"- Adjudications checked: {validation.claim_checks}; judged wrong: {validation.disagreements} "
        f"(**{_pct(validation.disagreement_rate)}**, ceiling {MAX_ADJUDICATOR_DISAGREEMENT:.0%})",
        "",
        "## Readers",
        "",
        "| Reader | Docs | Claims | Verbatim | Precision | Recall high | Recall medium | $/filing | tok/s | Peak VRAM MB | Peak RAM MB | Failed batches |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in sorted(scores, key=lambda x: x.reader):
        per = s.usd_per_filing(sample_size)
        lines.append(
            f"| {s.reader} | {s.documents_done} | {s.claims} | {_pct(s.verbatim)} | {_pct(s.precision)} "
            f"| {_pct(s.recall_high)} | {_pct(s.recall_medium)} | "
            f"{'—' if per is None else f'{per:.4f}'} | {s.tokens_per_second or '—'} | "
            f"{s.peak_vram_mb or '—'} | {s.peak_ram_mb or '—'} | {s.failed_batches} |"
        )
    lines += ["", "## Decision", ""]
    if not selection.decided:
        lines.append("**NOT DECIDED.** The reference is not yet fit to judge:")
        lines += [f"- {w}" for w in selection.why_not_decided]
    elif selection.qualified:
        lines.append(
            f"**Selected: `{selection.winner}`** — the cheapest reader meeting every threshold."
        )
    else:
        lines.append(
            f"**No reader qualified.** `{selection.winner}` has the best high-materiality recall and is "
            "used on material filings only; the shortfall is a recorded limit."
        )
    lines += ["", "Why each reader did or did not qualify:", ""]
    for reader, why in sorted(selection.reasons.items()):
        lines.append(f"- `{reader}`: {'qualifies' if not why else '; '.join(why)}")
    lines += [
        "",
        "## Triage",
        "",
        "| Rule | Documents it would skip | High events inside | Medium events inside | Verdict |",
        "|---|---:|---:|---:|---|",
    ]
    failed = failed_triage_rules(triage_result)
    for name, n in triage_result.items():
        verdict = (
            "REMOVED"
            if name in failed
            else ("kept" if n["documents"] else "untested (no documents)")
        )
        lines.append(f"| {name} | {n['documents']} | {n['high']} | {n['medium']} | {verdict} |")
    return "\n".join(lines) + "\n"


def load_everything(
    sample: Sequence[readers.SampleDoc],
) -> tuple[list[dict[str, Any]], list[Cluster], list[Cluster], list[dict[str, Any]]]:
    """``(runs, model_reference, full_reference, adjudications)`` from what is on disk."""
    adjudications = reference._jsonl(reference.adjudications_path())
    human = read_human_events()
    shas = {d.sha256 for d in sample}
    model_ref = build_reference(adjudications)
    full_ref = build_reference(adjudications, [e for e in human if e["doc_sha256"] in shas])
    runs = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(readers.runs_dir().glob("*.json"))
    ]
    return runs, model_ref, full_ref, adjudications
