"""The twin — seed the books, step them daily, grade the gate. The cron entry point.

    uv run python scripts/twin.py seed     # ONE TIME: the reset event. Refuses to overwrite.
    uv run python scripts/twin.py daily    # the cron: step → mark → gate → write
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
import os
import sys
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from paper import _load_benchmark_series, _load_market

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.go_gate import Evidence, build_gate
from qalpha.live.policy import ALL_POLICIES, Decision, decisions_markdown
from qalpha.live.runner import Market, step
from qalpha.live.twin import (
    AI_VERDICT_HISTORY,
    CORE_EVALUATION_START,
    CORE_V1,
    DECIDING,
    NULL_P95_LOG_REL_WEALTH,
    REAL,
    TWIN_FULL,
    TWIN_HISTORY,
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
    load_books,
    load_history,
    load_off_market,
    mark,
    navs_from_history,
    save_books,
    seed_books,
    sync_flows,
)
from qalpha.live.verdicts import basket_verdicts, verdict_calls

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

#: Pre-registered with the treatment, and frozen for the run: a prompt change is a second
#: treatment, not an improvement. Recorded on every verdict row so a later reader knows which
#: prompt produced which call.
#: The AI treatment identifier. **Bump this whenever the prompt, the parser, the model or the
#: evidence rule changes** — the label is what a later reader uses to tell one treatment from
#: another, and a label that spans two rules makes the rows under it unusable.
#:
#: PR-8b (2026-08-30): a DROP required a ``source=`` URL to be *present*.
#: PR-8c (2026-09-05): a DROP acts only on a PRIMARY source (nseindia/bseindia/sebi/ibbi/mca);
#:   anything else is demoted to KEEP and recorded as a lead. That rule merged in PR #88 on
#:   2026-09-04 **without bumping this constant**, so the label would have covered both rules.
#:   No acting verdict was recorded between the merge and this bump, so PR-8b rows are all
#:   pre-demotion and the split is clean.
AI_PROMPT_VERSION = "PR-8c"


def _tradebook() -> list[object]:
    """The user's real trades — the ONLY source of cash flows for every book (§4c).

    The private gist holds the cumulative master, de-duplicated on Zerodha trade IDs, and needs a
    ``GIST_TOKEN``. A committed export is the fallback so the runner works locally and in a fresh
    checkout. Real trades are never written to this public repo — only read from the gist.
    """
    import os

    from qalpha.live.gist_store import find_gist_id, load_gist_file
    from qalpha.live.tradebook_store import trades_from_master_csv

    filename = "tradebook_master.csv"
    token = os.environ.get("GIST_TOKEN", "").strip() or os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        try:
            gist_id = os.environ.get("TRADEBOOK_GIST_ID", "").strip() or find_gist_id(
                token, filename
            )
            text = load_gist_file(token, gist_id, filename) if gist_id else None
            if text:
                return list(trades_from_master_csv(text))
            print("[twin] gist reachable but holds no master yet")
        except Exception as exc:
            print(f"[twin] gist unavailable ({exc}) — falling back to a local export")
    else:
        print("[twin] no GIST_TOKEN — falling back to a local export")
    local = Path("data/tradebook-YHK037-EQ.csv")
    if local.exists():
        from qalpha.live.tradebook import parse_tradebook

        return list(parse_tradebook(str(local)))
    return []


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
            model=os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-4-5",
            prompt_version=AI_PROMPT_VERSION,
        )
    except Exception as exc:
        print(f"[twin] WARNING: AI attempt not recorded ({exc})", file=sys.stderr)


def _ew_fund_series() -> pd.Series | None:
    """The point-in-time equal-weight Nifty-50 level that ``BASELINE_EW`` buys units of.

    **The defect this fixes.** Until 2026-08-30 the caller passed ``market.index_close`` — the
    NIFTYBEES series — to *both* ``baseline_mark`` and ``ew_fund_mark``. ``BASELINE_EW`` was
    therefore **cap-weighted NIFTYBEES minus a 0.41% fee**: not the equal-weight fund it is named
    after, and strictly *easier* to beat than ``BASELINE`` sitting next to it. Since ``TWIN_FULL vs
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


