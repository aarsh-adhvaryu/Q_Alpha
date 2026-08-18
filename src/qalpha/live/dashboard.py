"""Render the paper-book dashboard — the human/consumer-facing view of what the system is doing.

Produces a committable Markdown report (renders on GitHub) + a CSV of the equity track record, so
anyone can see — without running anything — today's recommendation, current holdings, the equity
curve vs Nifty 50 TRI, realized tax, and any orders awaiting human approval. This is the answer to
"how does a consumer know what it's doing": the system writes its own status, no AI in the loop.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd

from qalpha.accounting.capital_gains import twelve_months_after
from qalpha.accounting.tax_lots import FIFOLedger
from qalpha.data.prices import PriceData
from qalpha.live.go_scorecard import build_scorecard
from qalpha.live.paper import DailyPlan, PaperBook, _prices_on
from qalpha.live.runlog import RunLogEntry, health_markdown

if TYPE_CHECKING:
    from qalpha.live.deploy import WeaknessDeployAdvice


@dataclass(frozen=True)
class PaperFreshness:
    """Is the daily paper-run pipeline actually alive? (So the dashboard shows it, not assumes it.)"""

    last_update: date | None
    weekdays_stale: int  # full weekdays elapsed since the last mark (0 = up to date)
    is_stale: bool
    note: str


def _weekdays_after(a: date, b: date) -> int:
    """Count weekdays strictly after ``a`` up to and including ``b`` (0 if b <= a)."""
    n, d = 0, a + timedelta(days=1)
    while d <= b:
        if d.weekday() < 5:  # Mon-Fri
            n += 1
        d += timedelta(days=1)
    return n


def paper_freshness(book: PaperBook, today: date) -> PaperFreshness:
    """Freshness of the committed paper book vs the weekday cron meant to update it.

    The pipeline runs weekdays, so one elapsed weekday (today's mark may not have run yet) is OK;
    **two or more** means it missed a day → stale. Surfaced in the dashboard so the daily run is
    *seen* working, not trusted blindly.
    """
    curve = book.equity_curve
    if not curve:
        return PaperFreshness(None, 0, True, "No marks yet — the daily pipeline hasn't run.")
    last = date.fromisoformat(str(curve[-1]["date"]))
    stale_days = max(0, _weekdays_after(last, today) - 1)  # 1 weekday grace (today not yet marked)
    is_stale = stale_days >= 1
    if is_stale:
        note = f"⚠️ Stale — last marked {last}, {stale_days} weekday(s) missed. Check the cron."
    else:
        note = f"✓ Up to date — last marked {last}."
    return PaperFreshness(last, stale_days, is_stale, note)


def watchlist_is_stale(last_date: date, today: date, *, max_weekdays: int = 3) -> bool:
    """Is the cached Nifty-100 watchlist price panel too old to trust for a live buy brief?

    The panel is downloaded once and persists on disk, so without a staleness check the live deploy
    advisor could size buys off week-old prices. Weekday-aware (a Friday panel read on Monday is one
    weekday stale, not three), with one weekday of grace like :func:`paper_freshness`.
    """
    return _weekdays_after(last_date, today) - 1 >= max_weekdays


#: Is the deterministic buy list allowed on the **real-money** surface?
#:
#: ``True`` again since PR-3 (PLAN_TRUST_REPAIR.md). It was switched off on 2026-08-17 because two
#: defects made :func:`qalpha.live.deploy.advise_deploy_into_weakness` untrustworthy for a live
#: account; PR-2 closed the first (corporate actions read as discounts) and PR-3 the second (the
#: advisor never consulted the breakdown detector it ships with). The flag stays as the kill-switch:
#: flip it to ``False`` and every buy surface withholds itself again, with no other change.
#:
#: Scope: the **buy** side only. Sell and Raise-cash never consult it — they run on the validated
#: FIFO/tax engine, which none of this touches.
BUY_ADVICE_ON_REAL_MONEY = True


def buy_advice_withheld_markdown() -> str:
    """The notice shown when the buy list is switched off at the flag.

    Kept from PR-1 as a working kill-switch. Deliberately does *not* re-state the two original
    defects: both are fixed, and a notice that lies about why it is showing would be its own trust
    failure. Whoever flips the flag says why in the plan.
    """
    return (
        "🚧 **Buy suggestions are switched off.**\n\n"
        "The deterministic buy list has been withheld from this surface deliberately — see "
        "`PLAN_TRUST_REPAIR.md` for the current reason. Selection code is unchanged and nothing has "
        "been deleted; flipping `BUY_ADVICE_ON_REAL_MONEY` restores every buy surface.\n\n"
        "**Still live and unaffected:** *Sell a holding* and *Raise cash* — both run on the "
        "validated FIFO/cost/tax engine."
    )


def buy_advice_blocked_markdown(reasons: list[str]) -> str:
    """The notice shown when the buy list is *allowed* but its inputs failed a safety check.

    Distinct from the kill-switch above: here the rule is trusted and the **data** is not — a stale
    or failed-to-download watchlist panel (PR-2 / T1.3). Sell and Raise cash are priced off the core
    panel and stay available, which is why this never blocks the whole advisor.
    """
    lines = [
        "⚠️ **Buy suggestions withheld — the prices behind them are not trustworthy right now.**",
        "",
    ]
    lines += [f"- {r}" for r in reasons]
    lines += [
        "",
        "Sizing a buy list off a panel that failed to refresh is exactly the silent-wrong-number "
        "failure these guards exist to prevent, so it is withheld rather than shown with a caveat. "
        "*Sell a holding* and *Raise cash* are priced off a different panel and are unaffected.",
    ]
    return "\n".join(lines)


def buy_advice_scope_note() -> str:
    """The permanent framing that rides *with* the buy list — what this screen is, and is not.

    The buy rule has never been backtested. It shares no selection code and no names with the funnel
    the 18.2% headline describes, and no script has ever measured it against a baseline. That is not
    a reason to hide it — it is a reason to say so every single time it renders.
    """
    return (
        "**What this is:** a deterministic **technical screen** — names furthest below their own "
        "1-year high, spread across sectors, bought with whole shares at **₹0 capital-gains tax**. "
        "Prices are checked for continuity first, and each name carries this system's own "
        "breakdown verdict.\n\n"
        "**What this is not:** the validated strategy. This screen has **never been backtested** — "
        "it shares no selection code and no names with the factor funnel behind the 18.2% headline, "
        "and it has never been measured against a baseline. It is a starting point for your own "
        "judgement, not a result. Every order is still placed by you."
    )


def ai_signal_summary(
    lean: str | None, confidence: str | None, tilt: float, *, consumed_by: str
) -> str:
    """What the AI brief actually *did* — the machine-readable line and the one number it produced.

    T2.5: the brief asks for per-name analysis and costs ~57.6k input tokens a day, but its machine
    contract is a single ``SIGNAL:`` line with **no ticker field**, so the only thing any code can
    consume is a lean and a confidence, collapsed into one multiplier on deploy *size*. Rendering
    several paragraphs of per-name narrative directly under an unrelated buy list invited exactly the
    reading the user made — that the AI had picked those stocks. It hadn't; it cannot.

    So the summary leads with the part with consequences, and the prose moves behind it.
    """
    if lean is None:
        return (
            "**No AI signal today** — the deploy size runs at its neutral ×1.00. "
            "A missing brief changes nothing about which names are chosen."
        )
    effect = (
        "no change to deploy size"
        if abs(tilt - 1.0) < 1e-9
        else f"deploy size ×{tilt:.2f} ({'larger' if tilt > 1 else 'smaller'} tranche)"
    )
    return (
        f"**SIGNAL: lean={lean} · confidence={confidence}** → **{effect}**, in {consumed_by}.\n\n"
        "That single line is the *entire* machine-readable output. It carries **no ticker field**, "
        "so the AI cannot and does not choose a stock — it only nudges *how much* of the available "
        "cash is deployed now versus held back. Every name comes from the deterministic screen."
    )


def live_pm_brief_markdown(
    available_cash: Decimal, advice: WeaknessDeployAdvice, *, floor: Decimal
) -> str:
    """One-line "PM brief" for the Live tab — idle cash → concrete buy plan (Ops Layer PR-2).

    Pure/Streamlit-free so it is unit-testable. Renders the auto deploy-into-weakness suggestion as a
    compact single line ("💰 Idle cash ₹12,430 → market 🟢 normal: buy 2×ITC, 1×NTPC … ₹0 tax, buys
    only · leftover ₹514"). Below ``floor`` it returns ``""`` so the dashboard suppresses the nudge on
    trivial balances rather than pestering the user.
    """
    if available_cash < floor:
        return ""
    icon = {"normal": "🟢", "elevated": "🟠", "deep": "🔴"}.get(advice.weakness.level, "🟢")
    counts: Counter[str] = Counter()
    for o in advice.deploy.buy_orders:
        counts[o.ticker.removesuffix(".NS")] += int(o.quantity)
    action = (
        "buy " + ", ".join(f"{q}×{t}" for t, q in counts.most_common())
        if counts
        else "nothing fits cleanly right now"
    )
    off = advice.off_watchlist
    off_note = ""
    if off:
        total = sum((v for _, v in off if v is not None), Decimal("0"))
        off_note = f" · ₹{total:,.0f} in {len(off)} off-watchlist name{'s' if len(off) != 1 else ''} excluded"
    return (
        f"💰 **Idle cash ₹{available_cash:,.0f}** → market {icon} {advice.weakness.level}: "
        f"{action} (₹0 capital-gains tax, buys only) · leftover ₹{advice.deploy.leftover_cash:,.0f}"
        f"{off_note}"
    )


def systemic_risk_markdown(index_close: pd.Series, as_of: date) -> str:
    """Read-only 'systemic risk' watch panel — informational only, the system takes no action.

    Reports the product-side :func:`~qalpha.live.deploy.market_weakness` reading (Nifty drawdown from
    its rolling 1-year high) as a normal/elevated/deep risk gauge, and — when elevated — notes that
    the research-validated **tax-free short-futures hedge overlay** would suggest *considering* a
    hedge. This is the lightweight product signal; the richer cross-asset fragility gauge lives in
    the research repo. Nothing here trades, sells, or hedges — it is a dashboard advisory, like the
    paper book is a notional record.
    """
    from qalpha.live.deploy import market_weakness  # local import: avoids a package import cycle

    w = market_weakness(index_close, as_of)
    badge = {"normal": "🟢 NORMAL", "elevated": "🟠 ELEVATED", "deep": "🔴 DEEP STRESS"}[w.level]
    lines = [
        "## 🛡 Systemic-risk watch (read-only)",
        "",
        f"**{badge}** — Nifty is **{w.drawdown * 100:+.1f}%** from its 1-year high (as of {as_of}).",
        "",
    ]
    if w.level == "normal":
        lines.append(
            "- No elevated systemic stress on this signal. No hedge indicated. Keep investing "
            "steadily; route fresh capital tax-free as usual."
        )
    else:
        lines.append(
            "- **Stress elevated.** The research-validated tax-free **short index-futures hedge** "
            "(keep the shares, nullify the exposure — proven to cut COVID drawdown −25→−10% on the "
            "book) would suggest *considering* a hedge here."
        )
        lines.append(
            "- This is **informational only** — the product places no derivatives trade. Executing a "
            "futures hedge is a separate, manually-operated decision (F&O account + real-cost review)."
        )
    lines += [
        "",
        "_Lightweight product signal (index drawdown). The richer cross-asset fragility gauge "
        "(vol·credit·FX·correlation) lives in the research repo. This panel never trades._",
    ]
    return "\n".join(lines)


def _benchmark_return_pct(benchmark: pd.Series, start: date, as_of: date) -> float | None:
    idx = pd.DatetimeIndex(benchmark.index)
    window = benchmark[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(as_of))]
    if len(window) < 2:
        return None
    first, last = float(window.iloc[0]), float(window.iloc[-1])
    return (last - first) / first * 100.0 if first > 0 else None


def _sparkline(values: list[float]) -> str:
    if len(values) < 2:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    span = hi - lo or 1.0
    return "".join(blocks[min(7, int((v - lo) / span * 7))] for v in values)


def today_brief_markdown(
    as_of: date,
    *,
    core_action: str,
    market_level: str,
    market_drawdown: float,
    market_note: str,
    hedge_note: str,
    health_note: str,
    go_verdict: str | None = None,
    deploy_candidates: list[tuple[str, float]] | None = None,
) -> str:
    """The one-screen "what do I do today" brief — assembles the engines into a single ordered list.

    Pure formatter (no data access, no trading) so it unit-tests cleanly: the dashboard computes the
    pieces (core decision, market weakness, hedge signal, position health, GO verdict) and hands them
    here. Mirrors a desk's morning note: hold/act on the core, where to put new money, whether to
    hedge, which holdings to watch.
    """
    level_badge = {"normal": "🟢", "elevated": "🟠", "deep": "🔴"}.get(market_level, "🟢")
    lines = [
        f"## 📋 Today — what to do  ·  {as_of}",
        "",
        f"**Core** — {core_action}",
    ]
    if go_verdict:
        lines.append(f"**Readiness** — real-money GO verdict: **{go_verdict}**.")
    lines.append("")
    lines.append(
        f"**💰 New money** — market {level_badge} **{market_level}** "
        f"({market_drawdown * 100:+.1f}% from 1y high). {market_note}"
    )
    if deploy_candidates:
        names = " · ".join(f"{t} ({p * 100:.0f}% off high)" for t, p in deploy_candidates)
        lines.append(f"  - Most out-of-favour now: {names}")
    lines.append("  - Open **Add money** for the exact, diversified, ₹0-tax buy list.")
    lines += [
        "",
        f"**🛡 Hedge** — {hedge_note}",
        "",
        f"**🩺 Holdings** — {health_note}",
        "",
        "_Read the sentiment, then execute what's above — the system advises, you place the order._",
    ]
    return "\n".join(lines)


# --- Plain-English clarity layer (Ops Layer follow-up) -------------------------------------------
# Pure helpers that translate the dashboard's numbers/jargon into everyday language + a good/bad read,
# so a non-quant can tell at a glance how things are going and whether anything needs doing.

_GO_PLAIN = {
    "GO": "✅ **Cleared** — the evidence says the strategy is ready for real money.",
    "READY": "✅ **Ready, bar a shock** — every test it can pass is green; the only thing left is to "
    "live through a real market drop (that can't be scheduled).",
    "NO-GO": "🔴 **Not safe** — the strategy is misbehaving vs how it was validated. Do NOT go live.",
    "NOT YET": "⏳ **Still proving itself** — gathering evidence; this is the normal, expected state "
    "until the track record is long enough and it has survived a volatility event.",
}
_MARKET_PLAIN = {
    "normal": "🟢 calm — near its highs; add steadily / dollar-cost average",
    "elevated": "🟠 pulled back a bit — a better-than-usual time to add new money",
    "deep": "🔴 down a lot — historically one of the *better* times to add (tax-free buys)",
}


def performance_read(book_return_pct: float, benchmark_return_pct: float | None) -> str:
    """One plain sentence on whether the book is beating the market (the whole goal, after tax)."""
    if benchmark_return_pct is None:
        return f"Your book is **{book_return_pct:+.1f}%** since it started."
    gap = book_return_pct - benchmark_return_pct
    if gap >= 0.5:
        verdict = f"🟢 **Ahead of the market** by {gap:.1f} points"
    elif gap <= -0.5:
        verdict = f"🔴 **Behind the market** by {-gap:.1f} points"
    else:
        verdict = "🟢 **Roughly tracking the market**"
    return (
        f"{verdict} — **{book_return_pct:+.1f}%** vs Nifty's **{benchmark_return_pct:+.1f}%** since "
        "the book started. (Beating the index *after tax* is the whole point.)"
    )


def plain_summary_markdown(
    *,
    book_return_pct: float,
    benchmark_return_pct: float | None,
    market_level: str,
    go_verdict: str,
    action_needed: bool,
) -> str:
    """The one-screen 'in plain English' summary — how you're doing, the market, readiness, to-dos."""
    todo = (
        "⚠️ **Yes** — there's a suggested action below. (You always place the order yourself.)"
        if action_needed
        else "**No** — nothing needs your attention right now. Investing here is mostly waiting."
    )
    return "\n".join(
        [
            "### 🧭 In plain English",
            "",
            f"- **How you're doing:** {performance_read(book_return_pct, benchmark_return_pct)}",
            f"- **The market today:** {_MARKET_PLAIN.get(market_level, market_level)}.",
            f"- **Ready for real money?** {_GO_PLAIN.get(go_verdict, go_verdict)}",
            f"- **Anything to do?** {todo}",
        ]
    )


def glossary_markdown() -> str:
    """Every term on the dashboard, defined in plain words — the 'look anything up' panel."""
    return "\n".join(
        [
            "**The terms on this page, in plain words:**",
            "",
            "- **Nifty 50 TRI** — the index *including dividends*; the fair yardstick. Beating it "
            "**after tax** is the goal.",
            "- **Drawdown** — how far you are below your highest-ever point (−10% = 10% below the "
            "peak). Everyone has them; what matters is whether yours are worse than the market's.",
            "- **Sharpe** — return per unit of bumpiness. Higher = a smoother ride for the same gain "
            "(~1.0+ is good).",
            "- **GO / READY / NOT YET / NO-GO** — the real-money verdict. NOT YET = still proving "
            "itself (normal). READY = done bar a market shock. GO = cleared. NO-GO = misbehaving, "
            "stay out.",
            "- **Systemic risk / hedge** — how stressed the *whole* market is. When high, the "
            "research suggests *considering* a tax-free futures hedge — informational, it never "
            "trades.",
            "- **Market weakness (normal / elevated / deep)** — how far the index is below its "
            "1-year high. Deeper = historically a better time to put in **new** money.",
            "- **Rebalance** — periodically resetting the portfolio to its target weights. This "
            "system does it *rarely* (about yearly) on purpose — trading less means less tax.",
            "- **Realized tax** — capital-gains tax actually triggered by sells so far. The engine "
            "keeps this low; buying new names is ₹0 tax.",
            "- **Position health / idiosyncratic** — is *one* holding breaking down on its own (not "
            "just a market-wide dip)? It flags it to watch; it never auto-sells.",
            "- **Satellite sleeve** — a small pocket (≤8%) for discretionary/judgement picks, kept "
            "separate from the validated core.",
        ]
    )


def go_readiness_markdown(book: PaperBook, benchmark: pd.Series, as_of: date) -> str:
    """The deterministic GO scorecard for the forward paper run, as dashboard markdown.

    A real multi-criterion verdict (not a countdown): it flips to GO the moment the evidence clears —
    earlier than the 6-month target if it does, NO-GO if the strategy misbehaves live. See
    :mod:`qalpha.live.go_scorecard`.
    """
    return build_scorecard(book.equity_curve, benchmark, as_of).render()


def ltcg_safe_sell_note(ledger: FIFOLedger, ticker: str, as_of: date) -> str:
    """Per-holding "safe minimal holding period" cell for the tax-smart holdings table.

    The single biggest tax lever the strategy leans on is the §111A→§112A crossover: a lot held
    **past the long-term threshold** (default 365 days) is taxed at 12.5% (LTCG) instead of 20%
    (STCG). This returns a compact cell saying when the *whole* open position in ``ticker`` becomes
    long-term — the safe-sell date, taken from the **newest** open lot (hold until then and any sale
    of the line is fully LTCG). Selling earlier is always allowed; it just taxes the still-short-term
    portion at 20%.

    * ``🟢 now (12.5%)`` — every open lot is already long-term; sell anytime at the low rate.
    * ``⏳ Nd · DD Mon YY`` — hold N more days (to that date) before the line is fully LTCG-safe.
    * ``—`` — nothing held / undated lots.
    """
    lots = ledger.open_lots(ticker)
    if not lots:
        return "—"
    newest = max(lot.acquisition_date for lot in lots)
    # §2(42A) needs *more than* 12 calendar months, so the first safe date is the day AFTER the
    # anniversary. `ltcg_holding_days` (365) is the engine's approximation and is a day early —
    # quoting it here would tell the user to sell while the line is still taxed at 20%.
    lt_date = twelve_months_after(newest) + timedelta(days=1)
    days = (lt_date - as_of).days
    if days <= 0:
        return "🟢 now (12.5%)"
    return f"⏳ {days}d · {lt_date:%d %b %y}"


# ---- the operating checklist: what the user should do next, from real state ----------------------


@dataclass(frozen=True)
class ChecklistItem:
    """One step of the live operating procedure, resolved against the account's actual state."""

    label: str
    state: str  # "done" | "todo" | "blocked" | "waiting"
    detail: str

    @property
    def icon(self) -> str:
        return {"done": "✅", "todo": "👉", "blocked": "🛑", "waiting": "⏳"}[self.state]


def next_actions(
    *,
    advice_safe: bool,
    tradebook_trades: int,
    reconciles: bool,
    idle_cash: Decimal,
    cash_floor: Decimal,
    holdings: int,
    days_to_next_ltcg: int | None,
    unreconciled_sells: int,
    buy_advice_available: bool = True,
) -> list[ChecklistItem]:
    """The operating procedure as state, not prose — so the app can say what to do next.

    Ordered by dependency: a blocked step above makes the ones below it moot. Each item is derived
    from something the app already knows, never from a stored "user said done" flag — the checklist
    can therefore never drift out of sync with the account.
    """
    items: list[ChecklistItem] = []

    items.append(
        ChecklistItem(
            "Inputs trustworthy",
            "done" if advice_safe else "blocked",
            "Prices fresh, every holding quoted, broker session live."
            if advice_safe
            else "Advice is withheld — fix the banner above before acting on any number here.",
        )
    )

    if tradebook_trades == 0:
        items.append(
            ChecklistItem(
                "Upload your tradebook",
                "todo",
                "Console → Reports → Tradebook → Equity → download CSV → upload above. "
                "Without it, holding periods are unknown and tax is assumed short-term.",
            )
        )
    elif not reconciles:
        items.append(
            ChecklistItem(
                "Reconcile the tradebook",
                "blocked",
                f"{tradebook_trades} trades loaded but the rebuilt holdings do not match your "
                "broker. Off-market credits (IPO allotments, transfers) are the usual cause — "
                "every tax figure is an estimate until this matches.",
            )
        )
    else:
        items.append(
            ChecklistItem(
                "Tradebook reconciled",
                "done",
                f"{tradebook_trades} trades replayed; rebuilt holdings match your broker exactly. "
                "Stack each new export after you trade.",
            )
        )

    if idle_cash >= cash_floor and not buy_advice_available:
        # Don't route the user to a tab that is withheld — a checklist that points at advice the app
        # is refusing to give is exactly the incoherence PR-1 exists to remove.
        items.append(
            ChecklistItem(
                "Idle cash — buy plan withheld",
                "blocked",
                f"₹{idle_cash:,.0f} sitting idle, but the buy list is withheld pending two "
                "defect fixes (see **Add money** for what they are). Holding cash is the safe "
                "action until it returns; selling and raising cash are unaffected.",
            )
        )
    elif idle_cash >= cash_floor:
        items.append(
            ChecklistItem(
                "Deploy idle cash",
                "todo",
                f"₹{idle_cash:,.0f} sitting idle. Use **Add money** below for the ₹0-tax buy plan, "
                "then place the orders yourself in Kite.",
            )
        )
    else:
        items.append(
            ChecklistItem(
                "No idle cash to deploy",
                "done",
                f"₹{idle_cash:,.0f} is below the ₹{cash_floor:,.0f} floor — nothing to route.",
            )
        )

    if holdings == 0:
        items.append(ChecklistItem("Hold and wait", "waiting", "No positions yet."))
    elif days_to_next_ltcg is None:
        items.append(
            ChecklistItem(
                "Hold — every line is long-term",
                "done",
                "All holdings qualify for the 12.5% rate. Selling is still a choice, not a plan: "
                "low turnover is the validated edge.",
            )
        )
    else:
        items.append(
            ChecklistItem(
                "Hold — don't sell yet",
                "waiting",
                f"{days_to_next_ltcg} days until your next line turns long-term. Selling before "
                "then is taxed at 20% instead of 12.5%.",
            )
        )

    if unreconciled_sells > 0:
        items.append(
            ChecklistItem(
                "Reconcile your realized tax",
                "todo",
                f"You have {unreconciled_sells} sell(s) on record. Console → Reports → Tax P&L → "
                "download the .xlsx and upload it above to confirm our figure matches Zerodha's "
                "to the paise.",
            )
        )

    return items


def checklist_markdown(items: list[ChecklistItem]) -> str:
    """Render the checklist as compact Markdown (one line per step)."""
    return "\n".join(f"{i.icon} **{i.label}** — {i.detail}" for i in items)


# Tax branches that our FIFO engine implements and unit-tests, but which have never been confirmed
# against a real Zerodha Tax P&L (the only reconciled sell to date was single-lot, all-STCG, no loss).
def unverified_tax_branches(
    *,
    has_loss_lot: bool,
    has_ltcg: bool,
    distinct_cost_bases: int,
    uses_exemption: bool,
) -> list[str]:
    """Which never-broker-verified tax branches a proposed sell would exercise.

    Surfaced so the user knows *before* placing the order that this particular sale is the one worth
    reconciling afterwards. None of these are believed wrong — they are simply unconfirmed by a third
    party, and a sale that touches them is the evidence that would close the gap.
    """
    branches: list[str] = []
    if has_loss_lot:
        branches.append("§70 loss set-off (a loss lot nets against the gain)")
    if has_ltcg:
        branches.append("long-term classification at the 12.5% rate")
    if distinct_cost_bases > 1:
        branches.append(f"multi-lot FIFO across {distinct_cost_bases} different cost bases")
    if uses_exemption:
        branches.append("the ₹1.25L annual LTCG exemption")
    return branches


def render_markdown(
    book: PaperBook,
    prices: PriceData,
    benchmark: pd.Series,
    plan: DailyPlan,
    as_of: date,
    run_log: list[RunLogEntry] | None = None,
) -> str:
    prices_dec = _prices_on(prices, as_of)
    equity = book.portfolio.market_value(prices_dec)
    ret = book.total_return_pct(prices, as_of)
    bench = _benchmark_return_pct(benchmark, book.start_date, as_of)
    bench_str = f"{bench:+.2f}%" if bench is not None else "—"
    days = (as_of - book.start_date).days
    weights = book.portfolio.current_weights(prices_dec)

    lines: list[str] = []
    lines.append("# Q-Alpha — Paper-Trading Dashboard")
    lines.append("")
    lines.append(
        f"_Notional paper trading (no real money) of the validated tax-aware strategy. "
        f"As of **{as_of}** · generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC}._"
    )
    lines.append("")
    lines.append("## At a glance")
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Started | {book.start_date} ({days} days) |")
    lines.append(f"| Notional capital | ₹{book.starting_capital:,.0f} |")
    lines.append(f"| Equity (marked) | ₹{equity:,.0f} |")
    lines.append(f"| Return since start | **{ret:+.2f}%** |")
    lines.append(f"| Nifty 50 TRI (same window) | {bench_str} |")
    lines.append(f"| Cash | ₹{book.portfolio.cash:,.0f} |")
    lines.append(f"| Realized tax to date | ₹{book.realized_tax():,.2f} |")
    lines.append(f"| Rebalances | {len(book.history)} |")
    lines.append(f"| Strategy | shrink-weighted, annual, tax-aware (band {book.params.band}) |")
    lines.append("")

    lines.append("## Today's recommendation")
    lines.append("")
    if plan.has_orders:
        lines.append(f"⚠️ **ACTION NEEDED — {plan.decision.reason}**")
        lines.append("")
        lines.append("| Side | Ticker | Qty | Price |")
        lines.append("|---|---|---|---|")
        for o in plan.proposed_orders:
            lines.append(f"| {o.side.name} | {o.ticker} | {o.quantity} | ₹{o.price} |")
        lines.append("")
        lines.append("_Approve with:_ `uv run python scripts/paper.py apply`")
    else:
        lines.append(f"✅ **HOLD** — {plan.decision.reason}. No orders today.")
    lines.append("")

    lines.append("## Holdings")
    lines.append("")
    if weights:
        lines.append("| Ticker | Qty | Price | Value | Weight | LTCG-safe |")
        lines.append("|---|---|---|---|---|---|")
        for t, q in sorted(book.portfolio.positions().items()):
            px = prices_dec.get(t, Decimal("0"))
            val = q * px
            safe = ltcg_safe_sell_note(book.portfolio.ledger, t, as_of)
            lines.append(
                f"| {t} | {q} | ₹{px} | ₹{val:,.0f} | {weights.get(t, 0.0) * 100:.1f}% | {safe} |"
            )
        lines.append("")
        lines.append(
            "> **LTCG-safe** = the safe minimal holding date: hold until then and the whole line "
            "sells at the lower **12.5%** long-term rate instead of **20%** short-term "
            "(§111A→§112A). Selling earlier is allowed — it just taxes the still-short-term shares "
            "at 20%. `🟢 now` = already fully long-term."
        )
    else:
        lines.append("_No holdings yet._")
    lines.append("")

    curve = book.equity_curve
    lines.append("## Equity track record")
    lines.append("")
    if len(curve) >= 2:
        spark = _sparkline([float(p["equity"]) for p in curve])
        lines.append(f"`{spark}`  ({len(curve)} daily marks; full series in `paper_equity.csv`)")
        lines.append("")
        lines.append("| Date | Equity | Return |")
        lines.append("|---|---|---|")
        for p in curve[-10:]:
            eq = Decimal(p["equity"])
            r = float((eq - book.starting_capital) / book.starting_capital) * 100
            lines.append(f"| {p['date']} | ₹{eq:,.0f} | {r:+.2f}% |")
    else:
        lines.append("_Track record begins — one daily mark recorded so far._")
    lines.append("")

    lines.append("## GO readiness (criterion 6)")
    lines.append("")
    lines.append(go_readiness_markdown(book, benchmark, as_of))
    lines.append("")
    if run_log is not None:
        lines.append(health_markdown(run_log))
        lines.append("")
    lines.append("---")
    lines.append(
        "_The decision engine is the same code validated in the backtest "
        "([reports/PHASE0_VERDICT.md](PHASE0_VERDICT.md)); this page is regenerated daily by the "
        "pipeline, not by hand._"
    )
    return "\n".join(lines) + "\n"


def equity_csv(book: PaperBook) -> str:
    """The equity track record as CSV (durable, plottable)."""
    rows = ["date,equity,cash,return_pct"]
    for p in book.equity_curve:
        eq = Decimal(p["equity"])
        r = (
            float((eq - book.starting_capital) / book.starting_capital) * 100
            if book.starting_capital > 0
            else 0.0
        )
        rows.append(f"{p['date']},{eq},{p['cash']},{r:.4f}")
    return "\n".join(rows) + "\n"
