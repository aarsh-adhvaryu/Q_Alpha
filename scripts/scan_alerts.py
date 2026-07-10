"""Daily opportunity scan → Telegram alerts — the "analyst" that runs in the paper cron (PR-1).

Runs in the same GitHub Actions job as ``paper.py daily``, *after* the book is marked. It gathers
today's already-computed facts (market weakness off the real NIFTYBEES benchmark, the GO scorecard,
freshness, and whether a rebalance just auto-applied or is pending), asks the pure
:func:`qalpha.live.scan.evaluate` which alerts are worth sending, ships them via
:func:`qalpha.live.notify.send_telegram`, and persists the (tracked, secret-free) alert state.

**Fail-soft, always exit 0.** A missed alert is fine; a red cron is not — every path swallows its
error, logs it, and returns 0. Flags:

    scan_alerts.py                       # the cron path: gather → evaluate → send → persist state
    scan_alerts.py --test                # send one test message (verify the wiring) and exit
    scan_alerts.py --force-digest        # emit the weekly digest now (verification), don't burn the slot
    scan_alerts.py --pipeline-failed MSG # the `if: failure()` step: send a failure alert, standalone
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pandas as pd
from paper import BOOK_PATH, _load_benchmark_series, _load_market

from qalpha.config import Config
from qalpha.live.deploy import cheapness_scores, market_weakness
from qalpha.live.go_scorecard import build_scorecard, trading_days_remaining
from qalpha.live.notify import send_telegram, telegram_configured
from qalpha.live.paper import PaperBook
from qalpha.live.runlog import load_runs
from qalpha.live.scan import ScanFacts, evaluate, load_state, save_state

WATCHLIST_CSV = Path("data/universes/nifty100_watchlist.csv")
WATCHLIST_PANEL = Path("data/historical/prices_watchlist.parquet")


def _tranche_policy(level: str) -> str:
    """The pre-committed deploy-into-weakness policy text (stated in every weakness alert, PR-1)."""
    if level == "deep":
        return (
            "📉 Pre-committed policy: deploy <b>100%</b> of idle cash into this pullback — the "
            "calculated risk on deep weakness (tax-free buys only, you place the orders)."
        )
    if level == "elevated":
        return (
            "📉 Pre-committed policy: deploy <b>50%</b> of idle cash now — a better-than-usual entry "
            "(tax-free buys only, you place the orders)."
        )
    return "Deploy steadily / dollar-cost average; keep dry powder."


def _out_of_favour_names(as_of: date) -> str:
    """Top out-of-favour Nifty-100 names for a weakness alert (best-effort — empty on any failure).

    The watchlist price panel is gitignored, so on a fresh CI checkout it's absent; we download it
    in-job (reusing the watchlist builder) only when this runs — i.e. only on genuinely weak days,
    so a normal-market scan never pays the cost.
    """
    try:
        if not WATCHLIST_CSV.exists():
            return ""
        if not WATCHLIST_PANEL.exists():
            import subprocess

            subprocess.run(
                [sys.executable, "scripts/build_nifty100_watchlist.py", "--prices"],
                check=False,
                cwd=Path.cwd(),
                timeout=300,
            )
        if not WATCHLIST_PANEL.exists():
            return ""
        from qalpha.data.ingest import load_parquet

        wl = pd.read_csv(WATCHLIST_CSV)
        tickers = [str(t) for t in wl["ticker"]]
        prices = load_parquet(str(WATCHLIST_PANEL))
        cheap = cheapness_scores(prices, tickers, as_of)
        top = sorted(cheap.items(), key=lambda kv: kv[1], reverse=True)[:3]
        if not top:
            return ""
        parts = [f"{t.removesuffix('.NS')} ({-score:.0%} off 1y high)" for t, score in top]
        return "Most out of favour: " + ", ".join(parts) + "."
    except Exception as exc:
        print(f"[scan] out-of-favour names skipped: {exc}")
        return ""


def _benchmark_return_pct(bench: pd.Series, start: date, as_of: date) -> float | None:
    """TRI return over the book's live window (start→as_of), for the digest book-vs-TRI line."""
    hist = bench.dropna()
    b_start = hist.loc[: pd.Timestamp(start)]
    b_end = hist.loc[: pd.Timestamp(as_of)]
    if b_start.empty or b_end.empty:
        return None
    return float(b_end.iloc[-1] / b_start.iloc[-1] - 1.0) * 100.0