def _ai_verdicts(books: dict, market: Market, cfg: Config) -> dict:
    """Ask the AI about the basket ``TWIN_FULL`` is about to buy — the run's single AI treatment.

    Asked about **TWIN_FULL's** candidates specifically, because that is the only book whose policy
    consults them. The verdict for a ticker is a view on the company, not on a book, so one map
    serves every book; ``runner._deploy`` keeps any name the map does not mention.

    Costs nothing on a day with no deployable cash, which is most days — the screen only runs when
    idle cash clears ``idle_cash_floor``, so in practice the model is asked roughly when a SIP lands.
    Fail-soft throughout: any error returns ``{}``, which downstream means keep the whole basket, so
    TWIN_FULL degrades to exactly TWIN_NO_AI rather than to an empty book.
    """
    from qalpha.data.prices import PriceData
    from qalpha.live.deploy import advise_deploy_into_weakness

    book = books.get(TWIN_FULL)
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
        verdicts, raw, usage = basket_verdicts(
            basket, market.sector_of or {}, market.wl_prices, market.as_of
        )
    except Exception as exc:
        print(f"[twin] AI verdicts unavailable ({exc}) — TWIN_FULL keeps the whole basket")
        _log_attempt(market, "error", str(exc))
        return {}
    if not verdicts:
        # No key, a refusal, or nothing parseable. Every one of these keeps the basket — and every
        # one is now distinguishable from a day the model genuinely had no objection.
        _log_attempt(market, "no_verdicts_parsed", f"{len(basket)} candidate(s)", raw=raw)
        return {}
    dropped = [t for t, v in verdicts.items() if not v.keep]
    demoted = [t for t, v in verdicts.items() if v.demoted]
    if demoted:
        print(
            f"[twin] {len(demoted)} veto(es) DEMOTED for want of a primary source {demoted} — "
            "recorded as leads, not acted on"
        )
    print(
        f"[twin] AI verdicts: {len(verdicts)} name(s), {len(dropped)} dropped "
        f"{dropped} · tokens in/out {usage.get('input', 0)}/{usage.get('output', 0)}"
    )
    # Provenance first, and unconditionally: a verdict that is acted on but not recorded cannot be
    # scored afterwards, and scoring it afterwards is the entire point of the experiment.
    try:
        # The undeployed cash is logged because dropped names are NOT replaced and survivors are
        # NOT rescaled (the no-resize guard is a real safety property and stays). That means
        # TWIN_FULL − TWIN_NO_AI measures "the veto PLUS the cash drag it causes", not selection
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
            model=os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-4-5",
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
            model=os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-4-5",
            prompt_version=AI_PROMPT_VERSION,
        )
        print(f"✓ ai verdicts: {n} row(s) on file → {AI_VERDICT_HISTORY}")
    except Exception as exc:
        # Provenance failing is not a reason to act anyway. A DROP that changes TWIN_FULL without a
        # row recording *why* is an unauditable treatment: in twelve months nobody could tell a
        # legitimate governance veto from a hallucination, which is the whole question. Returning {}
        # keeps every name, degrading TWIN_FULL to exactly TWIN_NO_AI — a lost treatment, not a
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
    trades = _tradebook()
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


