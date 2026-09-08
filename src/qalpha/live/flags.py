"""What the exchange and the filings say about names you are about to buy. **Flags, never vetoes.**

The iron rule on the buy list is *flag, don't veto* — selection stays deterministic and the decision
stays the user's. This module renders what the evidence layer found next to the basket, so a warning
is in front of him at the moment it matters instead of sitting in a report nobody opens.

It **cannot change the basket**. It takes an already-decided list of tickers and returns markdown.
There is no path from here back into selection or sizing, and that is deliberate: the moment a
warning can silently remove a name, the screen is no longer the thing being measured.

**It reads only what is on disk.** No network, no model call, no clock. The daily job archives the
exchange file and the filings; this reads that archive. If the archive is stale or missing it says
so rather than implying a clean bill — an absent warning and no warning are different facts, and
only one of them is reassuring.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from pathlib import Path

from qalpha.live.evidence import BLOCK, PASS, UNKNOWN, WATCH, Provenance, load_archive
from qalpha.live.evidence import assess as exchange_assess
from qalpha.live.extraction import EXTRACTION_VERSION

EVENT_LOG = Path("data/evidence/events.jsonl")
COVERAGE_LOG = Path("data/evidence/coverage.jsonl")

#: A coverage row older than this cannot speak for today's basket.
MAX_COVERAGE_AGE_DAYS = 4

#: How far back to look for an archived exchange file before giving up. The exchange publishes on
#: trading days, so a Monday reads Friday's; beyond this the file is too old to speak for today and
#: the panel says so instead of quietly using it.
MAX_FILE_AGE_DAYS = 4

#: Events at or above this concern level are shown. Defined in the EX-2 prompt as *how much this
#: should worry someone who already owns the shares* — not how newsworthy it is. EX-1 rated routine
#: results `high` and is ignored here by version.
SHOWN_CONCERN = {"high"}


def filings_read(tickers: Iterable[str], *, as_of: date, path: Path = COVERAGE_LOG) -> set[str]:
    """Names whose filings were **actually read**, at the current extractor, recently enough.

    ### Why this exists, and why its absence was the worst defect in this file

    The panel used to call a name "clear" whenever the exchange passed and no current-version event
    mentioned it. With zero EX-2 events on file — which is the state after every version bump — that
    made **every** name clear, including names whose filings had never been opened. The module
    docstring in this very file says an absent warning and no warning are different facts and only
    one of them is reassuring. The code said otherwise.

    A name counts as read only when the day's coverage row says ``complete``, was produced by the
    current extraction version, and is no older than :data:`MAX_COVERAGE_AGE_DAYS`.
    """
    if not path.exists():
        return set()
    wanted = {t.removesuffix(".NS") for t in tickers}
    cutoff = (as_of - timedelta(days=MAX_COVERAGE_AGE_DAYS)).isoformat()
    read: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not row.get("complete"):
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION:
            continue
        if str(row.get("as_of", "")) < cutoff:
            continue
        ticker = str(row.get("ticker", "")).removesuffix(".NS")
        if ticker in wanted:
            read.add(ticker)
    return read


def _latest_exchange_file(
    as_of: date,
) -> tuple[dict[str, dict[str, str]], Provenance | None, int]:
    """The most recent archived regulatory-indicator file, and how many days old it is."""
    for back in range(MAX_FILE_AGE_DAYS + 1):
        rows, prov = load_archive(as_of - timedelta(days=back))
        if prov is not None:
            return rows, prov, back
    return {}, None, -1


def recent_concerns(
    tickers: Iterable[str], *, since: date, path: Path = EVENT_LOG
) -> dict[str, list[dict[str, str]]]:
    """High-concern verified events per ticker, newest first, from the current extractor only.

    Three filters, each of which has already been a defect somewhere in this repo: the quote must
    have been **verified** against the stored document, the row must come from the **current**
    extraction version, and the event must be recent enough to still matter.
    """
    if not path.exists():
        return {}
    wanted = {t.removesuffix(".NS") for t in tickers}
    out: dict[str, list[dict[str, str]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") != "event" or not row.get("verified"):
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION:
            continue
        if str(row.get("materiality", "")).lower() not in SHOWN_CONCERN:
            continue
        ticker = str(row.get("ticker", "")).removesuffix(".NS")
        if ticker not in wanted:
            continue
        if str(row.get("as_of", "")) < since.isoformat():
            continue
        out.setdefault(ticker, []).append(
            {
                "type": str(row.get("event_type", "")),
                "summary": str(row.get("summary", "")),
                "passage": str(row.get("passage", "")),
                "url": str(row.get("doc_url", "")),
                "on": str(row.get("as_of", "")),
            }
        )
    for events in out.values():
        events.sort(key=lambda e: e["on"], reverse=True)
    return out


def flags_markdown(tickers: Sequence[str], *, as_of: date, lookback_days: int = 30) -> str:
    """The panel. Renders under a basket and changes nothing about it."""
    if not tickers:
        return ""
    rows, prov, age = _latest_exchange_file(as_of)
    concerns = recent_concerns(tickers, since=as_of - timedelta(days=lookback_days))

    lines: list[str] = ["#### ⚠️ What the exchange and the filings say", ""]
    if prov is None:
        lines.append(
            f"**No archived exchange file within {MAX_FILE_AGE_DAYS} days.** These names have "
            "**not** been checked against NSE's own indicators. That is not a clean bill — it is a "
            "gap. The daily job archives the file; if this persists, it is not running."
        )
        return "\n".join(lines)

    read = filings_read(tickers, as_of=as_of)
    flagged: list[str] = []
    clean: list[str] = []
    unread: list[str] = []
    for ticker in tickers:
        verdict = exchange_assess(ticker, rows, prov, as_of=as_of)
        bare = ticker.removesuffix(".NS")
        events = concerns.get(bare, [])
        if verdict.state == PASS and not events:
            # Clear on the exchange and nothing found in the filings — but "nothing found" only
            # means something if the filings were read. Otherwise this is a gap wearing a tick.
            (clean if bare in read else unread).append(ticker)
            continue
        bits: list[str] = []
        if verdict.state == BLOCK:
            bits.append(f"🔴 **exchange: {verdict.detail}**")
        elif verdict.state == WATCH:
            bits.append(f"🟡 exchange: {verdict.detail}")
        elif verdict.state == UNKNOWN:
            bits.append(f"⚪ exchange: {verdict.detail}")
        for event in events[:2]:
            source = f" · [filing]({event['url']})" if event["url"] else ""
            bits.append(f"🟡 {event['type'].replace('_', ' ')}: {event['summary']}{source}")
        flagged.append(f"- **{ticker.removesuffix('.NS')}** — " + "; ".join(bits))

    if flagged:
        lines += flagged
    else:
        lines.append("Nothing flagged on any name in this basket.")
    if unread:
        lines += [
            "",
            "⚪ **Filings NOT read for: "
            + ", ".join(t.removesuffix(".NS") for t in unread)
            + ".** The exchange lists nothing against them, and nobody has opened their filings. "
            "That is a gap, not a clean bill.",
        ]
    if clean:
        lines += [
            "",
            f"_Clear (exchange **and** filings read): "
            f"{', '.join(t.removesuffix('.NS') for t in clean)}._",
        ]
    stamp = "today's" if age == 0 else f"{age}-day-old"
    lines += [
        "",
        f"_Exchange indicators from the {stamp} NSE file "
        f"(`{prov.sha256[:12]}…`); filings from the last {lookback_days} days._",
        "_**These are flags, not vetoes.** Nothing here removed a name from the basket above — "
        "the screen chose it and the decision is yours._",
    ]
    return "\n".join(lines)
