"""The twin — seed the books, step them daily, record the gaps. The cron entry point.

    uv run python scripts/twin.py seed     # ONE TIME: the reset event. Refuses to overwrite.
    uv run python scripts/twin.py daily    # the cron: step → mark → write
    uv run python scripts/twin.py status   # print the comparison without writing

**Fake money only.** The twin books decide for themselves; the real Zerodha account is the *state
source*, never a target. Nothing here can place an order — no broker client is imported.

**The tradebook is the only source of cash flows** (PLAN_REDESIGN §4c). There is no schedule: the
user invests what he chooses, uploads the export, and those trades become the dated flows every book
receives. A calendar injection the real account never got is the flaw that voided a predecessor run.

**Fail-soft, always exit 0** where the cron is concerned — a missed mark is recoverable, a red cron
that stops the whole pipeline is not. ``seed`` is the exception: it refuses rather than guess.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from paper import _load_benchmark_series, _load_market

from qalpha.config import Config
from qalpha.live import atomic
from qalpha.live.ai_brief import NameVerdict
from qalpha.live.console import use_utf8
from qalpha.live.extraction import EXTRACTION_VERSION
from qalpha.live.policy import ALL_POLICIES, Decision, decisions_markdown
from qalpha.live.runner import Market, step
from qalpha.live.tradebook import TradebookTrade
from qalpha.live.twin import (
    AI_VERDICT_HISTORY,
    DECIDING,
    EVALUATION_START,
    REAL,
    SYSTEM,
    TWIN_HISTORY,
    BookMark,
    Gap,
    TwinBook,
    append_ai_attempt,
    append_ai_verdicts,
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
from qalpha.live.verdicts import AI_PROMPT_VERSION, event_verdicts, verdict_calls

REPORT = Path("reports/twin_dashboard.md")
DECISIONS_LOG = Path("reports/twin_decisions.md")
MARKS = Path("data/twin/marks.json")
WATCHLIST_PANEL = Path("data/historical/prices_watchlist.parquet")
WATCHLIST_CSV = Path("data/universes/nifty100_watchlist.csv")
#: The point-in-time Nifty-50 panel BASELINE_EW is priced from. Not the watchlist: the purchasable
#: alternative being modelled is a Nifty-50 **equal-weight index fund**, so the benchmark has to be
#: the index that fund tracks, on point-in-time membership.
EW_PANEL = Path("data/historical/prices_pit_2026.parquet")
EW_CSV = Path("data/universes/nifty50_membership_2026.csv")

#: Imported, not re-declared: `qalpha.live.verdicts` owns the treatment identifier now, because the
#: page's capability register reads it and `src/` cannot import from `scripts/`. Its history — PR-8b,
#: PR-8c, AI-V2 — is recorded there.


def _tradebook() -> tuple[list[TradebookTrade], list[str]]:
    """The user's real trades — the ONLY source of cash flows for every book (§4c).

    **The same folder the page reads**, :data:`qalpha.live.tradebook.EXPORT_DIR`. It used to be a
    private gist plus ``data/tradebook-YHK037-EQ.csv``, a file that does not exist here — so the
    instruction the user is actually given ("drop the Console export in ``data/tradebooks/``") dated
    the page's lots and could never stop the twin aborting. The gist stays as an override for
    whoever has one; without ``GIST_TOKEN`` it is not consulted and is not an error.

    Returns ``(trades, notes)``. The notes are named absences, and the caller refuses on them.
    """
    import os

    from qalpha.live.tradebook import EXPORT_DIR, read_exports

    token = os.environ.get("GIST_TOKEN", "").strip() or os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        from qalpha.live.gist_store import find_gist_id, load_gist_file
        from qalpha.live.tradebook_store import trades_from_master_csv

        filename = "tradebook_master.csv"
        try:
            gist_id = os.environ.get("TRADEBOOK_GIST_ID", "").strip() or find_gist_id(
                token, filename
            )
            text = load_gist_file(token, gist_id, filename) if gist_id else None
            if text:
                return list(trades_from_master_csv(text)), []
            print("[twin] gist reachable but holds no master yet — reading the local folder")
        except Exception as exc:
            print(f"[twin] gist unavailable ({exc}) — reading the local folder")
    trades, notes = read_exports(EXPORT_DIR)
    for note in notes:
        print(f"[twin] {note}")
    return list(trades), notes


def _market(as_of: date) -> Market | None:
    """Gather the day's world. Returns ``None`` when the panel is missing — never a silent default."""
    prices, _universe, _sector = _load_market()
    bench = _load_benchmark_series()
    wl_prices = None
    watchlist: list[str] | None = None
    sector_of: dict[str, str] | None = None
    if WATCHLIST_PANEL.exists() and WATCHLIST_CSV.exists():
        from qalpha.data.ingest import load_parquet
        from qalpha.live.price_integrity import (
            excluded_from_tilt,
            rebase_starts,
            unexplained_gaps,
        )

        wl_prices = load_parquet(str(WATCHLIST_PANEL))
        wl = pd.read_csv(WATCHLIST_CSV)
        sector_of = dict(zip(wl["ticker"], wl["sector"], strict=False))
        watchlist = [t for t in wl["ticker"] if t in wl_prices.adj_close.columns]
        gaps = unexplained_gaps(wl_prices.adj_close, watchlist, as_of)
        rebase, exclude = rebase_starts(gaps), excluded_from_tilt(gaps)
    else:
        rebase, exclude = {}, set()
    adj = wl_prices.adj_close if wl_prices is not None else prices.adj_close
    marks = {
        t: Decimal(str(float(adj[t].loc[: pd.Timestamp(as_of)].dropna().iloc[-1])))
        for t in adj.columns
        if not adj[t].loc[: pd.Timestamp(as_of)].dropna().empty
    }
    return Market(
        as_of=as_of,
        prices=marks,
        index_close=bench,
        adj_close=adj,
        rebase_from=rebase,
        exclude=exclude,
        watchlist=watchlist,
        sector_of=sector_of,
        wl_prices=wl_prices,
    )


