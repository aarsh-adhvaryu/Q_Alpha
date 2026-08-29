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
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from paper import _load_benchmark_series, _load_market

from qalpha.config import Config
from qalpha.live.go_gate import Evidence, build_gate
from qalpha.live.policy import POLICIES, Decision, decisions_markdown
from qalpha.live.runner import Market, step
from qalpha.live.twin import (
    AUTONOMOUS,
    BACKTEST_NOISE_FLOOR,
    REAL,
    baseline_mark,
    compare,
    comparison_frame,
    comparison_markdown,
    ew_fund_mark,
    load_books,
    mark,
    save_books,
    seed_books,
    sync_flows,
)

REPORT = Path("reports/twin_dashboard.md")
DECISIONS_LOG = Path("reports/twin_decisions.md")
MARKS = Path("data/twin/marks.json")
WATCHLIST_PANEL = Path("data/historical/prices_watchlist.parquet")
WATCHLIST_CSV = Path("data/universes/nifty100_watchlist.csv")


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
    books = seed_books(trades, cfg)
    save_books(books)
    flows = books[REAL].flows
    print(
        f"✓ seeded {len(books)} books from {len(trades)} trades · {len(flows)} flows · "
        f"₹{books[REAL].net_invested:,.2f} net invested · start {flows[0].on}"
    )
    return 0


def _marks_and_gate(books: dict, market: Market, cfg: Config):
    """Mark every book, add both baselines, and grade the gate on what is actually known."""
    from qalpha.live.tradebook import replay_tradebook

    marks = {n: mark(b, market.prices, market.as_of) for n, b in books.items() if n != REAL}
    real = replay_tradebook(_tradebook(), cfg).portfolio
    books[REAL].portfolio = real
    marks[REAL] = mark(books[REAL], market.prices, market.as_of)

    flows = books[REAL].flows
    for m in (
        baseline_mark(flows, market.index_close, market.as_of),
        ew_fund_mark(flows, market.index_close, market.as_of),
    ):
        if m is not None:
            marks[m.name] = m
    gaps = compare(marks, noise_floor=BACKTEST_NOISE_FLOOR)
    gate_gap = next((g.rupees for g in gaps if g.gates), None)
    months = next((g.months for g in gaps if g.gates), None)
    # Criterion 2 measures the fall THIS BOOK LIVED THROUGH — from the first cash flow, not a
    # trailing year. A -14.8% drop that happened before the money went in tests nothing, and the
    # first run of this file reported exactly that as a green.
    start = flows[0].on if flows else market.as_of
    window = market.index_close.loc[pd.Timestamp(start) : pd.Timestamp(market.as_of)]
    worst = float((window / window.cummax() - 1).min()) if len(window) > 1 else None
    gate = build_gate(
        Evidence(
            months_of_flows=months,
            worst_drawdown_in_window=worst,
            gap_vs_ew_baseline=gate_gap,
            noise_floor=BACKTEST_NOISE_FLOOR,
            reconciled_complex_sale=False,
            reconciled_corporate_action=False,
            tradebook_reconciles=True,
            unguarded_price_gaps=0,
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
    for d in sync_flows(books, trades):
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

    decisions: list[Decision] = []
    for name in AUTONOMOUS:
        if name in books:
            decisions += step(books[name], POLICIES[name], market, cfg)
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
    marks, gaps, gate = _marks_and_gate(books, market, cfg)
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
