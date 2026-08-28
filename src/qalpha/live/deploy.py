"""Deploy-in-weakness engine — the tax-free "buy cheap, diversify" layer (Q_alpha.md §2.9).

The manual investor's real problem: large-caps are rarely cheap outside a crash, so to diversify and
find better entries the opportunity set has to be wider (Nifty 100), and fresh capital should lean
toward names that are **out of favour** and into **market weakness** — all as **buys only**, which
realize **zero capital-gains tax** (the tax-free way to "buy cheap", vs churning the book).

This module adds three deterministic, price-based layers on top of the validated, tested
:func:`~qalpha.live.advisor.advise_deploy` (which already routes new money to underweights as ₹0-tax
buys):

1. :func:`market_weakness` — how far the index sits below its rolling high → a *when to deploy more*
   advisory (normal / elevated / deep). A self-contained signal from the product's own index series;
   the richer cross-asset **fragility gauge** lives in the research repo (advisory upgrade path).
2. :func:`cheapness_scores` — how far each name has pulled back from its own 1-year high → a *where*
   tilt. **Honest scope:** this is a *technical* out-of-favour proxy, NOT fundamental valuation
   (true P/E "cheap" needs fundamentals, currently data-blocked).
3. :func:`deploy_target` — a diversified (equal-weight, sector-capped) target over the watchlist,
   tilted toward the cheaper names; fed straight into ``advise_deploy`` for the ₹0-tax buy plan.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction
from qalpha.backtest.portfolio import Portfolio, TradeRecord, to_decimal_price
from qalpha.data.prices import PriceData
from qalpha.live.advisor import DeployAdvice, advise_deploy
from qalpha.live.position_health import HoldingHealth, position_health
from qalpha.live.price_integrity import (
    PriceGap,
    excluded_from_tilt,
    gaps_note,
    rebase_starts,
    unexplained_gaps,
)
from qalpha.live.satellite import SatelliteRegistry, core_view_excluding

_HIGH_WINDOW = 252  # ~1 trading year for the rolling high


@dataclass(frozen=True)
class MarketWeakness:
    """How stressed the market is right now — the 'when to deploy more' advisory."""

    drawdown: float  # current level vs its rolling 1y high (≤ 0)
    level: str  # "normal" | "elevated" | "deep"
    note: str

    def render(self) -> str:
        pct = self.drawdown * 100
        return f"Market weakness: **{self.level}** ({pct:+.1f}% from 1y high) — {self.note}"


def market_weakness(index_close: pd.Series, as_of: date) -> MarketWeakness:
    """Classify market weakness from the index's drawdown vs its rolling 1-year high.

    Deeper drawdowns are historically better-than-average entry points for *fresh* capital — so the
    advisory leans into them (always as tax-free buys, never selling the existing book).
    """
    hist = index_close.loc[: pd.Timestamp(as_of)].dropna()
    if hist.empty:
        return MarketWeakness(0.0, "normal", "no index history — deploy steadily.")
    window = hist.tail(_HIGH_WINDOW)
    dd = float(window.iloc[-1] / window.max() - 1.0)
    if dd <= -0.12:
        return MarketWeakness(
            dd,
            "deep",
            "significant drawdown — historically strong forward returns; deploy "
            "aggressively into the pullback (tax-free buys).",
        )
    if dd <= -0.05:
        return MarketWeakness(
            dd, "elevated", "market has pulled back — a better-than-usual entry; lean into it."
        )
    return MarketWeakness(
        dd, "normal", "near highs — deploy steadily / dollar-cost average; keep dry powder."
    )


def cheapness_scores(
    prices: PriceData,
    tickers: list[str],
    as_of: date,
    *,
    window: int = _HIGH_WINDOW,
    rebase_from: Mapping[str, date] | None = None,
    no_tilt: Collection[str] | None = None,
) -> dict[str, float]:
    """Per-name 'out of favour' score in [0,1): fractional pullback below its own 1y high.

    0 = at/above its rolling high; 0.30 = 30% below it. A *technical* cheapness proxy (pulled back),
    not fundamental valuation. Names without enough history get 0 (no tilt rather than a guess).

    **Price-continuity inputs (PR-2).** ``adj_close`` corrects splits and dividends and nothing else,
    so a demerger leaves a step-down that this rule would read as a discount for a full year — the
    defect that put two price artifacts at the top of a real ₹100,000 recommendation. Callers pass
    :func:`~qalpha.live.price_integrity.rebase_starts` as ``rebase_from`` to measure a flagged name's
    high only over the window that starts at its gap (the first comparable price), and
    :func:`~qalpha.live.price_integrity.excluded_from_tilt` as ``no_tilt`` for flagged names with too
    little post-gap history to read — those score 0. Both default to off, leaving the original
    behaviour exactly intact for every caller that does not opt in.
    """
    adj = prices.adj_close
    cutoff = pd.Timestamp(as_of)
    rebase = rebase_from or {}
    untilted = set(no_tilt or ())
    out: dict[str, float] = {}
    for t in tickers:
        if t not in adj.columns or t in untilted:
            out[t] = 0.0
            continue
        series = adj[t].loc[:cutoff].dropna()
        if len(series) < 20:
            out[t] = 0.0
            continue
        cur = float(series.iloc[-1])
        start = rebase.get(t)
        if start is not None:  # discontinuous series — the pre-gap high is a different instrument
            series = series[series.index >= pd.Timestamp(start)]
            if series.empty:
                out[t] = 0.0
                continue
        high = float(series.tail(window).max())
        out[t] = max(0.0, 1.0 - cur / high) if high > 0 else 0.0
    return out


def deploy_target(
    tickers: list[str],
    sector_of: Mapping[str, str],
    cheapness: Mapping[str, float],
    *,
    tilt: float = 1.0,
    max_sector_weight: float = 0.30,
    max_names: int | None = None,
) -> pd.Series:
    """Diversified, sector-capped, cheapness-tilted target weights over the watchlist.

    Base is equal weight (diversification); each name is scaled by ``1 + tilt·cheapness`` so
    pulled-back names get a heavier target; then each sector's total is capped at
    ``max_sector_weight`` and the whole renormalised to sum to 1. ``tilt=0`` → pure equal weight.
    ``max_names`` keeps only the top-N highest-target names (the concentration dial — fewer, bigger
    positions instead of a thin sliver of everything), renormalised to sum to 1 **and re-capped**, so
    the delivered basket carries the sector constraint rather than a pre-truncation basket that was
    never handed to anyone (PR-3 / T1.4).
    """
    if not tickers:
        return pd.Series(dtype=float)
    raw = pd.Series(
        {t: (1.0 + tilt * max(0.0, cheapness.get(t, 0.0))) for t in tickers}, dtype=float
    )
    sectors = pd.Series({t: str(sector_of.get(t, "?")) for t in tickers})

    w = _cap_sectors(raw, sectors, max_sector_weight).sort_values(ascending=False)
    if max_names is not None and len(w) > max_names:
        # Concentrate into the top-N, then **re-apply the cap to what actually survives** (PR-3).
        # Capping before truncation constrained a basket that was never delivered: the top slice of a
        # cheapness ranking is exactly where one sector clusters (an IT-wide de-rating puts four IT
        # names in the top 15), so the cap the code advertised could be silently exceeded by the
        # basket the user was handed.
        kept = w.head(max_names).index
        w = _cap_sectors(raw[kept], sectors[kept], max_sector_weight).sort_values(ascending=False)
    return w


def _cap_sectors(raw: pd.Series, sectors: pd.Series, max_sector_weight: float) -> pd.Series:
    """Normalise ``raw`` to sum to 1 with no sector above ``max_sector_weight``.

    Water-filling: fix any sector that would exceed the cap at exactly the cap, then re-spread the
    remaining budget over the still-free sectors (proportional to raw), repeating until no free
    sector violates the cap. Each fixed sector holds the cap; free names share what's left. An
    infeasible cap (fewer sectors than ``1 / max_sector_weight``) degrades gracefully to the
    renormalised proportional weights rather than raising.
    """
    all_secs = set(sectors)
    capped: set[str] = set()
    while len(capped) < len(all_secs):
        free_names = sectors[~sectors.isin(capped)].index
        budget = 1.0 - max_sector_weight * len(capped)
        if len(free_names) == 0 or budget <= 0:
            break
        w_free = raw[free_names] / raw[free_names].sum() * budget
        sec_tot = w_free.groupby(sectors[free_names]).sum()
        violators = sec_tot[sec_tot > max_sector_weight + 1e-12]
        if violators.empty:
            break
        capped.add(str(violators.idxmax()))

    w = pd.Series(0.0, index=raw.index)
    free_names = sectors[~sectors.isin(capped)].index
    budget = 1.0 - max_sector_weight * len(capped)
    if len(free_names) and budget > 0:
        w[free_names] = raw[free_names] / raw[free_names].sum() * budget
    for sec in capped:
        names = sectors[sectors == sec].index
        w[names] = raw[names] / raw[names].sum() * max_sector_weight
    if float(w.sum()) > 0:  # renormalise (handles an infeasible cap gracefully)
        w = w / w.sum()
    return w


@dataclass(frozen=True)
class WeaknessDeployAdvice:
    """The full 'deploy fresh capital into weakness, tax-free' recommendation."""

    weakness: MarketWeakness
    deploy: DeployAdvice
    target: pd.Series
    cheapest: list[tuple[str, float]]  # top out-of-favour names (ticker, pullback)
    # Holdings outside the watchlist (or registered satellite) — tracked, never steered. Their
    # capital is treated as withdrawn (satellite-sleeve philosophy): shown so the user knows the
    # advisor saw them, excluded from target sizing. Value is None when no price source covers
    # the name (fail-loud: listed as unpriced rather than silently dropped).
    off_watchlist: tuple[tuple[str, Decimal | None], ...] = ()
    # Names whose price series has an unexplained one-day step (PR-2). Their cheapness has already
    # been re-based (or zeroed) before sizing — this is the audit trail, so the UI can say *why* a
    # name that looks 65% off its high is not being treated as 65% cheap.
    price_gaps: tuple[PriceGap, ...] = ()
    # The §4.7 idiosyncratic-breakdown verdict on every name in the delivered basket (PR-3). The
    # detector already existed and already disagreed with the advisor — it was simply never pointed
    # at candidates, only at holdings. Advisory: it annotates, it never vetoes a name.
    candidate_health: tuple[HoldingHealth, ...] = ()
    # Names the breakdown filter removed before ranking (2026-08-19). Reported so the screen's
    # decision is visible and auditable, not silent.
    filtered_out: tuple[str, ...] = ()
    # Names removed because the user said to leave them alone, not because the market did.
    cooling_off: tuple[str, ...] = ()
    # The sector mix of the basket **as actually delivered**, and the cap it was sized against. The
    # cap is enforced on target *weights*; whole shares cannot always honour it, so what the user
    # buys can exceed what the screen advertised. Reported, per PR-4: the number on screen is the
    # delivered one, not the intended one.
    sector_mix: tuple[tuple[str, float], ...] = ()
    max_sector_weight: float = 0.3
    # Share of the whole candidate universe the detector rates "breaking", so the basket's own share
    # can be read against a baseline. Without it a mostly-red table is uninterpretable: a screen that
    # selects pulled-back names will always overlap a breakdown test, and the only question that
    # matters is *by how much more than the universe it drew from*.
    universe_breaking_rate: float | None = None

    def sector_note(self) -> str:
        """The delivered sector mix, and an explicit flag when it exceeds the cap it was sized to.

        Found in the pre-flight audit (2026-08-24). ``_cap_sectors`` caps *target weights* correctly,
        but the basket is bought in whole shares and the leftover is water-filled, so the delivered
        mix drifts above the target. Measured on the live watchlist at a ₹1,00,000 deploy: at 6+
        names the cap holds (23–29%), but at 5 names NBFC lands at **33.9%**, at 4 names 33.6%, and
        at 3 names **50.0%** — against an advertised 30%.

        Below roughly six names the cap is not merely missed, it is *arithmetically unreachable*: at
        five equal-weight names one name is already 20%, so any two in the same sector is 40%. The
        honest fix is therefore disclosure, not a tighter clamp — a clamp that cannot be satisfied
        would either fail silently or return an empty basket. So the delivered figure is shown, and
        the reason a small basket cannot be diversified is stated where the user chooses the number.
        """
        if not self.sector_mix:
            return ""
        top, share = max(self.sector_mix, key=lambda kv: kv[1])
        mix = " · ".join(f"{name} {pct:.0%}" for name, pct in self.sector_mix)
        if share <= self.max_sector_weight + 0.005:
            return f"**Sector mix (as delivered):** {mix} — within the {self.max_sector_weight:.0%} cap."
        return (
            f"⚠️ **Sector mix (as delivered): {mix}** — **{top} is {share:.0%}, above the "
            f"{self.max_sector_weight:.0%} cap** this basket was sized against. The cap is applied "
            "to target weights, but shares are bought whole, and a basket this small cannot honour "
            "it: at five names one name is already 20%, so any two in a sector exceeds 30%. "
            "**Spreading across more names is the only thing that fixes it** — the cap holds from "
            "about six names up."
        )

    def cooling_off_note(self) -> str:
        """What was skipped because *you* said so — never silent, however long ago you said it."""
        if not self.cooling_off:
            return ""
        names = ", ".join(t.removesuffix(".NS") for t in self.cooling_off)
        return (
            f"🚫 **Skipped {len(self.cooling_off)} name(s) you chose to exit:** {names}. "
            "Selling costs tax and buying does not, so re-entering a name you deliberately left "
            "would be real money spent for nothing. Clear it on the Sell tab to make it buyable "
            "again; it lapses on its own otherwise."
        )

    def filtered_note(self) -> str:
        """The ✅ line — what the screen removed on your behalf, and on what test."""
        if not self.filtered_out:
            return ""
        n = len(self.filtered_out)
        shown = ", ".join(t.removesuffix(".NS") for t in self.filtered_out[:8])
        more = f" and {n - 8} more" if n > 8 else ""
        return (
            f"✅ **The screen removed {n} name{'s' if n != 1 else ''} before choosing** — each one "
            "is in a sustained, *name-specific* decline on this system's §4.7 breakdown test, which "
            "is the opposite of the 'temporarily out of favour' story a pullback screen assumes. "
            f"Excluded: {shown}{more}."
        )

    def candidate_health_note(self) -> str:
        """The per-name verdict table — '' when no candidate could be assessed.

        This is the system telling you, beside its own recommendation, which of these names it would
        flag for *exit* if you already held them. Selection stays deterministic and unchanged: the
        user asked to see the disagreement, not to have it silently resolved.
        """
        if not self.candidate_health:
            return ""
        rows = [
            "**The breakdown detector's verdict on these same names** (§4.7 — the test this system "
            "runs over your *holdings*, now pointed at what it is recommending):",
            "",
            "| | Name | 6-month | vs market | Verdict |",
            "|---|---|---|---|---|",
        ]
        order = {"breaking": 0, "watch": 1, "healthy": 2}
        for h in sorted(self.candidate_health, key=lambda h: (order[h.level], h.ticker)):
            rows.append(
                f"| {h.icon} | {h.ticker} | {h.trailing_return:+.0%} | {h.excess_vs_market:+.0%} | "
                f"{h.level} |"
            )
        breaking = [h.ticker for h in self.candidate_health if h.level == "breaking"]
        if not breaking:
            return "\n".join(rows)
        n = len(self.candidate_health)
        share = len(breaking) / n
        rows += [
            "",
            f"⚠️ **{len(breaking)} of {n} recommended names are ones this system would flag for "
            "review-for-exit if you held them.**",
        ]
        if self.universe_breaking_rate is not None and self.universe_breaking_rate > 0:
            ratio = share / self.universe_breaking_rate
            rows.append(
                f"For scale: **{self.universe_breaking_rate:.0%} of the whole watchlist** is "
                f"breaking down right now, so this basket is **{ratio:.1f}× more concentrated** in "
                "them than the universe it was drawn from."
            )
        rows.append(
            "Some overlap is unavoidable — a pullback screen and a breakdown test look at the same "
            "price fall. But 🔴 means the fall is **name-specific**, not the market, which is the "
            "opposite of the 'temporarily out of favour' story the cheapness tilt assumes. These "
            "are the names to check by hand before you place an order."
        )
        return "\n".join(rows)

    def price_gaps_note(self) -> str:
        """The ⚠️ continuity line — '' when every series in the universe was continuous."""
        return gaps_note({g.ticker: g for g in self.price_gaps})

    def off_watchlist_note(self) -> str:
        """The ℹ️ visibility line — '' when the book is watchlist-only (render unchanged)."""
        if not self.off_watchlist:
            return ""
        priced = [(t, v) for t, v in self.off_watchlist if v is not None]
        unpriced = [t for t, v in self.off_watchlist if v is None]
        total = sum((v for _, v in priced), Decimal("0"))
        parts = [f"{t} ₹{v:,.0f}" for t, v in priced]
        if unpriced:
            parts.append("unpriced: " + ", ".join(unpriced))
        n = len(self.off_watchlist)
        return (
            f"ℹ️ ₹{total:,.0f} across {n} holding{'s' if n != 1 else ''} outside the watchlist "
            f"({'; '.join(parts)}) — tracked, not steered; excluded from target sizing."
        )

    def render(self) -> str:
        lines = [
            self.weakness.render(),
            "",
            "Most out-of-favour (pulled back from 1y high — technical, not P/E):",
        ]
        lines += [f"  - {t}: {p * 100:.0f}% below 1y high" for t, p in self.cheapest]
        cooling = self.cooling_off_note()
        if cooling:
            lines += ["", cooling]
        filtered = self.filtered_note()
        if filtered:
            lines += ["", filtered]
        gaps = self.price_gaps_note()
        if gaps:
            lines += ["", gaps]
        health = self.candidate_health_note()
        if health:
            lines += ["", health]
        note = self.off_watchlist_note()
        if note:
            lines += ["", note]
        sectors = self.sector_note()
        if sectors:
            lines += ["", sectors]
        lines += ["", self.deploy.render()]
        return "\n".join(lines)


def _delivered_sector_mix(
    orders: Sequence[TradeRecord], sector_of: Mapping[str, str]
) -> tuple[tuple[str, float], ...]:
    """Sector shares of the basket actually bought, largest first — whole shares, not target weights."""
    by_sector: dict[str, Decimal] = {}
    for order in orders:
        value = order.quantity * order.price
        sector = sector_of.get(order.ticker, "OTHER")
        by_sector[sector] = by_sector.get(sector, Decimal("0")) + value
    total = sum(by_sector.values(), Decimal("0"))
    if total <= 0:
        return ()
    return tuple(
        sorted(((s, float(v / total)) for s, v in by_sector.items()), key=lambda kv: -kv[1])
    )


def advise_deploy_into_weakness(
    portfolio: Portfolio,
    amount: Decimal,
    watchlist: list[str],
    sector_of: Mapping[str, str],
    prices: PriceData,
    index_close: pd.Series,
    as_of: date,
    *,
    tilt: float = 1.0,
    max_sector_weight: float = 0.30,
    max_name_fraction: float = 0.20,
    max_names: int | None = None,
    broker_prices: Mapping[str, Decimal] | None = None,
    known_actions: Mapping[str, Sequence[CorporateAction]] | None = None,
    exclude_breaking: bool = True,
    do_not_buy: Collection[str] = (),
    spend_idle_cash: bool = True,
) -> WeaknessDeployAdvice:
    """Recommend deploying ``amount`` of new money across the Nifty-100 watchlist — diversified,
    tilted toward out-of-favour names, leaning into market weakness — as **buys only (₹0 tax)**.

    Composes the price-based weakness/cheapness layers with the validated ``advise_deploy`` (the
    ₹0-tax greedy buy engine). Names already richly held still count toward the target, so the buys
    fill the genuine underweights — diversifying the book rather than doubling down.

    ``max_name_fraction`` keeps the deploy diversified at whole-share granularity: a name whose **one
    share** costs more than this fraction of ``amount`` is dropped from the target, so a single pricey
    share can't swallow a small deploy (it returns once the deploy is large enough to fit it). If that
    would leave too few names (<3), the filter is relaxed — better some deploy than none.

    ``broker_prices`` (optional) marks holdings the watchlist panel can't price (IPO allotments,
    off-index picks) — pass the live ``ltp()`` / paper marks. Any held name outside ``watchlist``
    (or registered satellite) is **shown + excluded**: listed with its value in the advice so the
    user knows the advisor saw it, but its capital is treated as withdrawn (the satellite-sleeve
    philosophy) — targets are sized over the core book only, and it is never bought or sold here.
    Watchlist names the user picked himself still steer the gap-fill exactly as before.

    **Price continuity (PR-2).** Every candidate's series is checked for an unexplained one-day step
    before it is scored. ``adj_close`` corrects splits and dividends but never demergers, so such a
    step reads as a permanent discount to a 1-year-high rule — the defect that put two artifacts at
    the top of a real recommendation. A flagged name's high is re-based to its gap rather than the
    name being dropped, and the flags ride along on the advice so the UI can explain itself.
    ``known_actions`` optionally supplies splits/dividends so a genuine, already-adjusted action is
    not reported as a defect.
    """
    adj = prices.adj_close
    cutoff = pd.Timestamp(as_of)
    priced = [t for t in watchlist if t in adj.columns and not adj[t].loc[:cutoff].dropna().empty]

    last_price: dict[str, float] = {t: float(adj[t].loc[:cutoff].dropna().iloc[-1]) for t in priced}
    cap = float(amount) * max_name_fraction
    affordable = [t for t in priced if last_price[t] <= cap]
    universe = affordable if len(affordable) >= 3 else priced  # don't over-restrict tiny deploys

    # The screen decides, rather than deferring (2026-08-19). `cheapness` alone ranks on "furthest
    # below its 1-year high", which is very nearly the same list as "falling apart" — that is why the
    # delivered basket came back 7-of-7 flagged by this system's own §4.7 breakdown test, at 5× the
    # watchlist's base rate. Annotating that was honest but useless: it handed the user a basket the
    # system would not stand behind and asked them to adjudicate.
    #
    # So the breakdown test is now a **filter, not a label**. A name in a sustained, idiosyncratic
    # decline is not a discount, and the screen removes it before ranking rather than shipping it
    # with a warning. The result is a shallower average discount and a naturally sector-diversified
    # basket (7 sectors instead of 4-of-7 in IT), with zero names the system would flag for exit.
    #
    # Fails open, deliberately: too little history to judge, or too few survivors to build a basket,
    # and the filter stands down rather than returning nothing. `exclude_breaking=False` restores the
    # pre-2026-08-19 behaviour for comparison.
    breaking: set[str] = set()
    pre_filter_universe = list(universe)
    # Computed ONCE, over the full pre-filter universe, and reused by every consumer below. The
    # continuity guard was wired into `cheapness_scores` and not into `position_health`, so the same
    # screen scored VEDL 22.1% off its high while its own detector called the same name a −59%
    # breakdown. A superset of names is harmless: each consumer only looks up what it scores.
    gaps = unexplained_gaps(adj, pre_filter_universe, as_of, actions=known_actions)
    rebase, untilted = rebase_starts(gaps), excluded_from_tilt(gaps)
    if exclude_breaking:
        report = position_health(adj, universe, as_of, rebase_from=rebase, exclude=untilted)
        breaking = {h.ticker for h in report.holdings if h.level == "breaking"}
        healthy = [t for t in universe if t not in breaking]
        # Never starve the basket: if the filter would leave too little to diversify across, keep the
        # full universe. Some deploy on flagged names beats no deploy at all.
        if len(healthy) >= max(3, max_names or 0):
            universe = healthy
        else:
            breaking = set()

    # Names the user deliberately exited (``live/cooling_off.py``). Removed *before* ranking, so a
    # name on cooling-off cannot be re-bought — the point being that selling is taxed and buying is
    # not, so a silent re-entry means real money paid for nothing. This is the only filter in the
    # screen that encodes the user's stated intent rather than a measurement, which is exactly why it
    # is reported on the advice rather than applied quietly.
    on_cooling_off = sorted(set(do_not_buy) & set(universe))
    if on_cooling_off:
        universe = [t for t in universe if t not in set(do_not_buy)]

    cheap = cheapness_scores(
        prices,
        universe,
        as_of,
        rebase_from=rebase,
        no_tilt=untilted,
    )
    # Keep building the positions you already own (2026-08-20). User's framing, and it is the right
    # one: "if a company is good, and getting a good deal, why not add to it?"
    #
    # Without this, a monthly SIP sprawls. `advise_deploy` funds whatever is furthest below target,
    # and a name you hold *zero* of is always furthest below — so each month's freshly-ranked
    # newcomers outrank every position you already hold. Simulated over five monthly deploys on real
    # price history that produced **19 names in five months** (~40 in a year), each a stranded
    # ~₹10,000 lot that never gets topped up again. Nothing is sold, so there is no tax damage; it
    # simply never builds a position in anything.
    #
    # So the slots go to held names first. A holding keeps its slot for exactly as long as it still
    # earns it — it must still clear the breakdown filter, the continuity guard and the affordability
    # cap, since `universe` is the already-screened list. A name that breaks down loses its slot and a
    # fresh candidate takes it. That is the whole rule: **add to what is still good, replace only what
    # stopped being good.**
    held_still_screened = [t for t in universe if t in portfolio.positions()]
    preselected = max_names is not None and len(universe) > max_names
    if preselected:
        # Every healthy holding stays a candidate, not just the top `max_names` of them (user's
        # idea, 2026-08-20): "it knows the distribution of the portfolio — instead of selling, it
        # balances it in the next buy." `max_names` therefore caps how many *new* names may be
        # opened, not how many existing positions may be topped up. Without this, a holding that
        # slips out of the fresh ranking is stranded forever at whatever weight it happened to
        # reach — measured at 19 names, that tail was UPL 1.5%, NMDC 1.1%, VEDL 0.7%.
        keep = held_still_screened
        slots = (max_names or 0) - len(keep)
        fresh = [t for t in sorted(universe, key=lambda x: -cheap.get(x, 0.0)) if t not in keep]
        selected = keep + fresh[: max(0, slots)]
    else:
        selected = list(universe)

    target = deploy_target(
        selected,
        sector_of,
        cheap,
        tilt=tilt,
        max_sector_weight=max_sector_weight,
        # When we have already chosen the roster, a second truncation would undo the stickiness by
        # re-ranking held names out on cheapness alone.
        max_names=None if preselected else max_names,
    )

    price_dec: dict[str, Decimal] = {}
    for t in set(selected) | set(universe) | set(portfolio.positions()):
        if t in adj.columns:
            series = adj[t].loc[:cutoff].dropna()
            if not series.empty:
                price_dec[t] = to_decimal_price(float(series.iloc[-1]))

    # Show + exclude: held names outside the watchlist (or registered satellite) are tracked, not
    # steered. Their capital is withdrawn from the sizing base (core view), and they're valued for
    # the visibility line — broker price first, panel price as fallback, None = unpriced (listed,
    # never silently dropped; Portfolio.holdings_value would otherwise skip them without a trace).
    registry = SatelliteRegistry.load()
    held = set(portfolio.positions())
    excluded = (held - set(watchlist)) | (held & registry.tickers)
    off_watchlist: tuple[tuple[str, Decimal | None], ...] = ()
    core = portfolio
    if excluded:
        core = core_view_excluding(portfolio, excluded)
        qty = portfolio.positions()

        def _mark(t: str) -> Decimal | None:
            price = (broker_prices or {}).get(t, price_dec.get(t))
            return qty[t] * price if price is not None else None

        off_watchlist = tuple((t, _mark(t)) for t in sorted(excluded))

    deploy = advise_deploy(core, amount, target, price_dec, as_of, spend_idle_cash=spend_idle_cash)
    weakness = market_weakness(index_close, as_of)
    cheapest = sorted(cheap.items(), key=lambda kv: kv[1], reverse=True)[:5]

    # Point the §4.7 breakdown detector at the **candidates** (PR-3 / T1.2). It has always run over
    # holdings only, so the advisor and the exit test could reach opposite verdicts on the same name
    # on the same day and neither surface would notice. Assessed over the names actually being
    # recommended — the ones with buy orders, or the target if nothing fits — against the full
    # watchlist cross-section, so "vs market" means the same thing it does on the holdings panel.
    recommended = sorted({o.ticker for o in deploy.buy_orders}) or sorted(target.index)
    # Health is still reported on the delivered basket — the filter should make this boring, and a
    # 🔴 appearing here again is the signal that it stopped working.
    # Measured over the universe **as it stood before the breakdown filter ran** (pre-flight audit,
    # 2026-08-24). It used to read `universe`, which by this point has had every breaking name
    # removed — so the rate was 0.0 by construction and the one sentence that makes the health table
    # interpretable ("the basket is N× more concentrated in them than the universe it was drawn
    # from") never rendered. It went missing in exactly the case it exists for: the filter failing
    # open and a 🔴 reaching the basket anyway.
    universe_health = position_health(
        adj, sorted(pre_filter_universe), as_of, rebase_from=rebase, exclude=untilted
    ).holdings
    by_ticker = {h.ticker: h for h in universe_health}
    health = [by_ticker[t] for t in recommended if t in by_ticker]
    breaking_rate = (
        sum(h.level == "breaking" for h in universe_health) / len(universe_health)
        if universe_health
        else None
    )

    return WeaknessDeployAdvice(
        weakness=weakness,
        deploy=deploy,
        target=target,
        cheapest=cheapest,
        off_watchlist=off_watchlist,
        sector_mix=_delivered_sector_mix(deploy.buy_orders, sector_of),
        max_sector_weight=max_sector_weight,
        price_gaps=tuple(gaps[t] for t in sorted(gaps)),
        candidate_health=tuple(health),
        universe_breaking_rate=breaking_rate,
        filtered_out=tuple(sorted(breaking)),
        cooling_off=tuple(on_cooling_off),
    )
