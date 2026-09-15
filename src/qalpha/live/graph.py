"""The knowledge graph: what Q-Alpha knows about companies and how they connect — and since when.

**The record is an append-only assertion log** (``data/graph/assertions.jsonl``). Neo4j is a
projection of it for traversal (:mod:`qalpha.live.graph_neo4j`), rebuilt from the log on demand.
The log is the record because it is the only form in which a correction can leave yesterday's view
reproducible: nothing in it is ever edited, and a Neo4j database that someone ``SET`` a property in
would silently rewrite what the investor was told.

**Every assertion is one of four kinds of knowledge**, and never quietly another:

* ``DISCLOSED`` — a company or outlet said it: the archived document's hash and the verbatim
  passage (with offsets where the text matches exactly).
* ``COMPUTED`` — code derived it: the inputs and the code version.
* ``INFERRED`` — a model concluded it: model id, digest, confidence. **Never returned by a fact
  query**; asked for by name, and labelled when it is.
* ``MISSING`` — a known gap: what is not known, and why.

**Two time axes.** *Valid time* (``valid_from``/``valid_to``) is when the fact applied in the world.
*Knowledge time* (``known_from``/``known_to``) is when Q-Alpha held that version: from when the
source was public **and** ingested, until a later version superseded it. Every query takes both —
"what did we believe on K about V" — and a correction received today closes the old version's
``known_to`` today, so a replay of yesterday still sees what yesterday saw.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

GRAPH_DIR = Path("data/graph")
SCHEMA_VERSION = "GRAPH-1"

DISCLOSED = "DISCLOSED"
COMPUTED = "COMPUTED"
INFERRED = "INFERRED"
MISSING = "MISSING"
CLASSES = (DISCLOSED, COMPUTED, INFERRED, MISSING)
#: What a fact query returns. An inference is not a fact, however confident.
FACTS = (DISCLOSED, COMPUTED)

NODE = "node"
EDGE = "edge"


def log_path() -> Path:
    return GRAPH_DIR / "assertions.jsonl"


# ---- schema -----------------------------------------------------------------------------------

NODE_LABELS = frozenset(
    {
        "Company",  # listed (id company:TICKER) or not (id org:slug), prop `listed`
        "Sector",
        "Segment",
        "Geography",
        "FinancialPeriod",
        "DebtInstrument",
        "RatingAgency",
        "Person",
        "Risk",
        "ValuationAssumption",
        "Document",
        "Passage",
        "Event",
        "Headline",
        "Thesis",
        "Intention",
        "Decision",
    }
)

#: Relationship type → allowed (from labels, to labels). **Direction carries meaning**:
#: ``SUPPLIER_TO`` runs supplier → customer, ``OWNS`` owner → owned, ``SUBSIDIARY_OF`` child → parent.
EDGE_TYPES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "IN_SECTOR": (frozenset({"Company"}), frozenset({"Sector"})),
    "HAS_SEGMENT": (frozenset({"Company"}), frozenset({"Segment"})),
    "REPORTED": (frozenset({"Company"}), frozenset({"FinancialPeriod"})),
    "ISSUED": (frozenset({"Company"}), frozenset({"DebtInstrument"})),
    "RATED_BY": (frozenset({"DebtInstrument", "Company"}), frozenset({"RatingAgency"})),
    "DIRECTOR_OF": (frozenset({"Person"}), frozenset({"Company"})),
    "KMP_OF": (frozenset({"Person"}), frozenset({"Company"})),
    "PROMOTER_OF": (frozenset({"Person", "Company"}), frozenset({"Company"})),
    "FACES": (frozenset({"Company"}), frozenset({"Risk"})),
    "SUPPLIER_TO": (frozenset({"Company"}), frozenset({"Company"})),
    "OWNS": (frozenset({"Company", "Person"}), frozenset({"Company"})),
    "SUBSIDIARY_OF": (frozenset({"Company"}), frozenset({"Company"})),
    "COMPETES_WITH": (frozenset({"Company"}), frozenset({"Company"})),
    "OPERATES_IN": (frozenset({"Company", "Segment"}), frozenset({"Geography"})),
    "RELATED_PARTY_WITH": (frozenset({"Company"}), frozenset({"Company", "Person"})),
    "CONTAINS": (frozenset({"Document"}), frozenset({"Passage"})),
    "EVIDENCED_BY": (frozenset({"Event", "Headline"}), frozenset({"Passage"})),
    "ABOUT": (
        frozenset({"Event", "Headline", "Thesis", "Intention"}),
        frozenset({"Company"}),
    ),
    "REVISED_TO": (frozenset({"Thesis"}), frozenset({"Thesis"})),
    "ASSUMES": (frozenset({"Thesis"}), frozenset({"ValuationAssumption"})),
    "SUPPORTS": (frozenset({"Event", "Headline", "FinancialPeriod"}), frozenset({"Thesis"})),
    "CONTRADICTS": (frozenset({"Event", "Headline", "FinancialPeriod"}), frozenset({"Thesis"})),
    "DECIDED_ON": (frozenset({"Decision"}), frozenset({"Company"})),
    "CITES": (
        frozenset({"Decision", "Intention"}),
        frozenset({"Event", "Headline", "FinancialPeriod", "Company", "Passage"}),
    ),
    "FOLLOWS": (frozenset({"Decision"}), frozenset({"Intention"})),
}

#: The business connections the coverage report asks about, per company.
CONNECTION_TYPES = (
    "SUPPLIER_TO",
    "OWNS",
    "SUBSIDIARY_OF",
    "COMPETES_WITH",
    "OPERATES_IN",
    "RELATED_PARTY_WITH",
    "HAS_SEGMENT",
    "RATED_BY",
    "DIRECTOR_OF",
)


class GraphError(ValueError):
    """An assertion that would put something untrue-by-construction into the record."""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "unnamed"


def company_id(ticker: str) -> str:
    return f"company:{ticker.removesuffix('.NS').upper()}"


# ---- assertions -------------------------------------------------------------------------------


def _iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()


@dataclass(frozen=True)
class Assertion:
    """One version of one fact. ``key`` is the fact's identity; versions share it."""

    kind: str  # NODE or EDGE
    label: str  # node label or relationship type
    subject: str  # node id (for an edge: from)
    epistemic: str
    source: Mapping[str, Any]
    known_from: datetime
    object: str | None = None  # an edge's to; None for a node
    object_label: str | None = None
    subject_label: str | None = None
    props: Mapping[str, Any] = field(default_factory=dict)
    valid_from: date | None = None
    valid_to: date | None = None
    #: Distinguishes two facts between the same ends, e.g. two supply contracts. Part of the key.
    qualifier: str = ""
    #: Set when loaded from the log: when a later version replaced this one.
    known_to: datetime | None = None

    @property
    def key(self) -> str:
        if self.kind == NODE:
            return f"node|{self.subject}"
        return f"edge|{self.subject}|{self.label}|{self.object}|{self.qualifier}"

    @property
    def content(self) -> dict[str, Any]:
        """Everything that makes two versions different facts, known time excluded."""
        return {
            "kind": self.kind,
            "label": self.label,
            "subject": self.subject,
            "subject_label": self.subject_label,
            "object": self.object,
            "object_label": self.object_label,
            "qualifier": self.qualifier,
            "props": dict(sorted(self.props.items())),
            "epistemic": self.epistemic,
            "source": dict(sorted(self.source.items())),
            "valid_from": _iso(self.valid_from),
            "valid_to": _iso(self.valid_to),
        }

    @property
    def id(self) -> str:
        body = json.dumps(
            {**self.content, "known_from": _iso(self.known_from)}, sort_keys=True, default=str
        )
        return hashlib.sha256(body.encode()).hexdigest()[:24]

    def valid_at(self, when: date) -> bool:
        return (self.valid_from is None or self.valid_from <= when) and (
            self.valid_to is None or when < self.valid_to
        )

    def known_at(self, when: datetime) -> bool:
        return self.known_from <= when and (self.known_to is None or when < self.known_to)

    def as_row(self) -> dict[str, Any]:
        return {"op": "assert", "id": self.id, **self.content, "known_from": _iso(self.known_from)}


