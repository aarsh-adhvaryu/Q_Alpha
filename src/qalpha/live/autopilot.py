"""Auto-pilot — the fake-money "watch the system invest & see if it works" core.

The advisor recommends buys ("what to do"); the auto-pilot *follows its own advice* forward on fake
money so you can watch it play out. Three books, identical cash flows, answer the two questions:
**A** strategy only · **B** strategy + the AI's daily nudge · **C** buy-and-hold NIFTYBEES — so
*A vs C* = "does deploy-into-weakness beat holding?" and *B vs A* = "does the AI insight help?".

This module is the pure, tested core — the AI signal, the fixed deploy-tilt rule, capital-flow-aware
book accounting, and the decision-and-outcome ledger. No I/O beyond JSON round-trips; the daily runner
(``scripts/autopilot.py``) and the dashboard sit on top. Money is ``Decimal`` (project convention).

**Rule (a) is intact:** the auto-pilot drives the *advisor* (``advise_deploy_into_weakness``), never
the backtest engine, and the AI is a context-only nudge that never computes a number — so the
validated headline stays provably unchanged. The AI signal is **unvalidated by construction** —
measuring whether acting on it helps is the whole point (see ``docs/PREREGISTRATION_autopilot.md``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

# ---- the AI signal --------------------------------------------------------------------------------

_LEANS = {"up", "flat", "down"}
_CONF = {"low", "medium", "high"}
# Book B's fixed deploy tilt: 1.0 ± (direction × confidence weight), clamped. Pre-registered — not
# tuned to a result. up+high → deploy 1.4×; down+high → 0.6×; flat or absent → 1.0×.
_CONF_WEIGHT = {"low": 0.10, "medium": 0.25, "high": 0.40}
_TILT_MIN, _TILT_MAX = 0.5, 1.5
# The machine-readable line the AI brief appends, e.g. "SIGNAL: lean=up; band=0.4..0.9; confidence=medium"
_SIGNAL_RE = re.compile(
    r"SIGNAL:\s*lean=(?P<lean>up|flat|down)\s*;\s*band=(?P<lo>-?\d+(?:\.\d+)?)\.\.(?P<hi>-?\d+(?:\.\d+)?)\s*;\s*confidence=(?P<conf>low|medium|high)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AISignal:
    """A day's structured read, parsed from the brief. ``lean`` ∈ up/flat/down; ``confidence`` too."""

    as_of: str
    lean: str
    confidence: str
    band_lo: float
    band_hi: float

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "lean": self.lean,
            "confidence": self.confidence,
            "band_lo": self.band_lo,
            "band_hi": self.band_hi,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> AISignal:
        return cls(
            as_of=str(d["as_of"]),
            lean=str(d["lean"]),
            confidence=str(d["confidence"]),
            band_lo=float(d["band_lo"]),  # type: ignore[arg-type]
            band_hi=float(d["band_hi"]),  # type: ignore[arg-type]
        )


def parse_ai_signal(brief_text: str, as_of: str) -> AISignal | None:
    """Extract the structured ``SIGNAL:`` line from a brief; ``None`` if absent/malformed (fail-soft
    → Book B then falls back to a neutral 1.0× tilt, so a missing signal can't break the study)."""
    m = _SIGNAL_RE.search(brief_text or "")
    if not m:
        return None
    lean, conf = m.group("lean").lower(), m.group("conf").lower()
    if lean not in _LEANS or conf not in _CONF:
        return None
    return AISignal(as_of, lean, conf, float(m.group("lo")), float(m.group("hi")))


def signal_tilt(signal: AISignal | None) -> float:
    """The fixed deploy-size multiplier Book B applies to the strategy's deploy amount. Neutral (1.0)
    when there is no signal or the lean is flat. Clamped to [0.5, 1.5]. Pre-registered, never tuned."""
    if signal is None or signal.lean == "flat":
        return 1.0
    direction = 1.0 if signal.lean == "up" else -1.0
    tilt = 1.0 + direction * _CONF_WEIGHT.get(signal.confidence, 0.0)
    return max(_TILT_MIN, min(_TILT_MAX, tilt))


