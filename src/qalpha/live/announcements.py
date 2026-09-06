"""NSE corporate announcements — the primary documents themselves (PLAN_SYSTEM §L1, Phase B).

**What changes here.** The AI veto searched the open web, four searches for a whole basket, and its
"verification" was a hostname allowlist. A URL on `nseindia.com` passed whether or not the page it
pointed at said anything about the claim — the first real veto cited a stock *quote page*. Nothing
was stored, so a year later nobody could re-open what the model claimed to have read, and re-opening
it is the entire purpose of requiring a citation.

This module fetches the exchange's announcement index for a name, downloads the **actual filing**,
hashes it, archives it beside its provenance, and extracts its text. What the model reads is then a
document this repo holds a copy of, and every claim it makes can be checked against those bytes.

**It decides nothing.** No verdict, no score, no ranking. It hands text and provenance to
:mod:`qalpha.live.extraction`, which extracts events, which are recorded and — for now — consumed by
nobody. Shadow first.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from qalpha.live.evidence import Provenance, sha256_of

ARCHIVE_DIR = Path("data/evidence/announcements")

_INDEX_URL = "https://www.nseindia.com/api/corporate-announcements"
#: NSE serves the archive host without a session; the site root itself answers 403. Verified
#: 2026-09-05. A browser user-agent is required — the default urllib/curl agent is refused.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)
REFERER = "https://www.nseindia.com/"

#: Cap on what one document may contribute to a prompt. A 60-page annual report would otherwise
#: crowd out every other name in the basket and silently truncate the ones that follow.
MAX_DOCUMENT_CHARS = 12_000


@dataclass(frozen=True)
class Announcement:
    """One row of the exchange's announcement index — metadata, not yet the document."""

    symbol: str
    seq_id: str
    subject: str
    summary: str
    disseminated_at: datetime
    attachment_url: str
    isin: str = ""

    @property
    def has_document(self) -> bool:
        return self.attachment_url.lower().endswith(".pdf")

    def render(self) -> str:
        return f"{self.disseminated_at:%Y-%m-%d %H:%M} · {self.symbol} · {self.subject}"


def index_url(symbol: str, *, index: str = "equities") -> str:
    """The published index for one name. Bare NSE symbol, so ``.NS`` is stripped by the caller."""
    return f"{_INDEX_URL}?index={index}&symbol={symbol.removesuffix('.NS')}"


def _parse_dt(raw: str) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_index(payload: str, *, symbol: str = "") -> list[Announcement]:
    """Parse the index JSON. Rows the exchange did not date are **dropped, never dated by us**.

    A filing with no dissemination timestamp cannot be ordered against a price, so it cannot support
    a claim about what was knowable when. Substituting today's date would make it look current.
    """
    try:
        rows = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    out: list[Announcement] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        when = _parse_dt(str(row.get("an_dt") or row.get("exchdisstime") or ""))
        if when is None:
            continue
        sym = str(row.get("symbol") or symbol).strip().upper()
        if not sym:
            continue
        out.append(
            Announcement(
                symbol=sym,
                seq_id=str(row.get("seq_id") or "").strip(),
                subject=str(row.get("desc") or "").strip(),
                summary=str(row.get("attchmntText") or "").strip(),
                disseminated_at=when,
                attachment_url=str(row.get("attchmntFile") or "").strip(),
                isin=str(row.get("sm_isin") or "").strip(),
            )
        )
    out.sort(key=lambda a: a.disseminated_at, reverse=True)
    return out


def since(
    announcements: Iterable[Announcement], cutoff: date, *, limit: int | None = None
) -> list[Announcement]:
    """Announcements disseminated on or after ``cutoff``, newest first."""
    kept = [a for a in announcements if a.disseminated_at.date() >= cutoff]
    return kept[:limit] if limit is not None else kept


# --- the document itself --------------------------------------------------------------------


def document_paths(ann: Announcement, *, directory: Path = ARCHIVE_DIR) -> tuple[Path, Path]:
    """``(pdf_path, provenance_path)``. Keyed on the exchange's own sequence id, never on a title."""
    stem = ann.seq_id or sha256_of(ann.attachment_url.encode())[:16]
    base = directory / ann.symbol
    return base / f"{stem}.pdf", base / f"{stem}.provenance.json"


def write_document(
    payload: bytes,
    ann: Announcement,
    *,
    http_status: int,
    retrieved_at_utc: datetime | None = None,
    directory: Path = ARCHIVE_DIR,
) -> Provenance:
    """Persist the filing exactly as served, plus provenance, **before anything reads it**."""
    pdf_path, prov_path = document_paths(ann, directory=directory)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(payload)
    prov = Provenance(
        source_url=ann.attachment_url,
        retrieved_at_utc=retrieved_at_utc or datetime.now(UTC),
        http_status=http_status,
        sha256=sha256_of(payload),
        byte_length=len(payload),
        document_date=ann.disseminated_at.date(),
    )
    prov_path.write_text(
        json.dumps(
            {
                "source_url": prov.source_url,
                "retrieved_at_utc": prov.retrieved_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "http_status": prov.http_status,
                "bytes": prov.byte_length,
                "sha256": prov.sha256,
                "document_date": prov.document_date.isoformat(),
                "symbol": ann.symbol,
                "seq_id": ann.seq_id,
                "subject": ann.subject,
            },
            indent=1,
        )
        + "\n"
    )
    return prov


