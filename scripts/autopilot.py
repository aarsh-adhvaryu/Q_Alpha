"""autopilot.py — the daily runner for the SYSTEM BOOK: the whole system acting on its own advice.

ONE fake-money book runs everything the system can do, every day, against the real world (not a
calendar): it receives cash (monthly top-up + the dashboard's Add-money), **deploys idle cash into
out-of-favour names exactly as the Add-money advisor suggests** (AI-paced sizing via the fixed
``signal_tilt``), **rebalances only when the §4.6 tax-benefit gate says it's worth the tax**
(evaluated every run — self-timed, never forced), and carries the tax-free hedge readout in stress.
Its track record IS the advice's track record — the closed loop that earns trust.

Two comparators with **identical cash flows**, so the comparison is fair:
- **Shadow** — the same system with the AI tilt OFF → System − Shadow = what the AI added.
- **Baseline** — every rupee straight into NIFTYBEES → System − Baseline = what the system added
  over doing nothing.

    python scripts/autopilot.py daily              # the cron entry point
    python scripts/autopilot.py status             # recent track record
    python scripts/autopilot.py inject 50000 --reason "XYZ IPO"   # manual top-up (all three, equally)
    python scripts/autopilot.py autodeposit off    # toggle the ₹50k monthly top-up

**Fake money, never a real order.** Rule (a) intact: the validated engine computes every number; the
AI only paces deploy size. The clean ₹2L GO book (``data/paper/book.json``) is untouched — it remains
the criterion-6 evidence. The earlier A/B/C wallet books are FROZEN (superseded by System-vs-Shadow,
which answers the same "does the AI help?" question inside the full system).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.backtest.portfolio import TradeRecord
from qalpha.config import Config
from qalpha.data.ingest import load_parquet
from qalpha.data.prices import PriceData
from qalpha.live.autopilot import (
    Book,
    Decision,
    ai_hit_rate,
    basket_value,
    book_deploy_amount,
    clear_pending,
    load_ledger,
    load_pending,
    load_state,
    log_manual_injection,
    parse_ai_signal,
    pct_return,
    resolve_decision,
    save_ledger,
    save_state,
    signal_tilt,
)
from qalpha.live.dashboard import watchlist_is_stale
from qalpha.live.deploy import advise_deploy_into_weakness, market_weakness
from qalpha.live.hedge import apply_futures_hedge, hedge_active, stress_gauge
from qalpha.live.paper import PaperBook, StrategyParams

sys.path.insert(0, str(Path(__file__).parent))
from paper import (
    BENCHMARK_PARQUET,
    BOOK_PATH,
    _load_benchmark_series,
    _load_market,
    _refresh_benchmark,
)

FORWARD_START = "2026-07-06"  # the system book's fixed start (continuity with the adaptive book)
RESOLVE_CALENDAR_DAYS = 28  # ≈20 trading days — each deploy is scored vs Nifty over this window
NIFBEES = "NIFTYBEES.NS"

WATCHLIST_CSV = Path("data/universes/nifty100_watchlist.csv")
WATCHLIST_PARQUET = Path("data/historical/prices_watchlist.parquet")
BRIEF_MD = Path("reports/ai_brief.md")
DASHBOARD_MD = Path("reports/autopilot_dashboard.md")

# The System book = the former smart-rebalance book, upgraded (same file → its ₹2L history carries
# over). ADAPTIVE cadence: the funnel is evaluated every run; the §4.6 gate decides if a trade is
# worth the tax. NEVER the validated GO book (data/paper/book.json).
SYSTEM_BOOK_PATH = Path("data/paper/adaptive_book.json")
SHADOW_BOOK_PATH = Path("data/paper/shadow_book.json")  # cloned from the system book on first run
BASELINE_PATH = Path("data/autopilot/baseline_book.json")  # NIFTYBEES buy-and-hold, same cash flows
FLOWS_PATH = Path(
    "data/autopilot/system_flows.json"
)  # wallet→book transfers (for flow-adjusted math)
SYSTEM_TRACK_CSV = Path("data/autopilot/system_track.csv")

SYSTEM_CAPITAL = Decimal("200000")  # the core each book started with
MONTHLY_DEPOSIT = Decimal("50000")
DEPLOY_FLOOR = Decimal("5000")  # don't bother deploying dust (mirrors the idle-cash floor)

HEDGE_TAU = 0.7  # operate at τ≥0.7 (robustness battery: τ=0.6 hedges too eagerly)
HEDGE_PERSIST = 5
HEDGE_RATIO = 0.5


# ---- data (product panels; the system book needs core + watchlist merged) -------------------------


def _load_watchlist() -> tuple[list[str], dict[str, str]]:
    df = pd.read_csv(WATCHLIST_CSV)
    tickers = [str(t) for t in df["ticker"].tolist()]
    sector_of = {str(r.ticker): str(r.sector) for r in df.itertuples(index=False)}
    return tickers, sector_of


def _ensure_panels() -> None:
    """Watchlist panel + NIFTYBEES benchmark present and fresh (the core panel is the paper cron's)."""
    stale = not WATCHLIST_PARQUET.exists() or watchlist_is_stale(
        load_parquet(str(WATCHLIST_PARQUET)).dates[-1].date(), date.today()
    )
    if stale:
        subprocess.run(
            [sys.executable, "scripts/build_nifty100_watchlist.py", "--prices"], check=False
        )
    if not BENCHMARK_PARQUET.exists():
        _refresh_benchmark()


def _load_wl_prices() -> tuple[PriceData, pd.Series]:
    """The Nifty-100 watchlist panel with NIFTYBEES merged in, + the NIFTYBEES series (the benchmark)."""
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


def _merge_panels(core: PriceData, wl: PriceData) -> PriceData:
    """One panel = the core (Nifty-50 PIT, feeds the funnel) ∪ the watchlist (prices the deployed
    names). **Everything is ffilled** (causal — carries only past values forward): if one panel has a
    session the other lacks (e.g. the core panel a day behind the watchlist), a holding must never
    silently lose its mark and vanish from the valuation — that would crater the book's equity on
    paper. Live-layer valuation only — the backtest engine never sees this."""
    idx = core.adj_close.index.union(wl.adj_close.index)
    extra = [c for c in wl.adj_close.columns if c not in core.adj_close.columns]
    adj = core.adj_close.reindex(idx).ffill()
    adj[extra] = wl.adj_close[extra].reindex(idx).ffill()
    raw = core.close_raw.reindex(idx).ffill()
    raw[extra] = wl.close_raw[extra].reindex(idx).ffill()
    vol = core.volume.reindex(idx).ffill()
    vol[extra] = wl.volume[extra].reindex(idx).fillna(0.0)
    return PriceData(adj_close=adj, close_raw=raw, volume=vol)


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


# ---- persisted trio state --------------------------------------------------------------------------


def _load_system_books(cfg: Config) -> tuple[PaperBook, PaperBook]:
    """The system book (init if absent) and its no-AI shadow (cloned from the system on first run so
    both start identical; they diverge only through the AI tilt from then on)."""
    if not SYSTEM_BOOK_PATH.exists():
        PaperBook.init(
            SYSTEM_BOOK_PATH,
            cfg,
            starting_capital=SYSTEM_CAPITAL,
            start_date=date.fromisoformat(FORWARD_START),
            params=StrategyParams(tax_aware=True, force_refresh=False, rebalance_freq="ADAPTIVE"),
        )
    if not SHADOW_BOOK_PATH.exists():
        SHADOW_BOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHADOW_BOOK_PATH.write_text(SYSTEM_BOOK_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return PaperBook.load(SYSTEM_BOOK_PATH, cfg), PaperBook.load(SHADOW_BOOK_PATH, cfg)


def _load_baseline() -> Book:
    if BASELINE_PATH.exists():
        return Book.from_dict(json.loads(BASELINE_PATH.read_text(encoding="utf-8")))
    return Book(name="BASE")


def _save_baseline(b: Book) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(b.to_dict(), indent=2) + "\n", encoding="utf-8")


def _load_flows() -> dict[str, dict[str, str]]:
    if FLOWS_PATH.exists():
        data: dict[str, dict[str, str]] = json.loads(FLOWS_PATH.read_text(encoding="utf-8"))
        return data
    return {"system": {}, "shadow": {}}


def _save_flows(flows: dict[str, dict[str, str]]) -> None:
    FLOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLOWS_PATH.write_text(json.dumps(flows, indent=2) + "\n", encoding="utf-8")


def _wallets(state: dict[str, object]) -> dict[str, Decimal]:
    raw = state.get("wallets")
    if isinstance(raw, dict):
        return {k: Decimal(str(v)) for k, v in raw.items()}
    return {"system": Decimal("0"), "shadow": Decimal("0")}


def _contributed(state: dict[str, object]) -> dict[str, Decimal]:
    raw = state.get("contributed")
    if isinstance(raw, dict):
        return {k: Decimal(str(v)) for k, v in raw.items()}
    return {"system": SYSTEM_CAPITAL, "shadow": SYSTEM_CAPITAL}


def _persist_trio_state(
    state: dict[str, object], wallets: dict[str, Decimal], contributed: dict[str, Decimal]
) -> None:
    state["wallets"] = {k: str(v) for k, v in wallets.items()}
    state["contributed"] = {k: str(v) for k, v in contributed.items()}


def _inject_trio(
    amount: Decimal,
    wallets: dict[str, Decimal],
    contributed: dict[str, Decimal],
    baseline: Book,
) -> None:
    """Deposit the SAME fake cash into all three (system/shadow wallets + baseline) so no top-up can
    ever bias the relative verdict."""
    wallets["system"] += amount
    wallets["shadow"] += amount
    contributed["system"] += amount
    contributed["shadow"] += amount
    baseline.inject(amount)


# ---- acting on the system's own advice --------------------------------------------------------------


def _record_dict(r: TradeRecord) -> dict[str, str]:
    return {
        "date": r.date.isoformat(),
        "ticker": r.ticker,
        "side": r.side.name,
        "quantity": str(r.quantity),
        "price": str(r.price),
        "cost": str(r.cost),
        "tax": str(r.tax),
    }


def _deploy_from_wallet(
    bk: PaperBook,
    amount: Decimal,
    watchlist: list[str],
    wl_sectors: dict[str, str],
    merged: PriceData,
    nifbees: pd.Series,
    as_of: date,
) -> tuple[dict[str, int], str]:
    """Move ``amount`` from the wallet into the book and execute the Add-money advisor's buy list on
    it — the system acting on its own advice. Whole shares; ``Portfolio.buy`` is cash-capped, so an
    unaffordable order simply shrinks/skips. Leftover stays as book cash (the §4.6 gate's §2.9
    idle-cash routing consolidates it at the next worthwhile rebalance)."""
    bk.portfolio.cash += amount
    advice = advise_deploy_into_weakness(
        bk.portfolio, amount, watchlist, wl_sectors, merged, nifbees, as_of, max_names=15
    )
    basket: dict[str, int] = {}
    records: list[TradeRecord] = []
    for order in advice.deploy.buy_orders:
        qty = Decimal(int(order.quantity))
        if qty <= 0:
            continue
        rec = bk.portfolio.buy(as_of, order.ticker, qty, Decimal(str(order.price)))
        if rec is not None:
            records.append(rec)
            basket[rec.ticker] = basket.get(rec.ticker, 0) + int(rec.quantity)
    top = ", ".join(f"{t} (−{p * 100:.0f}%)" for t, p in advice.cheapest[:3])
    rationale = f"weakness={advice.weakness.level}; deploy ₹{amount:,.0f} into: {top}"
    bk.history.append(
        {
            "as_of": as_of.isoformat(),
            "reason": f"deploy: {rationale}",
            "orders": [_record_dict(r) for r in records],
        }
    )
    return basket, rationale


def _buy_and_hold(book: Book, price: Decimal) -> None:
    qty = int(book.cash / price)
    if qty > 0:
        book.buy(NIFBEES, qty, price)


# ---- outcome resolution -----------------------------------------------------------------------------


def _resolve_due(ledger: list[Decision], merged: PriceData, nifbees: pd.Series, as_of: str) -> int:
    resolved = 0
    for i, d in enumerate(ledger):
        if d.resolved or d.resolve_on > as_of:
            continue
        exit_val = basket_value(d.basket, _last_prices(merged, list(d.basket), as_of))
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


# ---- downside protection: the tax-free hedge overlay (flow-adjusted) --------------------------------


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(((peak - equity) / peak).max() or 0.0)


def _run_hedge_overlay(
    nifbees: pd.Series, flows: dict[str, str], book_path: Path = SYSTEM_BOOK_PATH
) -> dict[str, float] | None:
    """Overlay the validated tax-free short-futures hedge on a book's committed equity curve —
    **measured only, the book itself is untouched** (run on the System book AND, read-only, on the
    validated ₹2L GO book so the protection evidence accrues on both without contaminating the GO
    gate). Returns are **flow-adjusted** — a wallet→book deploy is a transfer, not a gain, so it's
    stripped before the daily return is computed. Stateless; fake money; never a real F&O trade."""
    try:
        if not book_path.exists():
            return None
        curve = json.loads(book_path.read_text(encoding="utf-8")).get("equity_curve", [])
        if len(curve) < 3:
            return None
        eq = pd.Series({p["date"]: float(p["equity"]) for p in curve}).sort_index()
        eq.index = pd.to_datetime(eq.index)
        flow = pd.Series({pd.Timestamp(d): float(a) for d, a in flows.items()}, dtype=float)
        flow = flow.reindex(eq.index).fillna(0.0)
        book_ret = ((eq - flow) / eq.shift(1) - 1.0).dropna()
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
        return {
            "hedged_return": (float(res.equity.iloc[-1]) - 1.0) * 100,
            "unhedged_return": (float(unhedged.iloc[-1]) - 1.0) * 100,
            "hedged_dd": _max_drawdown(res.equity) * 100,
            "unhedged_dd": _max_drawdown(unhedged) * 100,
            "hedge_on": bool(active.reindex(book_ret.index).fillna(False).iloc[-1]),
            "episodes": res.episodes,
        }
    except Exception as exc:  # fail-soft — the readout must never break the run
        print(f"[system] hedge overlay skipped (non-fatal): {exc}")
        return None


# ---- track + report ---------------------------------------------------------------------------------


def _append_system_track(row: dict[str, object]) -> None:
    if SYSTEM_TRACK_CSV.exists():
        df = pd.read_csv(SYSTEM_TRACK_CSV)
        df = df[df["date"] != row["date"]]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    SYSTEM_TRACK_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values("date").reset_index(drop=True).to_csv(SYSTEM_TRACK_CSV, index=False)


def _render_report(
    as_of: str,
    rows: dict[str, dict[str, float]],
    ledger: list[Decision],
    level: str,
    sig: str,
    today_notes: list[str],
    hedge: dict[str, float] | None,
    core_hedge: dict[str, float] | None = None,
) -> str:
    n_days = len(pd.read_csv(SYSTEM_TRACK_CSV)) if SYSTEM_TRACK_CSV.exists() else 0
    worked, total = ai_hit_rate(ledger, book="SYS")
    labels = {
        "system": "🧠 **System** — deploys on its own advice (AI-paced) + tax-gated rebalance",
        "shadow": "System, AI off (the attribution twin)",
        "baseline": "Everything into NIFTYBEES (do-nothing baseline)",
    }
    lines = [
        "# The System book — the whole system acting on its own advice",
        "",
        f"_As of **{as_of}** · {n_days} marks · market weakness: **{level}** · AI: {sig} · "
        "**fake money, no real orders**._",
        "",
        "| Book | What it is | Value | Contributed | Profit | Return |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for key in ("system", "shadow", "baseline"):
        s = rows[key]
        lines.append(
            f"| **{key}** | {labels[key]} | ₹{s['value']:,.0f} | ₹{s['contributed']:,.0f} | "
            f"₹{s['profit']:,.0f} | {s['return_pct']:+.2f}% |"
        )
    sys_vs_base = rows["system"]["profit"] - rows["baseline"]["profit"]
    sys_vs_shd = rows["system"]["profit"] - rows["shadow"]["profit"]
    lines += [
        "",
        f"- **System − Baseline** (does the whole system beat doing nothing?): **₹{sys_vs_base:,.0f}**",
        f"- **System − Shadow** (does the AI add value?): **₹{sys_vs_shd:,.0f}**",
        f"- **AI deploy hit-rate** (system deploys that beat Nifty over ~20d): **{worked}/{total}**",
        "",
        "## Today's decisions",
        "",
    ]
    lines += [f"- {n}" for n in (today_notes or ["- held — no action worth its cost today."])]
    if hedge is not None:
        hstate = "🛡️ HEDGE ON" if hedge["hedge_on"] else "hedge off (calm)"
        lines += [
            "",
            "## 🛡 Downside protection — the tax-free hedge overlay",
            "",
            f"- **System book:** return **{float(hedge['hedged_return']):+.2f}%** hedged vs "
            f"**{float(hedge['unhedged_return']):+.2f}%** unhedged · worst drawdown "
            f"**−{float(hedge['hedged_dd']):.1f}%** vs **−{float(hedge['unhedged_dd']):.1f}%** · "
            f"episodes **{int(hedge['episodes'])}** · now: {hstate}",
        ]
        if core_hedge is not None:
            lines += [
                f"- **Validated ₹2L core (measured only — the GO book itself is untouched):** return "
                f"**{float(core_hedge['hedged_return']):+.2f}%** hedged vs "
                f"**{float(core_hedge['unhedged_return']):+.2f}%** unhedged · worst drawdown "
                f"**−{float(core_hedge['hedged_dd']):.1f}%** vs "
                f"**−{float(core_hedge['unhedged_dd']):.1f}%**",
            ]
        lines += [
            "",
            "> Keep the shares (₹0 capital-gains tax), short Nifty futures while systemic stress is "
            "elevated. The gauge is **coincident** — in calm the hedge is off and curves match; its "
            "value shows only in a real stress event. (Selling defensively was tested and LOST to "
            "tax.) The GO-book line is a read-only measurement so the protection evidence accrues on "
            "the validated core too, without touching the criterion-6 gate.",
        ]
    lines += [
        "",
        "## Recent resolved deploys",
        "",
        "| Date | Book | Basket return | Nifty | Verdict | AI at the time |",
        "|---|---|---:|---:|---|---|",
    ]
    for d in [d for d in ledger if d.resolved][-10:][::-1]:
        lines.append(
            f"| {d.as_of} | {d.book} | {d.outcome_return_pct:+.1f}% | "
            f"{d.benchmark_return_pct:+.1f}% | {d.verdict} | {d.ai_insight} |"
        )
    lines += [
        "",
        "> **Low power early — not a verdict.** Needs months + a real volatility event. The baseline "
        "seeded at its own first run (a few sessions after the system's 2026-07-06 start) — flows are "
        "identical from then on. The earlier A/B/C wallet books are frozen (superseded by "
        "System-vs-Shadow inside the full system).",
    ]
    return "\n".join(lines) + "\n"


# ---- commands ---------------------------------------------------------------------------------------


def cmd_daily() -> int:
    _ensure_panels()
    watchlist, wl_sectors = _load_watchlist()
    wl_prices, nifbees = _load_wl_prices()
    if nifbees.empty:
        print("[system] no NIFTYBEES prices — nothing to mark.")
        return 0
    as_of_str = str(wl_prices.dates[-1].date())
    if as_of_str < FORWARD_START:
        print(f"[system] latest session {as_of_str} precedes the start — waiting.")
        return 0
    as_of = date.fromisoformat(as_of_str)

    cfg = Config()
    core_prices, universe, core_sectors = _load_market()
    merged = _merge_panels(core_prices, wl_prices)
    state, ledger, flows = load_state(), load_ledger(), _load_flows()
    baseline = _load_baseline()
    system, shadow = _load_system_books(cfg)
    wallets, contributed = _wallets(state), _contributed(state)

    # Baseline seeds its ₹2L at its first run (start-offset caveat is disclosed in the report).
    if not state.get("baseline_seeded"):
        baseline.inject(SYSTEM_CAPITAL)
        state["baseline_seeded"] = True

    # Add-money queued from the dashboard — ALWAYS applied (even on an already-marked day) so a
    # top-up is never lost; it deploys on the next session.
    pending_total = Decimal("0")
    for item in load_pending():
        amt = Decimal(str(item.get("amount", "0")))
        if amt > 0:
            _inject_trio(amt, wallets, contributed, baseline)
            log_manual_injection(amt, str(item.get("reason", "(from dashboard)")))
            pending_total += amt
    if pending_total > 0:
        clear_pending()
        print(f"[system] applied ₹{pending_total:,.0f} of queued Add-money to all three books.")

    if state.get("system_last_marked") == as_of_str:  # idempotent per session
        _persist_trio_state(state, wallets, contributed)
        _save_baseline(baseline)
        save_state(state)
        print(f"[system] already marked {as_of_str} — deposits saved, deploy skipped.")
        return 0

    # Monthly top-up (first observed session of a new month; the ₹2L core counts as the start month).
    month = as_of_str[:7]
    last_month = state.get("trio_last_deposit_month")
    if last_month is None:
        state["trio_last_deposit_month"] = month
    elif month != last_month:
        if state.get("monthly_autodeposit", True):
            _inject_trio(MONTHLY_DEPOSIT, wallets, contributed, baseline)
            print(f"[system] monthly top-up ₹{MONTHLY_DEPOSIT:,.0f} to all three books.")
        state["trio_last_deposit_month"] = month

    # Market + AI context.
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
        else "none (neutral 1.00×)"
    )
    resolve_on = (as_of + timedelta(days=RESOLVE_CALENDAR_DAYS)).isoformat()
    today_notes: list[str] = []

    # 1) Deploy idle wallet cash — the system acting on its own Add-money advice (AI-paced for the
    #    system, neutral for the shadow).
    for key, bk, use_ai in (("system", system, True), ("shadow", shadow, False)):
        amt = book_deploy_amount(wallets[key], level, signal, ai=use_ai)
        if amt < DEPLOY_FLOOR:
            continue
        wallets[key] -= amt
        flows.setdefault(key, {})
        flows[key][as_of_str] = str(Decimal(flows[key].get(as_of_str, "0")) + amt)
        basket, rationale = _deploy_from_wallet(
            bk, amt, watchlist, wl_sectors, merged, nifbees, as_of
        )
        if basket:
            book_tag = "SYS" if key == "system" else "SHD"
            ai_note = sig_desc if use_ai else "n/a (AI off)"
            ledger.append(
                Decision(as_of_str, book_tag, str(amt), basket, rationale, ai_note, resolve_on)
            )
            today_notes.append(f"**{key}** deployed ₹{amt:,.0f} — {rationale}")

    # 2) Adaptive rebalance — evaluated EVERY run; the §4.6 tax-benefit gate decides. Real-world
    #    responsive, never calendar-forced. May consolidate earlier opportunistic buys into the core
    #    target when (and only when) that's worth the tax.
    for key, bk in (("system", system), ("shadow", shadow)):
        plan = bk.plan(merged, universe, core_sectors, as_of)
        if plan.decision.actionable:
            bk.apply(merged, plan)
            today_notes.append(f"**{key}** 🔁 rebalanced — {plan.decision.reason}")
        elif key == "system":
            today_notes.append(f"gate: {plan.decision.reason}")

    # 3) Baseline: every idle rupee straight into NIFTYBEES.
    nif_px = _price_on(nifbees, as_of_str)
    if nif_px is not None:
        _buy_and_hold(baseline, nif_px)

    # 4) Mark, resolve, hedge, report, persist.
    system.mark(merged, as_of)
    shadow.mark(merged, as_of)
    n_res = _resolve_due(ledger, merged, nifbees, as_of_str)
    if n_res:
        print(f"[system] resolved {n_res} deploy decision(s).")
    hedge = _run_hedge_overlay(nifbees, flows.get("system", {}))
    # The same protection, MEASURED on the validated ₹2L GO book's committed curve (read-only — the
    # GO book itself is untouched, so the criterion-6 gate stays clean and its clock never restarts).
    core_hedge = _run_hedge_overlay(nifbees, {}, book_path=BOOK_PATH)

    rows: dict[str, dict[str, float]] = {}
    for key, bk in (("system", system), ("shadow", shadow)):
        value = float(bk.equity(merged, as_of)) + float(wallets[key])
        contrib = float(contributed[key])
        rows[key] = {
            "value": value,
            "contributed": contrib,
            "profit": value - contrib,
            "return_pct": (value - contrib) / contrib * 100.0,
        }
    base_prices = {NIFBEES: nif_px} if nif_px is not None else {}
    rows["baseline"] = {
        "value": float(baseline.value(base_prices)),
        "contributed": float(baseline.net_contributions),
        "profit": float(baseline.profit(base_prices)),
        "return_pct": baseline.return_pct(base_prices),
    }
    _append_system_track(
        {
            "date": as_of_str,
            **{
                f"{k}_{f}": round(rows[k][f], 3 if f == "return_pct" else 2)
                for k in ("system", "shadow", "baseline")
                for f in ("value", "profit", "return_pct")
            },
            "hedge_on": bool(hedge["hedge_on"]) if hedge else False,
        }
    )
    DASHBOARD_MD.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_MD.write_text(
        _render_report(as_of_str, rows, ledger, level, sig_desc, today_notes, hedge, core_hedge),
        encoding="utf-8",
    )

    state["system_last_marked"] = as_of_str
    _persist_trio_state(state, wallets, contributed)
    _save_baseline(baseline)
    _save_flows(flows)
    save_ledger(ledger)
    save_state(state)
    print(
        f"[system] marked {as_of_str}: "
        + " · ".join(f"{k} ₹{rows[k]['value']:,.0f} ({rows[k]['return_pct']:+.2f}%)" for k in rows)
    )
    return 0


def cmd_status() -> int:
    if not SYSTEM_TRACK_CSV.exists():
        print("[system] no track record yet — run `daily` first.")
        return 0
    print(pd.read_csv(SYSTEM_TRACK_CSV).tail(10).to_string(index=False))
    return 0


def cmd_inject(amount: Decimal, reason: str) -> int:
    state = load_state()
    baseline = _load_baseline()
    wallets, contributed = _wallets(state), _contributed(state)
    _inject_trio(amount, wallets, contributed, baseline)
    log_manual_injection(amount, reason)
    _persist_trio_state(state, wallets, contributed)
    _save_baseline(baseline)
    save_state(state)
    print(f"[system] injected ₹{amount:,.0f} into all three books — reason: {reason}")
    return 0


def cmd_autodeposit(on: bool) -> int:
    state = load_state()
    state["monthly_autodeposit"] = on
    save_state(state)
    print(f"[system] monthly ₹50k auto-top-up is now {'ON' if on else 'OFF'}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "daily", help="the cron entry point: fund + deploy + gate-rebalance + mark + report"
    )
    sub.add_parser("status", help="print the recent track record")
    p_inj = sub.add_parser("inject", help="manual top-up into all three books")
    p_inj.add_argument("amount", type=Decimal)
    p_inj.add_argument("--reason", default="(unspecified)")
    p_auto = sub.add_parser("autodeposit", help="toggle the ₹50k monthly top-up")
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