def _marks_and_gate(books: dict, market: Market, cfg: Config, *, persist: bool = True):
    """Mark every book, add both baselines, and grade the gate on what is actually known.

    ``persist=False`` makes this **genuinely read-only**. ``twin.py status`` is documented as a
    read-only view and called this with the default, so merely *looking* at the twin appended a
    history row — a reporting command mutating the append-only evidence record.
    """
    from qalpha.live.tradebook import replay_tradebook

    marks = {n: mark(b, market.prices, market.as_of) for n, b in books.items() if n != REAL}
    real = replay_tradebook(_tradebook(), cfg).portfolio
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
            append_history(marks, [], as_of=market.as_of, gate_verdict=None)
        except Exception as exc:
            print(f"[twin] WARNING: values not recorded ({exc})", file=sys.stderr)
    # One NAV basis per track. A NAV unitized from run 2's start says nothing about a window that
    # opens a week later, so the two are computed separately and namespaced — `compare` reads the
    # track-prefixed key and never silently borrows the other track's.
    rows = load_history()
    navs = {f"run2:{k}": v for k, v in navs_from_history(rows).items()}
    navs.update(
        {f"core_v1:{k}": v for k, v in navs_from_history(rows, start=CORE_EVALUATION_START).items()}
    )
    gaps = compare(marks, null_p95=NULL_P95_LOG_REL_WEALTH, navs=navs)
    # **RUN 2 NO LONGER AUTHORISES.** Its treatment changed inside its own window — two AI rules
    # under one version label — so it was reclassified an operational rehearsal. An experiment
    # declared methodologically invalid must never later produce a GO, so it keeps its statistic
    # (recorded under `tracks`) and loses its authority. The GO gate reads the authorising track
    # only, which is CORE_V1. Until that book exists the gate has no gap and says CANNOT ASSESS,
    # which is the honest answer rather than a borrowed one.
    rehearsal = next((g for g in gaps if g.gates and g.track == "run2"), None)
    authorizing = next((g for g in gaps if g.authorizes), None)
    if rehearsal is not None:
        print(
            f"[twin] rehearsal (non-authorising): {rehearsal.left} vs {rehearsal.right} — G = "
            + ("n/a" if rehearsal.log_rel_wealth is None else f"{rehearsal.log_rel_wealth:+.5f}")
        )
    if authorizing is None:
        print("[twin] GO gate: no authorising track yet — CORE_V1 not created, gap CANNOT ASSESS")
    else:
        window_note = "not yet open" if authorizing.months < 1 else f"{authorizing.months} month(s)"
        print(
            f"[twin] GO gate reads {authorizing.left} vs {authorizing.right} — {window_note} "
            f"since {CORE_EVALUATION_START}, G = "
            + (
                "n/a"
                if authorizing.log_rel_wealth is None
                else f"{authorizing.log_rel_wealth:+.5f}"
            )
        )
    gate_gap = authorizing.rupees if authorizing else None
    gate_g = authorizing.log_rel_wealth if authorizing else None
    months = authorizing.months if authorizing else None
    # Criterion 2 measures the fall THIS BOOK LIVED THROUGH — from the first cash flow, not a
    # trailing year. A -14.8% drop that happened before the money went in tests nothing, and the
    # first run of this file reported exactly that as a green.
    # The registered window, not the first flow ever recorded — criterion 2 must test the fall this
    # *experiment* lived through, and the tradebook reaches back before the experiment began.
    # The AUTHORISING window. Criterion 2 must test the fall the gating experiment lived through,
    # and that experiment is now CORE_V1, whose clock opens later than run 2's.
    gate_start = CORE_EVALUATION_START
    start = max(gate_start, flows[0].on) if flows else gate_start
    window = market.index_close.loc[pd.Timestamp(start) : pd.Timestamp(market.as_of)]
    worst = float((window / window.cummax() - 1).min()) if len(window) > 1 else None
    gate = build_gate(
        Evidence(
            months_of_flows=months,
            worst_drawdown_in_window=worst,
            gap_vs_ew_baseline=gate_gap,
            log_rel_wealth=gate_g,
            null_p95=NULL_P95_LOG_REL_WEALTH,
            # These four were hard-coded: two invented REDs and two invented GREENs. The greens are
            # the dangerous pair — `tradebook_reconciles=True` and `unguarded_price_gaps=0` asserted
            # a clean reconciliation and a clean feed that nothing had checked, which is this repo's
            # signature defect (a number labelled as something it is not) sitting inside the gate
            # itself. `None` reads ⚪ CANNOT ASSESS, which blocks a GO exactly as a red does while
            # saying honestly that nobody looked.
            reconciled_complex_sale=None,
            reconciled_corporate_action=None,
            tradebook_reconciles=None,
            unguarded_price_gaps=None,
        ),
        market.as_of,
    )
    return marks, gaps, gate


