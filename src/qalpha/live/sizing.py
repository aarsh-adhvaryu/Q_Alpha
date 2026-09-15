"""From what the investor intends to what a book actually orders — by rules code enforces.

The investor states **intentions**, not share counts: which company, whether to open, add, hold,
reduce or exit, how convinced it is, what share of the book it wants, and why. This module turns
those into orders **for one book** — its holdings, its cash, its allowance, its rules. Two books
given the same intentions can order different things, which is exactly how the shadow comparison
tests a sizing rule without a second model call.

**Purchases are limited; selling is decided.** No rule here produces a sale. A holding that grows
past a limit on price alone pauses further purchases and is flagged for review; a sale happens only
when an intention says reduce or exit, with a reason.

**The allowance** (formula → example → why):

    A(m) = min(carry(m−1) + monthly, ceiling)          carry(m) = max(0, A(m) − purchases filled in m)
    available = A(m) − purchases filled this month − buy orders queued and not yet filled

Example with ₹50,000 a month and a ₹1,00,000 ceiling: September spends ₹20,000 → carry ₹30,000.
October: A = min(30,000 + 50,000, 1,00,000) = ₹80,000. A queued ₹25,000 order leaves ₹55,000.
Why: a month without conviction should not forfeit the month's money — but a year of unspent
instalments should not arrive as one lump either. **The allowance is not cash.** It limits buying;
when it expires no rupee of cash disappears, and a buy needs both.

**New positions** (expanding rules): open at ``max(tier target, ₹15,000)`` if cash, allowance and
caps allow it, otherwise do not open. At a ₹3 lakh book a starter's 2–3% is ₹6–9k, so it opens at
₹15,000 or not at all. The minimum and the name ceiling apply to **new purchases only**: an existing
position that has become small, or a count above the ceiling after a rule change, never causes a sale.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from typing import Any

from qalpha.accounting.costs import Side, compute_costs
from qalpha.accounting.portfolio import Portfolio
from qalpha.live.mandate import Sizing

OPEN, ADD, HOLD, REDUCE, EXIT = "open", "add", "hold", "reduce", "exit"
INTENTS = (OPEN, ADD, HOLD, REDUCE, EXIT)
CONVICTIONS = ("core", "standard", "starter")
BUY, SELL = "BUY", "SELL"


class IntentionError(ValueError):
    """An intention that cannot be sized as stated. The review records it; nothing is guessed."""


@dataclass(frozen=True)
class Intention:
    ticker: str
    intent: str
    conviction: str
    #: Share of the whole book (cash included) the investor wants in this name, as a fraction.
    desired_exposure: Decimal | None
    thesis: str
    reason: str
    invalidate_if: str
    evidence_ids: tuple[str, ...]

    def check(self, *, held: bool) -> None:
        if self.intent not in INTENTS:
            raise IntentionError(f"{self.ticker}: unknown intent {self.intent!r}")
        if self.conviction not in CONVICTIONS:
            raise IntentionError(f"{self.ticker}: conviction must be one of {CONVICTIONS}")
        if self.intent in (ADD, HOLD, REDUCE, EXIT) and not held:
            raise IntentionError(f"{self.ticker}: {self.intent} needs a holding; nothing is held")
        if self.intent == OPEN and held:
            raise IntentionError(f"{self.ticker}: already held — that is add, not open")
        if self.intent in (OPEN, ADD, REDUCE) and (
            self.desired_exposure is None or not Decimal("0") < self.desired_exposure < Decimal("1")
        ):
            raise IntentionError(
                f"{self.ticker}: {self.intent} needs a desired exposure between 0 and 1"
            )
        if self.intent in (REDUCE, EXIT) and not self.reason.strip():
            raise IntentionError(f"{self.ticker}: a sale needs its own investment or risk reason")


@dataclass(frozen=True)
class Order:
    ticker: str
    action: str  # BUY or SELL
    quantity: int
    #: What happened to the intention, in words, naming the rule that decided.
    status: str
    estimated_outlay: Decimal = Decimal("0")


@dataclass(frozen=True)
class Outcome:
    """What one intention produced for one book: an order or none, and why."""

    ticker: str
    intent: str
    order: Order | None
    status: str


# ---- the allowance ----------------------------------------------------------------------------


def month_of(day: date) -> str:
    return day.isoformat()[:7]


def _months(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def allowance(
    month: str, purchases: Mapping[str, Decimal], *, first_month: str, rules: Sizing
) -> Decimal:
    """A(m): this month's allowance before anything is bought in it. See the module docstring."""
    if month < first_month:
        return Decimal("0")
    carry = Decimal("0")
    value = Decimal("0")
    for m in _months(first_month, month):
        value = min(carry + rules.monthly_allowance, rules.allowance_ceiling)
        carry = max(Decimal("0"), value - purchases.get(m, Decimal("0")))
    return value


