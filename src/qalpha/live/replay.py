"""A replay: the investor run over past sessions, on its own book, from the state that existed then.

    for each session from the start to the end:
        money that arrived → corporate actions → fill yesterday's orders → review → mark → checkpoint

**The same investor.** The review, the fill, the limits and the accounting are
:func:`qalpha.live.manager.review`, :func:`~qalpha.live.manager.fill_pending`,
:func:`qalpha.live.twin.credit_actions` and the tradebook replay — the evening run's own functions,
called with a date. Nothing here decides, sizes or fills.

**Nothing after the session.** The world handed to the evening of ``T`` holds no row after ``T``:

- prices, volumes and the benchmark are cut at ``T``; adjusted closes are re-based so ``T``'s adjusted
  close equals its close, because a vendor's adjusted series scales every earlier level by dividends
  and splits paid *later* — a number nobody on ``T`` had;
- filings are documents the exchange had published by ``T``, from the corpus as it stood when the
  run was registered (``corpus.json``) — read later, published then (see :mod:`evidence_log`);
- a source that did not exist for ``T`` is named in the packet (``data_gaps``), not left empty.

**The starting book is the one that existed on the start date**: the tradebook and the broker's
ledger replayed through that day, with the corporate actions due by then. Copying today's holdings
into an earlier date would hand the investor its own future.

**Its own records**, under ``data/replay/<run>/``: ``run.json`` (the registration: window, model,
mandate digest, code commit, corpus date, spend ceiling), ``state.json`` (the book and one row per
session, written atomically as one checkpoint after every session), and ``manager/`` (receipts,
decisions, logbook, fills, scorecard). The evening run's records are never opened for writing.

**It resumes.** A run stopped anywhere continues from the last checkpoint. A session interrupted
half-way is redone from its saved book: the fill is not written twice and the receipt answers the
review, so no decision is made or paid for twice.

**Its own money.** Model calls go through :mod:`qalpha.live.spend` as a named job with an explicit
ceiling, counted across every month. Simulating three months never draws on any month's operating
allowance. A spend stop ends the run *before* that session is checkpointed, so raising the ceiling
and resuming retries it rather than recording a review that never happened.

**What a replay cannot show.** The model may already know how these sessions turned out. A replay
tests that the investor runs — researches, decides, fills, remembers, resumes — and records how it
behaved; its returns are descriptive and are not evidence of skill.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.live import atomic, manager
from qalpha.live.evidence_log import Corpus
from qalpha.live.flows import Flow, benchmark_leg
from qalpha.live.market import Market
from qalpha.live.nav import unitized_nav
from qalpha.live.price_integrity import excluded_from_tilt, rebase_starts, unexplained_gaps
from qalpha.live.spend import SpendStopError
from qalpha.live.tradebook import TradebookTrade, replay_tradebook
from qalpha.live.twin import (
    OffMarketCredit,
    TwinBook,
    apply_off_market,
    book_from_state,
    book_state,
    credit_actions,
    ew_fund_mark,
)

REPLAY_ROOT = Path("data/replay")
BOOK = "SYSTEM-REPLAY"

#: The evening run's records. A replay that changed any of them has failed, whatever else it did.
LIVE_RECORDS = (
    Path("data/twin"),
    Path("data/evidence"),
    Path("data/facts/financials.jsonl"),
)


class ReplayStoppedError(RuntimeError):
    """The run stopped before a session could happen — money, identity, or a changed registration.

    Nothing about the stopped session is checkpointed, so resuming retries it.
    """


# ---- the registration --------------------------------------------------------------------------


def investor_digest() -> str:
    """The investor being replayed: version, model, the whole mandate and the prompt text."""
    body = json.dumps(
        {
            "version": manager.VERSION,
            "model": manager.MODEL,
            "mandate": manager.MANDATE.to_dict(),
            "prompt": manager.PROMPT,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()[:24]


def inputs_digest(
    full: Market,
    end: date,
    *,
    trades: Sequence[TradebookTrade],
    flows: Sequence[Flow],
    actions: Sequence[CorporateAction],
    off_market: Sequence[OffMarketCredit],
) -> str:
    """Everything a run reads besides the corpus and the code, through its end date, as one digest.

    Prices for a past session can change — a re-download fills a missing close — and a run whose
    inputs changed between two resumes would decide its later sessions on a different world than its
    earlier ones. The corpus is frozen into the run; these are checked instead, and a change is a new
    run.
    """
    stamp = pd.Timestamp(end)
    h = hashlib.sha256()
    panel = full.wl_prices
    frames = [] if panel is None else [panel.adj_close, panel.close_raw, panel.volume]
    for frame in frames:
        cut = frame.loc[:stamp]
        h.update(pd.util.hash_pandas_object(cut, index=True).to_numpy().tobytes())
        h.update("|".join(map(str, cut.columns)).encode())
    h.update(
        pd.util.hash_pandas_object(full.index_close.loc[:stamp], index=True).to_numpy().tobytes()
    )
    h.update(json.dumps(sorted((full.sector_of or {}).items())).encode())
    h.update(json.dumps(list(full.watchlist or [])).encode())
    for item in (
        *sorted(repr(t) for t in trades if t.trade_date <= end),
        *sorted(repr(f) for f in flows if f.on <= end),
        *sorted(repr(a) for a in actions if a.ex_date <= end),
        *sorted(repr(c) for c in off_market if c.on <= end),
    ):
        h.update(item.encode())
    return h.hexdigest()[:24]


@dataclass(frozen=True)
class Plan:
    """What a run is, fixed when it is created. A change to any of it is a different run."""

    run_id: str
    start: date
    end: date
    #: The corpus date: filings and headlines recorded after this are not used, so a run reads the
    #: same evidence on every resume while the evening run keeps collecting.
    recorded_by: date
    ceiling_usd: Decimal
    version: str
    model: str
    investor: str
    commit: str
    created_at: str
    #: :func:`inputs_digest` at registration.
    inputs: str

    @property
    def spend_job(self) -> str:
        return f"replay:{self.run_id}"

    def to_dict(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "recorded_by": self.recorded_by.isoformat(),
            "ceiling_usd": str(self.ceiling_usd),
            "version": self.version,
            "model": self.model,
            "investor": self.investor,
            "commit": self.commit,
            "created_at": self.created_at,
            "inputs": self.inputs,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Plan:
        return cls(
            run_id=str(raw["run_id"]),
            start=date.fromisoformat(str(raw["start"])),
            end=date.fromisoformat(str(raw["end"])),
            recorded_by=date.fromisoformat(str(raw["recorded_by"])),
            ceiling_usd=Decimal(str(raw["ceiling_usd"])),
            version=str(raw["version"]),
            model=str(raw["model"]),
            investor=str(raw["investor"]),
            commit=str(raw["commit"]),
            created_at=str(raw["created_at"]),
            inputs=str(raw["inputs"]),
        )


def new_plan(
    run_id: str,
    *,
    start: date,
    end: date,
    recorded_by: date,
    ceiling_usd: Decimal,
    commit: str,
    inputs: str,
) -> Plan:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", run_id):
        raise ValueError(f"run id {run_id!r}: letters, digits, '.', '_' and '-' only")
    if end < start:
        raise ValueError(f"the end {end} is before the start {start}")
    if recorded_by < end:
        raise ValueError(
            f"the corpus date {recorded_by} is before the end {end}: sessions after it could not be "
            "given the filings they had"
        )
    return Plan(
        run_id=run_id,
        start=start,
        end=end,
        recorded_by=recorded_by,
        ceiling_usd=ceiling_usd,
        version=manager.VERSION,
        model=manager.MODEL,
        investor=investor_digest(),
        commit=commit,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        inputs=inputs,
    )


def changed_since(plan: Plan, *, commit: str, inputs: str) -> list[str]:
    """Why what would run now is not what this run registered. Empty when it is."""
    out = []
    if plan.version != manager.VERSION:
        out.append(f"version {plan.version} → {manager.VERSION}")
    if plan.model != manager.MODEL:
        out.append(f"model {plan.model} → {manager.MODEL}")
    if plan.investor != investor_digest():
        out.append("the mandate or the prompt changed")
    if plan.commit != commit:
        out.append(f"code commit {plan.commit} → {commit}")
    if plan.inputs != inputs:
        out.append(
            "the prices, tradebook, ledger or corporate actions up to the end date changed "
            f"(inputs {plan.inputs} → {inputs})"
        )
    return out


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def plan(self) -> Path:
        return self.root / "run.json"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def corpus(self) -> Path:
        return self.root / "corpus.json"

    @property
    def store(self) -> manager.Store:
        return manager.Store(self.root / "manager")


def paths_for(run_id: str, root: Path | None = None) -> Paths:
    # Resolved at call time, so a test that redirects REPLAY_ROOT reaches every caller.
    return Paths((REPLAY_ROOT if root is None else root) / run_id)


def save_plan(paths: Paths, plan: Plan, corpus: Corpus) -> None:
    """Register a run: the corpus first, so a registration never exists without the corpus it names."""
    if paths.plan.exists():
        raise ValueError(f"{paths.plan} exists: a registered run is never rewritten")
    if corpus.recorded_by != plan.recorded_by:
        raise ValueError("the corpus and the registration name different corpus dates")
    atomic.write_text(paths.corpus, json.dumps(corpus.to_dict()) + "\n")
    atomic.write_text(paths.plan, json.dumps(plan.to_dict(), indent=2) + "\n")


def load_plan(paths: Paths) -> Plan | None:
    if not paths.plan.exists():
        return None
    return Plan.from_dict(json.loads(paths.plan.read_text(encoding="utf-8")))


def load_corpus(paths: Paths) -> Corpus:
    return Corpus.from_dict(json.loads(paths.corpus.read_text(encoding="utf-8")))


# ---- the starting book -------------------------------------------------------------------------


def reconstruct(
    start: date,
    *,
    trades: Sequence[TradebookTrade],
    flows: Sequence[Flow],
    actions: Sequence[CorporateAction],
    off_market: Sequence[OffMarketCredit],
    cfg: Config,
) -> TwinBook:
    """The book as it stood at the close of ``start``: the evening run's REAL, cut at that date.

    Trades, deposits, allotments and corporate actions dated after ``start`` do not exist yet. The
    arithmetic is :func:`scripts.twin.replay_real`'s — funded money less what the trades spent.
    """
    replay = replay_tradebook(
        [t for t in trades if t.trade_date <= start],
        cfg,
        corporate_actions=[a for a in actions if a.ex_date <= start],
    )
    portfolio = replay.portfolio
    apply_off_market(portfolio, [c for c in off_market if c.on <= start])
    funded = [f for f in flows if f.on <= start]
    portfolio.cash = sum((f.amount for f in funded), Decimal("0")) - replay.net_spent
    return TwinBook(name=BOOK, portfolio=portfolio, flows=funded, actions_through=start)


# ---- the world on one evening ------------------------------------------------------------------


def sessions(full: Market, start: date, end: date) -> list[date]:
    """Trading sessions in the window, from the benchmark's own bars (as the fill does)."""
    return sorted(
        d.date()
        for d in pd.DatetimeIndex(full.index_close.dropna().index)
        if start <= d.date() <= end
    )