def _log_attempt(market: Market | None, status: str, detail: str = "", raw: str = "") -> None:
    """Record one AI attempt, fail-soft. A missing audit row must not stop the cron."""
    if market is None:
        return
    try:
        append_ai_attempt(
            as_of=market.as_of,
            status=status,
            detail=detail,
            raw=raw,
            model=_VERDICT_SOURCE,
            prompt_version=AI_PROMPT_VERSION,
        )
    except Exception as exc:
        print(f"[twin] WARNING: AI attempt not recorded ({exc})", file=sys.stderr)


def _ew_fund_series() -> pd.Series | None:
    """The point-in-time equal-weight Nifty-50 level that ``BASELINE_EW`` buys units of.

    **The defect this fixes.** Until 2026-08-30 the caller passed ``market.index_close`` — the
    NIFTYBEES series — to *both* ``baseline_mark`` and ``ew_fund_mark``. ``BASELINE_EW`` was
    therefore **cap-weighted NIFTYBEES minus a 0.41% fee**: not the equal-weight fund it is named
    after, and strictly *easier* to beat than ``BASELINE`` sitting next to it. Since ``SYSTEM vs
    BASELINE_EW`` is the **only** comparison that opens the GO gate, the gate was measuring the wrong
    thing in the wrong direction — the entire reason for gating against the fund rather than the
    index (Phase 4: 76% of the screen's gap over NIFTYBEES *is* the equal-weight premium) was
    defeated by one argument.

    :func:`equal_weight_pit` rebalances monthly across exactly the names that were index members on
    that date and priceable then, so it neither front-runs future entrants nor holds dead names.
    The absolute base is arbitrary — ``benchmark_leg`` buys units at each flow date, so only the
    series' *shape* matters.

    Returns ``None`` when the panel is missing, which propagates to no ``BASELINE_EW`` mark and a
    criterion 3 of ⚪ CANNOT ASSESS. That is the point: a missing benchmark must stop the gate, never
    quietly borrow the one next to it.
    """
    if not (EW_PANEL.exists() and EW_CSV.exists()):
        print(f"[twin] no equal-weight panel ({EW_PANEL}) — BASELINE_EW cannot be marked")
        return None
    from qalpha.backtest.baselines import equal_weight_pit
    from qalpha.data.ingest import load_parquet
    from qalpha.data.universe import Universe

    panel = load_parquet(str(EW_PANEL))
    universe = Universe.from_csv(str(EW_CSV))
    index = pd.DatetimeIndex(panel.dates)
    return equal_weight_pit(panel, universe, index, Decimal("100"))


