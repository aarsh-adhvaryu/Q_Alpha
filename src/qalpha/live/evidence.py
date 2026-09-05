"""Pre-trade evidence from NSE's own regulatory-indicator file (PLAN_SYSTEM §L1, Phase B).

**Why this module exists.** Every input to the buy decision was a price. ``advise_deploy_into_weakness``
reads an adjusted-close panel, an index series and a sector label, and nothing else — so a name that
had been re-rating downward for two years and a name in an ordinary pullback produced the same
number, because the signal is distance below a *trailing* high and the trailing high walks down
behind a falling stock. No amount of compute recovers information that was never supplied.

This is the first adapter that reads something which is not a price, and it reads it from the
exchange rather than deriving it. ``live/valuation.py`` tried to *reproduce* NSE's "Scrip PE is
greater than 50" caution from a yfinance trailing P/E, and got a different answer than NSE did
because yfinance serves consolidated earnings while the exchange computed standalone. The fix for
disagreeing with a source is to read the source.

**Five states, and two of them are different kinds of silence** (see
``reports/PREREGISTRATION_EVIDENCE_V1.md`` §3, frozen before this file was written):

``UNKNOWN`` means *we should know and do not* — the feed failed, or is staler than tolerance.
``NOT_COVERED`` means *this version never claimed to look* — fundamentals, filings, pledges. If the
two ever collapse into each other, every unbuilt feature starts producing ``HUMAN_REQUIRED`` and the
user learns to click through the one that matters.

**A caution is a warning, not a disqualifier.** The exchange mandates a pop-up, not a prohibition, so
the P/E indicator produces ``WATCH``. Blocking a trade on a figure that contradicts the one the
user's own broker is displaying is worse than flagging it. That decision was recorded before the
data was seen.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

#: The five states. ``NOT_COVERED`` is reported per-dimension, never as a whole-name verdict.
PASS = "PASS"
WATCH = "WATCH"
BLOCK = "BLOCK"
UNKNOWN = "UNKNOWN"
NOT_COVERED = "NOT_COVERED"

#: NSE writes ``100`` for "indicator does not apply". Every other value is an active flag: boolean
#: indicators carry ``0``, staged measures (GSM/ASM/ESM) carry the stage number. Verified against
#: REG1_IND270826 and REG1_IND150626 — VBL reads ``0`` on a date its P/E caution was live.
CLEAR = "100"

#: A file older than this cannot speak for today. Pre-registered; do not widen without a new version.
STALENESS_TOLERANCE_DAYS = 4

ARCHIVE_DIR = Path("data/evidence/reg_ind")
_BASE_URL = "https://nsearchives.nseindia.com/content/cm"

# --- column names, exactly as NSE writes them -------------------------------------------------
COL_SYMBOL = "Symbol"
COL_STATUS = "Status"
COL_SERIES = "Series"
COL_GSM = "GSM"
COL_LT_ASM = "Long_Term_Additional_Surveillance_Measure (Long Term ASM)"
COL_ST_ASM = "Short_Term_Additional_Surveillance_Measure (Short Term ASM)"
COL_IRP = "Insolvency_Resolution_Process(IRP)"
COL_BZ_SZ = "Under BZ/SZ Series"
COL_PE_50 = "Scrip PE is greater than 50 (4 trailing quarters)"

_META_COLUMNS = frozenset({"ScripCode", COL_SYMBOL, "Nse Exclusive", COL_STATUS, COL_SERIES})

#: Staged measures where **stage 2 or above** is a hard condition (pre-registration §4).
_STAGED_BLOCK_AT = 2
_STAGED_COLUMNS = (COL_GSM, COL_LT_ASM, COL_ST_ASM)

#: Suspended.
_STATUS_SUSPENDED = "S"
#: Trade-to-trade / surveillance settlement series — delivery-only, and a hard condition here.
_T2T_SERIES = frozenset({"BZ", "SZ", "BE"})

#: Dimensions this version does not evaluate. Reported so that silence is never read as approval.
NOT_COVERED_DIMENSIONS: tuple[str, ...] = (
    "fundamentals",
    "earnings quality",
    "debt and cash flow",
    "promoter pledges",
    "related-party transactions",
    "auditor changes",
    "corporate announcements",
)


@dataclass(frozen=True)
class Provenance:
    """What a later reader needs to re-open the exact document this assessment came from.

    An assessment that cannot name its document hash is not evidence — :func:`assess` returns
    ``UNKNOWN`` rather than a verdict when this is absent.
    """

    source_url: str
    retrieved_at_utc: datetime
    http_status: int
    sha256: str
    byte_length: int
    #: The date the document *belongs to* — the trading day for a daily exchange file, the
    #: dissemination date for a filing. Not the date we fetched it; that is ``retrieved_at_utc``,
    #: and conflating the two is how a stale file passes a freshness check.
    document_date: date

    def render(self) -> str:
        return (
            f"{self.source_url} · retrieved {self.retrieved_at_utc:%Y-%m-%dT%H:%M:%SZ} · "
            f"{self.byte_length:,}b · sha256 {self.sha256[:16]}…"
        )


@dataclass(frozen=True)
class Indicator:
    """One active flag, with the raw value NSE published rather than our interpretation of it."""

    column: str
    raw_value: str

    @property
    def stage(self) -> int | None:
        """The stage number for a staged measure; ``None`` when the value is not an integer."""
        try:
            return int(self.raw_value)
        except ValueError:
            return None


@dataclass(frozen=True)
class Assessment:
    """One name's pre-trade evidence verdict, with everything needed to check it."""

    ticker: str
    state: str
    indicators: tuple[Indicator, ...] = ()
    provenance: Provenance | None = None
    detail: str = ""
    not_covered: tuple[str, ...] = field(default=NOT_COVERED_DIMENSIONS)

    @property
    def blocking(self) -> bool:
        """``BLOCK`` stops a buy. ``WATCH`` and ``UNKNOWN`` require a human, never an auto-buy."""
        return self.state == BLOCK

    @property
    def needs_human(self) -> bool:
        return self.state in {WATCH, UNKNOWN}

    def render(self) -> str:
        head = f"{self.ticker}: {self.state}"
        if self.detail:
            head += f" — {self.detail}"
        if self.indicators:
            flags = " · ".join(f"{i.column} = {i.raw_value}" for i in self.indicators)
            head += f"\n    active: {flags}"
        if self.provenance is not None:
            head += f"\n    source: {self.provenance.render()}"
        head += f"\n    not covered by v1: {', '.join(self.not_covered)}"
        return head