def available(
    month: str,
    purchases: Mapping[str, Decimal],
    *,
    pending_commitments: Decimal,
    first_month: str,
    rules: Sizing,
) -> Decimal:
    """What may still be committed to purchases this month. Never negative."""
    spent = purchases.get(month, Decimal("0"))
    return max(
        Decimal("0"),
        allowance(month, purchases, first_month=first_month, rules=rules)
        - spent
        - pending_commitments,
    )


def commitment(
    orders: Sequence[Mapping[str, Any]], prices: Mapping[str, Decimal], portfolio: Portfolio
) -> Decimal:
    """Queued, unfilled buys at their decision price plus estimated costs."""
    total = Decimal("0")
    for o in orders:
        if o.get("action") != BUY or int(o.get("quantity", 0)) <= 0:
            continue
        price = Decimal(str(o.get("price") or prices.get(str(o["ticker"]), Decimal("0"))))
        qty = Decimal(int(o["quantity"]))
        total += qty * price + compute_costs(Side.BUY, qty, price, portfolio.cost_cfg).total
    return total


# ---- sizing -----------------------------------------------------------------------------------


def _values(portfolio: Portfolio, prices: Mapping[str, Decimal]) -> dict[str, Decimal]:
    return {t: q * prices[t] for t, q in portfolio.positions().items() if q > 0 and t in prices}


def _nav(portfolio: Portfolio, prices: Mapping[str, Decimal]) -> Decimal:
    return portfolio.cash + sum(_values(portfolio, prices).values(), Decimal("0"))


def target_share(intention: Intention, rules: Sizing) -> tuple[Decimal, str]:
    """The share of the book this intention may aim at, and a note when a rule moved it."""
    desired = intention.desired_exposure or Decimal("0")
    if rules.tiers is None:
        if desired > rules.name_cap:
            return (
                rules.name_cap,
                f"desired {desired:.0%} capped at the {rules.name_cap:.0%} name limit",
            )
        return desired, ""
    low, high = rules.tiers[intention.conviction]
    if desired < low:
        return low, f"desired {desired:.1%} raised to the {intention.conviction} tier's {low:.0%}"
    if desired > high:
        return (
            high,
            f"desired {desired:.1%} lowered to the {intention.conviction} tier's {high:.0%}",
        )
    return desired, ""


def _fits(
    portfolio: Portfolio,
    ticker: str,
    qty: int,
    prices: Mapping[str, Decimal],
    sectors: Mapping[str, str],
    on: date,
    rules: Sizing,
    budget: Decimal,
) -> bool:
    trial = portfolio.clone()
    trade = trial.buy(on, ticker, Decimal(qty), prices[ticker])
    if trade is None or int(trade.quantity) != qty or trial.cash < 0:
        return False
    if Decimal(qty) * prices[ticker] + trade.cost > budget:
        return False
    nav = _nav(trial, prices)
    values = _values(trial, prices)
    sector_value = sum(
        (v for t, v in values.items() if sectors.get(t) == sectors[ticker]), Decimal("0")
    )
    return (
        values.get(ticker, Decimal("0")) <= nav * rules.name_cap
        and sector_value <= nav * rules.sector_cap
    )