#: What produced the verdicts, recorded on every row. It names a RULE, not a chat model, because
#: under AI-V2 nothing is asked — the reading happened earlier, in the evidence layers, and this is
#: policy over what they wrote down.
#: Spelled from the constant so a version bump cannot leave a user-visible label naming the
#: version before it. This line read "EX-2" by hand until 2026-09-11.
_VERDICT_SOURCE = f"rule:AI-V2 over verified {EXTRACTION_VERSION} filings (news demoted to leads)"


def _ai_verdicts(books: dict[str, TwinBook], market: Market, cfg: Config) -> dict[str, NameVerdict]:
    """Decide keep/drop for the basket ``SYSTEM`` is about to buy — the run's single AI treatment.

    Asked about **SYSTEM's** candidates specifically, because that is the only book whose policy
    consults them. The verdict for a ticker is a view on the company, not on a book, so one map
    serves every book; ``runner._deploy`` keeps any name the map does not mention.

    **Under AI-V2 no model is called here.** The filings and headlines were read earlier in the
    evening, each claim carrying a quote checked against archived bytes; this applies the registered
    rule to those rows. It needs no key, costs nothing, and a drop can be re-opened a year from now.
    Fail-soft throughout: any error returns ``{}``, which downstream means keep the whole basket, so
    SYSTEM degrades to exactly TWIN_NO_AI rather than to an empty book.
    """
    from qalpha.data.prices import PriceData
    from qalpha.live.deploy import advise_deploy_into_weakness

    book = books.get(SYSTEM)
    if book is None:
        return {}
    # The cash floor is checked FIRST and on its own: it is the cost control, and on most days it is
    # the reason no model call happens at all. Nothing above it may depend on market data.
    cash = book.portfolio.cash
    if cash < cfg.deploy_policy.idle_cash_floor:
        # Not an eligible day: no basket to ask about. Recorded anyway, because "the model was never
        # asked" and "the model was asked and kept everything" must not both look like silence.
        _log_attempt(market, "not_asked_cash_below_floor", f"cash ₹{cash:,.0f} < floor")
        return {}
    if market is None or not market.watchlist or not isinstance(market.wl_prices, PriceData):
        _log_attempt(market, "not_asked_no_watchlist")
        return {}
    try:
        advice = advise_deploy_into_weakness(
            book.portfolio,
            cash,
            market.watchlist,
            market.sector_of or {},
            market.wl_prices,
            market.index_close,
            market.as_of,
            max_names=cfg.deploy_policy.max_names_default,
            spend_idle_cash=False,
        )
        basket = {o.ticker: int(o.quantity) for o in advice.deploy.buy_orders}
        verdicts = event_verdicts(basket, as_of=market.as_of)
        # The audit row's `raw` is the evidence that fired, not a model's prose. No token count is
        # recorded at all: this treatment spends none, and a zero would read as a call that returned
        # nothing rather than as a call that never happened.
        raw = "\n".join(
            f"{v.ticker}: {'DROP' if not v.keep else 'lead'} — {v.reason} [{v.source}]"
            for v in sorted(verdicts.values(), key=lambda v: v.ticker)
        )
    except Exception as exc:
        print(f"[twin] AI verdicts unavailable ({exc}) — SYSTEM keeps the whole basket")
        _log_attempt(market, "error", str(exc))
        return {}
    if not verdicts:
        # Nothing on file objects to any candidate. Recorded, because "the rule found nothing" and
        # "the rule was never applied" must not both look like silence — the distinction PR-8's
        # attempt log exists for, and it survives the treatment change unchanged.
        _log_attempt(market, "no_event_matched", f"{len(basket)} candidate(s) clean", raw=raw)
        return {}
    dropped = [t for t, v in verdicts.items() if not v.keep]
    demoted = [t for t, v in verdicts.items() if v.demoted]
    if demoted:
        print(
            f"[twin] {len(demoted)} lead(s) from headlines {demoted} — recorded, not acted on. "
            "Only a filing can drop a name."
        )
    print(
        f"[twin] {AI_PROMPT_VERSION}: {len(verdicts)} name(s) matched an event, "
        f"{len(dropped)} dropped {dropped}"
    )
    # Provenance first, and unconditionally: a verdict that is acted on but not recorded cannot be
    # scored afterwards, and scoring it afterwards is the entire point of the experiment.
    try:
        # The undeployed cash is logged because dropped names are NOT replaced and survivors are
        # NOT rescaled (the no-resize guard is a real safety property and stays). That means
        # SYSTEM − TWIN_NO_AI measures "the veto PLUS the cash drag it causes", not selection
        # skill alone. Recording the cash is what lets the two be separated afterwards instead of
        # being confounded forever.
        # RUPEES, not share counts. Until 2026-09-05 this summed ``o`` — the *quantity* — so a
        # veto on 11 shares of a ₹3,000 name was recorded as "11". Every row written before that
        # date carries a share count in a field named cash, and the ``cash_unit`` tag below is what
        # lets a later reader tell the two apart without guessing from magnitude.
        held_back = sum(
            (
                Decimal(str(qty)) * market.prices[t]
                for t, qty in basket.items()
                if verdicts.get(t) and not verdicts[t].keep and t in market.prices
            ),
            Decimal("0"),
        )
        unpriced = [
            t
            for t, _ in basket.items()
            if verdicts.get(t) and not verdicts[t].keep and t not in market.prices
        ]
        append_ai_attempt(
            as_of=market.as_of,
            status="verdicts_recorded",
            detail=f"{len(verdicts)} parsed, {len(dropped)} dropped",
            raw=raw,
            model=_VERDICT_SOURCE,
            prompt_version=AI_PROMPT_VERSION,
            undeployed_cash=str(held_back),
            cash_unit="INR"
            if not unpriced
            else f"INR_INCOMPLETE_missing_price:{','.join(unpriced)}",
        )
        n = append_ai_verdicts(
            {
                t: {
                    "call": "keep" if v.keep else "drop",
                    "confidence": v.confidence,
                    "reason": v.reason,
                    "source": v.source,
                    "source_tier": v.source_tier,
                    "demoted": v.demoted,
                }
                for t, v in verdicts.items()
            },
            market.prices,
            as_of=market.as_of,
            model=_VERDICT_SOURCE,
            prompt_version=AI_PROMPT_VERSION,
        )
        print(f"✓ ai verdicts: {n} row(s) on file → {AI_VERDICT_HISTORY}")
    except Exception as exc:
        # Provenance failing is not a reason to act anyway. A DROP that changes SYSTEM without a
        # row recording *why* is an unauditable treatment: in twelve months nobody could tell a
        # legitimate governance veto from a hallucination, which is the whole question. Returning {}
        # keeps every name, degrading SYSTEM to exactly TWIN_NO_AI — a lost treatment, not a
        # corrupted one.
        print(
            f"[twin] verdicts NOT recorded ({exc}) — keeping every name rather than acting "
            "on an unrecorded decision",
            file=sys.stderr,
        )
        return {}
    return verdicts


