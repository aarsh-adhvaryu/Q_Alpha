"""The books — seed them once, then each evening: credit flows, step SYSTEM, mark every book.

    uv run python scripts/twin.py seed     # ONE TIME. Refuses to overwrite existing books.
    uv run python scripts/twin.py daily    # credit new flows → step SYSTEM → mark → append history
    uv run python scripts/twin.py status   # print the comparison without writing anything
    uv run python scripts/twin.py shadow   # one investor review on a COPY of SYSTEM; changes no book

**Paper books only.** No broker client is imported; nothing here can place an order.

**The tradebook is the only source of cash flows.** The user's Console exports in
``data/tradebooks/`` become the dated flows every book receives, so the books differ only in what
they did with the same rupees.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe
from qalpha.live import atomic, manager
from qalpha.live.benchmarks import equal_weight_pit
from qalpha.live.console import use_utf8
from qalpha.live.decisions import Decision, decisions_markdown
from qalpha.live.market import Market
from qalpha.live.panels import (
    BENCHMARK_PANEL,
    NIFTY50_PANEL,
    NIFTY50_UNIVERSE,
    WATCHLIST_PANEL,
    WATCHLIST_UNIVERSE,
)
from qalpha.live.price_integrity import (
    excluded_from_tilt,
    rebase_starts,
    repair_price_spikes,
    unexplained_gaps,
)
from qalpha.live.progress import IST
from qalpha.live.tradebook import EXPORT_DIR, TradebookTrade, read_exports, replay_tradebook
from qalpha.live.twin import (
    DECIDING,
    REAL,
    SYSTEM,
    TWIN_HISTORY,
    TWIN_STATE,
    BookMark,
    Gap,
    TwinBook,
    append_history,
    apply_off_market,
    assert_identical_flows,
    baseline_mark,
    compare,
    comparison_frame,
    comparison_markdown,
    ew_fund_mark,
    flows_with_off_market,
    is_autonomous,
    load_books,
    load_history,
    load_off_market,
    mark,
    navs_from_history,
    partial_export_reason,
    save_books,
    seed_books,
    sync_flows,
)

MARKS = TWIN_STATE.parent / "marks.json"

#: Exit code for "refused to write, nothing changed". Distinct from 1 (a crash) and from 0, so the
#: evening's ledger never records a refusal as a completed step.
ABORTED = 2


def _tradebook() -> tuple[list[TradebookTrade], list[str]]:
    """The user's real trades from ``data/tradebooks/``. Notes are named absences; callers refuse."""
    trades, notes = read_exports(EXPORT_DIR)
    for note in notes:
        print(f"[twin] {note}")
    return list(trades), notes


def _benchmark_series() -> pd.Series:
    """NIFTYBEES adjusted close, round-trip bad prints repaired (a real, persistent fall is kept)."""
    df = pd.read_parquet(BENCHMARK_PANEL)
    series = pd.Series(
        df["adj_close"].to_numpy(), index=pd.DatetimeIndex(df["date"]), name="nifty_tri"
    )
    clean, repaired = repair_price_spikes(series)
    if repaired:
        print(f"[twin] repaired {len(repaired)} corrupt benchmark print(s): {repaired}")
    return clean


def _market(as_of: date) -> Market | None:
    """The evening's world. ``None`` when a panel is missing — never a silent default."""
    if not (WATCHLIST_PANEL.exists() and WATCHLIST_UNIVERSE.exists() and BENCHMARK_PANEL.exists()):
        print(f"[twin] missing {WATCHLIST_PANEL}, {WATCHLIST_UNIVERSE} or {BENCHMARK_PANEL}")
        return None
    wl_prices = load_parquet(str(WATCHLIST_PANEL))
    wl = pd.read_csv(WATCHLIST_UNIVERSE)
    watchlist = [t for t in wl["ticker"] if t in wl_prices.adj_close.columns]
    gaps = unexplained_gaps(wl_prices.adj_close, watchlist, as_of)
    adj = wl_prices.adj_close
    marks = {
        t: Decimal(str(float(adj[t].loc[: pd.Timestamp(as_of)].dropna().iloc[-1])))
        for t in adj.columns
        if not adj[t].loc[: pd.Timestamp(as_of)].dropna().empty
    }
    return Market(
        as_of=as_of,
        prices=marks,
        index_close=_benchmark_series(),
        adj_close=adj,
        rebase_from=rebase_starts(gaps),
        exclude=excluded_from_tilt(gaps),
        watchlist=watchlist,
        sector_of=dict(zip(wl["ticker"], wl["sector"], strict=False)),
        wl_prices=wl_prices,
    )


