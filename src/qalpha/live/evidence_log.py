"""What the evidence logs say about a set of names on a date — read, never inferred.

Three rules, each of which has been a defect in this repository:

- **The current revision, not every line.** The logs are append-only; a re-read appends a row with the
  same ``_key`` and a higher ``revision``. Counting lines once turned 4 negative items into 12.
- **This corpus's reader, at the current version.** A row from another model, or with no reader
  recorded, is a real reading of something — not a reading of this corpus.
- **Nothing from after the date.** A row recorded, published or dated after ``as_of`` was not knowable
  on ``as_of``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from qalpha.live.extraction import EXTRACTION_VERSION, reader_matches
from qalpha.live.news import NEWS_EVENTS, NEWS_VERSION

EVENT_LOG = Path("data/evidence/events.jsonl")
COVERAGE_LOG = Path("data/evidence/coverage.jsonl")
EXTRACTED_LOG = Path("data/evidence/extracted.jsonl")
#: Documents the reader declined, one row per refusal (written by ``scripts/evidence.py``).
REFUSED_LOG = Path("data/evidence/refused.jsonl")
ANNOUNCEMENTS = Path("data/evidence/announcements")
NEWS_EVENT_LOG = NEWS_EVENTS

#: A coverage row older than this cannot speak for today.
MAX_COVERAGE_AGE_DAYS = 4

_MATERIALITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _truthy(value: object) -> bool:
    return value is True or str(value).lower() == "true"


def rows(path: Path) -> list[dict[str, object]]:
    """Every readable row at its **current revision**. An unreadable line is skipped, never guessed."""
    if not path.exists():
        return []
    out: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if any("_key" in row for row in out):
        from qalpha.live.twin import latest_by_key

        return latest_by_key(out, key="_key")
    return out


def _bare(ticker: object) -> str:
    return str(ticker).removesuffix(".NS")


def filings_read(tickers: Iterable[str], *, as_of: date, path: Path | None = None) -> set[str]:
    """Bare tickers whose filings were fully read, by this corpus, recently, and not after ``as_of``."""
    wanted = {_bare(t) for t in tickers}
    oldest = (as_of - timedelta(days=MAX_COVERAGE_AGE_DAYS)).isoformat()
    read: set[str] = set()
    for row in rows(path or COVERAGE_LOG):
        day = str(row.get("as_of", ""))
        if not (oldest <= day <= as_of.isoformat()):
            continue
        if not _truthy(row.get("complete")):
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION or not reader_matches(
            row.get("reader")
        ):
            continue
        if _bare(row.get("ticker")) in wanted:
            read.add(_bare(row.get("ticker")))
    return read


def _knowable(row: dict[str, object], as_of: date) -> bool:
    limit = as_of.isoformat()
    return all(
        str(row.get(field) or "")[:10] <= limit
        for field in ("as_of", "event_date", "disseminated_at", "published_at")
    )


def events(
    tickers: Iterable[str], *, as_of: date, per_ticker: int, paths: tuple[Path, Path] | None = None
) -> dict[str, list[dict[str, str]]]:
    """Verified filing and headline events per bare ticker: most material first, then newest.

    Every event carries its ``id`` (the log's ``_key``), so a decision can cite it and code can check
    the citation. Headlines are labelled as reports, not events: nine outlets carrying one court order
    are nine reports.
    """
    filing_log, news_log = paths or (EVENT_LOG, NEWS_EVENT_LOG)
    wanted = {_bare(t) for t in tickers}
    found: dict[str, list[dict[str, str]]] = {}
    for source, path in (("filing", filing_log), ("headline", news_log)):
        for row in rows(path):
            ticker = _bare(row.get("ticker"))
            if ticker not in wanted or not _truthy(row.get("verified")):
                continue
            if not reader_matches(row.get("model")):
                continue
            if source == "filing" and row.get("extraction_version") != EXTRACTION_VERSION:
                continue
            if source == "headline" and row.get("news_version") != NEWS_VERSION:
                continue
            if not row.get("_key") or not _knowable(row, as_of):
                continue
            found.setdefault(ticker, []).append(
                {
                    "id": str(row["_key"]),
                    "source": source if source == "filing" else "headline report",
                    "type": str(row.get("event_type", "")),
                    "materiality": str(row.get("materiality", "")),
                    "stance": str(row.get("stance", "")),
                    "date": str(
                        row.get("event_date") or row.get("published_at") or row.get("as_of") or ""
                    )[:10],
                    "summary": str(row.get("summary", "")),
                    "quote": str(row.get("passage", ""))[:400],
                    "uncertainty": str(row.get("uncertainty", "")),
                    "url": str(row.get("doc_url") or row.get("link") or ""),
                }
            )
    for ticker, items in found.items():
        items.sort(key=lambda e: e["date"], reverse=True)
        items.sort(
            key=lambda e: _MATERIALITY_RANK.get(e["materiality"], 3)
        )  # stable: newest within
        found[ticker] = items[:per_ticker]
    return found


@dataclass(frozen=True)
class Coverage:
    """What was read about one name, and — as plainly — what was not.

    ``read`` is the number of documents in the window this corpus actually extracted from.
    ``filed`` is how many the exchange listed. When they differ the difference is **named**, in
    :attr:`unread`, by the exchange's own subject line — because "nobody could read this newspaper
    advertisement" and "nobody looked at this company" are different facts, and only one of them
    should stop an investor. A scanned page the model cannot transcribe is a permanent gap; a name
    with no coverage row at all is an unopened name.
    """

    ticker: str
    #: A coverage row exists for this name, at the current version, from the corpus reader.
    opened: bool
    read: int
    filed: int
    #: ``{date, subject, url}`` per document in the window that has no extraction row.
    unread: tuple[dict[str, str], ...] = ()
    as_of: str = ""

    @property
    def complete(self) -> bool:
        return self.opened and not self.unread and self.read >= self.filed


def _extracted_hashes(path: Path | None = None) -> set[str]:
    return {
        str(row.get("sha256"))
        for row in rows(path or EXTRACTED_LOG)
        if row.get("extraction_version") == EXTRACTION_VERSION and reader_matches(row.get("reader"))
    }


def refused_hashes(path: Path | None = None) -> set[str]:
    """Documents this reader has declined, whatever the count — for saying *why* one was not read."""
    return {
        str(row.get("sha256"))
        for row in rows(path or REFUSED_LOG)
        if row.get("extraction_version") == EXTRACTION_VERSION and reader_matches(row.get("reader"))
    }


def unread_documents(
    ticker: str, *, window_days: int, as_of: date, archive: Path | None = None
) -> list[dict[str, str]]:
    """Documents the exchange listed in the window that this corpus has no reading of.

    Read from the archived index and provenance sidecars — the exchange's own subject line, so an
    unreadable filing can still be *described* to whoever is deciding.
    """
    import json as _json

    base = (archive or ANNOUNCEMENTS) / ticker.removesuffix(".NS")
    index_dir = base / "index"
    if not index_dir.exists():
        return []
    files = sorted(p for p in index_dir.glob("*.json") if not p.name.endswith(".provenance.json"))
    if not files:
        return []
    from qalpha.live.announcements import parse_index, since

    try:
        listed = parse_index(
            files[-1].read_text(encoding="utf-8"), symbol=ticker.removesuffix(".NS")
        )
    except (OSError, ValueError):
        return []
    known = _extracted_hashes()
    declined = refused_hashes()
    out: list[dict[str, str]] = []
    for ann in since(listed, as_of - timedelta(days=window_days)):
        if not ann.has_document or ann.disseminated_at.date() > as_of:
            continue
        prov = base / f"{ann.seq_id}.provenance.json"
        if not prov.exists():
            continue
        try:
            sha = str(_json.loads(prov.read_text(encoding="utf-8")).get("sha256", ""))
        except (OSError, ValueError):
            continue
        if sha and sha not in known:
            has_text = (base / f"{ann.seq_id}.txt.gz").exists()
            out.append(
                {
                    "on": ann.disseminated_at.date().isoformat(),
                    "subject": ann.subject or "(no subject given)",
                    "why": (
                        "the reader declined to read it"
                        if sha in declined
                        else "a scan with no text, and transcription failed"
                        if not has_text
                        else "not read yet"
                    ),
                    "url": ann.attachment_url,
                }
            )
    return out


def coverage(
    tickers: Iterable[str], *, as_of: date, path: Path | None = None
) -> dict[str, Coverage]:
    """Per name: was it opened, how much was read, and exactly which documents were not."""
    oldest = (as_of - timedelta(days=MAX_COVERAGE_AGE_DAYS)).isoformat()
    latest: dict[str, dict[str, object]] = {}
    for row in rows(path or COVERAGE_LOG):
        day = str(row.get("as_of", ""))
        if not (oldest <= day <= as_of.isoformat()):
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION or not reader_matches(
            row.get("reader")
        ):
            continue
        latest[_bare(row.get("ticker"))] = row
    out: dict[str, Coverage] = {}
    for ticker in tickers:
        bare = _bare(ticker)
        latest_row = latest.get(bare)
        if latest_row is None:
            out[bare] = Coverage(ticker=bare, opened=False, read=0, filed=0)
            continue
        read = int(str(latest_row.get("documents_read", 0) or 0))
        filed = int(str(latest_row.get("filings_in_window", 0) or 0))
        gaps = (
            unread_documents(
                bare, window_days=int(str(latest_row.get("window_days", 10) or 10)), as_of=as_of
            )
            if read < filed
            else []
        )
        out[bare] = Coverage(
            ticker=bare,
            opened=True,
            read=read,
            filed=filed,
            unread=tuple(gaps),
            as_of=str(latest_row.get("as_of", "")),
        )
    return out
