"""Current valuation facts for a pre-trade check — the gap VBL exposed.

**The defect this closes.** ``deploy.cheapness_scores`` measures the *fractional pullback below a
name's own 1-year high* and its docstring is explicit that this is "a **technical** cheapness proxy,
not fundamental valuation". The screen then ranks candidates **by** that pullback. So a name that fell
a long way is, to this system, definitionally attractive — and it has no way at all to ask whether the
fall made it cheap or merely less expensive.

VBL is the case. It fell ₹669 → ₹412, which the screen scores as 23.8% "cheap", while the exchange
was showing a **regulatory caution: "Scrip PE is greater than 50"**. A −38% fall that leaves a name
above P/E 50 means it was priced near P/E 80 before. Nothing was on sale. Zerodha's order window said
so and Q-Alpha said the opposite, because Q-Alpha reads prices and only prices.

**Why this is not "the data-blocked fundamentals problem".** That problem is *historical
point-in-time* fundamentals — earnings for ~75 names including delisted ones, each lagged to its real
publication date, so a backtest cannot see a number before it existed. It is hard and it stays open.
This module needs something completely different: **today's P/E for ~95 live names**, for a check that
runs before an order. One request per name, no history, no look-ahead surface at all.

**This is a check, never a factor.** It does not re-rank, re-weight or re-select — selection stays
deterministic and unchanged (the locked "flag, don't veto" discipline). It answers one question about
a name the screen has *already* chosen: is there a published reason to be careful?

**The threshold is the exchange's, not ours.** P/E > 50 is the level NSE/BSE themselves caution on, so
mirroring it requires no validation and invents no factor — we are surfacing a regulatory message the
user's broker already shows, which this system was talking over.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

#: The exchange's own cautionary threshold. Mirrored, not invented.
PE_CAUTION = 50.0
#: Kite nudges on stocks under this market cap as illiquid and manipulation-prone.
MIN_MARKET_CAP = 100_00_00_000  # ₹100 crore
#: Where the daily snapshot lands. Small, append-safe, committed by the cron.
VALUATION_CACHE = Path("data/valuation/snapshot.json")

#: Fetch one name's facts. Injectable so every function here is pure and CI never touches a network.
FetchFn = Callable[[str], Mapping[str, object]]


@dataclass(frozen=True)
class Valuation:
    """What is publicly known about a name's price *relative to its earnings*, and when we learned it.

    ``pe is None`` is a real state and must never be read as "fine": a loss-making company has no
    meaningful P/E, and a missing field is not evidence of cheapness. Both surface as UNKNOWN.
    """

    ticker: str
    pe: float | None
    forward_pe: float | None
    market_cap: float | None
    retrieved_at: datetime
    source: str = "yfinance"

    @property
    def rich(self) -> bool:
        """Above the exchange's published caution level."""
        return self.pe is not None and self.pe > PE_CAUTION

    @property
    def illiquid(self) -> bool:
        return self.market_cap is not None and self.market_cap < MIN_MARKET_CAP

    @property
    def unknown(self) -> bool:
        """No usable P/E — loss-making, or the field is absent. Reported, never assumed benign."""
        return self.pe is None or self.pe <= 0

    def caution(self) -> str | None:
        """The one-line reason to be careful, or ``None`` when nothing is flagged."""
        if self.illiquid:
            cr = (self.market_cap or 0) / 1_00_00_000
            return f"market cap ₹{cr:,.0f} cr is below ₹100 cr — illiquid and manipulation-prone"
        if self.rich:
            return f"P/E {self.pe:.1f} is above the exchange's caution level of {PE_CAUTION:.0f}"
        if self.unknown:
            return "no usable P/E (loss-making or not reported) — valuation cannot be assessed"
        return None