def validate(a: Assertion) -> None:
    """Refuse what the schema or the epistemic rules forbid. Raises :class:`GraphError`."""
    if a.epistemic not in CLASSES:
        raise GraphError(f"unknown epistemic class {a.epistemic!r}")
    if a.known_from.tzinfo is None:
        raise GraphError("known_from must be timezone-aware")
    if a.valid_from and a.valid_to and a.valid_to <= a.valid_from:
        raise GraphError(f"{a.key}: valid_to {a.valid_to} is not after valid_from {a.valid_from}")
    if a.kind == NODE:
        if a.label not in NODE_LABELS:
            raise GraphError(f"unknown node label {a.label!r}")
        if a.object is not None:
            raise GraphError("a node has no object")
    elif a.kind == EDGE:
        if a.label not in EDGE_TYPES:
            raise GraphError(f"unknown relationship {a.label!r}")
        if not a.object:
            raise GraphError(f"{a.label} needs an object")
        froms, tos = EDGE_TYPES[a.label]
        if a.subject_label not in froms or a.object_label not in tos:
            raise GraphError(
                f"{a.label} runs {sorted(froms)} → {sorted(tos)}, not "
                f"{a.subject_label} → {a.object_label}"
            )
    else:
        raise GraphError(f"unknown assertion kind {a.kind!r}")
    s = a.source
    if a.epistemic == DISCLOSED:
        has_doc = bool(re.fullmatch(r"[0-9a-f]{64}", str(s.get("doc_sha256", ""))))
        has_feed = bool(s.get("feed_sha256")) and bool(s.get("link"))
        if not (has_doc or has_feed) or not str(s.get("passage", "")).strip():
            raise GraphError(
                f"{a.key}: DISCLOSED needs the archived document (or feed) hash and a verbatim passage"
            )
    elif a.epistemic == COMPUTED:
        if not s.get("inputs") or not s.get("code_version"):
            raise GraphError(f"{a.key}: COMPUTED needs its inputs and code version")
    elif a.epistemic == INFERRED:
        confidence = s.get("confidence")
        if (
            not s.get("model")
            or not isinstance(confidence, int | float)
            or not 0 <= confidence <= 1
        ):
            raise GraphError(f"{a.key}: INFERRED needs the model and a confidence in [0, 1]")
    elif a.epistemic == MISSING and not str(s.get("reason", "")).strip():
        raise GraphError(f"{a.key}: MISSING needs the reason it is not known")