def _largest(portfolio: Portfolio, ticker: str, wanted: int, **kw: Any) -> int:
    lo, hi = 0, max(0, wanted)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _fits(portfolio, ticker, mid, **kw):
            lo = mid
        else:
            hi = mid - 1
    return lo


def plan(
    portfolio: Portfolio,
    intentions: Sequence[Intention],
    *,
    prices: Mapping[str, Decimal],
    sectors: Mapping[str, str],
    on: date,
    rules: Sizing,
    budget: Decimal,
) -> list[Outcome]:
    """Size every intention for this book. Sells first, then buys by conviction. Mutates a clone only.

    ``budget`` is :func:`available` for this book. Each outcome names the rule that decided it.
    """
    book = portfolio.clone()
    held = {t for t, q in book.positions().items() if q > 0}
    outcomes: list[Outcome] = []
    for i in intentions:
        i.check(held=i.ticker in held)

    for i in [x for x in intentions if x.intent in (REDUCE, EXIT)]:
        price = prices.get(i.ticker)
        qty_held = int(book.positions().get(i.ticker, Decimal("0")))
        if price is None:
            outcomes.append(Outcome(i.ticker, i.intent, None, "not sold: no price today"))
            continue
        if i.intent == EXIT:
            qty = qty_held
        else:
            target = (i.desired_exposure or Decimal("0")) * _nav(book, prices)
            excess = Decimal(qty_held) * price - target
            qty = (
                min(qty_held, int((excess / price).to_integral_value(rounding=ROUND_CEILING)))
                if excess > 0
                else 0
            )
        if qty <= 0:
            outcomes.append(
                Outcome(
                    i.ticker,
                    i.intent,
                    None,
                    "nothing to sell: already at or below the desired exposure",
                )
            )
            continue
        book.sell(on, i.ticker, Decimal(qty), price)
        order = Order(i.ticker, SELL, qty, f"{i.intent}: {i.reason}")
        outcomes.append(Outcome(i.ticker, i.intent, order, order.status))

    for i in [x for x in intentions if x.intent == HOLD]:
        outcomes.append(Outcome(i.ticker, i.intent, None, "held"))

    rank = {c: n for n, c in enumerate(CONVICTIONS)}
    left = budget
    for i in sorted(
        (x for x in intentions if x.intent in (OPEN, ADD)),
        key=lambda x: (rank[x.conviction], x.ticker),
    ):
        price, sector = prices.get(i.ticker), sectors.get(i.ticker)
        if price is None or price <= 0:
            outcomes.append(Outcome(i.ticker, i.intent, None, "not bought: no price today"))
            continue
        if not sector:
            outcomes.append(Outcome(i.ticker, i.intent, None, "not bought: sector unknown"))
            continue
        nav = _nav(book, prices)
        values = _values(book, prices)
        name_now = values.get(i.ticker, Decimal("0"))
        sector_now = sum((v for t, v in values.items() if sectors.get(t) == sector), Decimal("0"))
        if nav > 0 and name_now > nav * rules.review_name_above:
            outcomes.append(
                Outcome(
                    i.ticker,
                    i.intent,
                    None,
                    f"paused: {i.ticker} is {name_now / nav:.1%} of the book, above {rules.review_name_above:.0%} — review, not a sale",
                )
            )
            continue
        if nav > 0 and sector_now > nav * rules.review_sector_above:
            outcomes.append(
                Outcome(
                    i.ticker,
                    i.intent,
                    None,
                    f"paused: sector {sector} is {sector_now / nav:.1%} of the book, above {rules.review_sector_above:.0%} — review, not a sale",
                )
            )
            continue
        is_new = i.ticker not in {t for t, q in book.positions().items() if q > 0}
        count = len([t for t, q in book.positions().items() if q > 0])
        if is_new and count >= rules.max_names:
            outcomes.append(
                Outcome(
                    i.ticker,
                    i.intent,
                    None,
                    f"not opened: already {count} names (ceiling {rules.max_names}, new names only)",
                )
            )
            continue
        share, note = target_share(i, rules)
        want_value = share * nav - name_now
        if is_new:
            want_value = max(want_value, rules.min_new_position)
        if want_value <= 0:
            outcomes.append(
                Outcome(i.ticker, i.intent, None, "not bought: already at or above its target")
            )
            continue
        wanted = int((want_value / price).to_integral_value(rounding=ROUND_DOWN))
        if is_new and rules.min_new_position > 0:
            wanted = max(
                wanted,
                int((rules.min_new_position / price).to_integral_value(rounding=ROUND_CEILING)),
            )
        qty = _largest(
            book, i.ticker, wanted, prices=prices, sectors=sectors, on=on, rules=rules, budget=left
        )
        if is_new and rules.min_new_position > 0 and Decimal(qty) * price < rules.min_new_position:
            outcomes.append(
                Outcome(
                    i.ticker,
                    i.intent,
                    None,
                    f"not opened: ₹{rules.min_new_position:,.0f} minimum does not fit cash, the allowance "
                    f"(₹{left:,.0f} left) or the {rules.name_cap:.0%}/{rules.sector_cap:.0%} limits",
                )
            )
            continue
        if qty <= 0:
            outcomes.append(
                Outcome(
                    i.ticker,
                    i.intent,
                    None,
                    f"not bought: cash, the allowance (₹{left:,.0f} left) or the limits allow none",
                )
            )
            continue
        trade = book.buy(on, i.ticker, Decimal(qty), price)
        if trade is None:
            outcomes.append(Outcome(i.ticker, i.intent, None, "not bought: cash allows none"))
            continue
        outlay = Decimal(int(trade.quantity)) * price + trade.cost
        left -= outlay
        status = (
            "bought"
            if int(trade.quantity) >= wanted
            else f"cut from {wanted} to {int(trade.quantity)} by cash, allowance or limits"
        )
        if note:
            status = f"{status}; {note}"
        order = Order(i.ticker, BUY, int(trade.quantity), status, outlay)
        outcomes.append(Outcome(i.ticker, i.intent, order, status))
    return outcomes