@dataclass(frozen=True)
class ValuationReport:
    """The valuation facts for one proposed basket."""

    as_of: date
    valuations: tuple[Valuation, ...] = field(default_factory=tuple)

    @property
    def cautioned(self) -> tuple[Valuation, ...]:
        return tuple(v for v in self.valuations if v.caution() is not None)

    @property
    def clear(self) -> bool:
        return not self.cautioned

    def render(self) -> str:
        """Plain English. This lands on a surface where the label becomes an order."""
        if not self.valuations:
            return "No valuation data — **cannot assess** whether these names are expensive."
        if self.clear:
            inside = ", ".join(
                f"{v.ticker.removesuffix('.NS')} {v.pe:.0f}" for v in self.valuations if v.pe
            )
            return f"**Valuation check passed.** P/E: {inside}."
        lines = [
            "⚠️ **The screen calls these cheap because they fell. Valuation disagrees.**",
            "",
            "A large fall is not the same as a low price. A name that dropped 38% and still trades",
            "above P/E 50 was priced near P/E 80 before — nothing went on sale.",
            "",
        ]
        lines += [f"- **{v.ticker.removesuffix('.NS')}** — {v.caution()}" for v in self.cautioned]
        return "\n".join(lines)


def _default_fetch(ticker: str) -> Mapping[str, object]:
    """Lazy so ``yfinance`` is never imported in a pure test path."""
    import yfinance as yf

    return dict(yf.Ticker(ticker).info)


def _as_float(value: object) -> float | None:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if out != out else out  # NaN is not a number we can act on


def fetch_valuations(
    tickers: Iterable[str],
    *,
    fetch: FetchFn | None = None,
    now: datetime | None = None,
) -> dict[str, Valuation]:
    """Current P/E and market cap per name. A failure yields UNKNOWN, never a guess.

    Fail-soft per ticker: one name's missing data must not deny the whole basket a check.
    """
    fetch = fetch or _default_fetch
    stamp = now or datetime.now(UTC)
    out: dict[str, Valuation] = {}
    for ticker in tickers:
        try:
            info = fetch(ticker)
        except Exception as exc:
            print(f"[valuation] {ticker}: {type(exc).__name__} — recorded as unknown ({exc})")
            info = {}
        out[ticker] = Valuation(
            ticker=ticker,
            pe=_as_float(info.get("trailingPE")),
            forward_pe=_as_float(info.get("forwardPE")),
            market_cap=_as_float(info.get("marketCap")),
            retrieved_at=stamp,
        )
    return out


def check_basket(
    tickers: Iterable[str], valuations: Mapping[str, Valuation], *, as_of: date
) -> ValuationReport:
    """Assess the names actually being recommended. A name with no entry is UNKNOWN, not absent."""
    rows = tuple(
        valuations.get(t)
        or Valuation(t, None, None, None, retrieved_at=datetime.now(UTC), source="missing")
        for t in sorted(set(tickers))
    )
    return ValuationReport(as_of=as_of, valuations=rows)


def save_snapshot(valuations: Mapping[str, Valuation], *, path: Path = VALUATION_CACHE) -> int:
    """Persist the day's facts with provenance, so a decision can be replayed against what we saw."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source": "yfinance",
        "names": {
            t: {
                "pe": v.pe,
                "forward_pe": v.forward_pe,
                "market_cap": v.market_cap,
                "retrieved_at": v.retrieved_at.isoformat(),
            }
            for t, v in sorted(valuations.items())
        },
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(valuations)


def load_snapshot(path: Path = VALUATION_CACHE) -> dict[str, Valuation]:
    """Read yesterday's facts. Missing file → empty, which reads as UNKNOWN everywhere downstream."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, Valuation] = {}
    for ticker, row in (raw.get("names") or {}).items():
        try:
            stamp = datetime.fromisoformat(str(row.get("retrieved_at")))
        except (TypeError, ValueError):
            continue
        out[str(ticker)] = Valuation(
            ticker=str(ticker),
            pe=_as_float(row.get("pe")),
            forward_pe=_as_float(row.get("forward_pe")),
            market_cap=_as_float(row.get("market_cap")),
            retrieved_at=stamp,
        )
    return out