def cmd_seed(cfg: Config) -> int:
    """The reset event: create the five books from the tradebook. Refuses to overwrite."""
    from qalpha.live.twin import TWIN_STATE

    if TWIN_STATE.exists():
        print(
            f"[twin] {TWIN_STATE} already exists — refusing to re-seed.\n"
            "       Re-seeding resets the clock, which is a decision with a date, not a rerun. "
            "Archive the existing books first if that is genuinely intended.",
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
        # IPO allotments and other off-market credits never appear in a tradebook. Fund every book
        # with them so REAL does not hold shares the twins were never given money for.
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
    books: dict[str, TwinBook], market: Market, cfg: Config, *, persist: bool = True
) -> tuple[dict[str, BookMark], list[Gap]]:
    """Mark every book and add both baselines.

    **The GO gate was removed on 2026-09-12.** It asked whether the system beats the fund by
    more than chance, and that question cannot be answered on this data: the edge is 0.42%/yr
    against 5.3%/yr of drift, so detecting it at 95% needs roughly two hundred years. Six
    criteria and a matched null were machinery around a measurement that was never going to
    arrive. The gaps are still recorded — they are a description of what happened, which is
    honest — and nothing here authorises anything, which was already true.

    ``persist=False`` makes this **genuinely read-only**. ``twin.py status`` is documented as a
    read-only view and called this with the default, so merely *looking* at the twin appended a
    history row — a reporting command mutating the append-only evidence record.
    """
    from qalpha.live.tradebook import replay_tradebook

    marks = {n: mark(b, market.prices, market.as_of) for n, b in books.items() if n != REAL}
    real = replay_tradebook(_tradebook()[0], cfg).portfolio
    # The allotment is not a trade, so the replay cannot know about it — give REAL the lots, with
    # the allotment date, because that is what §2(42A) counts the holding period from.
    apply_off_market(real, load_off_market())
    books[REAL].portfolio = real
    marks[REAL] = mark(books[REAL], market.prices, market.as_of)

    flows = books[REAL].flows
    # BASELINE is NIFTYBEES; BASELINE_EW is the equal-weight fund. Two different series — passing
    # the same one to both is the bug this reads as a fix for.
    ew_series = _ew_fund_series()
    for m in (
        baseline_mark(flows, market.index_close, market.as_of),
        None if ew_series is None else ew_fund_mark(flows, ew_series, market.as_of),
    ):
        if m is not None:
            marks[m.name] = m
    # Two-pass, and deliberately so. The gating statistic is a ratio of *unitized NAVs*, which needs
    # the value path — so today's values are recorded first, the NAVs are read back out of the
    # append-only record, and only then can the gap be computed. `append_history` replaces a row with
    # the same date, so the second write below completes today's row rather than duplicating it.
    if persist:
        try:
            append_history(marks, [], as_of=market.as_of)
        except Exception as exc:
            print(f"[twin] WARNING: values not recorded ({exc})", file=sys.stderr)
    # One NAV basis per track. A NAV unitized from run 2's start says nothing about a window that
    # opens a week later, so the two are computed separately and namespaced — `compare` reads the
    # track-prefixed key and never silently borrows the other track's.
    rows = load_history()
    navs = {f"run2:{k}": v for k, v in navs_from_history(rows).items()}
    navs.update(
        {f"core_v1:{k}": v for k, v in navs_from_history(rows, start=EVALUATION_START).items()}
    )
    gaps = compare(marks, navs=navs)
    # **RUN 2 NO LONGER AUTHORISES.** Its treatment changed inside its own window — two AI rules
    # under one version label — so it was reclassified an operational rehearsal. An experiment
    # declared methodologically invalid must never later produce a GO, so it keeps its statistic
    # (recorded under `tracks`) and loses its authority. The GO gate reads the authorising track
    # only, which is CORE_V1. Until that book exists the gate has no gap and says CANNOT ASSESS,
    # which is the honest answer rather than a borrowed one.
    # The two tracks still report their own statistic, because a gap is a description of what
    # happened and descriptions are worth keeping. What has gone is the pretence that either one
    # could authorise anything.
    for gap in gaps:
        if gap.track:
            value = "n/a" if gap.log_rel_wealth is None else f"{gap.log_rel_wealth:+.5f}"
            print(f"[twin] {gap.track}: {gap.left} vs {gap.right} — G = {value}")
    return marks, gaps