def world_on(full: Market, day: date) -> Market | None:
    """The evening of ``day``, holding nothing after it. ``None`` when the panel has no row for it."""
    panel = full.wl_prices
    if panel is None or pd.Timestamp(day) not in panel.adj_close.index:
        return None
    view = panel.as_of(day)
    adj = view.adj_close.copy()
    raw = view.close_raw
    for ticker in adj.columns:
        series = adj[ticker].dropna()
        if series.empty:
            continue
        last = series.index[-1]
        close = raw.at[last, ticker]
        level = float(str(series.iloc[-1]))
        if pd.notna(close) and float(str(close)) > 0 and level > 0:
            adj[ticker] = adj[ticker] * (float(str(close)) / level)
    watchlist = [t for t in (full.watchlist or []) if t in adj.columns]
    gaps = unexplained_gaps(adj, watchlist, day)
    return Market(
        as_of=day,
        prices={
            t: Decimal(str(float(adj[t].dropna().iloc[-1])))
            for t in adj.columns
            if not adj[t].dropna().empty
        },
        index_close=full.index_close.loc[: pd.Timestamp(day)],
        adj_close=adj,
        rebase_from=rebase_starts(gaps),
        exclude=excluded_from_tilt(gaps),
        watchlist=watchlist,
        sector_of=full.sector_of,
        wl_prices=PriceData(adj, raw, view.volume),
    )


