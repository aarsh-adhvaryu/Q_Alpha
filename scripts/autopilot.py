"""autopilot.py — the daily runner for the fake-money "watch it invest & see if it works" auto-pilot.

The advisor recommends buys; the auto-pilot follows its own advice forward on fake money in three
books — **A** strategy only · **B** strategy + the AI's daily nudge · **C** buy-and-hold NIFTYBEES —
so you can watch whether the system makes money and whether the AI helps (see
``docs/PREREGISTRATION_autopilot.md``).

    python scripts/autopilot.py daily              # scheduled top-up + deploy + resolve + write (cron)
    python scripts/autopilot.py status             # print the current standings
    python scripts/autopilot.py inject 50000 --reason "XYZ IPO"   # manual top-up into all three books
    python scripts/autopilot.py autodeposit off    # toggle the ₹50k monthly auto-top-up

This is the product's own code — it imports the validated advisor (``advise_deploy_into_weakness``)
**directly** (no cross-repo fetch), reuses the product's price panels, and writes a committable track
record. **Rule (a) intact:** it drives the advisor, never the backtest engine; the AI only nudges
Book B's deploy size via a fixed rule; the validated headline is provably unchanged. **Fake money,
no real orders — ever.**
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import CostConfig, TaxConfig
from qalpha.data.ingest import load_parquet
from qalpha.data.prices import PriceData
from qalpha.live.autopilot import (
    BOOK_NAMES,
    Book,
    Decision,
    ai_hit_rate,
    basket_value,
    book_deploy_amount,
    inject_all,
    load_books,
    load_ledger,
    load_state,
    log_manual_injection,
    parse_ai_signal,
    pct_return,
    resolve_decision,
    save_books,
    save_ledger,
    save_state,
    scheduled_injection,
    signal_tilt,
)
from qalpha.live.dashboard import watchlist_is_stale
from qalpha.live.deploy import advise_deploy_into_weakness, market_weakness

sys.path.insert(0, str(Path(__file__).parent))
from paper import BENCHMARK_PARQUET, _load_benchmark_series, _refresh_benchmark

FORWARD_START = (
    "2026-07-06"  # fixed study start (first trading session on/after this seeds the books)
)
RESOLVE_CALENDAR_DAYS = 28  # ≈20 trading days — the window each decision is scored over vs Nifty
NIFBEES = "NIFTYBEES.NS"

WATCHLIST_CSV = Path("data/universes/nifty100_watchlist.csv")
WATCHLIST_PARQUET = Path("data/historical/prices_watchlist.parquet")
BRIEF_MD = Path("reports/ai_brief.md")
TRACK_CSV = Path("data/autopilot/track.csv")
DASHBOARD_MD = Path("reports/autopilot_dashboard.md")


# ---- watchlist + prices (reuse the product's panels — no yfinance-from-scratch) -------------------


def _load_watchlist() -> tuple[list[str], dict[str, str]]:
    df = pd.read_csv(WATCHLIST_CSV)
    tickers = [str(t) for t in df["ticker"].tolist()]
    sector_of = {str(r.ticker): str(r.sector) for r in df.itertuples(index=False)}
    return tickers, sector_of


def _ensure_panels() -> None:
    """Make sure the watchlist panel + NIFTYBEES benchmark are present and reasonably fresh. The paper
    cron refreshes the benchmark; the watchlist panel is refreshed here (via the build script) when
    absent or stale, so the auto-pilot never deploys on week-old prices."""
    stale = not WATCHLIST_PARQUET.exists() or watchlist_is_stale(
        load_parquet(str(WATCHLIST_PARQUET)).dates[-1].date(), date.today()
    )
    if stale:
        subprocess.run(
            [sys.executable, "scripts/build_nifty100_watchlist.py", "--prices"], check=False
        )
    if not BENCHMARK_PARQUET.exists():
        _refresh_benchmark()


def _load_prices() -> tuple[PriceData, pd.Series]:
    """The Nifty-100 watchlist panel with NIFTYBEES merged in (the deploy universe + the index/Book-C
    price in one ``PriceData``), plus the NIFTYBEES series (the study's Nifty benchmark)."""
    panel = load_parquet(str(WATCHLIST_PARQUET))
    nifbees = _load_benchmark_series()
    nb = nifbees.reindex(panel.adj_close.index).ffill()
    adj = panel.adj_close.copy()
    close_raw = panel.close_raw.copy()
    vol = panel.volume.copy()
    adj[NIFBEES] = nb
    close_raw[NIFBEES] = nb
    vol[NIFBEES] = 0.0
    prices = PriceData(adj_close=adj, close_raw=close_raw, volume=vol)
    return prices, prices.adj_close[NIFBEES].dropna()


def _price_on(series: pd.Series, as_of: str) -> Decimal | None:
    sub = series.loc[: pd.Timestamp(as_of)].dropna()
    return Decimal(str(float(sub.iloc[-1]))) if not sub.empty else None


def _last_prices(prices: PriceData, tickers: list[str], as_of: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for t in set(tickers) | {NIFBEES}:
        if t in prices.adj_close.columns:
            p = _price_on(prices.adj_close[t], as_of)
            if p is not None:
                out[t] = p
    return out


# ---- deploy via the validated advisor ------------------------------------------------------------


def _portfolio_reflecting(book: Book, last_prices: dict[str, Decimal], as_of: date) -> Portfolio:
    """A qalpha ``Portfolio`` mirroring the book's holdings so the advisor fills genuine underweights."""
    held_value = basket_value(book.holdings, last_prices)
    p = Portfolio(CostConfig(), TaxConfig(), cash=held_value + Decimal("1"))
    for t, q in sorted(book.holdings.items()):
        px = last_prices.get(t)
        if px is not None and q > 0:
            p.buy(as_of, t, Decimal(q), px)
    return p


def _deploy(
    book: Book,
    amount: Decimal,
    watchlist: list[str],
    sector_of: dict[str, str],
    prices: PriceData,
    nifbees: pd.Series,
    as_of: date,
) -> tuple[dict[str, int], str]:
    """Run the advisor for ``amount`` and *execute* the recommended buys on ``book``; return
    ``(basket, rationale)`` — the shares actually bought and a one-line model rationale."""
    if amount <= 0:
        return {}, "no deploy (calm / no idle wallet tranche due)"
    port = _portfolio_reflecting(book, _last_prices(prices, watchlist, as_of.isoformat()), as_of)
    advice = advise_deploy_into_weakness(
        port, amount, watchlist, sector_of, prices, nifbees, as_of, max_names=15
    )
    basket: dict[str, int] = {}
    spent = Decimal("0")
    for order in advice.deploy.buy_orders:
        qty = int(order.quantity)
        price = Decimal(str(order.price))
        if qty > 0 and price * qty <= book.cash:
            book.buy(order.ticker, qty, price)
            basket[order.ticker] = basket.get(order.ticker, 0) + qty
            spent += price * qty
    top = ", ".join(f"{t} (−{p * 100:.0f}%)" for t, p in advice.cheapest[:3])
    return basket, f"weakness={advice.weakness.level}; deployed ₹{spent:.0f} into: {top}"


def _buy_and_hold(book: Book, price: Decimal) -> None:
    """Book C: sink all idle cash into NIFTYBEES immediately (the dumb baseline)."""
    qty = int(book.cash / price)
    if qty > 0:
        book.buy(NIFBEES, qty, price)


# ---- decision resolution -------------------------------------------------------------------------


def _resolve_due(ledger: list[Decision], prices: PriceData, nifbees: pd.Series, as_of: str) -> int:
    resolved = 0
    for i, d in enumerate(ledger):
        if d.resolved or d.resolve_on > as_of:
            continue
        exit_val = basket_value(d.basket, _last_prices(prices, list(d.basket), as_of))
        basket_ret = pct_return(Decimal(d.amount), exit_val)
        entry_idx, exit_idx = _price_on(nifbees, d.as_of), _price_on(nifbees, as_of)
        bench_ret = (
            pct_return(entry_idx, exit_idx)
            if entry_idx is not None and exit_idx is not None
            else 0.0
        )
        ledger[i] = resolve_decision(d, basket_ret, bench_ret)
        resolved += 1
    return resolved


# ---- standings + dashboard -----------------------------------------------------------------------


def _standings(
    books: dict[str, Book], last_prices: dict[str, Decimal]
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for n in BOOK_NAMES:
        b = books[n]
        out[n] = {
            "value": float(b.value(last_prices)),
            "contributed": float(b.net_contributions),
            "profit": float(b.profit(last_prices)),
            "return_pct": b.return_pct(last_prices),
        }
    return out


def _append_track(as_of: str, standings: dict[str, dict[str, float]]) -> None:
    row: dict[str, object] = {"date": as_of}
    for n in BOOK_NAMES:
        row[f"{n}_value"] = round(standings[n]["value"], 2)
        row[f"{n}_profit"] = round(standings[n]["profit"], 2)
        row[f"{n}_return_pct"] = round(standings[n]["return_pct"], 3)
    if TRACK_CSV.exists():
        df = pd.read_csv(TRACK_CSV)
        df = df[df["date"] != as_of]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    TRACK_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values("date").reset_index(drop=True).to_csv(TRACK_CSV, index=False)


def _render_dashboard(
    as_of: str, standings: dict[str, dict[str, float]], ledger: list[Decision], level: str, sig: str
) -> str:
    worked, total = ai_hit_rate(ledger)
    n_days = len(pd.read_csv(TRACK_CSV)) if TRACK_CSV.exists() else 0
    labels = {
        "A": "Strategy only (deploy into weakness)",
        "B": "Strategy + AI nudge",
        "C": "Buy-and-hold NIFTYBEES",
    }
    lines = [
        "# Auto-pilot — did the system make money, and did the AI help?",
        "",
        f"_As of **{as_of}** · {n_days} marks · market weakness: **{level}** · "
        "**fake money, no real orders**._",
        "",
        "| Book | What it does | Value | Contributed | Profit | Return |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for n in BOOK_NAMES:
        s = standings[n]
        lines.append(
            f"| **{n}** | {labels[n]} | ₹{s['value']:,.0f} | ₹{s['contributed']:,.0f} | "
            f"₹{s['profit']:,.0f} | {s['return_pct']:+.2f}% |"
        )
    a_vs_c = standings["A"]["profit"] - standings["C"]["profit"]
    b_vs_a = standings["B"]["profit"] - standings["A"]["profit"]
    lines += [
        "",
        f"- **A − C** (does the strategy beat buy-and-hold?): **₹{a_vs_c:,.0f}**",
        f"- **B − A** (does the AI insight add value?): **₹{b_vs_a:,.0f}**",
        f"- **AI decision hit-rate** (Book-B deploys that beat Nifty): **{worked}/{total}**",
        f"- Today's AI signal: {sig}",
        "",
        "> **Low power early — this is not a verdict.** The claims need ≥3 months and a real "
        "volatility event before they mean anything; until then these are just the accruing numbers.",
        "",
        "## Recent resolved decisions",
        "",
        "| Date | Book | Basket return | Nifty | Verdict | AI insight |",
        "|---|---|---:|---:|---|---|",
    ]
    for d in [d for d in ledger if d.resolved][-10:][::-1]:
        lines.append(
            f"| {d.as_of} | {d.book} | {d.outcome_return_pct:+.1f}% | "
            f"{d.benchmark_return_pct:+.1f}% | {d.verdict} | {d.ai_insight} |"
        )
    return "\n".join(lines) + "\n"


# ---- commands ------------------------------------------------------------------------------------


def cmd_daily() -> int:
    _ensure_panels()
    watchlist, sector_of = _load_watchlist()
    prices, nifbees = _load_prices()
    if nifbees.empty:
        print("[autopilot] no NIFTYBEES prices — nothing to mark.")
        return 0
    as_of_str = str(prices.dates[-1].date())
    if as_of_str < FORWARD_START:
        print(f"[autopilot] latest session {as_of_str} precedes the study start — waiting.")
        return 0
    as_of = date.fromisoformat(as_of_str)

    books, ledger, state = load_books(), load_ledger(), load_state()

    if (
        state.get("last_marked") == as_of_str
    ):  # idempotent: a same-day re-run must not double-deploy
        print(f"[autopilot] already marked {as_of_str} — skipping.")
        return 0

    # Scheduled top-up — the ₹1L seed always; the ₹50k monthly only if the toggle is on.
    seeded_before = bool(state.get("seeded"))
    last_month = state.get("last_deposit_month")
    amount, new_month = scheduled_injection(
        as_of_str,
        seeded=seeded_before,
        last_deposit_month=str(last_month) if last_month else None,
    )
    if seeded_before and not state.get("monthly_autodeposit", True):
        amount = Decimal("0")  # monthly auto-top-up off → skip it (manual Add-money still works)
    if amount > 0:
        inject_all(books, amount)
        print(f"[autopilot] scheduled top-up ₹{amount:,.0f} into all three books.")
    state["seeded"] = True
    state["last_deposit_month"] = new_month
    state["last_marked"] = as_of_str

    level = market_weakness(nifbees, as_of).level
    signal = (
        parse_ai_signal(BRIEF_MD.read_text(encoding="utf-8"), as_of_str)
        if BRIEF_MD.exists()
        else None
    )
    tilt = signal_tilt(signal)
    sig_desc = (
        f"lean={signal.lean} confidence={signal.confidence} (tilt {tilt:.2f}×)"
        if signal is not None
        else "none (neutral 1.00× tilt)"
    )
    resolve_on = (as_of + timedelta(days=RESOLVE_CALENDAR_DAYS)).isoformat()

    amt_a = book_deploy_amount(books["A"].cash, level, None, ai=False)
    basket_a, rat_a = _deploy(books["A"], amt_a, watchlist, sector_of, prices, nifbees, as_of)
    if basket_a:
        ledger.append(
            Decision(as_of_str, "A", str(amt_a), basket_a, rat_a, "n/a (no AI)", resolve_on)
        )
    amt_b = book_deploy_amount(books["B"].cash, level, signal, ai=True)
    basket_b, rat_b = _deploy(books["B"], amt_b, watchlist, sector_of, prices, nifbees, as_of)
    if basket_b:
        ledger.append(Decision(as_of_str, "B", str(amt_b), basket_b, rat_b, sig_desc, resolve_on))
    nif_px = _price_on(nifbees, as_of_str)
    if nif_px is not None:
        _buy_and_hold(books["C"], nif_px)

    n_resolved = _resolve_due(ledger, prices, nifbees, as_of_str)
    if n_resolved:
        print(f"[autopilot] resolved {n_resolved} decision(s).")

    last_prices = _last_prices(prices, watchlist, as_of_str)
    standings = _standings(books, last_prices)
    _append_track(as_of_str, standings)
    DASHBOARD_MD.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_MD.write_text(
        _render_dashboard(as_of_str, standings, ledger, level, sig_desc), encoding="utf-8"
    )
    save_books(books)
    save_ledger(ledger)
    save_state(state)
    print(
        f"[autopilot] marked {as_of_str}: "
        + " · ".join(
            f"{n} ₹{standings[n]['value']:,.0f} ({standings[n]['return_pct']:+.2f}%)"
            for n in BOOK_NAMES
        )
    )
    return 0


def cmd_status() -> int:
    if not TRACK_CSV.exists():
        print("[autopilot] no track record yet — run `daily` first.")
        return 0
    print(pd.read_csv(TRACK_CSV).tail(10).to_string(index=False))
    return 0


def cmd_inject(amount: Decimal, reason: str) -> int:
    """A manual top-up — deposits the SAME amount into all three books (so it can't bias the relative
    A/B/C verdict) and logs the reason. Deployed on the next `daily` run."""
    books = load_books()
    inject_all(books, amount)
    save_books(books)
    log_manual_injection(amount, reason)
    print(f"[autopilot] manually injected ₹{amount:,.0f} into all three books — reason: {reason}")
    return 0


def cmd_autodeposit(on: bool) -> int:
    state = load_state()
    state["monthly_autodeposit"] = on
    save_state(state)
    print(f"[autopilot] monthly ₹50k auto-top-up is now {'ON' if on else 'OFF'}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("daily", help="scheduled top-up + deploy the three books + resolve + write")
    sub.add_parser("status", help="print the recent track record")
    p_inj = sub.add_parser("inject", help="manual top-up into all three books")
    p_inj.add_argument("amount", type=Decimal)
    p_inj.add_argument(
        "--reason", default="(unspecified)", help="why (an IPO, a tip, a news catalyst)"
    )
    p_auto = sub.add_parser("autodeposit", help="toggle the ₹50k monthly auto-top-up")
    p_auto.add_argument("state", choices=["on", "off"])
    args = parser.parse_args(argv)

    if args.cmd == "daily":
        return cmd_daily()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "inject":
        return cmd_inject(args.amount, args.reason)
    if args.cmd == "autodeposit":
        return cmd_autodeposit(args.state == "on")
    return 1


if __name__ == "__main__":
    sys.exit(main())