def _ew_fund_series() -> pd.Series | None:
    """The point-in-time equal-weight Nifty-50 level ``BASELINE_EW`` buys units of.

    Not NIFTYBEES: passing the same series to both baselines once made ``BASELINE_EW`` cap-weighted
    NIFTYBEES minus a fee — easier to beat than the do-nothing book beside it. ``None`` when the
    panel is missing, so ``BASELINE_EW`` goes unmarked rather than borrowing the other series.
    """
    if not (NIFTY50_PANEL.exists() and NIFTY50_UNIVERSE.exists()):
        print(f"[twin] no equal-weight panel ({NIFTY50_PANEL}) — BASELINE_EW cannot be marked")
        return None
    panel = load_parquet(str(NIFTY50_PANEL))
    universe = Universe.from_csv(str(NIFTY50_UNIVERSE))
    return equal_weight_pit(panel, universe, pd.DatetimeIndex(panel.dates), Decimal("100"))


def cmd_seed(cfg: Config) -> int:
    """Create the four books from the tradebook. Refuses to overwrite."""
    if TWIN_STATE.exists():
        print(
            f"[twin] {TWIN_STATE} already exists — refusing to re-seed. Re-seeding restarts every "
            "book's record; archive the existing books first if that is genuinely intended.",
            file=sys.stderr,
        )
        return 1
    trades, _notes = _tradebook()
    if not trades:
        print("[twin] no tradebook — nothing to seed from.", file=sys.stderr)
        return 1
    credits = load_off_market()
    books = seed_books(trades, cfg)
    if credits:
        # Allotments never appear in a tradebook. Fund every book with them so REAL does not hold
        # shares the other books were never given money for.
        flows = flows_with_off_market(trades, credits)
        extra = sum((c.amount for c in credits), Decimal("0"))
        for book in books.values():
            book.flows = list(flows)
            book.portfolio.cash += extra
        assert_identical_flows(list(books.values()))
        print(f"  + {len(credits)} off-market credit(s), ₹{extra:,.2f}")
    save_books(books)
    flows = books[REAL].flows
    print(
        f"✓ seeded {len(books)} books from {len(trades)} trades · {len(flows)} flows · "
        f"₹{books[REAL].net_invested:,.2f} net invested · start {flows[0].on}"
    )
    return 0


def _marks_and_gaps(
    books: dict[str, TwinBook],
    trades: list[TradebookTrade],
    market: Market,
    cfg: Config,
    *,
    persist: bool = True,
) -> tuple[dict[str, BookMark], list[Gap]]:
    """Mark every book and both baselines. ``persist=False`` is genuinely read-only."""
    marks = {n: mark(b, market.prices, market.as_of) for n, b in books.items() if n != REAL}
    real = replay_tradebook(trades, cfg).portfolio
    # An allotment is not a trade: give REAL the lot with its allotment date, which is what
    # §2(42A) counts the holding period from.
    apply_off_market(real, load_off_market())
    books[REAL].portfolio = real
    marks[REAL] = mark(books[REAL], market.prices, market.as_of)

    flows = books[REAL].flows
    ew_series = _ew_fund_series()
    for m in (
        baseline_mark(flows, market.index_close, market.as_of),
        None if ew_series is None else ew_fund_mark(flows, ew_series, market.as_of),
    ):
        if m is not None:
            marks[m.name] = m
    # Two passes: relative wealth is a ratio of unitized NAVs, which needs the value path. Today's
    # values go on file first, NAVs are read back, then the gaps. `append_history` revises a row
    # with the same date rather than duplicating it.
    if persist:
        append_history(marks, [], as_of=market.as_of)
    gaps = compare(marks, navs=navs_from_history(load_history()))
    return marks, gaps


