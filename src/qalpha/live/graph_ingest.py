"""Fill the knowledge graph from what is already on disk. No model calls, no network, $0.

Sources, and the kind of knowledge each becomes:

| Source | Becomes | Class | Known from |
|---|---|---|---|
| watchlist | Company, Sector, ``IN_SECTOR`` | COMPUTED | when ingested |
| verified filing events (corpus reader, current version) | Document, Passage, Event, ``CONTAINS``, ``EVIDENCED_BY``, ``ABOUT`` | DISCLOSED (Document: COMPUTED) | the later of dissemination and the day the corpus read it |
| verified headline events | Headline, ``ABOUT`` | DISCLOSED | the later of publication and the day it was read |
| filed quarterly results | FinancialPeriod, ``REPORTED`` | COMPUTED (parsed from XBRL by code) | when the exchange published the filing |
| the investor's decisions | Thesis, Decision, ``ABOUT``, ``REVISED_TO``, ``DECIDED_ON``, ``CITES`` | COMPUTED (a record of what the version wrote) | the decision's date |
| feeds not yet ingested | a MISSING gap per company and connection | MISSING | when ingested |

**Known time follows the evidence log's own rule.** An event read by the corpus on 12 September
about a filing disseminated in March was not something Q-Alpha knew in March; a replay of March must
not see it. That is the rule :func:`qalpha.live.evidence_log.events` already applies to packets, so
a graph answer and a packet on the same date cannot disagree about what was known.

A thesis is recorded as the investor's **own belief**: its node label says Thesis, it is never an
Event, and a fact query about a company never returns it as evidence.
"""

from __future__ import annotations

import csv
import gzip
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from qalpha.live import graph as g
from qalpha.live.progress import IST

INGEST_VERSION = "GRAPH-INGEST-1"

#: Connections the graph cannot know yet because no structured feed for them is ingested. Each gets
#: a recorded gap per company, so the coverage report says MISSING — known to be unknown — rather
#: than leaving a reader to wonder whether "no RATED_BY edge" means "no rating".
UNINGESTED_FEEDS = {
    "RATED_BY": "credit ratings are not ingested yet; the exchange's ratings disclosures need a feed",
    "DIRECTOR_OF": "board and KMP composition is not ingested yet",
    "OWNS": "the shareholding pattern is not ingested yet",
    "RELATED_PARTY_WITH": "related-party transaction disclosures are not ingested yet",
}


@dataclass
class Counts:
    new: int = 0
    revised: int = 0
    unchanged: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def record(self, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "new": self.new,
            "revised": self.revised,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
        }


def end_of_day(day: date) -> datetime:
    """The moment a review on ``day`` asks about: everything known by the end of that IST day."""
    return datetime.combine(day, time(23, 59, 59), tzinfo=IST).astimezone(UTC)


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)