def reg_ind_url(trading_date: date) -> str:
    """The published location of one day's file. NSE names it ``REG1_INDDDMMYY.csv``."""
    return f"{_BASE_URL}/REG1_IND{trading_date:%d%m%y}.csv"


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_reg_ind(text: str) -> dict[str, dict[str, str]]:
    """Parse the CSV into ``{symbol: row}``. Pure — no network, no clock, no defaults."""
    reader = csv.DictReader(io.StringIO(text))
    out: dict[str, dict[str, str]] = {}
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        symbol = row.get(COL_SYMBOL, "")
        if symbol:
            out[symbol] = row
    return out


def active_indicators(row: Mapping[str, str]) -> tuple[Indicator, ...]:
    """Every non-meta column NSE did not write ``100`` into.

    Empty strings are trailing filler, not signal. ``Filler*`` columns are unlabelled reserve space
    in the exchange's layout and carry nothing.
    """
    found: list[Indicator] = []
    for column, value in row.items():
        if column in _META_COLUMNS or not column or column.startswith("Filler"):
            continue
        if value and value != CLEAR:
            found.append(Indicator(column=column, raw_value=value))
    return tuple(found)


def _hard_conditions(row: Mapping[str, str], indicators: Sequence[Indicator]) -> list[str]:
    """The pre-registered ``BLOCK`` set (§4): suspension · T2T series · ASM/GSM stage ≥ 2 · IRP."""
    reasons: list[str] = []
    if row.get(COL_STATUS, "") == _STATUS_SUSPENDED:
        reasons.append("suspended by the exchange")
    series = row.get(COL_SERIES, "")
    if series in _T2T_SERIES:
        reasons.append(f"trade-to-trade settlement series {series}")
    for ind in indicators:
        if ind.column in _STAGED_COLUMNS:
            stage = ind.stage
            if stage is not None and stage >= _STAGED_BLOCK_AT:
                reasons.append(f"{ind.column} stage {stage}")
        elif ind.column == COL_IRP:
            reasons.append("insolvency resolution process active")
        elif ind.column == COL_BZ_SZ:
            reasons.append("flagged under BZ/SZ series")
    return reasons