def archive_starts(directory: Path) -> date | None:
    """The first date a dated archive directory holds anything for. ``None`` when it holds nothing."""
    days = [
        date.fromisoformat(p.name)
        for p in (directory.iterdir() if directory.exists() else [])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)
    ]
    return min(days) if days else None


def gaps_on(day: date, *, headlines_from: date | None) -> dict[str, str]:
    """Sources that did not exist for ``day``, in words the investor reads."""
    if headlines_from is None or day < headlines_from:
        since = f"begins {headlines_from}" if headlines_from else "is empty"
        return {
            "headlines": (
                f"No headlines were archived for this date (the archive {since}). Headline "
                "coverage is UNKNOWN — an empty headline list here is not a quiet period."
            )
        }
    return {}


# ---- one evening -------------------------------------------------------------------------------


def credit_flows(book: TwinBook, flows: Iterable[Flow], *, through: date) -> list[Flow]:
    """Money that reached the account by ``through`` and not yet this book: added to cash and flows."""
    known = {(f.on, f.amount) for f in book.flows}
    new = [f for f in flows if f.on <= through and (f.on, f.amount) not in known]
    for flow in sorted(new, key=lambda f: f.on):
        book.flows.append(flow)
        book.portfolio.cash += flow.amount
    return new


def packet_summary(packet: Mapping[str, Any]) -> dict[str, Any]:
    """What was in front of the investor, counted: names, gaps, filings filed and read, events."""
    return {
        "holdings": len(packet["portfolio"]["holdings"]),
        "candidates_shown": [c["ticker"] for c in packet["candidates"]],
        "not_shown": dict(packet["not_shown"]),
        "filings": {
            t: {
                "filed": c["documents_filed"],
                "read": c["documents_read"],
                "unread": len(c["could_not_read"]),
            }
            for t, c in packet["coverage"].items()
        },
        "events": {t: len(v) for t, v in packet["evidence"].items()},
        "exchange_unknown": sorted(
            t for t, v in packet["exchange"].items() if v["state"] == "UNKNOWN"
        ),
        "financials_unknown": sorted(t for t, v in packet["financials"].items() if "status" in v),
        "data_gaps": sorted(packet.get("data_gaps") or {}),
        "memory_notes": sum(len(v) for v in packet["memory"]["notes_by_name"].values())
        + len(packet["memory"]["portfolio_notes"]),
        "research_requests": len(packet.get("research") or []),
    }