def cmd_daily(cfg: Config) -> int:
    """Credit new flows, step SYSTEM, mark every book, append the day to the history."""
    books = load_books(cfg)
    if not books:
        print("[twin] not seeded — run `twin.py seed` first. Nothing marked.", file=sys.stderr)
        return ABORTED
    as_of = date.today()
    market = _market(as_of)
    if market is None:
        print("[twin] no market data — nothing marked (a data problem, not a quiet day).")
        return ABORTED

    trades, tradebook_notes = _tradebook()
    credits = load_off_market()
    for d in sync_flows(books, trades, credits):
        print(f"[twin] credited ₹{d.amount:,.2f} on {d.on} to all {len(books)} books")

    # A tradebook that reads empty while the books hold flows is a FAILED READ, not an empty account:
    # REAL would replay to ₹0 and every other book would appear to beat it by the whole balance.
    refusal: str | None
    if not trades and books[REAL].flows:
        refusal = (
            f"the tradebook read EMPTY but the books hold {len(books[REAL].flows)} flows "
            f"(₹{books[REAL].net_invested:,.2f}). That is a failed read, not an empty account."
        )
        if tradebook_notes:
            refusal += " " + " ".join(tradebook_notes)
    else:
        refusal = partial_export_reason(trades, books[REAL].start)
    if refusal:
        print(
            f"[twin] ABORT — {refusal}\n"
            "       Nothing was written. Check that a Zerodha Console tradebook export covering "
            "your first trade is in data/tradebooks/.",
            file=sys.stderr,
        )
        return ABORTED

    autonomous = is_autonomous(market.as_of)
    failure: str | None = None
    for name in DECIDING:
        book = books.get(name)
        if book is None:
            continue
        if autonomous:
            failure = step_system(book, market, now=datetime.now(IST))
            continue
        if book.stepped_through == market.as_of:
            continue
        # Mirror: until a start is registered, SYSTEM holds exactly what the user holds.
        book.portfolio = replay_tradebook(trades, cfg).portfolio
        apply_off_market(book.portfolio, credits)
        book.stepped_through = market.as_of
    if not autonomous:
        print(
            "[twin] SYSTEM mirrors REAL — no start date is registered, so it makes no choices of "
            "its own."
        )
    save_books(books)

    marks, gaps = _marks_and_gaps(books, trades, market, cfg)
    atomic.write_text(
        MARKS,
        json.dumps(
            {
                "as_of": as_of.isoformat(),
                "books": comparison_frame(marks).to_dict(orient="records"),
            },
            indent=2,
        )
        + "\n",
    )
    rows = append_history(marks, gaps, as_of=as_of)
    print(f"✓ history: {rows} row(s) on file → {TWIN_HISTORY}")
    print(comparison_markdown(marks, gaps))
    if failure:
        # The books are marked and saved; the REVIEW did not happen, and the ledger must say so.
        print(f"[twin] the investor's review is INCOMPLETE: {failure}", file=sys.stderr)
        return ABORTED
    return 0


def step_system(
    book: TwinBook,
    market: Market,
    *,
    now: datetime,
    make_brain: Callable[[], manager.Brain] = manager.brain,
    store: manager.Store = manager.STORE,
) -> str | None:
    """One evening for the investor's book: fill what was queued, then review. The reason it failed, or None.

    Fills first, so a review sees the book its earlier orders produced. A fill that is still waiting
    for its session is not a failure; a review that cannot happen is.
    """
    for fill in manager.fill_pending(book, market, now=now, store=store):
        print(
            f"[investor] {fill['action']} {fill['filled']}/{fill['requested']} {fill['ticker']} "
            f"@ ₹{fill['price']} — {fill['status']}"
        )
    try:
        decisions = manager.review(book, market, now=now, make_brain=make_brain, store=store)
    except manager.IncompleteReviewError as exc:
        return str(exc)
    print(decisions_markdown(decisions) if decisions else "[investor] already reviewed today")
    return None


def cmd_shadow(cfg: Config) -> int:
    """One real review on a COPY of SYSTEM. Nothing is saved to the books; its records go to shadow/.

    This is how a version is checked before its start date is registered: a real model call, a
    real receipt, real limits — and no book that has to live with it.
    """
    books = load_books(cfg)
    book = books.get(SYSTEM)
    market = _market(date.today())
    if book is None or market is None:
        print("[shadow] no SYSTEM book or no market data", file=sys.stderr)
        return ABORTED
    copy = TwinBook(
        name=f"{SYSTEM}-shadow", portfolio=book.portfolio.clone(), flows=list(book.flows)
    )
    store = manager.Store(manager.STORE.root / "shadow")
    try:
        now = datetime.now(IST)
        decisions: list[Decision] = manager.review(
            copy, market, now=now, store=store, require_today=False, known_on=now.date()
        )
    except manager.IncompleteReviewError as exc:
        print(f"[shadow] INCOMPLETE: {exc}", file=sys.stderr)
        return ABORTED
    print(decisions_markdown(decisions))
    print(
        f"[shadow] receipt and notes in {store.root} · pending orders: {copy.manager.get('pending')}"
    )
    return 0


def cmd_status(cfg: Config) -> int:
    books = load_books(cfg)
    if not books:
        print("[twin] not seeded.")
        return 0
    market = _market(date.today())
    if market is None:
        print("[twin] no market data.")
        return 0
    trades, _notes = _tradebook()
    marks, gaps = _marks_and_gaps(books, trades, market, cfg, persist=False)
    print(comparison_markdown(marks, gaps))
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8()  # first: Windows pipes fall back to cp1252 and die on a rupee sign
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["seed", "daily", "status", "shadow"])
    args = ap.parse_args(argv)
    cfg = Config()
    if args.cmd == "seed":
        return cmd_seed(cfg)
    if args.cmd == "shadow":
        return cmd_shadow(cfg)
    return cmd_daily(cfg) if args.cmd == "daily" else cmd_status(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
