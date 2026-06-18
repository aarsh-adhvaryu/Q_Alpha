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

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.backtest.portfolio import Portfolio, to_decimal_price
from qalpha.data.prices import PriceData
from qalpha.live.advisor import DeployAdvice, advise_deploy

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
    prices: PriceData, tickers: list[str], as_of: date, *, window: int = _HIGH_WINDOW
) -> dict[str, float]:
    """Per-name 'out of favour' score in [0,1): fractional pullback below its own 1y high.

    0 = at/above its rolling high; 0.30 = 30% below it. A *technical* cheapness proxy (pulled back),
    not fundamental valuation. Names without enough history get 0 (no tilt rather than a guess).
    """
    adj = prices.adj_close
    cutoff = pd.Timestamp(as_of)
    out: dict[str, float] = {}
    for t in tickers:
        if t not in adj.columns:
            out[t] = 0.0
            continue
        series = adj[t].loc[:cutoff].dropna()
        if len(series) < 20:
            out[t] = 0.0
            continue
        high = float(series.tail(window).max())
        cur = float(series.iloc[-1])
        out[t] = max(0.0, 1.0 - cur / high) if high > 0 else 0.0
    return out


def deploy_target(
    tickers: list[str],
    sector_of: Mapping[str, str],
    cheapness: Mapping[str, float],
    *,
    tilt: float = 1.0,
    max_sector_weight: float = 0.30,
) -> pd.Series:
    """Diversified, sector-capped, cheapness-tilted target weights over the watchlist.

    Base is equal weight (diversification); each name is scaled by ``1 + tilt·cheapness`` so
    pulled-back names get a heavier target; then each sector's total is capped at
    ``max_sector_weight`` and the whole renormalised to sum to 1. ``tilt=0`` → pure equal weight.
    """
    if not tickers:
        return pd.Series(dtype=float)
    raw = pd.Series(
        {t: (1.0 + tilt * max(0.0, cheapness.get(t, 0.0))) for t in tickers}, dtype=float
    )
    sectors = pd.Series({t: str(sector_of.get(t, "?")) for t in tickers})
    all_secs = set(sectors)

    # Water-filling: fix any sector that would exceed the cap at exactly the cap, then re-spread the
    # remaining budget over the still-free sectors (proportional to raw), repeating until no free
    # sector violates the cap. Each fixed sector holds the cap; free names share what's left.
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
    return w.sort_values(ascending=False)


@dataclass(frozen=True)
class WeaknessDeployAdvice:
    """The full 'deploy fresh capital into weakness, tax-free' recommendation."""

    weakness: MarketWeakness
    deploy: DeployAdvice
    target: pd.Series
    cheapest: list[tuple[str, float]]  # top out-of-favour names (ticker, pullback)

    def render(self) -> str:
        lines = [
            self.weakness.render(),
            "",
            "Most out-of-favour (pulled back from 1y high — technical, not P/E):",
        ]
        lines += [f"  - {t}: {p * 100:.0f}% below 1y high" for t, p in self.cheapest]
        lines += ["", self.deploy.render()]
        return "\n".join(lines)


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
) -> WeaknessDeployAdvice:
    """Recommend deploying ``amount`` of new money across the Nifty-100 watchlist — diversified,
    tilted toward out-of-favour names, leaning into market weakness — as **buys only (₹0 tax)**.

    Composes the price-based weakness/cheapness layers with the validated ``advise_deploy`` (the
    ₹0-tax greedy buy engine). Names already richly held still count toward the target, so the buys
    fill the genuine underweights — diversifying the book rather than doubling down.
    """
    adj = prices.adj_close
    cutoff = pd.Timestamp(as_of)
    priced = [t for t in watchlist if t in adj.columns and not adj[t].loc[:cutoff].dropna().empty]
    cheap = cheapness_scores(prices, priced, as_of)
    target = deploy_target(priced, sector_of, cheap, tilt=tilt, max_sector_weight=max_sector_weight)

    price_dec: dict[str, Decimal] = {}
    for t in set(priced) | set(portfolio.positions()):
        if t in adj.columns:
            series = adj[t].loc[:cutoff].dropna()
            if not series.empty:
                price_dec[t] = to_decimal_price(float(series.iloc[-1]))

    deploy = advise_deploy(portfolio, amount, target, price_dec, as_of)
    weakness = market_weakness(index_close, as_of)
    cheapest = sorted(cheap.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return WeaknessDeployAdvice(weakness=weakness, deploy=deploy, target=target, cheapest=cheapest)
