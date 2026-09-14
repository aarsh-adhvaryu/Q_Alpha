"""The books — seed them once, then each evening: credit flows, step SYSTEM, mark every book.

    uv run python scripts/twin.py seed     # ONE TIME. Refuses to overwrite existing books.
    uv run python scripts/twin.py daily    # credit new flows → step SYSTEM → mark → append history
    uv run python scripts/twin.py status   # print the comparison without writing anything
    uv run python scripts/twin.py refund   # re-fund every book from the imported ledger
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
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.universe import Universe
from qalpha.live import actions as actions_record
from qalpha.live import atomic, manager
from qalpha.live import calendar as nse
from qalpha.live import funding as funding_record
from qalpha.live.benchmarks import equal_weight_pit, unpriceable_members
from qalpha.live.console import use_utf8
from qalpha.live.decisions import Decision, decisions_markdown
from qalpha.live.flows import Flow
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
from qalpha.live.tradebook import (
    EXPORT_DIR,
    TradebookTrade,
    read_exports,
    replay_tradebook,
)
from qalpha.live.twin import (
    DECIDING,
    EVALUATION_START,
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
    credit_actions,
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


def _flows(trades: Sequence[TradebookTrade], credits: Sequence[object]) -> list[Flow] | None:
    """The dated money every book is funded with: the broker's ledger when it has been imported.

    ``None`` falls back to the tradebook — money that reached the market rather than money that
    reached the account — and says so, because the two are different figures and only one of them
    is what the user actually put in.
    """
    record = funding_record.load()
    if record is None:
        print(
            "[twin] no funding imported (data/twin/funding.json) — the books are funded from the "
            "tradebook, so idle cash sits outside the comparison. "
            "Run: uv run python scripts/reconcile_account.py --import"
        )
        return None
    flows = record.flows()
    print(
        f"[twin] funded from {record.source}: {len(flows)} movement(s), net ₹{record.net:,.2f} "
        f"(the broker's closing balance was ₹{record.closing_balance:,.2f})"
    )
    return flows


def _actions() -> list[CorporateAction]:
    """The corporate actions the replay may apply: reconciled ones only, or none with a reason.

    Unreconciled actions are named here rather than silently dropped — a dividend whose amount does
    not match the panel's own price adjustment is a thing to look at, not a rounding difference.
    """
    record = actions_record.load()
    if record is None:
        print(
            "[twin] no corporate actions imported (data/twin/corporate_actions.json) — dividends "
            "are NOT credited, while the baselines are marked on a total-return index that "
            "reinvests theirs. Run: uv run python scripts/corporate_actions.py --import"
        )
        return []
    if record.unreconciled:
        for r in record.unreconciled:
            print(f"[twin] NOT applied — {r.action.ticker} {r.action.ex_date}: {r.note}")
    return record.for_replay()


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
    """The evening's world, dated by **the session its prices come from**.

    ``as_of`` is the day being asked about; the market's own date is the last session on or before it
    that the panel actually holds. Run this on a Sunday and the world is Friday's, and says Friday —
    a market carrying Friday's closes under Sunday's date is a number wearing the wrong label, and
    everything downstream (the fill session, the history row, "is today's close final") reads it.
    """
    if not (WATCHLIST_PANEL.exists() and WATCHLIST_UNIVERSE.exists() and BENCHMARK_PANEL.exists()):
        print(f"[twin] missing {WATCHLIST_PANEL}, {WATCHLIST_UNIVERSE} or {BENCHMARK_PANEL}")
        return None
    wl_prices = load_parquet(str(WATCHLIST_PANEL))
    wl = pd.read_csv(WATCHLIST_UNIVERSE)
    watchlist = [t for t in wl["ticker"] if t in wl_prices.adj_close.columns]
    adj = wl_prices.adj_close
    sessions = [d.date() for d in pd.DatetimeIndex(adj.index) if d.date() <= as_of]
    if not sessions:
        print(f"[twin] the price panel holds no session on or before {as_of}")
        return None
    session = max(sessions)
    if session != as_of:
        print(f"[twin] {nse.describe(as_of, traded=False)}; the world is {session}'s close")
    gaps = unexplained_gaps(adj, watchlist, session)
    marks = {
        t: Decimal(str(float(adj[t].loc[: pd.Timestamp(session)].dropna().iloc[-1])))
        for t in adj.columns
        if not adj[t].loc[: pd.Timestamp(session)].dropna().empty
    }
    return Market(
        as_of=session,
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
    index = pd.DatetimeIndex(panel.dates)
    # A member the panel cannot price is left out of the equal weighting. That is the right number
    # and the wrong silence: the bar is then fifty names' worth of label over forty-nine names'
    # worth of arithmetic, so it is said out loud on every run.
    missing = unpriceable_members(panel, universe, index)
    if missing:
        named = ", ".join(f"{t.removesuffix('.NS')} ({n})" for t, n in list(missing.items())[:8])
        print(
            f"[twin] BASELINE_EW excludes {len(missing)} index member(s) the panel cannot price, "
            f"on this many sessions each: {named}. TATAMOTORS is the live case — its NSE symbol "
            "retired at the 2025 demerger and the membership file still carries no end date for it."
        )
    return equal_weight_pit(panel, universe, index, Decimal("100"))


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
    books = seed_books(trades, cfg, flows=_flows(trades, credits))
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


def set_aside_history(path: Path) -> int:
    """Move every history row aside, returning how many. Empty file, kept bytes.

    Takes the path rather than reaching for the module-level one, because a caller that cannot
    redirect it is a caller that writes to the live record — which is exactly what happened: a
    test of the refusal path ran the success path against `data/twin/history.jsonl` and emptied
    it. Nothing was lost, because this moves rather than deletes, but a test must not be able to
    reach the real file at all.
    """
    if not path.exists():
        return 0
    body = path.read_text(encoding="utf-8")
    rows = len([ln for ln in body.splitlines() if ln.strip()])
    if not rows:
        return 0
    kept = path.with_name("history-before-refunding.jsonl")
    existing = kept.read_text(encoding="utf-8") if kept.exists() else ""
    atomic.write_text(kept, existing + body)
    atomic.write_text(path, "")
    return rows


def cmd_refund(cfg: Config, *, history: Path = TWIN_HISTORY) -> int:
    """Re-fund every book from the broker's ledger, once, before anything has decided.

    The books were funded from the tradebook — money that reached the *market*. The ledger records
    money that reached the *account*, which is what the user actually put in, and the difference was
    ₹2,01,542 of idle cash that no book was measuring. Switching the basis changes what every
    comparison means, so it is a deliberate command rather than something a daily run does, it
    **refuses once any book has made its own decision**, and it is recorded in the registration.
    """
    record = funding_record.load()
    if record is None:
        print(
            "[twin] no funding imported. Run: uv run python scripts/reconcile_account.py --import",
            file=sys.stderr,
        )
        return ABORTED
    books = load_books(cfg)
    if not books:
        print("[twin] not seeded.", file=sys.stderr)
        return ABORTED
    decided = [n for n, b in books.items() if b.manager.get("last_review")]
    if decided:
        print(
            f"[twin] {', '.join(decided)} has already decided for itself. Re-funding would change "
            "the basis of a record that is already running; it is refused.",
            file=sys.stderr,
        )
        return ABORTED

    trades, notes = _tradebook()
    if notes or not trades:
        print(f"[twin] tradebook unusable: {'; '.join(notes) or 'it is empty'}", file=sys.stderr)
        return ABORTED
    before = sum((f.amount for f in books[REAL].flows), Decimal("0"))
    flows = record.flows()
    for book in books.values():
        book.flows = list(flows)
        book.portfolio.cash = record.net  # the baselines hold cash until they are marked into units
    assert_identical_flows(list(books.values()))
    replay_real(books[REAL], trades, cfg)
    for name in DECIDING:
        if name in books:
            replay_real(books[name], trades, cfg)  # SYSTEM still mirrors REAL; it has not decided
    save_books(books)
    # Every row written before this moment measured a different amount of money. Splicing the two
    # bases into one series draws a cliff that never happened — here, 490k falling to 294k overnight.
    # The rows are moved aside rather than deleted: they are a real record of a real basis, and the
    # only thing that is wrong is putting them on the same axis as the new one.
    moved = set_aside_history(history)
    modelled = books[REAL].portfolio.cash
    print(
        f"✓ re-funded {len(books)} book(s) from {record.source}\n"
        f"  net money in: ₹{before:,.2f} (tradebook) → ₹{record.net:,.2f} (ledger)\n"
        f"  REAL cash:    ₹{modelled:,.2f} modelled · ₹{record.closing_balance:,.2f} at the broker "
        f"· difference ₹{modelled - record.closing_balance:,.2f}\n"
        "  The difference is charges the tradebook does not carry (DP, payment-gateway, bank) and "
        "modelling error in the cost engine. It is shown, not absorbed."
    )
    if moved:
        print(
            f"  {moved} history row(s) measured the old basis and were moved to "
            "data/twin/history-before-refunding.jsonl. They are kept, not deleted; they are simply "
            "not on the same axis as what follows."
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
    """Mark every book and both baselines. ``persist=False`` is genuinely read-only.

    ``REAL`` must already hold the replayed tradebook — see :func:`replay_real`. It used to be
    replayed *here*, after the books were saved, so ``books.json`` recorded the user's own book as
    the cash it was seeded with and no holdings at all. The marks were right and the file was wrong,
    which is the shape of every labelling defect in this repository.
    """
    marks = {n: mark(b, market.prices, market.as_of) for n, b in books.items()}

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


def replay_real(book: TwinBook, trades: list[TradebookTrade], cfg: Config) -> None:
    """Put the user's actual holdings into ``REAL`` — the tradebook replayed, plus what it cannot show.

    An allotment is not a trade, so the replay cannot know about it; it is added as a dated lot,
    because §2(42A) counts the holding period from the allotment date.

    **The cash is what the book was funded with, less what the trades spent.** The tradebook does not
    record a balance, so before funding was imported this was ₹0 — an account that plainly held two
    lakh showed none, and every book was compared on money that had reached the market rather than
    money the user had put in.

    Corporate actions are interleaved into the replay by date, so a dividend credits cash on its
    ex-date before that day's trades (buying on the ex-date does not earn it) and a split reshapes
    the lots the broker's own share count has to match. Because the replay recomputes the book from
    the trades every run, nothing here can be credited twice.
    """
    replay = replay_tradebook(trades, cfg, corporate_actions=_actions())
    book.portfolio = replay.portfolio
    apply_off_market(book.portfolio, load_off_market())
    funded = sum((f.amount for f in book.flows), Decimal("0"))
    book.portfolio.cash = funded - replay.net_spent


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
    for d in sync_flows(books, trades, credits, flows=_flows(trades, credits)):
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
        refusal = partial_export_reason(trades, books[REAL].earliest_trade)
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
            # Before it decides: a dividend is cash it may spend, and a split changes what it holds.
            for note in credit_actions(book, _actions(), through=market.as_of):
                print(f"[twin] {name}: {note}")
            failure = step_system(book, market, now=datetime.now(IST))
            continue
        if book.stepped_through == market.as_of:
            continue
        if book.manager.get("last_review"):
            # It has decided for itself before. The mirror is keyed to the session date, and on a
            # holiday that date is the previous session — which can sit before the start. Copying
            # REAL over a book that has made its own decisions would erase them.
            print(f"[twin] {name} has decided before; it is not re-mirrored to REAL.")
            continue
        # Mirror: until the investor starts, SYSTEM holds exactly what the user holds.
        replay_real(book, trades, cfg)
        book.stepped_through = market.as_of
    if not autonomous:
        # Said in terms of SESSIONS. "Mirrors REAL until 2026-09-14", printed on 2026-09-14, read as
        # a contradiction: the start is a calendar date, but the book steps on the session its prices
        # come from, and on a holiday that session is an earlier day.
        when = (
            f"— the latest session is {market.as_of} and the registered start is "
            f"{EVALUATION_START}"
            + (f" ({why})" if (why := nse.closure_reason(EVALUATION_START)) else "")
            + ". It first decides on the evening of the first session on or after the start"
            if EVALUATION_START
            else "— no start date is registered"
        )
        print(f"[twin] SYSTEM mirrors REAL {when}; it makes no choices of its own yet.")
    # BEFORE the save, so the file records what REAL actually holds rather than the cash it was
    # seeded with.
    replay_real(books[REAL], trades, cfg)
    # The export was accepted, so it defines how far back trading is known to go. It only ever
    # moves backwards: a longer export lowers the watermark, a shorter one was refused above.
    if trades:
        seen = min(t.trade_date for t in trades)
        for book in books.values():
            book.earliest_trade = min(book.earliest_trade or seen, seen)
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
    # **Dated by the session the marks came from, never by the calendar.** Stamping a holiday's run
    # with today's date wrote Friday's marks under Monday's, which is one observation duplicated, not
    # two observations — and the evaluation harness counts observations.
    rows = append_history(marks, gaps, as_of=market.as_of)
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
    today = now.astimezone(IST).date()
    if market.as_of != today:
        # A closed exchange is not a failed evening. A weekday with no closing prices and no known
        # closure IS one: something did not download, and calling that "a quiet day" is the
        # substitution this repository keeps finding.
        why = nse.closure_reason(today)
        if why is None:
            return (
                f"{nse.describe(today, traded=False)} — the latest close is {market.as_of}. "
                "Refresh prices; nothing was reviewed."
            )
        print(f"[investor] {nse.describe(today, traded=False)} — nothing to review.")
    for fill in manager.fill_pending(book, market, now=now, store=store):
        print(
            f"[investor] {fill['action']} {fill['filled']}/{fill['requested']} {fill['ticker']} "
            f"@ ₹{fill['price']} — {fill['status']}"
        )
    if market.as_of != today:
        return None  # the exchange was shut; the fills above are all this evening had to do
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
    pending = copy.manager.get("pending") or {}
    orders = pending.get("orders", [])
    print(
        f"[shadow] {len(decisions)} decision(s); "
        + (
            "would queue "
            + ", ".join(f"{o['action']} {o['quantity']} {o['ticker']}" for o in orders)
            if orders
            else "nothing to queue"
        )
    )
    print(f"[shadow] receipt, notes and scorecard in {store.root} — no book was changed.")
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
    replay_real(books[REAL], trades, cfg)
    marks, gaps = _marks_and_gaps(books, trades, market, cfg, persist=False)
    print(comparison_markdown(marks, gaps))
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8()  # first: Windows pipes fall back to cp1252 and die on a rupee sign
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["seed", "daily", "status", "shadow", "refund"])
    args = ap.parse_args(argv)
    cfg = Config()
    if args.cmd == "seed":
        return cmd_seed(cfg)
    if args.cmd == "shadow":
        return cmd_shadow(cfg)
    if args.cmd == "refund":
        return cmd_refund(cfg)
    return cmd_daily(cfg) if args.cmd == "daily" else cmd_status(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