def _receipt_summary(store: manager.Store, name: str) -> dict[str, Any]:
    path = store.receipts / name
    if not name or not path.exists():
        return {}
    receipt = json.loads(path.read_text(encoding="utf-8"))
    return {"usage": receipt.get("usage", {}), **packet_summary(receipt["packet"])}


def step(
    book: TwinBook,
    market: Market,
    *,
    now: datetime,
    make_brain: Callable[[], manager.Brain],
    store: manager.Store,
    corpus: Corpus,
    gaps: Mapping[str, str],
    flows: Sequence[Flow],
    actions: Sequence[CorporateAction],
) -> dict[str, Any]:
    """One replayed evening, in the evening run's order. Mutates ``book``; returns the session's row.

    Raises :class:`ReplayStoppedError` when the review could not be paid for or the model is not the
    registered one: that session did not happen and must not be checkpointed.
    """
    day = market.as_of
    credited = credit_flows(book, flows, through=day)
    corporate = credit_actions(book, actions, through=day)
    fills = manager.fill_pending(book, market, now=now, store=store)
    waiting = (book.manager.get("pending") or {}).get("waiting")
    row: dict[str, Any] = {
        "as_of": day.isoformat(),
        "flows": [{"on": f.on.isoformat(), "amount": str(f.amount)} for f in credited],
        "corporate_actions": corporate,
        "fills": fills,
        "waiting": waiting,
    }
    try:
        decisions = manager.review(
            book,
            market,
            now=now,
            make_brain=make_brain,
            store=store,
            require_today=False,
            known_on=day,
            corpus=corpus,
            gaps=gaps,
        )
    except manager.IncompleteReviewError as exc:
        if isinstance(exc.__cause__, SpendStopError):
            raise ReplayStoppedError(str(exc)) from exc
        row.update(status="incomplete", reason=str(exc))
    else:
        last = book.manager.get("last_review") or {}
        row.update(
            status="reviewed",
            decisions=dict(Counter(d.action for d in decisions)),
            queued=list((book.manager.get("pending") or {}).get("orders", [])),
            packet=_receipt_summary(store, str(last.get("receipt", ""))),
        )
    closes = {t: manager.raw_close(market, day, t) for t in book.portfolio.positions()}
    unpriced = sorted(t for t, c in closes.items() if c is None)
    holdings = sum(
        (q * (closes[t] or 0) for t, q in book.portfolio.positions().items()), Decimal(0)
    )
    row.update(
        cash=str(book.portfolio.cash),
        names_held=len(closes),
        unpriced=unpriced,
        # A holding with no close today makes the book's value unknown, not its value without it.
        value=None if unpriced else str(book.portfolio.cash + holdings),
        net_invested=str(book.net_invested),
    )
    return row


