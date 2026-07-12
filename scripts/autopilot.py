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
from qalpha.config import Config, CostConfig, TaxConfig
from qalpha.data.ingest import load_parquet
from qalpha.data.prices import PriceData
from qalpha.live.autopilot import (
    BOOK_NAMES,
    Book,
    Decision,
    ai_hit_rate,
    apply_pending,
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
from qalpha.live.hedge import apply_futures_hedge, hedge_active, stress_gauge
from qalpha.live.paper import PaperBook, StrategyParams

sys.path.insert(0, str(Path(__file__).parent))
from paper import BENCHMARK_PARQUET, _load_benchmark_series, _load_market, _refresh_benchmark

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
# The "smart-rebalance" experiment book: the validated core strategy, but self-timed — it evaluates
# every run and rebalances ONLY when the §4.6 tax-benefit gate clears (not annual, not forced-frequent).
# A separate ₹2L notional book; NEVER the validated ₹2L GO book (data/paper/book.json), so the headline
# is untouched. Fake money.
ADAPTIVE_BOOK_PATH = Path("data/paper/adaptive_book.json")
ADAPTIVE_TRACK_CSV = Path("data/autopilot/adaptive_track.csv")
ADAPTIVE_CAPITAL = Decimal("200000")


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
    as_of: str,
    standings: dict[str, dict[str, float]],
    ledger: list[Decision],
    level: str,
    sig: str,
    adaptive: dict[str, object] | None = None,
    hedge: dict[str, object] | None = None,
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
    ]
    if adaptive is not None:
        state = "🔁 REBALANCED today" if adaptive["rebalanced"] else "— holding (gate not cleared)"
        lines += [
            "",
            "## 🔁 Smart-rebalance engine (self-timed core strategy, ₹2L fake)",
            "",
            "Runs the validated core strategy but **evaluates every day and trades only when the §4.6 "
            "tax-benefit gate clears** — self-timed, not annual, not forced-frequent. Tests whether the "
            "rebalance engine makes money without churning to tax.",
            "",
            f"- Value **₹{float(adaptive['value']):,.0f}** · return **{float(adaptive['return_pct']):+.2f}%** "
            f"vs Nifty **{float(adaptive['bench_pct']):+.2f}%** · rebalances so far: "
            f"**{int(adaptive['rebalances'])}** · today: {state}",
        ]
    if hedge is not None:
        hstate = "🛡️ HEDGE ON" if hedge["hedge_on"] else "— hedge off (calm)"
        lines += [
            "",
            "## 🛡 Downside protection — the tax-free hedge (on the smart-rebalance book)",
            "",
            "The validated way to **minimise loss in a crash without selling**: keep every share, "
            "overlay a short index-futures hedge while systemic stress is elevated (₹0 capital-gains "
            "tax; F&O cost + 30% tax modelled). **Fake money — never a real F&O trade.**",
            "",
            f"- Return **{float(hedge['hedged_return']):+.2f}%** hedged vs "
            f"**{float(hedge['unhedged_return']):+.2f}%** unhedged · worst drawdown "
            f"**−{float(hedge['hedged_dd']):.1f}%** hedged vs **−{float(hedge['unhedged_dd']):.1f}%** "
            f"unhedged · episodes: **{int(hedge['episodes'])}** · now: {hstate}",
            "",
            "> The gauge is **coincident** (fires *with* a drawdown, can't forecast) — so in a calm "
            "window the hedge stays off and the two curves are identical. Its value shows up only in a "
            "real stress event; that's exactly what it waits for.",
        ]
    lines += [
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


# ---- the smart-rebalance experiment book (self-timed core strategy) -------------------------------


def _run_adaptive_book(as_of: date, nifbees: pd.Series) -> dict[str, object] | None:
    """Mark the self-timed core-strategy book: evaluate the funnel EVERY run, but rebalance only when
    the §4.6 tax-benefit gate clears (so it trades rarely, on its own timing). A separate ₹2L notional
    book — never the validated GO book. Fail-soft: returns ``None`` if the strategy panel isn't loadable
    so the auto-pilot's A/B/C books still run."""
    try:
        cfg = Config()
        if not ADAPTIVE_BOOK_PATH.exists():
            PaperBook.init(
                ADAPTIVE_BOOK_PATH,
                cfg,
                starting_capital=ADAPTIVE_CAPITAL,
                start_date=date.fromisoformat(FORWARD_START),
                params=StrategyParams(
                    tax_aware=True, force_refresh=False, rebalance_freq="ADAPTIVE"
                ),
            )
        book = PaperBook.load(ADAPTIVE_BOOK_PATH, cfg)
        prices, universe, sector_of = _load_market()
        plan = book.plan(prices, universe, sector_of, as_of)
        rebalanced = bool(plan.decision.actionable)
        if rebalanced:
            book.apply(prices, plan)
        book.mark(prices, as_of)  # record equity every run (persists)
        value = float(book.equity(prices, as_of))
        ret = book.total_return_pct(prices, as_of)
        start_idx = _price_on(nifbees, book.start_date.isoformat())
        now_idx = _price_on(nifbees, as_of.isoformat())
        bench = pct_return(start_idx, now_idx) if start_idx and now_idx else 0.0
        row = {
            "date": as_of.isoformat(),
            "value": round(value, 2),
            "return_pct": round(ret, 3),
            "bench_pct": round(bench, 3),
            "rebalances": len(book.history),
        }
        if ADAPTIVE_TRACK_CSV.exists():
            df = pd.read_csv(ADAPTIVE_TRACK_CSV)
            df = df[df["date"] != row["date"]]
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        ADAPTIVE_TRACK_CSV.parent.mkdir(parents=True, exist_ok=True)
        df.sort_values("date").reset_index(drop=True).to_csv(ADAPTIVE_TRACK_CSV, index=False)
        if rebalanced:
            print(f"[autopilot] smart-rebalance book REBALANCED ({plan.decision.reason}).")
        return {
            "value": value,
            "return_pct": ret,
            "bench_pct": bench,
            "rebalanced": rebalanced,
            "rebalances": len(book.history),
            "reason": plan.decision.reason,
        }
    except Exception as exc:  # fail-soft — a missing strategy panel must not break the A/B/C books
        print(f"[autopilot] smart-rebalance book skipped (non-fatal): {exc}")
        return None


# ---- downside protection: the tax-free hedge overlay (promoted from research) --------------------

HEDGE_TAU = 0.7  # operate at τ≥0.7 (the robustness battery: τ=0.6 hedges too eagerly)
HEDGE_PERSIST = 5
HEDGE_RATIO = 0.5


def _max_drawdown(equity: pd.Series) -> float:
    """Worst peak-to-trough fall of an equity curve, as a positive fraction."""
    peak = equity.cummax()
    return float(((peak - equity) / peak).max() or 0.0)


def _run_hedge_overlay(nifbees: pd.Series) -> dict[str, object] | None:
    """Overlay the validated tax-free short-futures hedge on the smart-rebalance book's curve — the
    'minimise loss in a crash without selling' layer. Stateless (recomputed from the curve each run);
    fake money, never a real F&O trade. ``None`` if the book has too little history yet."""
    try:
        import json

        if not ADAPTIVE_BOOK_PATH.exists():
            return None
        curve = json.loads(ADAPTIVE_BOOK_PATH.read_text(encoding="utf-8")).get("equity_curve", [])
        if len(curve) < 3:
            return None  # need a few marks before a hedge overlay means anything
        s = pd.Series({p["date"]: float(p["equity"]) for p in curve}).sort_index()
        s.index = pd.to_datetime(s.index)
        book_ret = s.pct_change().dropna()
        if book_ret.empty:
            return None
        gauge = stress_gauge(nifbees)
        active = hedge_active(gauge, tau=HEDGE_TAU, persist=HEDGE_PERSIST)
        index_ret = nifbees.pct_change()
        res = apply_futures_hedge(
            book_ret,
            index_ret.reindex(book_ret.index).fillna(0.0),
            active.reindex(book_ret.index).fillna(False),
            h=HEDGE_RATIO,
        )
        unhedged = (1 + book_ret).cumprod()
        hedge_on_now = bool(active.reindex(book_ret.index).fillna(False).iloc[-1])
        return {
            "hedged_return": (float(res.equity.iloc[-1]) - 1.0) * 100,
            "unhedged_return": (float(unhedged.iloc[-1]) - 1.0) * 100,
            "hedged_dd": _max_drawdown(res.equity) * 100,
            "unhedged_dd": _max_drawdown(unhedged) * 100,
            "hedge_on": hedge_on_now,
            "episodes": res.episodes,
        }
    except Exception as exc:  # fail-soft — the hedge readout must never break the run
        print(f"[autopilot] hedge overlay skipped (non-fatal): {exc}")
        return None


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

    # Apply any deposits the dashboard's Add-money button queued to the repo (always — even on an
    # already-marked day — so a top-up is never lost; it just deploys on the next run).
    pending_total = apply_pending(books)
    if pending_total > 0:
        print(
            f"[autopilot] applied ₹{pending_total:,.0f} of queued Add-money into all three books."
        )

    # Market context — needed both to display the books and to size the A/B/C deploy.
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

    # The smart-rebalance experiment book — its OWN idempotency, so it seeds / catches up independently
    # of the A/B/C deploy (which is guarded separately below). Lets it start on the next run even when
    # the A/B/C books were already marked this session.
    adaptive: dict[str, object] | None = None
    if state.get("adaptive_last_marked") != as_of_str:
        adaptive = _run_adaptive_book(as_of, nifbees)
        if adaptive is not None:
            state["adaptive_last_marked"] = as_of_str

    hedge = _run_hedge_overlay(
        nifbees
    )  # downside protection on the smart-rebalance book (stateless)

    # A/B/C deploy — guarded so a same-day re-run never double-deploys the wallet books.
    already_marked = state.get("last_marked") == as_of_str
    if already_marked:
        print(
            f"[autopilot] A/B/C already marked {as_of_str} — deploy skipped (adaptive/pending refreshed)."
        )
    else:
        seeded_before = bool(state.get("seeded"))
        last_month = state.get("last_deposit_month")
        amount, new_month = scheduled_injection(
            as_of_str,
            seeded=seeded_before,
            last_deposit_month=str(last_month) if last_month else None,
        )
        if seeded_before and not state.get("monthly_autodeposit", True):
            amount = Decimal(
                "0"
            )  # monthly auto-top-up off → skip it (manual Add-money still works)
        if amount > 0:
            inject_all(books, amount)
            print(f"[autopilot] scheduled top-up ₹{amount:,.0f} into all three books.")
        state["seeded"] = True
        state["last_deposit_month"] = new_month
        state["last_marked"] = as_of_str

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
            ledger.append(
                Decision(as_of_str, "B", str(amt_b), basket_b, rat_b, sig_desc, resolve_on)
            )
        nif_px = _price_on(nifbees, as_of_str)
        if nif_px is not None:
            _buy_and_hold(books["C"], nif_px)
        n_resolved = _resolve_due(ledger, prices, nifbees, as_of_str)
        if n_resolved:
            print(f"[autopilot] resolved {n_resolved} decision(s).")

    # Always render + persist — so a queued Add-money or a fresh adaptive-book mark shows even on a
    # day the A/B/C books were already marked.
    last_prices = _last_prices(prices, watchlist, as_of_str)
    standings = _standings(books, last_prices)
    if not already_marked:
        _append_track(as_of_str, standings)
    DASHBOARD_MD.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_MD.write_text(
        _render_dashboard(as_of_str, standings, ledger, level, sig_desc, adaptive, hedge),
        encoding="utf-8",
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