def _when(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return _start_of_day(date.fromisoformat(text[:10]))
        except ValueError:
            return None
    if len(text) <= 10:
        return _start_of_day(value.date())
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def known_from(row: Mapping[str, object], *fields: str) -> datetime | None:
    """The later of when the source was public and when the corpus recorded it. ``None`` if neither."""
    stamps = [w for f in (*fields, "as_of") if (w := _when(row.get(f))) is not None]
    return max(stamps) if stamps else None


# ---- archive text, for passage offsets ---------------------------------------------------------


class ArchiveText:
    """Archived document text by hash, loaded on first use. Offsets are exact or absent."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._paths: dict[str, Path] | None = None

    def _index(self) -> dict[str, Path]:
        if self._paths is None:
            self._paths = {}
            for prov in self.root.glob("*/*.provenance.json"):
                try:
                    sha = str(json.loads(prov.read_text(encoding="utf-8")).get("sha256", ""))
                except (OSError, ValueError):
                    continue
                text = prov.with_name(prov.name.replace(".provenance.json", ".txt.gz"))
                if sha and text.exists():
                    self._paths[sha] = text
        return self._paths

    def offsets(self, sha: str, passage: str) -> tuple[int, int] | None:
        path = self._index().get(sha)
        if path is None or not passage:
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            return None
        start = text.find(passage)
        return None if start < 0 else (start, start + len(passage))


# ---- sources -----------------------------------------------------------------------------------


def companies(log: g.GraphLog, watchlist: Path, *, now: datetime, counts: Counts) -> None:
    if not watchlist.exists():
        counts.skip("watchlist missing")
        return
    with watchlist.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    source = {"inputs": str(watchlist), "code_version": INGEST_VERSION}
    for row in rows:
        ticker = str(row.get("ticker", "")).strip()
        sector = str(row.get("sector", "")).strip()
        if not ticker:
            continue
        cid = g.company_id(ticker)
        counts.record(
            log.add(
                g.Assertion(
                    kind=g.NODE,
                    label="Company",
                    subject=cid,
                    epistemic=g.COMPUTED,
                    source=source,
                    known_from=now,
                    props={"ticker": ticker, "listed": True},
                )
            )
        )
        if sector:
            sid = f"sector:{g.slug(sector)}"
            counts.record(
                log.add(
                    g.Assertion(
                        kind=g.NODE,
                        label="Sector",
                        subject=sid,
                        epistemic=g.COMPUTED,
                        source=source,
                        known_from=now,
                        props={"name": sector},
                    )
                )
            )
            counts.record(
                log.add(
                    g.Assertion(
                        kind=g.EDGE,
                        label="IN_SECTOR",
                        subject=cid,
                        subject_label="Company",
                        object=sid,
                        object_label="Sector",
                        epistemic=g.COMPUTED,
                        source=source,
                        known_from=now,
                    )
                )
            )


def filing_events(
    log: g.GraphLog, rows: Iterable[Mapping[str, object]], *, archive: ArchiveText, counts: Counts
) -> None:
    """Verified events from the corpus reader at the current extraction version."""
    from qalpha.live.extraction import EXTRACTION_VERSION, reader_matches

    for row in rows:
        if str(row.get("verified")).lower() != "true" and row.get("verified") is not True:
            counts.skip("filing event not verified")
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION or not reader_matches(
            row.get("model")
        ):
            counts.skip("filing event from another reader or version")
            continue
        sha, passage, key = (
            str(row.get("doc_sha256", "")),
            str(row.get("passage", "")),
            str(row.get("_key", "")),
        )
        ticker = str(row.get("ticker", ""))
        when = known_from(row, "disseminated_at")
        if not (sha and passage and key and ticker and when):
            counts.skip("filing event missing hash, passage, key, ticker or date")
            continue
        span = archive.offsets(sha, passage)
        disclosed = {
            "doc_sha256": sha,
            "passage": passage,
            "doc_url": str(row.get("doc_url", "")),
            "offset_start": None if span is None else span[0],
            "offset_end": None if span is None else span[1],
            "offsets": "exact" if span else "quote verified by normalised match; no exact offset",
        }
        doc_id, passage_id, event_id = (
            f"document:{sha}",
            f"passage:{sha[:16]}:{g.slug(passage)[:40]}",
            f"event:{key}",
        )
        valid = (
            None if not row.get("event_date") else date.fromisoformat(str(row["event_date"])[:10])
        )
        items = [
            g.Assertion(
                kind=g.NODE,
                label="Document",
                subject=doc_id,
                epistemic=g.COMPUTED,
                source={"inputs": f"archive provenance {sha}", "code_version": INGEST_VERSION},
                known_from=when,
                props={"url": str(row.get("doc_url", "")), "ticker": ticker},
            ),
            g.Assertion(
                kind=g.NODE,
                label="Passage",
                subject=passage_id,
                epistemic=g.DISCLOSED,
                source=disclosed,
                known_from=when,
                props={"text": passage},
            ),
            g.Assertion(
                kind=g.NODE,
                label="Event",
                subject=event_id,
                epistemic=g.DISCLOSED,
                source=disclosed,
                known_from=when,
                valid_from=valid,
                props={
                    "type": str(row.get("event_type", "")),
                    "materiality": str(row.get("materiality", "")),
                    "summary": str(row.get("summary", "")),
                    "event_date": str(row.get("event_date", "")),
                    "reader": str(row.get("model", "")),
                    "evidence_id": key,
                },
            ),
            g.Assertion(
                kind=g.EDGE,
                label="CONTAINS",
                subject=doc_id,
                subject_label="Document",
                object=passage_id,
                object_label="Passage",
                epistemic=g.DISCLOSED,
                source=disclosed,
                known_from=when,
            ),
            g.Assertion(
                kind=g.EDGE,
                label="EVIDENCED_BY",
                subject=event_id,
                subject_label="Event",
                object=passage_id,
                object_label="Passage",
                epistemic=g.DISCLOSED,
                source=disclosed,
                known_from=when,
            ),
            g.Assertion(
                kind=g.EDGE,
                label="ABOUT",
                subject=event_id,
                subject_label="Event",
                object=g.company_id(ticker),
                object_label="Company",
                epistemic=g.DISCLOSED,
                source=disclosed,
                known_from=when,
                valid_from=valid,
            ),
        ]
        for a in items:
            counts.record(log.add(a))


def headline_events(
    log: g.GraphLog, rows: Iterable[Mapping[str, object]], *, counts: Counts
) -> None:
    """Verified headline reports. A report, not an event: nine outlets are nine reports."""
    from qalpha.live.extraction import reader_matches
    from qalpha.live.news import NEWS_VERSION

    for row in rows:
        if str(row.get("verified")).lower() != "true" and row.get("verified") is not True:
            counts.skip("headline not verified")
            continue
        if row.get("news_version") != NEWS_VERSION or not reader_matches(row.get("model")):
            counts.skip("headline from another reader or version")
            continue
        key, ticker = str(row.get("_key", "")), str(row.get("ticker", ""))
        when = known_from(row, "published_at")
        passage, feed, link = (
            str(row.get("passage", "")),
            str(row.get("feed_sha256", "")),
            str(row.get("link", "")),
        )
        if not (key and ticker and when and passage and feed and link):
            counts.skip("headline missing key, ticker, date, passage or feed")
            continue
        disclosed = {"feed_sha256": feed, "link": link, "passage": passage}
        hid = f"headline:{key}"
        counts.record(
            log.add(
                g.Assertion(
                    kind=g.NODE,
                    label="Headline",
                    subject=hid,
                    epistemic=g.DISCLOSED,
                    source=disclosed,
                    known_from=when,
                    props={
                        "type": str(row.get("event_type", "")),
                        "materiality": str(row.get("materiality", "")),
                        "stance": str(row.get("stance", "")),
                        "summary": str(row.get("summary", "")),
                        "evidence_id": key,
                    },
                )
            )
        )
        counts.record(
            log.add(
                g.Assertion(
                    kind=g.EDGE,
                    label="ABOUT",
                    subject=hid,
                    subject_label="Headline",
                    object=g.company_id(ticker),
                    object_label="Company",
                    epistemic=g.DISCLOSED,
                    source=disclosed,
                    known_from=when,
                )
            )
        )


def financial_periods(log: g.GraphLog, quarters: Iterable[Any], *, counts: Counts) -> None:
    """Reconciled filed quarters. A restatement is a new version from the day it was filed."""
    for q in sorted(quarters, key=lambda q: q.filed_at):
        if not q.reconciled:
            counts.skip("quarter does not reconcile")
            continue
        cid = g.company_id(q.ticker)
        pid = f"period:{q.ticker.removesuffix('.NS')}:{q.period_end.isoformat()}:{q.basis}"
        source = {
            "inputs": f"{q.source_url} sha256={q.sha256}",
            "code_version": "financials XBRL parser",
        }
        when = q.filed_at if q.filed_at.tzinfo else q.filed_at.replace(tzinfo=UTC)
        props = {
            "period_start": q.period_start.isoformat(),
            "period_end": q.period_end.isoformat(),
            "basis": q.basis,
            "audited": q.audited,
            "filed_at": when.isoformat(),
            **{k: (None if v is None else str(v)) for k, v in q.facts.items()},
        }
        counts.record(
            log.add(
                g.Assertion(
                    kind=g.NODE,
                    label="FinancialPeriod",
                    subject=pid,
                    epistemic=g.COMPUTED,
                    source=source,
                    known_from=when,
                    valid_from=q.period_end,
                    props=props,
                )
            )
        )
        counts.record(
            log.add(
                g.Assertion(
                    kind=g.EDGE,
                    label="REPORTED",
                    subject=cid,
                    subject_label="Company",
                    object=pid,
                    object_label="FinancialPeriod",
                    epistemic=g.COMPUTED,
                    source={"inputs": source["inputs"], "code_version": source["code_version"]},
                    known_from=when,
                    valid_from=q.period_end,
                )
            )
        )


def decisions(log: g.GraphLog, rows: Iterable[Mapping[str, object]], *, counts: Counts) -> None:
    """The investor's recorded decisions and theses — its own beliefs, labelled as such."""
    last_thesis: dict[str, str] = {}
    held = log_nodes(log)
    for row in sorted(rows, key=lambda r: (str(r.get("as_of", "")), str(r.get("ticker", "")))):
        ticker, as_of, digest = (
            str(row.get("ticker", "")),
            str(row.get("as_of", "")),
            str(row.get("digest", "")),
        )
        if not (ticker and as_of and digest):
            counts.skip("decision missing ticker, date or digest")
            continue
        when = _start_of_day(date.fromisoformat(as_of[:10])) + timedelta(hours=18)
        source = {"inputs": f"receipt digest {digest}", "code_version": str(row.get("version", ""))}
        cid, bare = g.company_id(ticker), ticker.removesuffix(".NS")
        did, tid = f"decision:{digest}:{bare}", f"thesis:{bare}:{as_of[:10]}"
        items = [
            g.Assertion(
                kind=g.NODE,
                label="Decision",
                subject=did,
                epistemic=g.COMPUTED,
                source=source,
                known_from=when,
                props={
                    "action": str(row.get("action", "")),
                    "accepted_quantity": row.get("accepted_quantity"),
                    "status": str(row.get("status", "")),
                    "reason": str(row.get("reason", "")),
                    "model": str(row.get("model", "")),
                    "as_of": as_of,
                },
            ),
            g.Assertion(
                kind=g.EDGE,
                label="DECIDED_ON",
                subject=did,
                subject_label="Decision",
                object=cid,
                object_label="Company",
                epistemic=g.COMPUTED,
                source=source,
                known_from=when,
            ),
        ]
        thesis = str(row.get("thesis", "")).strip()
        if thesis:
            items += [
                g.Assertion(
                    kind=g.NODE,
                    label="Thesis",
                    subject=tid,
                    epistemic=g.COMPUTED,
                    source=source,
                    known_from=when,
                    props={
                        "text": thesis,
                        "invalidate_if": str(row.get("invalidate_if", "")),
                        "as_of": as_of,
                        "belief_of": str(row.get("version", "")),
                    },
                ),
                g.Assertion(
                    kind=g.EDGE,
                    label="ABOUT",
                    subject=tid,
                    subject_label="Thesis",
                    object=cid,
                    object_label="Company",
                    epistemic=g.COMPUTED,
                    source=source,
                    known_from=when,
                ),
            ]
            before = last_thesis.get(bare)
            if before and before != tid:
                items.append(
                    g.Assertion(
                        kind=g.EDGE,
                        label="REVISED_TO",
                        subject=before,
                        subject_label="Thesis",
                        object=tid,
                        object_label="Thesis",
                        epistemic=g.COMPUTED,
                        source=source,
                        known_from=when,
                    )
                )
            last_thesis[bare] = tid
        refs = row.get("evidence_ids")
        for raw_ref in refs if isinstance(refs, list) else []:
            ref = str(raw_ref)
            if ref.startswith(("price:", "exchange:")):
                target, label = cid, "Company"
            else:
                target, label = f"event:{ref}", "Event"
                if target not in held:
                    target, label = f"headline:{ref}", "Headline"
                    if target not in held:
                        counts.skip("decision cites an id the graph does not hold")
                        continue
            items.append(
                g.Assertion(
                    kind=g.EDGE,
                    label="CITES",
                    subject=did,
                    subject_label="Decision",
                    object=target,
                    object_label=label,
                    epistemic=g.COMPUTED,
                    source=source,
                    known_from=when,
                    qualifier=ref,
                )
            )
        for a in items:
            counts.record(log.add(a))


def log_nodes(log: g.GraphLog) -> set[str]:
    return {a.subject for a in log.versions.values() if a.kind == g.NODE}


def gaps(log: g.GraphLog, tickers: Iterable[str], *, now: datetime, counts: Counts) -> None:
    for ticker in tickers:
        cid = g.company_id(ticker)
        for rel, reason in UNINGESTED_FEEDS.items():
            counts.record(log.add(g.gap(cid, rel, reason=reason, known_from=now)))


def ingest_all(log: g.GraphLog, *, now: datetime | None = None) -> dict[str, Any]:
    """Everything on disk into ``log``, then flush. Idempotent: a second run adds nothing."""
    from qalpha.live import evidence_log
    from qalpha.live import financials as company_facts
    from qalpha.live.panels import WATCHLIST_UNIVERSE

    stamp = now or datetime.now(UTC)
    report: dict[str, Any] = {}
    counts = Counts()
    companies(log, WATCHLIST_UNIVERSE, now=stamp, counts=counts)
    report["companies"] = counts.as_dict()

    counts = Counts()
    filing_events(
        log,
        evidence_log.rows(evidence_log.EVENT_LOG),
        archive=ArchiveText(evidence_log.ANNOUNCEMENTS),
        counts=counts,
    )
    report["filing_events"] = counts.as_dict()

    counts = Counts()
    headline_events(log, evidence_log.rows(evidence_log.NEWS_EVENT_LOG), counts=counts)
    report["headlines"] = counts.as_dict()

    counts = Counts()
    financial_periods(log, company_facts.load(), counts=counts)
    report["financials"] = counts.as_dict()

    counts = Counts()
    decisions(log, evidence_log.rows(Path("data/twin/manager/decisions.jsonl")), counts=counts)
    report["decisions"] = counts.as_dict()

    counts = Counts()
    tickers = sorted(
        str(a.props.get("ticker"))
        for a in log.versions.values()
        if a.kind == g.NODE and a.label == "Company" and a.props.get("listed")
    )
    gaps(log, tickers, now=stamp, counts=counts)
    report["gaps"] = counts.as_dict()
    report["rows_written"] = log.flush()
    return report