def _parse_time(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _from_row(row: Mapping[str, Any]) -> Assertion:
    return Assertion(
        kind=str(row["kind"]),
        label=str(row["label"]),
        subject=str(row["subject"]),
        subject_label=row.get("subject_label"),
        object=row.get("object"),
        object_label=row.get("object_label"),
        qualifier=str(row.get("qualifier", "")),
        props=dict(row.get("props") or {}),
        epistemic=str(row["epistemic"]),
        source=dict(row.get("source") or {}),
        valid_from=None
        if not row.get("valid_from")
        else date.fromisoformat(str(row["valid_from"])),
        valid_to=None if not row.get("valid_to") else date.fromisoformat(str(row["valid_to"])),
        known_from=_parse_time(str(row["known_from"])),
    )


# ---- the log ----------------------------------------------------------------------------------


class GraphLog:
    """The append-only record. Loaded whole; written by appending only."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self.versions: dict[str, Assertion] = {}
        self._by_key: dict[str, list[str]] = {}
        self._pending: list[dict[str, Any]] = []
        self._load()

    @property
    def path(self) -> Path:
        return log_path() if self._path is None else self._path

    def _load(self) -> None:
        if not self.path.exists():
            return
        closed: dict[str, datetime] = {}
        order: list[str] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line from a killed write; the rest stands
            if row.get("op") == "assert":
                a = _from_row(row)
                self.versions[a.id] = a
                order.append(a.id)
            elif row.get("op") in ("supersede", "retract"):
                closed[str(row["id"])] = _parse_time(str(row["at"]))
        for aid in order:
            a = self.versions[aid]
            if aid in closed:
                a = _with_known_to(a, closed[aid])
                self.versions[aid] = a
            self._by_key.setdefault(a.key, []).append(aid)

    def current(self, key: str) -> Assertion | None:
        """The version held now: the latest-starting one not superseded."""
        live = [
            self.versions[i] for i in self._by_key.get(key, []) if self.versions[i].known_to is None
        ]
        return max(live, key=lambda a: a.known_from) if live else None

    def add(self, a: Assertion) -> str:
        """Record ``a``. Returns ``"new"``, ``"revised"`` or ``"unchanged"``. Nothing is overwritten.

        The same content already held is unchanged — re-ingesting is idempotent. Different content for
        the same key closes the held version at the new one's ``known_from``. A version that arrives
        *after* a later-known one (ingestion out of order) is recorded as already superseded by it,
        so the order of ingestion cannot change what any date's view contains.
        """
        validate(a)
        held = self.current(a.key)
        if a.id in self.versions:
            return "unchanged"
        earlier_same = any(
            self.versions[i].content == a.content and self.versions[i].known_from <= a.known_from
            for i in self._by_key.get(a.key, [])
        )
        if held is not None and held.content == a.content and a.known_from >= held.known_from:
            return "unchanged"
        if held is not None and a.known_from < held.known_from:
            # Arrived out of order: this version was known before the one held. Record it as known
            # from its own time and closed where the held version begins, so the order of ingestion
            # cannot change what any date's view contains. The same fact already known at least this
            # early adds nothing.
            if earlier_same:
                return "unchanged"
            self._write(a.as_row())
            self._write({"op": "supersede", "id": a.id, "by": held.id, "at": _iso(held.known_from)})
            self._remember(_with_known_to(a, held.known_from))
            return "revised"
        self._write(a.as_row())
        if held is not None:
            self._write({"op": "supersede", "id": held.id, "by": a.id, "at": _iso(a.known_from)})
            self.versions[held.id] = _with_known_to(held, a.known_from)
        self._remember(a)
        return "new" if held is None else "revised"

    def retract(self, key: str, *, at: datetime, reason: str) -> bool:
        """Stop holding a fact from ``at`` on — found wrong, or withdrawn. Earlier views keep it."""
        held = self.current(key)
        if held is None:
            return False
        self._write({"op": "retract", "id": held.id, "at": _iso(at), "reason": reason})
        self.versions[held.id] = _with_known_to(held, at)
        return True

    def _remember(self, a: Assertion) -> None:
        self.versions[a.id] = a
        self._by_key.setdefault(a.key, []).append(a.id)

    def _write(self, row: dict[str, Any]) -> None:
        self._pending.append(row)

    def flush(self) -> int:
        """Append everything recorded since the last flush, in one write. Returns rows written."""
        if not self._pending:
            return 0
        from qalpha.live.atomic import write_text

        existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        body = "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in self._pending)
        write_text(self.path, existing + body)
        n = len(self._pending)
        self._pending = []
        return n

    def view(self, *, valid_at: date, known_at: datetime) -> GraphView:
        return GraphView(
            [a for a in self.versions.values() if a.valid_at(valid_at) and a.known_at(known_at)],
            valid_at=valid_at,
            known_at=known_at,
        )


def _with_known_to(a: Assertion, at: datetime) -> Assertion:
    from dataclasses import replace

    return replace(a, known_to=at)


# ---- reading it --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One edge walked in a path, and which way."""

    edge: Assertion
    forward: bool  # walked subject → object

    def as_dict(self) -> dict[str, Any]:
        e = self.edge
        return {
            "assertion": e.id,
            "relationship": e.label,
            "from": e.subject,
            "to": e.object,
            "walked": "forward" if self.forward else "backward",
            "epistemic": e.epistemic,
            "props": dict(e.props),
            "passage": e.source.get("passage"),
            "doc_sha256": e.source.get("doc_sha256"),
            "valid_from": _iso(e.valid_from),
            "known_from": _iso(e.known_from),
        }


class GraphView:
    """Everything valid at one date and known at one moment. Read-only."""

    def __init__(
        self, assertions: Iterable[Assertion], *, valid_at: date, known_at: datetime
    ) -> None:
        self.valid_at = valid_at
        self.known_at = known_at
        self.nodes: dict[str, Assertion] = {}
        self.edges: list[Assertion] = []
        for a in assertions:
            if a.kind == NODE:
                self.nodes[a.subject] = a
            else:
                self.edges.append(a)

    def facts(self, *, classes: Sequence[str] = FACTS) -> list[Assertion]:
        return [e for e in self.edges if e.epistemic in classes]

    def _adjacent(
        self, node: str, classes: Sequence[str], types: Sequence[str] | None
    ) -> list[Step]:
        out: list[Step] = []
        for e in self.edges:
            if e.epistemic not in classes or (types is not None and e.label not in types):
                continue
            if e.subject == node:
                out.append(Step(e, True))
            elif e.object == node:
                out.append(Step(e, False))
        return out

    def paths(
        self,
        start: str,
        goal: str,
        *,
        max_hops: int = 3,
        types: Sequence[str] | None = None,
        classes: Sequence[str] = FACTS,
    ) -> list[list[Step]]:
        """Every simple path from ``start`` to ``goal`` of at most ``max_hops`` edges, shortest first."""
        found: list[list[Step]] = []
        queue: deque[tuple[str, list[Step], frozenset[str]]] = deque(
            [(start, [], frozenset({start}))]
        )
        while queue:
            node, path, seen = queue.popleft()
            if len(path) >= max_hops:
                continue
            for step in self._adjacent(node, classes, types):
                nxt = step.edge.object if step.forward else step.edge.subject
                if nxt is None or nxt in seen:
                    continue
                if nxt == goal:
                    found.append([*path, step])
                else:
                    queue.append((nxt, [*path, step], seen | {nxt}))
        return found

    def neighbourhood(
        self,
        start: str,
        *,
        hops: int = 1,
        types: Sequence[str] | None = None,
        classes: Sequence[str] = FACTS,
    ) -> list[dict[str, Any]]:
        """Nodes within ``hops`` edges, with the path that reaches each."""
        out: list[dict[str, Any]] = []
        queue: deque[tuple[str, list[Step]]] = deque([(start, [])])
        reached = {start}
        while queue:
            node, path = queue.popleft()
            if len(path) >= hops:
                continue
            for step in self._adjacent(node, classes, types):
                nxt = step.edge.object if step.forward else step.edge.subject
                if nxt is None or nxt in reached:
                    continue
                reached.add(nxt)
                out.append(
                    {
                        "node": nxt,
                        "label": self.label(nxt),
                        "path": [s.as_dict() for s in [*path, step]],
                    }
                )
                queue.append((nxt, [*path, step]))
        return out

    def label(self, node: str) -> str | None:
        held = self.nodes.get(node)
        return None if held is None else held.label

    def exposure(
        self,
        holdings: Sequence[str],
        entity: str,
        *,
        max_hops: int = 3,
        types: Sequence[str] | None = None,
    ) -> dict[str, list[list[dict[str, Any]]]]:
        """Which holdings connect to ``entity`` through disclosed or computed facts, and how."""
        out: dict[str, list[list[dict[str, Any]]]] = {}
        for h in holdings:
            found = self.paths(
                company_id(h) if ":" not in h else h, entity, max_hops=max_hops, types=types
            )
            if found:
                out[h] = [[s.as_dict() for s in p] for p in found]
        return out

    def suppliers_of(self, customer: str) -> list[Assertion]:
        """Disclosed or computed ``SUPPLIER_TO`` edges into ``customer`` (supplier → customer)."""
        return [e for e in self.facts() if e.label == "SUPPLIER_TO" and e.object == customer]

    def about(self, company: str, *, labels: Sequence[str] = ("Event", "Headline")) -> list[str]:
        return [
            e.subject
            for e in self.facts()
            if e.label == "ABOUT" and e.object == company and self.label(e.subject) in labels
        ]

    def contradictions(self, thesis: str) -> list[Assertion]:
        return [e for e in self.facts() if e.label == "CONTRADICTS" and e.object == thesis]

    def periods(self, company: str, metric: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """One metric across the company's reported periods, newest first."""
        rows = []
        for e in self.facts():
            if e.label != "REPORTED" or e.subject != company or e.object is None:
                continue
            node = self.nodes.get(e.object)
            if node is None:
                continue
            rows.append(
                {
                    "period": e.object,
                    "period_end": node.props.get("period_end"),
                    "basis": node.props.get("basis"),
                    "value": node.props.get(metric),
                    "filed_at": node.props.get("filed_at"),
                }
            )
        rows.sort(key=lambda r: str(r["period_end"]), reverse=True)
        return rows[:limit]

    def inferred(self, company: str) -> list[Assertion]:
        """Model inferences touching ``company``. Asked for explicitly, returned labelled."""
        return [
            e for e in self.edges if e.epistemic == INFERRED and company in (e.subject, e.object)
        ]

    def coverage(self, company: str) -> dict[str, str]:
        """Per connection type: ``known`` (a fact), ``MISSING`` (a recorded gap) or ``unknown``."""
        out: dict[str, str] = {}
        for rel in CONNECTION_TYPES:
            touching = [
                e for e in self.edges if e.label == rel and company in (e.subject, e.object)
            ]
            if any(e.epistemic in FACTS for e in touching):
                out[rel] = "known"
            elif any(e.epistemic == MISSING for e in touching) or self._gap(company, rel):
                out[rel] = "MISSING"
            else:
                out[rel] = "unknown"
        return out

    def _gap(self, company: str, rel: str) -> bool:
        node = self.nodes.get(f"gap:{company}:{rel}")
        return node is not None and node.epistemic == MISSING


def gap(company: str, relationship: str, *, reason: str, known_from: datetime) -> Assertion:
    """A recorded gap: ``relationship`` for ``company`` is not known, and why.

    Stored as a Risk-labelled MISSING node rather than an edge to nowhere, so a gap is never
    mistaken for a connection by a traversal.
    """
    return Assertion(
        kind=NODE,
        label="Risk",
        subject=f"gap:{company}:{relationship}",
        epistemic=MISSING,
        source={"reason": reason},
        known_from=known_from,
        props={"company": company, "relationship": relationship},
    )