def cmd_daily(cfg: Config) -> int:
    """Step every autonomous book, mark them all, grade the gate, write the report."""
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
    trades = _tradebook()
    credits = load_off_market()
    for d in sync_flows(books, trades, credits):
        print(f"[twin] credited ₹{d.amount:,.2f} on {d.on} to all {len(books)} books")

    # A tradebook that reads empty while the books hold flows is a FAILED READ, not an empty
    # account. Left unchecked, REAL replays to ₹0 against ₹3,04,144 of flows — a −100% line, with
    # every twin appearing to beat it by three lakh, written to the dashboard as a verdict. Refuse
    # to write anything: yesterday's report is far better than today's wrong one.
    if not trades and books[REAL].flows:
        print(
            f"[twin] ABORT — the tradebook read EMPTY but the books hold "
            f"{len(books[REAL].flows)} flows (₹{books[REAL].net_invested:,.2f}).\n"
            "       This is a failed read, not an empty account. Nothing was written; the previous "
            "report stands.\n"
            "       Check: GIST_TOKEN present in the job, and that it carries the `gist` scope.",
            file=sys.stderr,
        )
        return 0

    # The AI treatment. Until 2026-08-30 this was never gathered, so `Market.ai_verdicts` was always
    # None, `policy.use_ai and market.ai_verdicts` was always False, and all four twins were
    # byte-identical by construction — TWIN_FULL − TWIN_NO_AI could only ever have read ₹0. The
    # verdicts are asked for HERE, outside `step`, because the runner must stay pure and replayable:
    # it consumes a decided map, it never calls anything.
    # CORE_V1 is created once, and on purpose before its registered window opens: the deterministic
    # entry completes first so the measured period is not dominated by a book sitting in cash beside
    # a fully-invested fund. The window date is registered in advance and cannot be moved to suit a
    # result. Any cash still idle when it opens stays visible in the record rather than corrected.
    if CORE_V1 not in books:
        from qalpha.live.twin import assert_identical_flows

        seed_flows = books[REAL].flows
        pf = Portfolio(cfg.cost, cfg.tax, cash=sum((f.amount for f in seed_flows), Decimal("0")))
        books[CORE_V1] = TwinBook(name=CORE_V1, portfolio=pf, flows=list(seed_flows))
        assert_identical_flows(list(books.values()))
        save_books(books)
        print(
            f"[twin] CORE_V1 created with the identical flow set (₹{pf.cash:,.2f}). "
            f"Its measured window opens {CORE_EVALUATION_START}; see "
            "reports/PREREGISTRATION_CORE_V1.md"
        )

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
    for name in DECIDING:
        book = books.get(name)
        if book is None or book.stepped_through == market.as_of:
            continue
        decisions += step(book, ALL_POLICIES[name], market, cfg)
        book.stepped_through = market.as_of
    save_books(books)

    marks, gaps, gate = _marks_and_gate(books, market, cfg)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        f"# The twin — {as_of}\n\n_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. "
        "Fake money; the real account is the state source and is never traded._\n\n"
        + comparison_markdown(marks, gaps)
        + "\n\n---\n\n"
        + gate.render()
        + "\n",
        encoding="utf-8",
    )
    # Persist the marks the report was built from, so the dashboard charts plot exactly these
    # numbers rather than recomputing and quietly disagreeing with the table above them.
    MARKS.write_text(
        json.dumps(
            {
                "as_of": as_of.isoformat(),
                "books": comparison_frame(marks).to_dict(orient="records"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    DECISIONS_LOG.write_text(
        f"# Twin decisions — {as_of}\n\n" + decisions_markdown(decisions) + "\n", encoding="utf-8"
    )
    # The append-only record. Everything above this line is a snapshot that the next run destroys;
    # this is the only thing that accumulates. It is written LAST and fail-soft — a history write
    # that raised would stop the cron, and a stopped cron loses far more days than one bad row.
    try:
        rows = append_history(marks, gaps, as_of=as_of, gate_verdict=gate.verdict)
        print(f"✓ history: {rows} day(s) on file → {TWIN_HISTORY}")
    except Exception as exc:
        print(f"[twin] WARNING: history not appended ({exc})", file=sys.stderr)
    print(f"✓ {len(decisions)} decision(s) · gate: {gate.verdict} · → {REPORT}")
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
    marks, gaps, gate = _marks_and_gate(books, market, cfg, persist=False)
    print(comparison_markdown(marks, gaps))
    print()
    print(gate.render())
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["seed", "daily", "status"])
    args = ap.parse_args(argv)
    cfg = Config()
    if args.cmd == "seed":
        return cmd_seed(cfg)
    try:
        return cmd_daily(cfg) if args.cmd == "daily" else cmd_status(cfg)
    except Exception as exc:
        print(f"[twin] failed (non-fatal, cron stays green): {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
