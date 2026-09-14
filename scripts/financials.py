"""Point-in-time company financials: fetch the filed XBRL, check it adds up, store it.

    uv run python scripts/financials.py                 # what is on file, and what reconciles
    uv run python scripts/financials.py --import        # fetch every held name and candidate
    uv run python scripts/financials.py --import --only TCS,INFY

**No model calls.** This is XBRL parsing, not reading: it costs nothing but bandwidth.

Each quarter is stored with the timestamp the exchange disseminated it, which is what makes the
packet point-in-time — the investor is shown a number only from the day the market had it. Each is
checked against the Ind-AS statement's own internal identities (income = revenue + other income,
profit before exceptional items = income - expenses, profit after tax = PBT - tax). A filing whose
own figures do not add up is stored, named, and **not fed to the investor**.

**It changes no book.** It writes ``data/facts/financials.jsonl`` and the XBRL it parsed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.config import Config
from qalpha.live import financials as facts
from qalpha.live.announcements import _urlopen_fetch
from qalpha.live.console import use_utf8
from qalpha.live.twin import REAL, load_books

#: How far back to fetch. Four quarters is what the packet shows; eight gives every one of those a
#: year-ago comparison of its own, which is what makes growth computable rather than guessed.
QUARTERS = 8


def _filed_at(row: dict[str, object]) -> datetime | None:
    """When it was published. Never the board-meeting date, which precedes it.

    ``broadCastDate`` first, because it is always populated. ``exchdisstime`` — the exchange's own
    dissemination, a few minutes later — is the more precise figure, but the API returns it as null
    on some calls and not others for the *same* filing, so reading it first made the stored
    timestamp flip between imports: the same quarter was "filed" at 16:58 on one run and 17:02 on
    the next. A point-in-time store that changes on re-import is not one. The packet's cut-off is
    by date, so a few minutes decides nothing except across midnight, and a filing is fetched in
    the same evening run as the review that reads it — it cannot be in the store before it exists.
    """
    for field in ("broadCastDate", "exchdisstime", "filingDate"):
        raw = str(row.get(field) or "").strip()
        for shape in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
            try:
                return datetime.strptime(raw, shape)
            except ValueError:
                continue
    return None


def _period_end(row: dict[str, object]) -> date | None:
    """``toDate`` as a real date.

    It arrives as "31-Dec-2024". Sorting those as strings puts March above December and quietly
    fetches a two-year-old quarter as "the latest" — which is exactly what it did.
    """
    try:
        return datetime.strptime(str(row.get("toDate") or "").strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def _names(cfg: Config) -> list[str]:
    """Held names plus whatever the screen would put in front of the investor."""
    books = load_books(cfg)
    held = (
        sorted(t for t, q in books[REAL].portfolio.positions().items() if q > 0)
        if REAL in books
        else []
    )
    extra: list[str] = []
    try:
        import pandas as pd

        from qalpha.live.panels import WATCHLIST_UNIVERSE

        if WATCHLIST_UNIVERSE.exists():
            extra = sorted(pd.read_csv(WATCHLIST_UNIVERSE)["ticker"].astype(str).tolist())
    except Exception as exc:  # a missing watchlist is fewer names, never a crash
        print(f"[facts] watchlist unavailable ({exc}); held names only", file=sys.stderr)
    return sorted({*held, *extra})


def _import(names: list[str]) -> list[facts.Quarter]:
    quarters: list[facts.Quarter] = []
    facts.XBRL_DIR.mkdir(parents=True, exist_ok=True)
    for ticker in names:
        symbol = ticker.removesuffix(".NS")
        status, body = _urlopen_fetch(facts.INDEX_URL.format(symbol=symbol))
        if status != 200 or not body:
            print(f"  {symbol:12s} index unavailable (HTTP {status}) — no filings recorded")
            continue
        try:
            rows = json.loads(body)
        except ValueError:
            print(f"  {symbol:12s} index was not readable JSON — no filings recorded")
            continue
        dated = [(p, r) for r in rows if r.get("xbrl") and (p := _period_end(r)) is not None]
        # Consolidated preferred, per period: a company files standalone and consolidated as separate
        # XBRL documents, and the standalone accounts of a holding company describe a shell rather
        # than the business. But EVERY filing of the preferred basis is kept, not one of them. A
        # company that files the same quarter twice minutes apart (or restates it months later) has
        # two dissemination times, and choosing between them here depended on the order the API
        # happened to return rows in — the store came out different on every import. Which filing
        # was known on a given day is `financials.known_on`'s question, and it already answers it.
        by_period: dict[date, list[dict[str, object]]] = {}
        for period, row in dated:
            by_period.setdefault(period, []).append(row)
        chosen: list[tuple[date, dict[str, object]]] = []
        for period in sorted(by_period, reverse=True)[:QUARTERS]:
            rows_here = by_period[period]
            consolidated = [
                r
                for r in rows_here
                if str(r.get("consolidated", "")).strip().lower().startswith("cons")
            ]
            for row in sorted(
                consolidated or rows_here, key=lambda r: (str(_filed_at(r)), str(r.get("xbrl")))
            ):
                chosen.append((period, row))
        kept = 0
        for _period, row in chosen:
            url = str(row["xbrl"])
            when = _filed_at(row)
            if when is None:
                print(f"  {symbol:12s} a filing has no dissemination time — skipped, not guessed")
                continue
            cached = facts.XBRL_DIR / symbol / Path(url).name
            if cached.exists():
                payload = cached.read_bytes()
            else:
                code, payload = _urlopen_fetch(url)
                if code != 200 or not payload:
                    print(f"  {symbol:12s} {url.rsplit('/', 1)[-1]}: HTTP {code}")
                    continue
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            quarter = facts.parse(
                payload.decode("utf-8", "replace"),
                ticker=ticker,
                filed_at=when,
                url=url,
                sha256=digest,
            )
            if quarter is None:
                print(f"  {symbol:12s} {url.rsplit('/', 1)[-1]}: no headline context — not parsed")
                continue
            quarters.append(quarter)
            kept += 1
        broken = sum(1 for q in quarters if q.ticker == ticker and not q.reconciled)
        print(
            f"  {symbol:12s} {kept} quarter(s)"
            + (f", {broken} did NOT reconcile" if broken else ", all reconcile")
        )
    return quarters


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--import", dest="do_import", action="store_true", help="fetch and store")
    ap.add_argument("--only", default="", help="comma-separated symbols instead of every name")
    args = ap.parse_args(argv)
    cfg = Config()

    if args.do_import:
        names = (
            [
                f"{s.strip().upper().removesuffix('.NS')}.NS"
                for s in args.only.split(",")
                if s.strip()
            ]
            if args.only
            else _names(cfg)
        )
        if not names:
            print("[facts] no names to ask about — seed the books first.", file=sys.stderr)
            return 2
        print(f"[facts] asking the exchange for {len(names)} name(s), {QUARTERS} quarters each")
        quarters = _import(names)
        # Keep what was already stored for names this run did not touch.
        existing = [q for q in facts.load() if q.ticker not in set(names)]
        total = facts.save(existing + quarters)
        print(f"[facts] {total} quarter(s) on file → {facts.FACTS_PATH}")

    stored = facts.load()
    if not stored:
        print("[facts] nothing stored. Run: uv run python scripts/financials.py --import")
        return 1

    by_name: dict[str, list[facts.Quarter]] = {}
    for q in stored:
        by_name.setdefault(q.ticker, []).append(q)
    unreconciled = 0
    print(f"\n[facts] {len(stored)} quarter(s) across {len(by_name)} name(s)")
    for ticker in sorted(by_name):
        rows = sorted(by_name[ticker], key=lambda q: q.period_end, reverse=True)
        good = [q for q in rows if q.reconciled]
        unreconciled += len(rows) - len(good)
        latest = good[0] if good else None
        name = ticker.removesuffix(".NS")
        if latest is None:
            print(f"  {name:12s} {len(rows)} filed, NONE reconcile — the investor is shown none")
        else:
            revenue = latest.get("revenue")
            pat = latest.get("profit_after_tax")
            print(
                f"  {name:12s} {len(good)}/{len(rows)} reconcile · latest {latest.period_end} "
                f"({latest.basis}, filed {latest.filed_at:%Y-%m-%d %H:%M}) · "
                f"revenue {'unknown' if revenue is None else f'{revenue:,.0f}'} · "
                f"PAT {'unknown' if pat is None else f'{pat:,.0f}'}"
            )
        for q in rows:
            for why in q.breaks:
                print(f"      {q.period_end} NOT fed — {why}")

    if unreconciled:
        print(f"\n[facts] {unreconciled} quarter(s) did not reconcile and are not fed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