# ---- the run -----------------------------------------------------------------------------------


@dataclass
class State:
    book: TwinBook
    #: The origin: what the book was at the close of the start date, before its first review.
    boundary: dict[str, Any]
    sessions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def through(self) -> date | None:
        return date.fromisoformat(self.sessions[-1]["as_of"]) if self.sessions else None


def save_state(paths: Paths, state: State) -> None:
    """One atomic checkpoint: the book and every session row together, or neither."""
    payload = {
        "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "boundary": state.boundary,
        "book": book_state(state.book),
        "sessions": state.sessions,
    }
    atomic.write_text(
        paths.state, json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    )


def load_state(paths: Paths, cfg: Config) -> State | None:
    if not paths.state.exists():
        return None
    raw = json.loads(paths.state.read_text(encoding="utf-8"))
    return State(
        book=book_from_state(BOOK, raw["book"], cfg),
        boundary=dict(raw["boundary"]),
        sessions=list(raw["sessions"]),
    )


def boundary_of(book: TwinBook, market: Market) -> dict[str, Any]:
    closes = {t: manager.raw_close(market, market.as_of, t) for t in book.portfolio.positions()}
    unpriced = sorted(t for t, c in closes.items() if c is None)
    holdings = sum(
        (q * (closes[t] or 0) for t, q in book.portfolio.positions().items()), Decimal(0)
    )
    return {
        "as_of": market.as_of.isoformat(),
        "cash": str(book.portfolio.cash),
        "holdings": {t: str(q) for t, q in sorted(book.portfolio.positions().items())},
        "unpriced": unpriced,
        "value": None if unpriced else str(book.portfolio.cash + holdings),
        "net_invested": str(book.net_invested),
    }


def run(
    plan: Plan,
    paths: Paths,
    *,
    full: Market,
    now: datetime,
    make_brain: Callable[[], manager.Brain],
    trades: Sequence[TradebookTrade],
    flows: Sequence[Flow],
    actions: Sequence[CorporateAction],
    off_market: Sequence[OffMarketCredit],
    cfg: Config,
    headlines_from: date | None,
    log: Callable[[str], None] = print,
) -> State:
    """Replay every session from the last checkpoint to the end. Returns the state as checkpointed."""
    store = paths.store
    if store.root.resolve() == manager.STORE.root.resolve():
        raise ReplayStoppedError("a replay may not write to the evening run's investor records")
    corpus = load_corpus(paths)
    state = load_state(paths, cfg)
    days = sessions(full, plan.start, plan.end)
    if state is None:
        if not days or days[0] != plan.start:
            raise ReplayStoppedError(f"{plan.start} is not a session the benchmark has a close for")
        opening = world_on(full, plan.start)
        if opening is None:
            raise ReplayStoppedError(f"the watchlist panel has no closes for {plan.start}")
        book = reconstruct(
            plan.start, trades=trades, flows=flows, actions=actions, off_market=off_market, cfg=cfg
        )
        state = State(book=book, boundary=boundary_of(book, opening))
        save_state(paths, state)
        log(
            f"[replay] {plan.run_id}: book at the close of {plan.start} — "
            f"{len(book.portfolio.positions())} name(s), cash ₹{book.portfolio.cash:,.2f}"
        )
    for day in days:
        if state.through is not None and day <= state.through:
            continue
        market = world_on(full, day)
        if market is None:
            row: dict[str, Any] = {
                "as_of": day.isoformat(),
                "status": "incomplete",
                "reason": f"the watchlist panel has no closes for {day}, a session the benchmark traded",
                "value": None,
            }
        else:
            row = step(
                state.book,
                market,
                now=now,
                make_brain=make_brain,
                store=store,
                corpus=corpus,
                gaps=gaps_on(day, headlines_from=headlines_from),
                flows=flows,
                actions=actions,
            )
        state.sessions.append(row)
        save_state(paths, state)
        log(
            f"[replay] {day}: {row['status']}"
            + (f" — {row['reason']}" if row.get("reason") else "")
            + (f" · decisions {row['decisions']}" if row.get("decisions") else "")
            + (f" · filled {len(row['fills'])}" if row.get("fills") else "")
        )
    return state