# ---- cash-flow schedule (pre-registered; see the prereg) -----------------------------------------

SEED_LUMP = Decimal("100000")  # one-time seed on FORWARD_START, all three books
MONTHLY_DEPOSIT = Decimal(
    "50000"
)  # added on the first trading session of each month, all three books


def scheduled_injection(
    as_of: str, *, seeded: bool, last_deposit_month: str | None
) -> tuple[Decimal, str | None]:
    """The pre-registered mechanical deposit due on ``as_of`` (ISO ``YYYY-MM-DD``), and the new
    'last deposited month' marker to persist.

    - The **first-ever** run (``seeded`` False) deposits ``SEED_LUMP`` and also counts as that month's
      deposit, so the seed month isn't double-funded.
    - Otherwise, the **first run in a new calendar month** deposits ``MONTHLY_DEPOSIT`` (holiday-robust:
      whatever the first *observed* session of the month is).
    - Any later run in the same month deposits ₹0.

    Manual injections are handled separately (they are discretionary, not scheduled). Returns
    ``(amount, new_last_deposit_month)`` where the month marker is ``"YYYY-MM"``.
    """
    month = as_of[:7]
    if not seeded:
        return SEED_LUMP, month
    if month != last_deposit_month:
        return MONTHLY_DEPOSIT, month
    return Decimal("0"), last_deposit_month


# ---- deploy sizing (tranche of the wallet, scaling with weakness) --------------------------------

# Fraction of the idle wallet to deploy at each market-weakness level. Always opportunistic (a base
# even when calm — the engine tilts to the individual most out-of-favour names); more on dips.
# Fixed here, not tuned to a result (pre-registered).
_TRANCHE = {"normal": Decimal("0.25"), "elevated": Decimal("0.50"), "deep": Decimal("1.00")}


def deploy_fraction(market_level: str) -> Decimal:
    """The fraction of the idle wallet Book A deploys at this broad-weakness level."""
    return _TRANCHE.get(market_level, Decimal("0"))


def book_deploy_amount(
    wallet: Decimal, market_level: str, signal: AISignal | None, *, ai: bool
) -> Decimal:
    """How much of the wallet to deploy today. Book A = tranche × wallet; Book B additionally tilts by
    the AI signal. Always capped at the wallet and rounded to paise."""
    amount = wallet * deploy_fraction(market_level)
    if ai:
        amount *= Decimal(str(signal_tilt(signal)))
    amount = min(amount, wallet)
    return amount.quantize(Decimal("0.01"))


# ---- capital-flow-aware book accounting -----------------------------------------------------------


def _int_map(v: object) -> dict[str, int]:
    """Parse a JSON object into a ``{str: int}`` map (empty if it isn't a dict) — typed for mypy."""
    if not isinstance(v, dict):
        return {}
    return {str(k): int(val) for k, val in v.items()}