def extract_text(payload: bytes) -> str:
    """Text of a filing PDF. Returns ``""`` when it cannot be read — never a guess at the content.

    A scanned filing extracts to nothing. That is an honest empty, and downstream it produces no
    events rather than events about a document nobody could read.
    """
    import io

    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(payload))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception:
        return ""


def load_document(
    ann: Announcement, *, directory: Path = ARCHIVE_DIR
) -> tuple[str, Provenance | None]:
    """Read one archived filing back as text, **re-verifying its hash**.

    A stored document that no longer matches its provenance is treated as absent. A silently edited
    primary source is worse than a missing one, because it still looks like evidence.
    """
    pdf_path, prov_path = document_paths(ann, directory=directory)
    if not (pdf_path.exists() and prov_path.exists()):
        return "", None
    payload = pdf_path.read_bytes()
    meta = json.loads(prov_path.read_text())
    if sha256_of(payload) != meta.get("sha256"):
        return "", None
    prov = Provenance(
        source_url=str(meta["source_url"]),
        retrieved_at_utc=datetime.strptime(
            str(meta["retrieved_at_utc"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC),
        http_status=int(meta["http_status"]),
        sha256=str(meta["sha256"]),
        byte_length=int(meta["bytes"]),
        document_date=date.fromisoformat(str(meta["document_date"])),
    )
    return extract_text(payload), prov


@dataclass(frozen=True)
class SourceDocument:
    """One filing, its text and its provenance — the unit the extractor is allowed to read."""

    announcement: Announcement
    text: str
    provenance: Provenance

    @property
    def excerpt(self) -> str:
        return self.text[:MAX_DOCUMENT_CHARS]

    @property
    def truncated(self) -> bool:
        """Did the model see less than the whole filing?

        A truncated document is **not a document that was read**. The prompt carries
        :data:`MAX_DOCUMENT_CHARS`, so anything past that was never looked at, and counting it as
        covered would assert we had checked text nobody sent. Chunking long filings across several
        calls is the real fix; until then this flag keeps the coverage honest.
        """
        return len(self.text) > MAX_DOCUMENT_CHARS


def documents_for(
    announcements: Sequence[Announcement], *, directory: Path = ARCHIVE_DIR
) -> list[SourceDocument]:
    """Every archived, hash-verified, readable filing among ``announcements``.

    Silently skips what is missing or unreadable — the caller reports coverage separately, because
    "we read nothing about this name" and "we read everything and found nothing" must stay
    distinguishable, and only the caller knows which it is looking at.
    """
    out: list[SourceDocument] = []
    for ann in announcements:
        text, prov = load_document(ann, directory=directory)
        if prov is not None and text:
            out.append(SourceDocument(announcement=ann, text=text, provenance=prov))
    return out


# --- the network seam -------------------------------------------------------------------------
# One function does I/O; everything above is pure and tested without a network. The exchange is
# reachable over a plain GET, so there is no session, no cookie jar and no credential here.

FetchFn = Callable[[str], tuple[int, bytes]]


def _urlopen_fetch(url: str, *, timeout: float = 30.0) -> tuple[int, bytes]:
    """``(http_status, body)``. Network errors surface as a status of 0 and empty bytes."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Referer": REFERER, "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), b""
    except Exception:
        return 0, b""


def fetch_index(symbol: str, *, fetch: FetchFn | None = None) -> list[Announcement] | None:
    """The exchange's announcement index for one name.

    **``None`` means the fetch failed; ``[]`` means the exchange returned nothing.** Those are
    different facts and collapsing them is how "we could not check" becomes "nothing was filed" —
    the same substitution that made an unread filing list read as a clean bill of health. A caller
    that treats ``None`` as empty has reintroduced the defect.
    """
    status, body = (fetch or _urlopen_fetch)(index_url(symbol))
    if status != 200 or not body:
        return None
    return parse_index(body.decode("utf-8", errors="replace"), symbol=symbol.removesuffix(".NS"))


def fetch_document(
    ann: Announcement, *, fetch: FetchFn | None = None, directory: Path = ARCHIVE_DIR
) -> Provenance | None:
    """Download and archive one filing. Returns ``None`` when it could not be stored.

    An already-archived document is **not** re-fetched: the bytes we reasoned about are the bytes we
    keep, and re-downloading could silently swap a revised filing under an existing hash.
    """
    if not ann.has_document:
        return None
    pdf_path, prov_path = document_paths(ann, directory=directory)
    if pdf_path.exists() and prov_path.exists():
        _, existing = load_document(ann, directory=directory)
        if existing is not None:
            return existing
    status, body = (fetch or _urlopen_fetch)(ann.attachment_url)
    if status != 200 or not body:
        return None
    return write_document(body, ann, http_status=status, directory=directory)
