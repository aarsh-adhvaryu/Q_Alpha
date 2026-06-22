"""satellite.py — the IPO / discretionary "satellite" sleeve (Q_alpha.md §2 capital structure).

Bookkeeping for positions the optimizer **cannot** model — fresh listings with no price history (no
12-1 momentum, no covariance). They are the manual investor's discretionary call; the system
**tracks, taxes, and watches** them, but never optimizes them. The optimizer treats their capital as
**withdrawn** — it sizes the data-rich core over ``total - satellite_market_value``, recomputed each
rebalance, so a growing satellite naturally shrinks the optimized base (self-adjusting).

Why a separate sleeve, rather than "just let the no-data name fall out of the funnel": the funnel
would otherwise **leak**. A name with NaN momentum still earns a composite score
(``factors/score.py`` renormalises per row over the factors present), and the production ``shrink``
weighting's equal leg (``backtest/strategy.py``) hands a covariance-dropped name ``0.5 x (1/N)``
weight — a real position with **no risk model behind it**. So the clean control is *membership*: a
satellite name is excluded by registry, and **graduates** into the core universe only once it has a
**full funnel window** of clean history, at which point every factor and the covariance are real.

This module is pure bookkeeping over a ``Portfolio`` + a ``PriceData`` panel; it imports no engine
internals and mutates nothing, so the validated backtest (which holds no satellite lots) is a literal
no-op and the 18.2% headline is provably unchanged.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.advisor import SellAdvice, advise_sell

_ZERO = Decimal("0")

SATELLITE_POOL = "satellite"
REGISTRY_PATH = Path("data/satellite.json")

# Default sleeve risk budget (Q_alpha.md §2 tactical sleeve). Deployment is capped at COST; the
# concentration alert watches live market value (appreciation), surfacing — never automating — a trim.
DEFAULT_SLEEVE_CAP = 0.08
DEFAULT_NAME_CAP = 0.025


def funnel_window(cfg: Config) -> int:
    """Trading days of clean history a name needs before **every** optimizer input is real.

    Delegates to :meth:`FactorConfig.funnel_window` — the single source of truth shared with the
    engine/paper rebalance lookback, so the graduation gate can never drift from the window the
    optimizer actually pulls. ``dropna(how="any")`` in ``alloc/conditioning.py`` drops any name short
    of the *full* window from the covariance — so this, not the momentum lookback alone, is the binding
    graduation gate (a name at 253 days has real momentum but is still dropped from Σ).
    """
    return cfg.factor.funnel_window()


# ---- the registry: which tickers are discretionary satellite holdings ----------------------------


@dataclass
class SatelliteRegistry:
    """Maps each satellite ticker to its listing date (for the dated, causal graduation check).

    Source-agnostic by design: classification is by *registry membership*, so it works identically for
    a live ``kite.holdings()`` snapshot (whose holdings carry no ``pool``) and the paper book.
    """

    listed_on: dict[str, date] = field(default_factory=dict)

    def is_satellite(self, ticker: str) -> bool:
        return ticker in self.listed_on

    @property
    def tickers(self) -> set[str]:
        return set(self.listed_on)

    def add(self, ticker: str, listed_date: date) -> None:
        self.listed_on[ticker] = listed_date

    def remove(self, ticker: str) -> None:
        self.listed_on.pop(ticker, None)

    @classmethod
    def load(cls, path: Path = REGISTRY_PATH) -> SatelliteRegistry:
        """Load the registry, or an empty one if the file does not exist yet."""
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        return cls({str(t): date.fromisoformat(str(d)) for t, d in raw.items()})

    def save(self, path: Path = REGISTRY_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {t: d.isoformat() for t, d in sorted(self.listed_on.items())}
        path.write_text(json.dumps(payload, indent=2) + "\n")


def register_ipo(
    ticker: str, listed_date: date, *, path: Path = REGISTRY_PATH
) -> SatelliteRegistry:
    """Mark ``ticker`` as a discretionary satellite holding listed on ``listed_date`` (load→add→save)."""
    registry = SatelliteRegistry.load(path)
    registry.add(ticker, listed_date)
    registry.save(path)
    return registry


def classify_positions(
    tickers: Iterable[str], registry: SatelliteRegistry
) -> tuple[list[str], list[str]]:
    """Split ``tickers`` into ``(core, satellite)`` by registry membership (order preserved)."""
    core: list[str] = []
    satellite: list[str] = []
    for t in tickers:
        (satellite if registry.is_satellite(t) else core).append(t)
    return core, satellite


# ---- "withdrawn cash": the value base the optimizer sizes the core over -------------------------


def satellite_value(
    portfolio: Portfolio, registry: SatelliteRegistry, prices: Mapping[str, Decimal]
) -> Decimal:
    """Total live market value of the satellite holdings (priced names only)."""
    return sum(
        (
            qty * prices[t]
            for t, qty in portfolio.positions().items()
            if registry.is_satellite(t) and t in prices
        ),
        _ZERO,
    )


def core_value(
    portfolio: Portfolio, registry: SatelliteRegistry, prices: Mapping[str, Decimal]
) -> Decimal:
    """The base the optimizer manages = total market value minus satellite holdings (cash + core)."""
    return portfolio.market_value(prices) - satellite_value(portfolio, registry, prices)


def core_fraction(
    portfolio: Portfolio, registry: SatelliteRegistry, prices: Mapping[str, Decimal]
) -> float:
    """Core base as a fraction ``c`` of the total book (1.0 when there is no satellite)."""
    mv = portfolio.market_value(prices)
    if mv <= 0:
        return 1.0
    return float(core_value(portfolio, registry, prices) / mv)


def core_view(portfolio: Portfolio, registry: SatelliteRegistry) -> Portfolio:
    """A ``Portfolio`` of **only the core lots + the same cash** — the withdrawn-cash view the live
    caller hands to ``decide_rebalance``.

    With the satellite lots omitted, ``market_value`` / ``current_weights`` / the §4.6 gate dry-run all
    see core-only (so the optimizer sizes the core over ``cash + core holdings`` = total − satellite
    market value, self-adjusting as the satellite grows). The real book is left untouched — this is a
    read view, never the thing trades execute against. The FY LTCG tally and slippage model are carried
    so the gate's tax/cost estimate stays exact.
    """
    view = Portfolio(portfolio.cost_cfg, portfolio.tax_cfg, cash=portfolio.cash)
    view.slippage_model = portfolio.slippage_model
    for ticker in portfolio.ledger.all_tickers():
        if registry.is_satellite(ticker):
            continue
        for lot in portfolio.ledger.open_lots(ticker):
            view.ledger.add_lot(copy.deepcopy(lot))
    view.gains.restore_ltcg_by_fy(portfolio.gains.realized_ltcg_by_fy())
    return view


# ---- the insufficient-history guard (the fail-loud secondary net) -------------------------------


def has_sufficient_history(prices: PriceData, ticker: str, as_of: date, window: int) -> bool:
    """True iff ``ticker`` has ``window`` consecutive non-NaN ``adj_close`` rows on/before ``as_of``.

    Mirrors the funnel's real requirement: momentum needs the reach-back row, and
    ``alloc/conditioning.py`` drops any name with a NaN *anywhere* in the covariance window. Causal —
    only rows ``<= as_of`` are read, so a name that lists *after* ``as_of`` correctly fails (no
    look-ahead).
    """
    panel = prices.as_of(as_of, lookback=window)
    if ticker not in panel.tickers:
        return False
    col = panel.adj_close[ticker]
    return len(col) >= window and not bool(col.isna().any())


@dataclass(frozen=True)
class HistoryGuard:
    """Split of candidate tickers by whether the optimizer has enough history to size them safely."""

    eligible: list[str]  # full funnel window of clean history → safe for the optimizer
    flagged: list[str]  # insufficient history → excluded from scoring, routed to the manual sleeve


def history_guard(
    prices: PriceData, tickers: Iterable[str], as_of: date, window: int
) -> HistoryGuard:
    """Partition ``tickers`` into optimizer-eligible vs insufficient-history (drop **before** scoring).

    This is the safety net for a name that slips into the universe young (e.g. a Nifty fast-track
    inclusion at ~3 months) — it never reaches the partial-factor scorer, so it cannot leak an
    unmodelled weight; it is flagged for the manual sleeve instead.
    """
    eligible: list[str] = []
    flagged: list[str] = []
    for t in tickers:
        (eligible if has_sufficient_history(prices, t, as_of, window) else flagged).append(t)
    return HistoryGuard(eligible=eligible, flagged=flagged)


def is_graduated(prices: PriceData, ticker: str, as_of: date, window: int) -> bool:
    """A satellite name graduates once it has a **full funnel window** of clean history (every
    optimizer input is then real). Liquidity is enforced separately by the funnel's own ADV gate.
    """
    return has_sufficient_history(prices, ticker, as_of, window)


# ---- concentration alert (surface, never auto-trim) --------------------------------------------


@dataclass(frozen=True)
class ConcentrationAlert:
    """A satellite position (or the whole sleeve) whose **live** weight has breached a cap."""

    scope: str  # "sleeve" or a ticker
    weight: float
    cap: float
    message: str


def concentration_alerts(
    portfolio: Portfolio,
    registry: SatelliteRegistry,
    prices: Mapping[str, Decimal],
    *,
    sleeve_cap: float = DEFAULT_SLEEVE_CAP,
    name_cap: float = DEFAULT_NAME_CAP,
) -> list[ConcentrationAlert]:
    """Alert (never act) when satellite **live market value** breaches the sleeve or per-name cap.

    The caps govern *deployment* at cost (bounding fresh risk, letting winners run untaxed); this
    watches *appreciation* at market value — a runaway winner is a genuine concentration the user
    resolves with a deliberate, tax-aware trim. Surfaced, not automated (never realise tax for you).
    """
    mv = portfolio.market_value(prices)
    out: list[ConcentrationAlert] = []
    if mv <= 0:
        return out
    sleeve_w = float(satellite_value(portfolio, registry, prices) / mv)
    if sleeve_w > sleeve_cap:
        out.append(
            ConcentrationAlert(
                "sleeve",
                sleeve_w,
                sleeve_cap,
                f"Satellite sleeve is {sleeve_w:.1%} of the book (cap {sleeve_cap:.0%}) — "
                "consider a deliberate, tax-aware trim.",
            )
        )
    for t, qty in portfolio.positions().items():
        if registry.is_satellite(t) and t in prices:
            w = float(qty * prices[t] / mv)
            if w > name_cap:
                out.append(
                    ConcentrationAlert(
                        t,
                        w,
                        name_cap,
                        f"{t} is {w:.1%} of the book (per-name cap {name_cap:.0%}) — appreciation "
                        "has outgrown the cap; a trim is your call.",
                    )
                )
    return out


# ---- sector-footprint accounting + the bound transform (label-only diversification) ------------


def satellite_sector_footprint(
    portfolio: Portfolio,
    registry: SatelliteRegistry,
    sector_of: Mapping[str, str],
    prices: Mapping[str, Decimal],
) -> dict[str, float]:
    """Each sector's satellite exposure as a fraction of the **total** book (live MV x known label).

    Uses only the sector *label* (a fact) and live market value (a fact) — never the IPO's risk, which
    is unmeasurable. This is what lets the core diversify *around* a held telecom IPO without folding
    an index proxy into the covariance.
    """
    mv = portfolio.market_value(prices)
    out: dict[str, float] = {}
    if mv <= 0:
        return out
    for t, qty in portfolio.positions().items():
        if registry.is_satellite(t) and t in prices:
            sector = sector_of.get(t, "UNKNOWN")
            out[sector] = out.get(sector, 0.0) + float(qty * prices[t] / mv)
    return out


def tighten_sector_bounds(
    footprint: Mapping[str, float], core_frac: float, *, floor: float, cap: float
) -> dict[str, tuple[float, float]]:
    """Per-sector core-allocator ``(lo, hi)`` adjusted for the satellite footprint.

    We want each sector's **total-book** weight in ``[floor, cap]``. With the core allocator's weight
    ``w`` a fraction of the core (``c = core_frac``) and the satellite footprint ``f`` a fraction of
    the total book::

        floor <= f + w*c <= cap   =>   (floor - f)/c <= w <= (cap - f)/c

    Both bounds are floored at 0: you cannot short the core to offset an over-cap satellite (long
    only) — an over-cap sector collapses the core's room to 0 and is handled by a concentration alert,
    not by going negative. This is applied **only** to the sector's bounds (a constraint), never folded
    into ``w'Sw``/Σ — that would require an index proxy and would oversize the IPO.
    """
    out: dict[str, tuple[float, float]] = {}
    if core_frac <= 0:
        return out
    for sector, f in footprint.items():
        lo = max(0.0, (floor - f) / core_frac)
        hi = max(0.0, (cap - f) / core_frac)
        out[sector] = (lo, hi)
    return out


# ---- the live wiring: what the dashboard/CLI hands to decide_rebalance + shows the user ----------


def core_decision_inputs(
    portfolio: Portfolio,
    registry: SatelliteRegistry,
    prices: PriceData,
    universe: Universe,
    sector_of: Mapping[str, str],
    prices_dec: Mapping[str, Decimal],
    as_of: date,
    cfg: Config,
) -> tuple[Portfolio, set[str], dict[str, tuple[float, float]]]:
    """Assemble the three satellite-aware inputs the live caller passes to ``decide_rebalance``.

    Returns ``(core_view, blacklist, sector_bounds_override)``:

    * **core_view** — the withdrawn-cash Portfolio (satellite omitted) the optimizer sizes the core over.
    * **blacklist** — every satellite ticker (the primary registry gate) **plus** any universe name that
      lacks a full funnel window of clean history (the secondary fail-loud net for young index adds);
      ``decide_rebalance`` already drops these from selection.
    * **sector_bounds_override** — the core sector boxes tightened for the satellite's sector footprint
      (label-only diversification), to feed ``allocate_sectors`` via ``select_and_weight``.

    Pure: reads state, builds inputs, mutates nothing. When the registry is empty (no satellite) this is
    ``(full book, {history-flagged names}, {})`` — i.e. it adds nothing the validated path didn't do.
    """
    window = cfg.factor.funnel_window()
    members = universe.members_on(as_of)
    guard = history_guard(prices, members, as_of, window)
    blacklist = set(registry.tickers) | set(guard.flagged)
    view = core_view(portfolio, registry)
    footprint = satellite_sector_footprint(portfolio, registry, sector_of, prices_dec)
    overrides = tighten_sector_bounds(
        footprint,
        core_fraction(portfolio, registry, prices_dec),
        floor=cfg.optimizer.sector_weight_min,
        cap=cfg.optimizer.sector_weight_max,
    )
    return view, blacklist, overrides


@dataclass(frozen=True)
class SatelliteHolding:
    """One satellite position with its graduation countdown and exact tax/exit advice."""

    ticker: str
    quantity: Decimal
    price: Decimal
    value: Decimal
    book_weight: float
    listed_date: date | None
    trading_days_listed: int
    window: int
    ready_to_graduate: bool
    graduates_on: date | None
    sell_advice: SellAdvice


@dataclass(frozen=True)
class SatelliteReport:
    """The flagged 'discretionary / non-optimized' section the dashboard shows for the IPO sleeve."""

    as_of: date
    holdings: list[SatelliteHolding]
    alerts: list[ConcentrationAlert]
    total_value: Decimal
    sleeve_weight: float

    def render(self) -> str:
        if not self.holdings:
            return "_No discretionary (satellite/IPO) holdings registered._"
        lines = [
            "### 🛰 Discretionary holdings (satellite / IPO) — **not optimized by the model**",
            "",
            f"These are your own calls. The optimizer treats them as withdrawn cash and never trades "
            f"them; the system only tracks, taxes, and watches them. Sleeve: "
            f"{_rupees(self.total_value)} ({self.sleeve_weight:.1%} of the book).",
            "",
            "| Holding | Qty | Price | Value | Book % | Listed | Graduation |",
            "|---|---|---|---|---|---|---|",
        ]
        for h in self.holdings:
            if h.ready_to_graduate:
                grad = "✅ old enough — graduate it (add to universe + ingest history)"
            elif h.graduates_on is not None:
                grad = f"{h.trading_days_listed}/{h.window} td — ~{h.graduates_on}"
            else:
                grad = "unknown (no listing date)"
            lines.append(
                f"| {h.ticker} | {h.quantity} | {_rupees(h.price)} | {_rupees(h.value)} | "
                f"{h.book_weight:.1%} | {h.listed_date or '?'} | {grad} |"
            )
        for h in self.holdings:
            lines += ["", f"**{h.ticker} — exit tax if you sell now:**", h.sell_advice.render()]
        if self.alerts:
            lines += [
                "",
                "**⚠️ Concentration alerts** (surface only — any trim is your tax-aware call):",
            ]
            lines += [f"- {a.message}" for a in self.alerts]
        return "\n".join(lines)


def satellite_report(
    portfolio: Portfolio,
    registry: SatelliteRegistry,
    prices_dec: Mapping[str, Decimal],
    as_of: date,
    cfg: Config,
    *,
    sleeve_cap: float = DEFAULT_SLEEVE_CAP,
    name_cap: float = DEFAULT_NAME_CAP,
) -> SatelliteReport:
    """Build the discretionary-sleeve report: per-holding graduation countdown + exact exit tax + alerts.

    Graduation countdown is **time-based** (business days since the registered listing date), so it works
    even before the IPO's price history is ingested — it tells you *when* a name is old enough to move
    into the optimized core (a deliberate action: remove from the registry, add to the universe, ingest
    its prices). The exit tax for each holding is the exact FIFO figure from the validated advisor.
    """
    window = cfg.factor.funnel_window()
    mv = portfolio.market_value(prices_dec)
    holdings: list[SatelliteHolding] = []
    for ticker, qty in portfolio.positions().items():
        if not registry.is_satellite(ticker):
            continue
        price = prices_dec.get(ticker)
        if price is None or price <= 0:
            continue
        value = qty * price
        listed = registry.listed_on.get(ticker)
        if listed is not None and listed <= as_of:
            td_listed = max(0, len(pd.bdate_range(listed, as_of)) - 1)
            graduates_on = pd.bdate_range(start=listed, periods=window + 1)[-1].date()
        else:
            td_listed = 0
            graduates_on = None
        holdings.append(
            SatelliteHolding(
                ticker=ticker,
                quantity=qty,
                price=price,
                value=value,
                book_weight=float(value / mv) if mv > 0 else 0.0,
                listed_date=listed,
                trading_days_listed=td_listed,
                window=window,
                ready_to_graduate=td_listed >= window,
                graduates_on=graduates_on,
                sell_advice=advise_sell(portfolio, ticker, price, as_of, cfg),
            )
        )
    holdings.sort(key=lambda h: h.value, reverse=True)
    total = satellite_value(portfolio, registry, prices_dec)
    return SatelliteReport(
        as_of=as_of,
        holdings=holdings,
        alerts=concentration_alerts(
            portfolio, registry, prices_dec, sleeve_cap=sleeve_cap, name_cap=name_cap
        ),
        total_value=total,
        sleeve_weight=float(total / mv) if mv > 0 else 0.0,
    )


def _rupees(value: Decimal) -> str:
    return f"₹{value:,.2f}"