@dataclass
class Book:
    """One fake-money book. ``net_contributions`` (fake cash put in) is tracked apart from value, so an
    injection is never mistaken for profit: ``profit = value − net_contributions``."""

    name: str
    cash: Decimal = Decimal("0")
    holdings: dict[str, int] = field(default_factory=dict)
    net_contributions: Decimal = Decimal("0")
    # The day this book started measuring (PR-4 / T2.1). Without it a book's return is a number with
    # no window, and two books started weeks apart get compared as though they covered the same
    # period — which is exactly how one NIFTYBEES series came to look like two contradictory
    # baselines (+0.98% and +3.92%, 28 days apart). Recoverable only from system_track.csv before.
    start_date: date | None = None

    def inject(self, amount: Decimal, on: date | None = None) -> None:
        """Add fake cash (an external contribution, not a gain).

        The first injection stamps ``start_date`` when ``on`` is given — the book begins measuring
        the day it is first funded, not the day the file happens to be created.
        """
        self.cash += amount
        self.net_contributions += amount
        if self.start_date is None and on is not None:
            self.start_date = on

    def buy(self, ticker: str, qty: int, price: Decimal) -> None:
        """Buy whole shares with cash (no tax on buys). Raises if it can't afford it."""
        cost = price * qty
        if cost > self.cash:
            raise ValueError(
                f"{self.name}: cannot afford {qty}×{ticker} @ {price} (cash {self.cash})"
            )
        self.cash -= cost
        self.holdings[ticker] = self.holdings.get(ticker, 0) + qty

    def value(self, prices: dict[str, Decimal]) -> Decimal:
        """Mark-to-market: cash + held shares valued at ``prices`` (missing price → that name skipped)."""
        held = sum(prices.get(t, Decimal("0")) * q for t, q in self.holdings.items())
        return self.cash + held

    def profit(self, prices: dict[str, Decimal]) -> Decimal:
        return self.value(prices) - self.net_contributions

    def return_pct(self, prices: dict[str, Decimal]) -> float:
        """Profit as a % of what was put in (money-weighted; fair across books with equal cash flows)."""
        if self.net_contributions <= 0:
            return 0.0
        return float(self.profit(prices) / self.net_contributions) * 100.0

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "name": self.name,
            "cash": str(self.cash),
            "holdings": dict(self.holdings),
            "net_contributions": str(self.net_contributions),
        }
        if self.start_date is not None:
            out["start_date"] = self.start_date.isoformat()
        return out

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Book:
        raw_start = d.get("start_date")
        return cls(
            name=str(d["name"]),
            cash=Decimal(str(d["cash"])),
            holdings=_int_map(d.get("holdings")),
            net_contributions=Decimal(str(d["net_contributions"])),
            start_date=date.fromisoformat(str(raw_start)) if raw_start else None,
        )