# ---- what the run shows ------------------------------------------------------------------------


def fingerprint(entries: Sequence[Path] | None = None) -> dict[str, str]:
    """A hash of every record file under ``entries`` — compared before and after a run."""
    prints: dict[str, str] = {}
    for base in LIVE_RECORDS if entries is None else entries:
        files = [base] if base.is_file() else sorted(base.rglob("*")) if base.is_dir() else []
        for path in files:
            if path.is_file():
                prints[path.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return prints


def changed(before: Mapping[str, str], after: Mapping[str, str]) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def outcome(
    state: State,
    store: manager.Store,
    *,
    index_close: pd.Series,
    ew_series: pd.Series | None,
) -> dict[str, Any]:
    """Descriptive figures over the run — **not evidence of skill**, and labelled so wherever shown.

    Unitized NAV so deposits are not returns. The baselines receive the book's value at the boundary
    on the start date and every later deposit on its day: the same money on the same days. A session
    whose value is unknown is left out of the series and counted, never filled from a neighbour.
    """
    start = date.fromisoformat(state.boundary["as_of"])
    later = [f for f in state.book.flows if f.on > start]
    points = [(date.fromisoformat(r["as_of"]), r["value"]) for r in state.sessions]
    known = [(d, Decimal(str(v))) for d, v in points if v is not None]
    unknown = [d.isoformat() for d, v in points if v is None]
    result: dict[str, Any] = {"sessions": len(points), "value_unknown_on": unknown}
    if state.boundary.get("value") is None or not known:
        result["note"] = "the book's value is unknown at the boundary or on every session"
        return result

    opening = Decimal(str(state.boundary["value"]))
    funded = [Flow(on=start, amount=opening), *later]

    def navs(values: list[tuple[date, Decimal]]) -> pd.Series:
        series = pd.Series(
            [float(v) for _, v in values],
            index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in values]),
        )
        return unitized_nav(series, [(f.on, float(f.amount)) for f in later])

    def summary(values: list[tuple[date, Decimal]]) -> dict[str, float]:
        nav = navs(values)
        peak = nav.cummax()
        return {
            "return_pct": round((float(nav.iloc[-1]) / float(nav.iloc[0]) - 1) * 100, 2),
            "max_drawdown_pct": round(float((nav / peak - 1).min()) * 100, 2),
        }

    system = [(start, opening), *[(d, v) for d, v in known if d != start]]
    result["system"] = {
        **summary(system),
        "value_end": str(known[-1][1]),
        "cash_end": state.sessions[-1].get("cash"),
    }
    bench = []
    ew = []
    for d, _ in system:
        # Only money that had arrived by ``d``. Both marks replay every flow they are given, whatever
        # its date: handed the whole list, a deposit made later was already in the fund on the first
        # day and was added again when it arrived — a rising index read as a 25% loss.
        arrived = [f for f in funded if f.on <= d]
        leg = benchmark_leg(arrived, index_close, d)
        if leg is not None:
            bench.append((d, leg.value))
        if ew_series is not None and (m := ew_fund_mark(arrived, ew_series, d)) is not None:
            ew.append((d, m.value))
    if len(bench) == len(system):
        result["baseline_niftybees"] = summary(bench)
    if len(ew) == len(system):
        result["baseline_equal_weight_fund"] = summary(ew)

    fills = [f for f in _rows(store.fills) if int(f.get("filled", 0) or 0) > 0]
    traded = sum((Decimal(str(f["filled"])) * Decimal(str(f["price"])) for f in fills), Decimal(0))
    average = sum((v for _, v in system), Decimal(0)) / len(system)
    result["turnover_pct_of_average_value"] = (
        round(float(traded / average * 100), 2) if average else None
    )
    result["costs"] = str(sum((Decimal(str(f.get("cost", "0"))) for f in fills), Decimal(0)))
    result["tax"] = str(sum((Decimal(str(f.get("tax", "0"))) for f in fills), Decimal(0)))
    result["traded_value"] = str(traded)
    return result