def _gather_facts(today: date) -> ScanFacts:
    """Assemble today's :class:`ScanFacts` from the marked book + benchmark (the cron just ran)."""
    cfg = Config()
    prices, universe, sector_of = _load_market()
    book = PaperBook.load(BOOK_PATH, cfg)
    as_of = prices.dates[-1].date()
    bench = _load_benchmark_series()

    weakness = market_weakness(bench, as_of)
    deploy_lines = _tranche_policy(weakness.level)
    if weakness.level in ("elevated", "deep"):
        names = _out_of_favour_names(as_of)
        if names:
            deploy_lines += "\n" + names

    scorecard = build_scorecard(book.equity_curve, bench, as_of)

    from qalpha.live.dashboard import paper_freshness

    fresh = paper_freshness(book, today)

    # Rebalance state: the daily run (which ran just before us) auto-applies scheduled orders and logs
    # the action to the run log; a pending plan means orders await human approval. Read both cleanly.
    plan = book.plan(prices, universe, sector_of, as_of)
    recent = load_runs(limit=1)
    applied = (
        bool(recent)
        and "auto-applied" in recent[-1].action
        and recent[-1].as_of == as_of.isoformat()
    )
    rebalance_summary = ""
    if applied and book.history:
        orders = book.history[-1].get("orders", [])
        rebalance_summary = "\n".join(
            f"{o['side']} {o['ticker']} {o['quantity']}"
            for o in orders[:10]  # type: ignore[index]
        )
    elif plan.has_orders:
        rebalance_summary = "\n".join(
            f"{o.side.name} {o.ticker} {o.quantity}" for o in plan.proposed_orders[:10]
        )

    digest_body = _digest_body(book, prices, bench, scorecard.verdict, weakness.level, as_of)

    return ScanFacts(
        as_of=as_of,
        weakness_level=weakness.level,
        weakness_note=weakness.render(),
        deploy_lines=deploy_lines,
        go_verdict=scorecard.verdict,
        rebalance_applied=applied,
        rebalance_pending=plan.has_orders,
        rebalance_date=as_of.isoformat(),
        rebalance_summary=rebalance_summary,
        freshness_stale=fresh.is_stale,
        freshness_note=fresh.note,
        digest_body=digest_body,
    )


def _digest_body(
    book: PaperBook,
    prices: object,
    bench: pd.Series,
    go_verdict: str,
    market_level: str,
    as_of: date,
) -> str:
    """The Monday heartbeat: book vs TRI, market level, GO progress, next rebalance, idle-cash nudge."""
    book_ret = book.total_return_pct(prices, as_of)  # type: ignore[arg-type]
    tri = _benchmark_return_pct(bench, book.start_date, as_of)
    tri_line = f"{tri:+.1f}%" if tri is not None else "n/a"
    days_left = trading_days_remaining(book.equity_curve)
    go_line = (
        go_verdict if days_left == 0 else f"{go_verdict} ({days_left} trading days to power floor)"
    )
    return "\n".join(
        [
            f"Paper book <b>{book_ret:+.1f}%</b> vs Nifty TRI {tri_line} (since {book.start_date}).",
            f"Market: <b>{market_level}</b> · GO scorecard: <b>{go_line}</b>.",
            f"Next scheduled rebalance {book.next_rebalance_label()}.",
            "💰 Idle cash? Open the dashboard and log in to size fresh capital into the current market.",
            "",
            "<i>Silence during the week = all well.</i>",
        ]
    )


def _send(alerts: list[object]) -> None:
    for a in alerts:
        kind = getattr(a, "kind", "?")
        text = getattr(a, "text", "")
        ok = send_telegram(str(text))
        print(f"[scan] {kind}: {'sent' if ok else 'NOT sent (no config / send failed)'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="send a test alert and exit")
    parser.add_argument("--force-digest", action="store_true", help="emit the weekly digest now")
    parser.add_argument(
        "--pipeline-failed", default=None, help="send a pipeline-failure alert (msg)"
    )
    args = parser.parse_args(argv)

    if not telegram_configured():
        print("[scan] Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) — no-op.")
        # Still fall through for --pipeline-failed logging, but sends will just no-op.

    if args.test:
        ok = send_telegram(
            "✅ <b>Q-Alpha test alert</b> — the notification spine is wired correctly."
        )
        print(f"[scan] test alert: {'sent' if ok else 'NOT sent'}")
        return 0

    if args.pipeline_failed:
        # Standalone (runs in the `if: failure()` step where the environment may be broken) — send the
        # failure alert directly, never touching the book/state.
        ok = send_telegram(f"🚨 <b>Paper pipeline failed</b>\n{args.pipeline_failed}")
        print(f"[scan] pipeline-failed alert: {'sent' if ok else 'NOT sent'}")
        return 0

    try:
        today = datetime.now(UTC).date()
        facts = _gather_facts(today)
        state = load_state()
        alerts, new_state = evaluate(facts, state, today, force_digest=args.force_digest)
        if not alerts:
            print("[scan] no edge today — nothing to send (silence = all well).")
        _send(alerts)
        save_state(new_state)
    except Exception as exc:
        print(f"[scan] scan failed (non-fatal, cron stays green): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