# ---- decision + outcome ledger --------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """One logged deploy, with the model reason + AI insight at the time and its later outcome.

    Outcome fields are filled once ``resolve_on`` passes: the bought basket's realised return over the
    window vs Nifty → ``verdict`` (worked / didn't / flat)."""

    as_of: str
    book: str  # "A" | "B"
    amount: str  # Decimal deployed (as str)
    basket: dict[str, int]  # ticker -> qty bought
    model_rationale: str
    ai_insight: str  # e.g. "lean=up confidence=medium (tilt 1.25×)" — snapshot at decision time
    resolve_on: str  # date to score the outcome
    resolved: bool = False
    outcome_return_pct: float | None = None
    benchmark_return_pct: float | None = None
    verdict: str = ""  # "worked" | "didn't" | "flat" | ""

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "book": self.book,
            "amount": self.amount,
            "basket": dict(self.basket),
            "model_rationale": self.model_rationale,
            "ai_insight": self.ai_insight,
            "resolve_on": self.resolve_on,
            "resolved": self.resolved,
            "outcome_return_pct": self.outcome_return_pct,
            "benchmark_return_pct": self.benchmark_return_pct,
            "verdict": self.verdict,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Decision:
        return cls(
            as_of=str(d["as_of"]),
            book=str(d["book"]),
            amount=str(d["amount"]),
            basket=_int_map(d.get("basket")),
            model_rationale=str(d.get("model_rationale", "")),
            ai_insight=str(d.get("ai_insight", "")),
            resolve_on=str(d["resolve_on"]),
            resolved=bool(d.get("resolved", False)),
            outcome_return_pct=_opt_float(d.get("outcome_return_pct")),
            benchmark_return_pct=_opt_float(d.get("benchmark_return_pct")),
            verdict=str(d.get("verdict", "")),
        )


def _opt_float(v: object) -> float | None:
    return None if v is None else float(v)  # type: ignore[arg-type]


_WORK_TOL = 0.5  # a decision "worked" only if it beat Nifty by > 0.5 pt over its window (else flat)


def resolve_decision(
    decision: Decision, basket_return_pct: float, benchmark_return_pct: float
) -> Decision:
    """Fill in a due decision's outcome and verdict (pure — returns a new resolved ``Decision``)."""
    gap = basket_return_pct - benchmark_return_pct
    verdict = "worked" if gap > _WORK_TOL else ("didn't" if gap < -_WORK_TOL else "flat")
    return Decision(
        as_of=decision.as_of,
        book=decision.book,
        amount=decision.amount,
        basket=decision.basket,
        model_rationale=decision.model_rationale,
        ai_insight=decision.ai_insight,
        resolve_on=decision.resolve_on,
        resolved=True,
        outcome_return_pct=basket_return_pct,
        benchmark_return_pct=benchmark_return_pct,
        verdict=verdict,
    )


def ai_hit_rate(decisions: list[Decision], book: str = "B") -> tuple[int, int]:
    """Over resolved decisions of the AI-tilted ``book`` ("B" in the wallet study; "SYS" in the
    System book), (times the deploy beat Nifty, total resolved) — the running 'did acting on the AI
    work' tally. Returns (0, 0) when nothing has resolved yet."""
    resolved = [d for d in decisions if d.resolved and d.book == book]
    worked = sum(1 for d in resolved if d.verdict == "worked")
    return worked, len(resolved)


# ---- outcome scoring helpers (pure) --------------------------------------------------------------


def basket_value(basket: dict[str, int], prices: dict[str, Decimal]) -> Decimal:
    """Mark a bought basket (ticker → qty) to ``prices`` (a missing price contributes 0)."""
    return sum((prices.get(t, Decimal("0")) * q for t, q in basket.items()), start=Decimal("0"))


def pct_return(entry: Decimal, exit_: Decimal) -> float:
    """Simple percentage return ``(exit/entry − 1) × 100``; 0.0 when ``entry`` is non-positive."""
    if entry <= 0:
        return 0.0
    return float((exit_ - entry) / entry) * 100.0


def due_decisions(ledger: list[Decision], as_of: str) -> list[Decision]:
    """Unresolved decisions whose ``resolve_on`` has arrived (``≤ as_of``) — ready to be scored."""
    return [d for d in ledger if not d.resolved and d.resolve_on <= as_of]


# ---- persistence ----------------------------------------------------------------------------------

LEDGER_PATH = Path("data/autopilot/ledger.json")


def load_ledger(path: Path = LEDGER_PATH) -> list[Decision]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [Decision.from_dict(d) for d in json.loads(text)]


def save_ledger(decisions: list[Decision], path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([d.to_dict() for d in decisions], indent=2) + "\n", encoding="utf-8")


# The three books, their wallet state, and the manual-injection log — persisted so the daily runner
# and the dashboard's "Add money" button share one source of truth.
BOOK_NAMES = ("A", "B", "C")
BOOKS_PATH = Path("data/autopilot/books.json")
STATE_PATH = Path("data/autopilot/state.json")
MANUAL_LOG_PATH = Path("data/autopilot/manual_injections.json")


def load_books(path: Path = BOOKS_PATH) -> dict[str, Book]:
    """The three books (fresh empty ones if none persisted yet)."""
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return {n: Book.from_dict(data[n]) for n in BOOK_NAMES}
    return {n: Book(name=n) for n in BOOK_NAMES}


def save_books(books: dict[str, Book], path: Path = BOOKS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {n: books[n].to_dict() for n in BOOK_NAMES}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_state(path: Path = STATE_PATH) -> dict[str, object]:
    """Wallet/run state: ``seeded``, ``last_deposit_month`` (funding is manual — no auto-deposit)."""
    if path.exists():
        data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
        return data
    return {"seeded": False, "last_deposit_month": None}


def save_state(state: dict[str, object], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def inject_all(books: dict[str, Book], amount: Decimal) -> None:
    """Deposit the SAME fake cash into all three books (so a top-up can never bias the A/B/C verdict)."""
    for n in BOOK_NAMES:
        books[n].inject(amount)


# ---- fixed-notional baskets: making System − Shadow an ablation (PLAN_TRUST_REPAIR PR-7) ----------
#
# The pre-registration says the AI tilt changes deploy **size only**. It did not. Each book called the
# advisor with its *own* portfolio and its *own* amount, and two mechanisms turned a size difference
# into a composition difference: ``max_name_fraction`` filters candidates by ``price ≤ amount × 0.20``,
# so a smaller deploy sees a smaller universe; and whole-share rounding drops different names at
# different scales. Six weeks of that compounded into two different funds — 32 names vs 28, only 26
# shared — and a "did the AI help?" signal of ₹1,541 sitting under ₹1,964 of one day's rounding noise.
#
# The fix: compute the day's basket **once**, at a fixed reference notional, against an empty book.
# Both books then execute *that* basket, scaled. Composition is identical by construction, so the only
# thing System − Shadow can measure is the thing the study is about.

#: The notional the day's basket is computed at. Fixed and arbitrary — it must not track either
#: book's size, or the amount-dependence this exists to remove creeps straight back in.
REFERENCE_NOTIONAL = Decimal("100000")


def scaled_basket(
    reference: Mapping[str, int], amount: Decimal, notional: Decimal = REFERENCE_NOTIONAL
) -> dict[str, int]:
    """Scale a reference basket's whole-share quantities to ``amount``.

    Truncating (not rounding) keeps the executed value at or below the scaled target, which matters
    because ``Portfolio.buy`` is cash-capped — a rounded-up order would silently shrink and reintroduce
    the amount-dependence. Names that scale below one whole share come back as ``0`` rather than being
    dropped here, so the caller can see them and make a *symmetric* decision about both books.
    """
    if notional <= 0 or amount <= 0:
        return dict.fromkeys(reference, 0)
    scale = amount / notional
    return {t: int(Decimal(q) * scale) for t, q in reference.items()}


def common_basket(*baskets: Mapping[str, int]) -> set[str]:
    """The names every book can actually buy at its own size — the executable intersection.

    Dropping a name from *one* book because it rounded to zero there is precisely how composition
    drifted apart. Deciding it once, across all books, is what makes the difference between them
    purely a matter of size.
    """
    if not baskets:
        return set()
    sets = [{t for t, q in b.items() if q > 0} for b in baskets]
    return set.intersection(*sets) if sets else set()


# Pending manual injections queued by the dashboard's Add-money button. Because the dashboard (Streamlit
# Cloud) and the daily runner (GitHub Actions) are different machines, the button writes here IN THE REPO
# (via the GitHub API); the runner applies + clears them, staying the sole writer of ``books.json``.
PENDING_PATH = Path("data/autopilot/pending_injections.json")


def load_pending(path: Path = PENDING_PATH) -> list[dict[str, object]]:
    """Queued deposits the runner hasn't applied yet (empty if none)."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    data = json.loads(text)
    return data if isinstance(data, list) else []


def entry_id(item: Mapping[str, object]) -> str:
    """A stable identity for one queued deposit.

    The queue is written by the Streamlit host and read by the Actions runner — two machines, no
    lock — so an entry has to be identifiable by *content*, not by its position in a list. Entries
    queued before ids existed get a deterministic hash of their own fields, so the same legacy entry
    always resolves to the same id and can still be claimed exactly once.
    """
    existing = item.get("id")
    if existing:
        return str(existing)
    raw = f"{item.get('at', '')}|{item.get('amount', '0')}|{item.get('reason', '')}"
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


@dataclass(frozen=True)
class AppliedInjection:
    """One deposit the runner has credited to the books but not yet durably saved."""

    entry_id: str
    amount: Decimal
    reason: str


def clear_pending(path: Path = PENDING_PATH) -> None:
    """Empty the whole queue. **Prefer :func:`clear_applied`** — this truncates unconditionally and
    will destroy anything queued since the runner last read the file. Kept for tests and recovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]\n", encoding="utf-8")


def clear_applied(applied: Sequence[AppliedInjection], path: Path = PENDING_PATH) -> int:
    """Remove **only** the entries the runner actually applied; return how many survived.

    The bug this closes (T3.2): the runner used to truncate the queue to ``[]`` after reading it, so a
    deposit queued by the dashboard between the read and the write was **destroyed unread** — the same
    failure family as the ₹50k lost in July. Re-reading here is what makes that safe: entries that
    arrived in the meantime are unknown to ``applied``, so they are written back and picked up on the
    next run instead of vanishing.

    Call this **after** the books are persisted. Clearing first meant a crash anywhere in the long
    deploy/gate/mark pipeline that follows left the queue empty and the money never credited — a
    strictly worse outcome than a deposit applied twice.
    """
    claimed = {a.entry_id for a in applied}
    survivors = [item for item in load_pending(path) if entry_id(item) not in claimed]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(survivors, indent=2) + "\n", encoding="utf-8")
    return len(survivors)


def apply_pending(
    books: dict[str, Book], path: Path = PENDING_PATH
) -> tuple[Decimal, list[AppliedInjection]]:
    """Deposit every queued injection into all three books. Returns the total applied (₹0 if the
    queue was empty) and the claimed entries.

    **Does not clear the queue** — the caller must call :func:`clear_applied` once the books are
    durably saved, and :func:`log_manual_injection` for the audit trail. Both orderings are
    load-bearing: see those functions for the money that was lost learning it.
    """
    total = Decimal("0")
    applied: list[AppliedInjection] = []
    for item in load_pending(path):
        amt = Decimal(str(item.get("amount", "0")))
        if amt > 0:
            inject_all(books, amt)
            applied.append(
                AppliedInjection(
                    entry_id=entry_id(item),
                    amount=amt,
                    reason=str(item.get("reason", "(from dashboard)")),
                )
            )
            total += amt
    return total, applied


def log_manual_injection(
    amount: Decimal,
    reason: str,
    path: Path = MANUAL_LOG_PATH,
    *,
    entry_id: str | None = None,
) -> bool:
    """Append a discretionary top-up (amount + the user's stated reason) for honesty/audit.

    Returns whether an entry was written. **Append-once**: given an ``entry_id`` already present in
    the log, this is a no-op. That is what makes the audit trail idempotent under the re-runs the
    daily cron actually performs — re-logging the same queue entry on each pass is how the log came
    to claim ₹440,500 against ₹200,000 truly injected, a drift of ₹240,500 across 2026-07-12 →
    2026-08-12. The duplicate pairs are still visible in the log, timestamped minutes apart.

    **Call this only after the deposit has been persisted** (``save_state``/``save_books``). This
    file is an audit record, so a phantom entry is worse than a missing one: writing it up-front
    meant any crash in the pipeline that follows left the log claiming money the books never got.
    """
    from datetime import datetime

    path.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if entry_id is not None and any(str(e.get("id", "")) == entry_id for e in log):
        return False  # already recorded — the cron re-ran, the money did not arrive twice
    record: dict[str, str] = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "amount": str(amount),
        "reason": reason,
    }
    if entry_id is not None:
        record["id"] = entry_id
    log.append(record)
    path.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    return True