# ---- comparing books --------------------------------------------------------------------------


def metrics(
    portfolio: Portfolio, prices: Mapping[str, Decimal], sectors: Mapping[str, str]
) -> dict[str, Any]:
    """What expansion should change, measured the same way for every book."""
    values = _values(portfolio, prices)
    nav = _nav(portfolio, prices)
    if nav <= 0:
        return {"nav": "0", "why": "the book has no value"}
    weights = [v / nav for v in values.values()]
    invested = sum(weights, Decimal("0"))
    by_sector: dict[str, Decimal] = {}
    for t, v in values.items():
        by_sector[sectors.get(t, "unknown")] = (
            by_sector.get(sectors.get(t, "unknown"), Decimal("0")) + v
        )
    concentration = sum((w * w for w in weights), Decimal("0"))
    return {
        "nav": str(round(nav, 2)),
        "cash": str(round(portfolio.cash, 2)),
        "deployed_pct": round(float(invested) * 100, 2),
        "names": len(values),
        # 1 / Σw² over holdings, weights of the invested part: how many equal positions this book is like.
        "effective_names": None
        if invested == 0
        else round(float(invested * invested / concentration), 2),
        "largest_name_pct": None if not weights else round(float(max(weights)) * 100, 2),
        "largest_sector_pct": None
        if not by_sector
        else round(float(max(by_sector.values()) / nav) * 100, 2),
    }
