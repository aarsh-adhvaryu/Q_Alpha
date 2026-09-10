"""Daily evidence collection — shadow mode. Observes candidates; changes nothing.

    uv run python scripts/evidence.py daily

**What it does.** For today's candidate basket plus every held name: fetch and archive the exchange's
regulatory-indicator file, fetch and archive each name's announcement index, download and archive
every filing in the window, extract events from those filings, record them append-only, and render a
pre-trade report.

**What it does not do.** It does not touch a book, size an order, alter a basket, or feed the twin.
`CORE_V1`'s clock is untouched by design — its treatment resets only on a screen change and nothing
here is one. The report is written so a human can read whether this layer *would* have said
something useful, for as long as it takes to trust it.

**Why shadow first.** With filings listed but unread every candidate reads `UNKNOWN`, which is
correct and useless: a gate answering `HUMAN_REQUIRED` eight times a day about names it has not
opened teaches its reader to click through. Coverage has to become real before the answer means
anything, and this job is what makes it real.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from qalpha.config import Config
from qalpha.live.announcements import (
    Announcement,
    SourceDocument,
    documents_for,
    fetch_and_archive_index,
    fetch_document,
    since,
)
from qalpha.live.evidence import (
    STALENESS_TOLERANCE_DAYS,
    Assessment,
    Provenance,
    load_archive,
    parse_reg_ind,
    reg_ind_url,
    write_archive,
)
from qalpha.live.evidence import (
    assess as exchange_assess,
)
from qalpha.live.extraction import (
    DEFAULT_MODEL,
    EXTRACTION_VERSION,
    ExtractedEvent,
    default_generate,
    event_rows,
    extract,
)
from qalpha.live.pipeline import (
    ANCHOR_TICKER,
    ProposedOrder,
    decision_rows,
    propose,
)
from qalpha.live.pretrade import (
    AnnouncementCoverage,
    assess_basket,
    basket_markdown,
)
from qalpha.live.twin import _append_jsonl

EVENT_LOG = Path("data/evidence/events.jsonl")
DECISION_LOG = Path("data/evidence/decisions.jsonl")
#: Documents already put through the extractor, keyed on their content hash. Without it the same
#: filing is re-read every day of its window — measured at ~33 model calls a day, roughly ten times
#: what is needed, because a 10-day window re-presents the same documents ten times.
EXTRACTED_LOG = Path("data/evidence/extracted.jsonl")
REPORT = Path("reports/pretrade.md")
COVERAGE_LOG = Path("data/evidence/coverage.jsonl")

#: How far back to look for filings. Wider than a day so a missed run is caught up rather than
#: leaving a permanent hole — GitHub drops scheduled jobs under load, and one was dropped on
#: 2026-09-05.
LOOKBACK_DAYS = 10

#: How far back to read for a name **never covered before**. Ten days of history is not a basis for
#: judging a company: an auditor resignation from day eleven would simply be invisible, and the name
#: would read clean because nobody looked. A first sighting reads a year; every day after that reads
#: :data:`LOOKBACK_DAYS`, because by then the gap is genuinely small.
BOOTSTRAP_DAYS = 365

#: Cap on documents fetched per name per run. A first run on a name with years of filings would
#: otherwise download hundreds; the window bounds it in practice and this bounds the pathological
#: case. **Hitting it makes coverage incomplete, which reads UNKNOWN — it never silently passes.**
MAX_DOCUMENTS_PER_NAME = 25  # retained: other modules import it
#: Filings fetched per name per run. Fetching is a cached GET; this only bounds a pathological name.
MAX_FETCH_PER_NAME = 200
#: Documents sent to the MODEL per name per run — the cap that actually costs tokens and minutes.
#: Unread documents carry over, so a 365-day bootstrap closes over several runs rather than never.
MAX_EXTRACT_PER_RUN = 25


def _fetch_one_reg_ind(day: date) -> tuple[dict[str, dict[str, str]], Provenance | None]:
    """One day's regulatory-indicator file, archived before it is parsed."""
    import urllib.request

    from qalpha.live.announcements import REFERER, USER_AGENT

    rows, prov = load_archive(day)
    if prov is not None:
        return rows, prov
    try:
        request = urllib.request.Request(
            reg_ind_url(day), headers={"User-Agent": USER_AGENT, "Referer": REFERER}
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            status, payload = int(response.status), bytes(response.read())
    except Exception:
        return {}, None
    # A partial file is worse than none: it would read as "no indicator active" for every name it
    # happens not to contain. The real file is ~600 KB.
    if status != 200 or len(payload) < 10_000:
        return {}, None
    prov = write_archive(payload, day, http_status=status)
    print(
        f"[evidence] REG1_IND {day} archived \u00b7 {prov.byte_length:,}b \u00b7 sha {prov.sha256[:16]}\u2026"
    )
    return parse_reg_ind(payload.decode("utf-8", errors="replace")), prov


def _fetch_reg_ind(as_of: date) -> tuple[dict[str, dict[str, str]], Provenance | None]:
    """The most recent regulatory-indicator file **within the staleness tolerance**.

    The exchange publishes on trading days, so a weekend or holiday run has no file of its own and
    must read back to the last session. Walking back further than
    :data:`~qalpha.live.evidence.STALENESS_TOLERANCE_DAYS` is refused rather than stretched:
    ``assess`` would reject the file anyway, and a caller that quietly widened the window would be
    substituting an old fact for a missing one.
    """
    for back in range(STALENESS_TOLERANCE_DAYS + 1):
        day = as_of - timedelta(days=back)
        rows, prov = _fetch_one_reg_ind(day)
        if prov is not None:
            if back:
                print(
                    f"[evidence] no file for {as_of} (non-trading day) \u2014 using {day}, {back}d old"
                )
            return rows, prov
    print(
        f"[evidence] no REG1_IND within {STALENESS_TOLERANCE_DAYS} days of {as_of} \u2014 "
        "the exchange dimension reads UNKNOWN, which blocks every PASS"
    )
    return {}, None


@dataclass(frozen=True)
class ScreenBasket:
    """What the deterministic screen actually proposed, with its ranking and sizing intact."""

    orders: list[ProposedOrder]
    held: list[str]
    cash: Decimal
    sector_of: dict[str, str]
    prices: dict[str, Decimal]

    @property
    def tickers(self) -> list[str]:
        """Names to gather evidence on: the screen's picks in rank order, then what is held."""
        seen: dict[str, None] = {}
        for order in self.orders:
            seen.setdefault(order.ticker, None)
        for ticker in self.held:
            seen.setdefault(ticker, None)
        return list(seen)


def _screen_basket(cfg: Config, as_of: date) -> ScreenBasket:
    """Run the screen **as the policy specifies, against the real book and the real cash.**

    ### The defect this replaces

    The previous version ran the screen against a fabricated ₹1,00,000 on an *empty* portfolio,
    took the correctly ranked and sized orders it returned, **discarded the rank and the quantity on
    the very next line**, merged the bare tickers with current holdings, and returned them
    ``sorted()`` — alphabetically. The decision loop was then handed **one share** of each, in
    alphabetical order, funded by a *different* budget: the book's actual idle cash.

    So the report read EXECUTE over a ranking the screen never produced, at sizes it never chose,
    against money it was never shown. Every unit test passed, because they hand correctly ranked and
    sized candidates straight to ``propose`` and none of them exercises this function. Right
    function, wrong argument — the exact class the golden-day replay exists to catch, and could not,
    because nothing tested the caller.

    ### Why a rejected name is not backfilled with the next stock

    Replacing a rejected pick requires re-running the screen without it, which **re-sizes the whole
    basket**. ``max_names`` is part of the frozen policy: a screen asked for a different number of
    names is a different screen, and measuring it would stop measuring the thing under test. So a
    rejected name shrinks the basket and its money goes to the anchor. The anchor is the
    replacement, and it is an honest one.
    """

    from paper import _load_benchmark_series

    from qalpha.backtest.portfolio import Portfolio
    from qalpha.data.ingest import load_parquet
    from qalpha.live.deploy import advise_deploy_into_weakness
    from qalpha.live.twin import CORE_V1, TWIN_FULL, load_books

    held: list[str] = []
    portfolio: Portfolio | None = None
    cash = Decimal("0")
    try:
        books = load_books(cfg)
        book = books.get(CORE_V1) or books.get(TWIN_FULL)
        if book is not None:
            portfolio = book.portfolio
            cash = book.portfolio.cash
            held = sorted(t for t, q in book.portfolio.positions().items() if q > 0)
    except Exception as exc:
        print(f"[evidence] could not read the books ({exc}) — no screen basket today")

    try:
        panel = load_parquet("data/historical/prices_watchlist.parquet")
        wl = pd.read_csv("data/universes/nifty100_watchlist.csv")
        sector_of = dict(zip(wl["ticker"], wl["sector"], strict=False))
        watchlist = [t for t in wl["ticker"] if t in panel.adj_close.columns]
    except Exception as exc:
        print(f"[evidence] no watchlist panel ({exc}) — covering held names only")
        return ScreenBasket([], held, cash, {}, {})

    marks: dict[str, Decimal] = {}
    for ticker in set(watchlist) | set(held) | {ANCHOR_TICKER}:
        if ticker in panel.adj_close.columns:
            series = panel.adj_close[ticker].dropna()
            if len(series):
                marks[ticker] = Decimal(str(float(series.iloc[-1])))
    if ANCHOR_TICKER not in marks:
        try:
            bench = _load_benchmark_series().dropna()
            if len(bench):
                marks[ANCHOR_TICKER] = Decimal(str(float(bench.iloc[-1])))
        except Exception:
            pass

    if portfolio is None or cash <= 0:
        return ScreenBasket([], held, cash, sector_of, marks)

    try:
        advice = advise_deploy_into_weakness(
            portfolio,
            cash,
            watchlist,
            sector_of,
            panel,
            _load_benchmark_series(),
            min(as_of, pd.Timestamp(panel.adj_close.index.max()).date()),
            max_names=cfg.deploy_policy.max_names_default,
            spend_idle_cash=False,
        )
    except Exception as exc:
        print(f"[evidence] the screen did not run ({exc}) — covering held names only")
        return ScreenBasket([], held, cash, sector_of, marks)

    # Rank AND quantity preserved. The screen orders by allocated weight, so index 0 is its
    # strongest preference, and the quantity is the one it sized. Nothing downstream changes either.
    orders = [
        ProposedOrder(str(o.ticker), int(o.quantity), Decimal(str(o.price)), rank=i)
        for i, o in enumerate(advice.deploy.buy_orders)
        if int(o.quantity) > 0
    ]
    return ScreenBasket(orders, held, cash, sector_of, marks)


def _already_extracted() -> set[str]:
    """Document hashes whose findings are **on file** at the current extractor version.

    A version bump re-reads everything on purpose: EX-1 rated routine results `high` because the
    prompt never said material to whom, so its findings are not the findings EX-2 would produce.

    **A row alone is not enough.** It must carry ``events_recorded`` — written only after the events
    it counts were durably appended (see :func:`_mark_extracted`). Rows without that field were
    written by the version of this script that marked documents read *before* persisting anything,
    so they attest to nothing; they are re-read, which costs tokens and loses no evidence.

    That is not hypothetical. On 2026-09-08 ``extracted.jsonl`` carried **199 rows at EX-2 while
    events.jsonl held 193 events, every one of them EX-1** — 199 documents recorded as read whose
    findings existed nowhere. Under the old rule every one of them was a permanent cache hit.
    """
    if not EXTRACTED_LOG.exists():
        return set()
    out: set[str] = set()
    for line in EXTRACTED_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("extraction_version") == EXTRACTION_VERSION and "events_recorded" in row:
            out.add(str(row.get("sha256", "")))
    return out


def _mark_extracted(hashes: object, *, events_recorded: int) -> None:
    """Record that these documents were read **and that their findings reached the log**.

    Call this LAST — after the events and the coverage row are on disk. The receipt is written after
    the thing it is a receipt for, so an interruption can only ever lose the receipt, never the
    evidence. The reverse ordering is what produced the 199 orphaned rows above: the mark was
    durable per name inside the loop while the events waited in memory for the loop to finish, and
    anything that stopped the run in between turned unread documents into permanent cache hits.

    ``events_recorded`` is the count for this batch, and **zero is a real answer** — a filing that
    genuinely says nothing a shareholder need worry about is a no-event receipt, which is different
    from a document nobody read.
    """
    rows = [
        {
            "sha256": h,
            "extraction_version": EXTRACTION_VERSION,
            "events_recorded": events_recorded,
            "_key": f"{EXTRACTION_VERSION}:{h}",
        }
        for h in hashes
    ]
    if not rows:
        return
    try:
        _append_jsonl(EXTRACTED_LOG, rows, key="_key")
    except Exception as exc:
        print(f"[evidence] WARNING: extraction ledger not updated ({exc})", file=sys.stderr)


def _record_coverage(as_of: date, ticker: str, cov: AnnouncementCoverage, window_days: int) -> None:
    """Write one name's coverage row the moment that name is finished.

    This was a single bulk write after the whole loop, which meant a run that did not reach the end
    recorded no coverage for any name — including the ones it had fully read. On 2026-09-08 the step
    was killed at its 20-minute cap having produced 110 events, and **not one coverage row was
    written**, so every name kept reading "Filings NOT read" on the buy screen while its findings sat
    in ``events.jsonl``. Same disease as the extraction receipt, one file over.

    ``_append_jsonl`` supersedes by revision rather than replacing, so a row written here can be
    corrected by a later run and never lost — including the incomplete rows a killed run leaves,
    which is what ``_seen_before`` needs in order not to burn a name's 365-day bootstrap.
    """
    try:
        _append_jsonl(
            COVERAGE_LOG,
            [
                {
                    "as_of": as_of.isoformat(),
                    "ticker": ticker,
                    "filings_in_window": cov.filings_in_window,
                    "documents_read": cov.documents_read,
                    "extraction_ran": cov.extraction_ran,
                    "index_fetched": cov.index_fetched,
                    "complete": cov.complete,
                    # The window this verdict actually covers. Without it a reader cannot tell a
                    # ten-day look from a year's, and both would print the same word.
                    "window_days": window_days,
                    "extraction_version": EXTRACTION_VERSION,
                    "_key": f"{as_of.isoformat()}:{ticker}",
                }
            ],
            key="_key",
        )
    except Exception as exc:
        print(f"[evidence] WARNING: coverage not recorded for {ticker} ({exc})", file=sys.stderr)


def _recall_events(hashes: set[str], path: Path = EVENT_LOG) -> list[ExtractedEvent]:
    """Reload the findings already on file for these documents. **The cache must not lose warnings.**

    A cached document counted toward coverage and returned NOTHING to the assessment, so the same
    archived filing produced ``WATCH`` on the run that read it and ``PASS`` on every run after:

        first run   coverage complete · 1 verified concern · WATCH
        cached run  coverage complete · 0 findings         · PASS

    The event was on disk the whole time. The cached path simply never read it back — which turns a
    real auditor-resignation warning into a clean bill on the second day, silently. Reading the
    document again would cost the tokens the cache exists to save; reading its FINDINGS costs a file
    scan.

    Only current-version, verified rows are returned, for the same reasons the live path applies:
    EX-1 rated routine results ``high``, and an unverified quote is a fabrication.
    """
    if not hashes or not path.exists():
        return []
    out: list[ExtractedEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") != "event" or str(row.get("doc_sha256", "")) not in hashes:
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION or not row.get("verified"):
            continue
        try:
            out.append(
                ExtractedEvent(
                    ticker=str(row["ticker"]),
                    event_type=str(row.get("event_type", "")),
                    event_date=(
                        date.fromisoformat(str(row["event_date"]))
                        if row.get("event_date")
                        else None
                    ),
                    materiality=str(row.get("materiality", "")),
                    passage=str(row.get("passage", "")),
                    summary=str(row.get("summary", "")),
                    uncertainty=str(row.get("uncertainty", "")),
                    doc_sha256=str(row.get("doc_sha256", "")),
                    doc_url=str(row.get("doc_url", "")),
                    disseminated_at=datetime.fromisoformat(
                        str(row.get("disseminated_at", "1970-01-01T00:00:00+00:00"))
                    ),
                    model=str(row.get("model", "")),
                    extraction_version=str(row.get("extraction_version", "")),
                    verified=True,
                )
            )
        except (KeyError, ValueError):
            continue
    return out


def _persist_events(events: list[ExtractedEvent], as_of: date) -> bool:
    """Append one name's events to the log. ``True`` only if they are durably on disk.

    Returns True for an empty list: nothing to write is not a failure, and the caller still needs to
    write a no-event receipt for the documents it read.
    """
    if not events:
        return True
    try:
        _append_jsonl(EVENT_LOG, event_rows(events, as_of=as_of), key="_key")
        return True
    except Exception as exc:
        print(f"[evidence] WARNING: events not recorded ({exc})", file=sys.stderr)
        return False


def _seen_before(ticker: str) -> bool:
    """Has this name ever been **successfully** covered at the current extractor?

    Not "does a row exist". A row is written every run including the failed ones — no API key, an
    extraction that errored, a document cap that left the window unread. Counting those as seen
    means the 365-day bootstrap is skipped for a name nobody ever finished reading, which is the
    only chance that name gets at a year of history.

    Sixteen incomplete rows written during local testing on 2026-09-08 would have done exactly that
    to sixteen names.
    """
    if not COVERAGE_LOG.exists():
        return False
    for line in COVERAGE_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            row.get("ticker") == ticker
            and row.get("complete")
            and row.get("extraction_version") == EXTRACTION_VERSION
        ):
            return True
    return False


def _window_days(ticker: str) -> int:
    """The assessment window for this name, in days. Recorded, never assumed by a reader."""
    return LOOKBACK_DAYS if _seen_before(ticker) else BOOTSTRAP_DAYS


def _cover_name(
    ticker: str, as_of: date, cutoff: date, generate: object | None, model: str
) -> tuple[AnnouncementCoverage, list[ExtractedEvent], int]:
    """Fetch, archive, read and extract one name. Returns ``(coverage, events, unverified)``."""
    anns, index_prov = fetch_and_archive_index(ticker, as_of)
    if anns is None:
        print(f"  {ticker:<16} index UNREACHABLE — dimension reads UNKNOWN")
        return AnnouncementCoverage(), [], 0

    # COUNT THE WHOLE WINDOW, FETCH ONLY A CAPPED SLICE OF IT. The previous version sliced and
    # counted the same list, so a name with 30 filings reported "25 read of 25" and read as fully
    # covered. The cap is a fetch budget, never a redefinition of what was filed — and a name that
    # exceeds it is INCOMPLETE, which is UNKNOWN, which is the honest answer.
    in_window = [a for a in since(anns, cutoff) if a.has_document]

    # FETCH THE WHOLE WINDOW; CAP ONLY THE MODEL CALLS. Fetching is a cached HTTP GET and costs
    # nothing after the first time; extraction is what costs tokens and minutes. The old code capped
    # the FETCH at the newest 25, which made a name with more filings than that **permanently
    # incomplete**: `complete` requires documents_read >= filings_in_window, documents_read could
    # never exceed 25, and every run re-selected the same newest 25. Thirty filings meant UNKNOWN
    # for ever, and the buy screen said "Filings NOT read" for that name until the end of time.
    stored: list[Announcement] = []
    for ann in in_window[:MAX_FETCH_PER_NAME]:
        if fetch_document(ann) is not None:
            stored.append(ann)
    docs = documents_for(stored)

    truncated = 0  # chunking means nothing is truncated; kept as a guard, not an expectation
    events: list[ExtractedEvent] = []
    unverified = 0
    extraction_ran = False
    done = _already_extracted()
    # Documents already carrying a current-version receipt have been read on an earlier run. They
    # count toward coverage without costing a token again — that is what makes the window close
    # ACROSS runs instead of restarting every day (gate 3: "bootstrap the declared filing window
    # across capped runs").
    already = [d for d in docs if d.provenance.sha256 in done]
    fresh = [d for d in docs if d.provenance.sha256 not in done]
    if len(fresh) > MAX_EXTRACT_PER_RUN:
        print(
            f"  {ticker:<16} {len(fresh)} unread of {len(in_window)} filed — extracting "
            f"{MAX_EXTRACT_PER_RUN} this run, the rest resume tomorrow"
        )
        fresh = fresh[:MAX_EXTRACT_PER_RUN]
    # WHAT THE CACHE ALREADY KNOWS. Without this the findings of a cached document never reach the
    # assessment, and a filing that produced WATCH on Monday produces PASS on Tuesday.
    recalled = _recall_events({d.provenance.sha256 for d in already})
    if recalled:
        print(f"  {ticker:<16} {len(recalled)} concern(s) recalled from earlier runs")
    if docs and not fresh:
        # Every document in this window carries a receipt proving its findings reached events.jsonl
        # (``_already_extracted`` only counts rows that do). Re-reading would cost the same tokens
        # for the same answer. This branch used to assume that rather than check it, so a poisoned
        # cache produced `complete: true` with no events on file — unread reading as clean, which is
        # the fifteenth row of the table in CLAUDE.md.
        extraction_ran = True
        docs_to_read: list[SourceDocument] = []
    else:
        docs_to_read = fresh
    if generate is not None and docs_to_read:
        found, discarded, _raw, usage = extract(docs_to_read, generate=generate, model=model)  # type: ignore[arg-type]
        extraction_ran = usage.get("failed_batches", 0) == 0
        events, unverified = found, discarded
        if not extraction_ran:
            print(f"  {ticker:<16} extraction had {usage['failed_batches']} failed batch(es)")
        # ORDER IS THE WHOLE FIX. Events first, receipt second — and no receipt at all if the events
        # did not land. An interruption here can lose a receipt, which costs one re-read tomorrow.
        # It can no longer lose the evidence while keeping the receipt, which cost 199 documents.
        elif _persist_events(found, as_of):
            _mark_extracted([d.provenance.sha256 for d in docs_to_read], events_recorded=len(found))
        else:
            extraction_ran = False  # the findings are not on file, so this name is NOT covered
    elif generate is None:
        pass  # reported once for the whole run, not once per name
    else:
        extraction_ran = True  # nothing filed: there was nothing to extract, and that is complete

    # Read = carries a receipt. `already` were read on earlier runs; the fresh batch joins them only
    # if this run's extraction actually landed. Counting len(docs) counted FETCHED, not read, which
    # is the same "listing is not reading" defect AnnouncementCoverage was created to stop.
    read_now = len(already) + (len(fresh) if extraction_ran else 0)
    coverage = AnnouncementCoverage(
        # The true window size, not the capped slice. This is the number that decides completeness.
        filings_in_window=len(in_window),
        documents_read=read_now,
        documents_truncated=truncated,
        extraction_ran=extraction_ran,
        index_fetched=True,
    )
    flag = "✓" if coverage.complete else "…"
    print(
        f"  {ticker:<16} {flag} {len(in_window):>3} filed · {read_now:>3} read "
        f"({len(already)} cached + {len(fresh) if extraction_ran else 0} new) · "
        f"{len(events):>2} event(s) · {unverified} discarded"
        + (f" · index sha {index_prov.sha256[:12]}…" if index_prov else "")
    )
    # Recalled first: they are the older findings, and the order a reader sees them in should be
    # the order they were found in.
    return coverage, [*recalled, *events], unverified


def _record_gaps(as_of: date) -> None:
    """Name any **trading session** the twin has no row for.

    Sessions come from the benchmark price series, not from ``weekday() < 5``. A weekday rule
    false-positives on every exchange holiday, and an alarm that cries wolf on Diwali is one the
    reader learns to skip — which is exactly how a genuinely dropped cron would then go unnoticed.
    """
    from qalpha.live.twin import load_history

    rows = load_history()
    if not rows:
        return
    seen = {str(r.get("as_of")) for r in rows}
    first = date.fromisoformat(min(seen))
    try:
        from paper import _load_benchmark_series

        sessions = [d.date() for d in _load_benchmark_series().index]
    except Exception as exc:
        print(f"[evidence] cannot list trading sessions ({exc}) — gap check skipped, not passed")
        return
    missing = [d for d in sessions if first <= d < as_of and d.isoformat() not in seen]
    if not missing:
        return
    print(
        f"[evidence] ⚠️ the twin has NO row for {len(missing)} trading session(s): "
        + ", ".join(d.isoformat() for d in missing[-10:])
        + "\n           A missing session is a hole in the record, not a zero. GitHub drops "
        "scheduled jobs under load."
    )


def _budget_is_new(cash: Decimal) -> bool:
    """Has the deployable money changed since the last decision we recorded?

    A shadow proposal that never executes sees the same idle cash every day. Logging it daily would
    inflate the cohort with repeats of one decision — and a count of observations is exactly the
    thing the cohort exists to be trusted on.
    """
    if not DECISION_LOG.exists():
        return True
    last = ""
    for line in DECISION_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                last = str(json.loads(line).get("budget", ""))
            except json.JSONDecodeError:
                continue
    return last != str(cash)


def cmd_daily(cfg: Config, as_of: date) -> int:
    print(f"[evidence] shadow run for {as_of} — observes candidates, changes nothing")
    _record_gaps(as_of)

    rows, exchange_prov = _fetch_reg_ind(as_of)
    basket = _screen_basket(cfg, as_of)
    tickers = basket.tickers
    if not tickers:
        print("[evidence] no candidates and no holdings — nothing to cover")
        return 0
    print(
        f"[evidence] covering {len(tickers)} name(s) — {len(basket.orders)} screened "
        f"(₹{sum((o.value for o in basket.orders), Decimal('0')):,.0f} of ₹{basket.cash:,.0f} cash), "
        f"{len(basket.held)} held · filings since {as_of - timedelta(days=LOOKBACK_DAYS)}"
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    generate = default_generate(api_key) if api_key else None
    if generate is None:
        print(
            "[evidence] no ANTHROPIC_API_KEY — filings will be archived but NOT read. Coverage "
            "stays incomplete and every name reads UNKNOWN, which is the honest answer."
        )

    coverage: dict[str, AnnouncementCoverage] = {}
    windows: dict[str, int] = {}
    events: dict[str, list[ExtractedEvent]] = {}
    unverified: dict[str, int] = {}
    # A BUDGET, NOT A CAP. The workflow gives this step 20 minutes and SIGKILLs it at the boundary,
    # and `continue-on-error` then reports the corpse as "success" — which is exactly what happened
    # on 2026-09-08 (16:44:54 → 17:05:06, killed at 20m12s, step green, no coverage written at all).
    # Stopping ourselves a little early means the run ends by choice: everything done is on disk,
    # the names not reached are named, and the exit says so. Being killed loses the summary and the
    # in-flight name's work; stopping loses neither.
    budget = timedelta(seconds=int(os.environ.get("EVIDENCE_BUDGET_SECONDS", "900")))
    started = datetime.now(UTC)
    # `covered` is the count already finished — at the break it equals the loop index, because
    # every earlier iteration wrote its coverage row before incrementing.
    for covered, ticker in enumerate(tickers):
        if datetime.now(UTC) - started > budget:
            print(
                f"[evidence] time budget {budget} reached after {covered}/{len(tickers)} name(s). "
                f"Stopping cleanly — everything read so far is on disk, and the receipts mean "
                f"tomorrow's run resumes past it rather than starting again."
            )
            break
        days = _window_days(ticker)
        windows[ticker] = days
        if days != LOOKBACK_DAYS:
            print(
                f"  {ticker:<16} first sighting — reading {days} days of filings, not {LOOKBACK_DAYS}"
            )
        cov, found, bad = _cover_name(ticker, as_of, as_of - timedelta(days=days), generate, model)
        coverage[ticker] = cov
        events[ticker] = found
        unverified[ticker] = bad
        # DURABLE PER NAME, for the same reason the events are. This was one bulk write after the
        # loop, so the 2026-09-08 timeout produced 110 events and ZERO coverage rows — every name
        # still reading "Filings NOT read" on the buy screen while its findings sat in events.jsonl.
        # A row written here can only be superseded by a later revision, never lost.
        _record_coverage(as_of, ticker, cov, windows[ticker])

    # Events are already on disk — ``_cover_name`` persists each name's findings before it writes
    # that name's receipt. This used to be the single bulk write for the whole run, which is what
    # made every event in the run depend on the last name finishing.
    all_events = [e for found in events.values() for e in found]
    if all_events:
        print(f"[evidence] {len(all_events)} event(s) recorded → {EVENT_LOG}")

    exchange: dict[str, Assessment] = (
        {t: exchange_assess(t, rows, exchange_prov, as_of=as_of) for t in tickers}
        if exchange_prov is not None
        else {}
    )
    report = assess_basket(
        tickers, exchange=exchange, events=events, coverage=coverage, unverified=unverified
    )

    proposal = propose(
        as_of=as_of,
        candidates=basket.orders,
        target_names=len(basket.orders),
        holdings=dict.fromkeys(basket.held, 1),
        prices=basket.prices,
        sector_of=basket.sector_of,
        exchange=exchange,
        events=events,
        coverage=coverage,
        unverified=unverified,
        budget=basket.cash,
        anchor_price=basket.prices.get(ANCHOR_TICKER),
    )
    print(f"[evidence] shadow decision: {proposal.outcome} — {proposal.reason}")

    # THE SAME CASH IS NOT A NEW OBSERVATION. This runs daily against whatever is idle, so without
    # this guard the cohort would fill with the same names re-"decided" every day and look like many
    # observations when it is one. A decision is recorded only when the money behind it changed.
    if _budget_is_new(basket.cash):
        try:
            rows = [{**r, "budget": str(basket.cash)} for r in decision_rows(proposal)]
            if rows:
                n = _append_jsonl(DECISION_LOG, rows, key="_key")
                print(f"[evidence] {len(rows)} decision(s) recorded → {DECISION_LOG} ({n} on file)")
        except Exception as exc:
            print(f"[evidence] WARNING: decisions not recorded ({exc})", file=sys.stderr)
    else:
        print(
            f"[evidence] budget unchanged at ₹{basket.cash:,.0f} — not recorded again; "
            "the same cash re-examined is not a new observation"
        )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    complete = sum(1 for c in coverage.values() if c.complete)
    REPORT.write_text(
        f"# Pre-trade evidence — {as_of}\n\n"
        f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. **Shadow mode: this changes nothing.** "
        "No book, basket or order is affected, and the CORE_V1 clock is untouched._\n\n"
        f"Coverage: **{complete} of {len(tickers)}** name(s) fully read"
        + ("" if exchange_prov is None else f" · exchange file `{exchange_prov.sha256[:16]}…`")
        + "\n\n"
        + proposal.render()
        + "\n\n---\n\n"
        + basket_markdown(report, as_of=as_of)
        + "\n\n## Detail\n\n```\n"
        + "\n\n".join(a.render() for a in report.values())
        + "\n```\n",
        encoding="utf-8",
    )
    print(f"[evidence] report → {REPORT}  ({complete}/{len(tickers)} fully covered)")
    for ticker, a in report.items():
        if a.blocked or a.flagged_events:
            print(f"[evidence] {ticker}: {a.state}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["daily"])
    ap.add_argument("--as-of", default=None, help="override the date (default: today, UTC)")
    args = ap.parse_args(argv)
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC).date()
    return cmd_daily(Config(), as_of)


if __name__ == "__main__":
    raise SystemExit(main())