def log_correction(amount: Decimal, note: str, path: Path = MANUAL_LOG_PATH) -> None:
    """Append a signed correction to the audit log — never rewrite or delete an existing entry.

    The log over-counted by ₹240,500 and the honest repair is not to quietly drop the duplicate rows:
    they are evidence of what the runner did. A correction entry brings the *total* back to the truth
    while leaving the erroneous history legible, which is what an audit trail is for.
    """
    from datetime import datetime

    path.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    log.append(
        {
            "at": datetime.now().isoformat(timespec="seconds"),
            "amount": str(amount),
            "reason": note,
            "kind": "correction",
        }
    )
    path.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")


def manual_log_total(path: Path = MANUAL_LOG_PATH) -> Decimal:
    """Total ₹ the audit log claims was injected (₹0 if there is no log yet)."""
    if not path.exists():
        return Decimal("0")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return Decimal("0")
    entries = json.loads(text)
    return sum((Decimal(str(e.get("amount", "0"))) for e in entries), Decimal("0"))


def manual_log_drift(injected: Decimal, path: Path = MANUAL_LOG_PATH) -> Decimal:
    """``log total − money actually credited``. Non-zero ⇒ the log is not a reliable record.

    ``injected`` is the truth from the state file (``contributed − seed``). Any drift is reported,
    never silently corrected: the log is an append-only record, so the honest move is to surface the
    discrepancy rather than rewrite history.
    """
    return manual_log_total(path) - injected