def assess(
    ticker: str,
    rows: Mapping[str, Mapping[str, str]],
    provenance: Provenance | None,
    *,
    as_of: date,
) -> Assessment:
    """Classify one name against one day's file.

    ``ticker`` may carry the ``.NS`` suffix the price panel uses; NSE writes the bare symbol.

    The three ways this returns ``UNKNOWN`` are all "we should know and do not": no file, a file too
    old to speak for today, or a name the file does not list. None of them is an approval, and none
    of them is ``NOT_COVERED``.
    """
    symbol = ticker.removesuffix(".NS")
    covered = NOT_COVERED_DIMENSIONS

    if provenance is None:
        return Assessment(
            ticker, UNKNOWN, detail="no regulatory-indicator file", not_covered=covered
        )

    age = (as_of - provenance.document_date).days
    if age > STALENESS_TOLERANCE_DAYS:
        return Assessment(
            ticker,
            UNKNOWN,
            provenance=provenance,
            detail=(
                f"file is {age} days old (tolerance {STALENESS_TOLERANCE_DAYS}) — "
                "a stale file cannot speak for today"
            ),
            not_covered=covered,
        )

    row = rows.get(symbol)
    if row is None:
        return Assessment(
            ticker,
            UNKNOWN,
            provenance=provenance,
            detail=f"{symbol} is not listed in the file — absence is not a clean bill",
            not_covered=covered,
        )

    indicators = active_indicators(row)
    hard = _hard_conditions(row, indicators)
    if hard:
        return Assessment(
            ticker, BLOCK, indicators, provenance, "; ".join(hard), not_covered=covered
        )
    if indicators:
        names = ", ".join(i.column for i in indicators)
        return Assessment(
            ticker,
            WATCH,
            indicators,
            provenance,
            f"advisory indicator(s) active: {names}",
            not_covered=covered,
        )
    return Assessment(
        ticker,
        PASS,
        (),
        provenance,
        "no active regulatory indicator on this date",
        not_covered=covered,
    )


def assess_basket(
    tickers: Iterable[str],
    rows: Mapping[str, Mapping[str, str]],
    provenance: Provenance | None,
    *,
    as_of: date,
) -> dict[str, Assessment]:
    """Assess every candidate. Ordering follows the caller's, so a report reads in basket order."""
    return {t: assess(t, rows, provenance, as_of=as_of) for t in tickers}


# --- archival I/O ------------------------------------------------------------------------------
# The raw bytes are written to disk *before* anything is parsed, and the provenance sidecar is
# written from those bytes. A verdict derived from a document nobody kept is not checkable, which
# is the failure the first AI veto demonstrated: it cited a URL that evidenced nothing, and by the
# time anyone looked, the claim could no longer be verified from what had been recorded.


def archive_paths(trading_date: date, *, directory: Path = ARCHIVE_DIR) -> tuple[Path, Path]:
    """``(csv_path, provenance_path)`` for one trading date."""
    stem = f"REG1_IND{trading_date:%d%m%y}"
    return directory / f"{stem}.csv", directory / f"{stem}.provenance.json"


def write_archive(
    payload: bytes,
    document_date: date,
    *,
    http_status: int,
    retrieved_at_utc: datetime | None = None,
    directory: Path = ARCHIVE_DIR,
) -> Provenance:
    """Persist the unmodified bytes plus their provenance sidecar. Returns the provenance."""
    import json

    csv_path, prov_path = archive_paths(document_date, directory=directory)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_bytes(payload)
    prov = Provenance(
        source_url=reg_ind_url(document_date),
        retrieved_at_utc=retrieved_at_utc or datetime.now(UTC),
        http_status=http_status,
        sha256=sha256_of(payload),
        byte_length=len(payload),
        document_date=document_date,
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
            },
            indent=1,
        )
        + "\n"
    )
    return prov


def load_archive(
    trading_date: date, *, directory: Path = ARCHIVE_DIR
) -> tuple[dict[str, dict[str, str]], Provenance | None]:
    """Read one archived day back.

    Returns ``({}, None)`` when the file is missing, which :func:`assess` turns into ``UNKNOWN``.
    **The stored hash is re-checked against the bytes on disk** — a file that no longer matches its
    provenance is treated as missing, because a silently edited primary document is worse than an
    absent one.
    """
    import json

    csv_path, prov_path = archive_paths(trading_date, directory=directory)
    if not (csv_path.exists() and prov_path.exists()):
        return {}, None
    payload = csv_path.read_bytes()
    meta = json.loads(prov_path.read_text())
    if sha256_of(payload) != meta.get("sha256"):
        return {}, None
    prov = Provenance(
        source_url=str(meta["source_url"]),
        retrieved_at_utc=datetime.strptime(
            str(meta["retrieved_at_utc"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC),
        http_status=int(meta["http_status"]),
        sha256=str(meta["sha256"]),
        byte_length=int(meta["bytes"]),
        # Both keys are read: sidecars written before the rename carry ``trading_date``.
        document_date=date.fromisoformat(
            str(meta.get("document_date") or meta.get("trading_date") or trading_date.isoformat())
        ),
    )
    return parse_reg_ind(payload.decode("utf-8", errors="replace")), prov