#: Exit code for "refused to write, nothing changed". Distinct from 1 so a caller can tell a
#: deliberate abort from a crash, and distinct from 0 so neither reads as a completed step.
ABORTED = 2


def cmd_daily(cfg: Config) -> int:
    """Step every autonomous book, mark them all, write the report."""
    books = load_books(cfg)
    if not books:
        print("[twin] not seeded — run `twin.py seed` first. Nothing marked.", file=sys.stderr)
        return 0
    as_of = date.today()
    market = _market(as_of)
    if market is None:
        print("[twin] no market data — nothing marked (this is a data problem, not a quiet day).")
        return 0

    # New money first: the user's flows are the twin's only funding, and a purchase that reached
    # REAL but not the twins would break the identical-flow invariant on his very next SIP.
    trades, tradebook_notes = _tradebook()
    credits = load_off_market()
    for d in sync_flows(books, trades, credits):
        print(f"[twin] credited ₹{d.amount:,.2f} on {d.on} to all {len(books)} books")

    # A tradebook that reads empty while the books hold flows is a FAILED READ, not an empty
    # account. Left unchecked, REAL replays to ₹0 against ₹3,04,144 of flows — a −100% line, with
    # every twin appearing to beat it by three lakh, written to the dashboard as a verdict. Refuse
    # to write anything: yesterday's report is far better than today's wrong one.
    refusal: str | None = None
    if not trades and books[REAL].flows:
        refusal = (
            f"the tradebook read EMPTY but the books hold {len(books[REAL].flows)} flows "
            f"(₹{books[REAL].net_invested:,.2f}). That is a failed read, not an empty account."
        )
        if tradebook_notes:
            refusal += " " + " ".join(tradebook_notes)
    else:
        # AN EXPORT THAT STARTS TOO LATE IS THE SAME DEFECT WITH ONE ROW IN IT, and the empty
        # check above cannot see it: REAL replays short and every book reads as beating it by
        # the lots the export left out. See `twin.partial_export_reason`.
        refusal = partial_export_reason(trades, books[REAL].start)
    if refusal:
        print(
            f"[twin] ABORT — {refusal}\n"
            "       Nothing was written; the previous report stands.\n"
            "       Check: is there a Zerodha Console export in data/tradebooks/ covering your "
            "first trade? Console → Reports → Tradebook → CSV. The twin reads the same folder "
            "the page does.",
            file=sys.stderr,
        )
        # NON-ZERO, because this is a refusal and the caller writes down what happened. Under the
        # cron `return 0` meant "do not go red"; under `live/daily.py` it means the ledger records
        # the twin as having STEPPED, and the page tells the user the evening completed while the
        # model book stood still. A deliberate refusal is still a thing that did not happen.
        return ABORTED

    # The AI treatment. Until 2026-08-30 this was never gathered, so `Market.ai_verdicts` was always
    # None, `policy.use_ai and market.ai_verdicts` was always False, and all four twins were
    # byte-identical by construction — SYSTEM − TWIN_NO_AI could only ever have read ₹0. The
    # verdicts are asked for HERE, outside `step`, because the runner must stay pure and replayable:
    # it consumes a decided map, it never calls anything.

    verdicts = _ai_verdicts(books, market, cfg)
    market = replace(market, ai_verdicts=verdict_calls(verdicts))

    # SAME-DAY IDEMPOTENCE. The cron saves books part-way through; if a later stage fails and the
    # job is retried, stepping again would re-execute today's paper decisions — buying the same
    # basket twice and showing one day's flows twice in an append-only record. A book already
    # stepped through `as_of` is skipped, so a retry completes the *rest* of the day's work.
    decisions: list[Decision] = []
    already = [n for n in DECIDING if n in books and books[n].stepped_through == market.as_of]
    if already:
        print(f"[twin] already stepped {market.as_of} for {', '.join(already)} — not re-deciding")
    from qalpha.live.tradebook import replay_tradebook

    autonomous = is_autonomous(market.as_of)
    if not autonomous:
        print(
            f"[twin] SYSTEM mirrors REAL until {EVALUATION_START} — it holds what you hold and "
            "makes no choices of its own. Registered before the window opened; see "
            "reports/PREREGISTRATION_SYSTEM.md."
        )
    for name in DECIDING:
        book = books.get(name)
        if book is None or book.stepped_through == market.as_of:
            continue
        if not autonomous:
            # Mirror: SYSTEM's holdings ARE the user's until the day it starts choosing, so the two
            # books open the experiment from one state and every later gap is a decision.
            books[name].portfolio = replay_tradebook(_tradebook()[0], cfg).portfolio
            apply_off_market(books[name].portfolio, load_off_market())
            book.stepped_through = market.as_of
            continue
        decisions += step(book, ALL_POLICIES[name], market, cfg)
        book.stepped_through = market.as_of
    save_books(books)

    marks, gaps = _marks_and_gaps(books, market, cfg)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_text(
        REPORT,
        f"# The twin — {as_of}\n\n_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. "
        "Fake money; the real account is the state source and is never traded._\n\n"
        + comparison_markdown(marks, gaps)
        + "\n",
    )
    # Persist the marks the report was built from, so the dashboard charts plot exactly these
    # numbers rather than recomputing and quietly disagreeing with the table above them.
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
    atomic.write_text(
        DECISIONS_LOG,
        f"# Twin decisions — {as_of}\n\n" + decisions_markdown(decisions) + "\n",
    )
    # The append-only record. Everything above this line is a snapshot that the next run destroys;
    # this is the only thing that accumulates. It is written LAST and fail-soft — a history write
    # that raised would stop the cron, and a stopped cron loses far more days than one bad row.
    try:
        rows = append_history(marks, gaps, as_of=as_of)
        print(f"✓ history: {rows} day(s) on file → {TWIN_HISTORY}")
    except Exception as exc:
        print(f"[twin] WARNING: history not appended ({exc})", file=sys.stderr)
    print(f"✓ {len(decisions)} decision(s) → {REPORT}")
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
    marks, gaps = _marks_and_gaps(books, market, cfg, persist=False)
    print(comparison_markdown(marks, gaps))
    return 0


def main(argv: list[str] | None = None) -> int:
    # UTF-8 FIRST, before anything prints. Windows falls back to cp1252 when stdout is a pipe,
    # and `uv run` pipes its child: on 2026-09-11 the `mark` step died on a rupee sign.
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["seed", "daily", "status"])
    args = ap.parse_args(argv)
    cfg = Config()
    if args.cmd == "seed":
        return cmd_seed(cfg)
    # THE SWALLOW IS GONE, AND SO IS THE THING IT WAS FOR. This caught every exception and
    # returned 0 so that a GitHub Actions run would not go red. There is no GitHub Actions run any
    # more — `live/daily.py` calls this, and it RECORDS what happened. Returning 0 after a failure
    # would have that ledger write "done" against a step that did nothing, and the resume logic
    # would then never run it again for these inputs. Silence used to cost a red tick; it now
    # costs the record.
    #
    # The caller still keeps the evening going: `run_pipeline` catches this, writes `failed` with
    # the message, and moves to the next step. That is fail-soft. This was fail-silent.
    return cmd_daily(cfg) if args.cmd == "daily" else cmd_status(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
