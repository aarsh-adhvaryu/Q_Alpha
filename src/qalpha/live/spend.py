"""What model calls cost, reserved before they are made.

**Why this exists.** The API key ran out of credits halfway through a backfill. Nothing in the
system knew what it had spent, so nothing could stop it, and the first sign was a failed call. A
budget that is only checked after the money is gone is a receipt, not a budget.

**How it works.** Every priced call reserves its *worst case* before it is sent:

    reserved = input_token_ceiling x input_price + max_output_tokens x output_price

and may proceed only if, for the current month,

    settled + open reservations + this reservation <= the partition's limit

When the reply arrives the reservation is settled at the real token counts, which are never higher.
Checking-then-spending would let eight concurrent workers each pass the check and together exceed
it; reserving under one lock cannot.

**Partitions.** Decisions are funded first. Reading and backfills may use at most
``cap - decisions_reserve``, so a long backfill can never spend the money the evening review needs.
Decisions may use the whole cap.

**Research is a one-time job with its own explicit budget**, not part of the monthly operating cap:
building and validating the reader reference set is a measurement, approved once, with a stated
ceiling. A research reservation names its job and is checked against that job's total ceiling across
every month; it never draws on the operating cap, so it can never spend the evening review's money.

**The ledger is the state.** An append-only JSONL file: ``reserve``, ``settle``, ``release`` rows.
An open reservation is a ``reserve`` row with no later ``settle`` or ``release`` for its id — so a
batch submitted before a restart is still counted after it, with nothing held in memory.

**Uncertain outcomes are counted, not forgotten.** A timeout or dropped connection after a request
was sent may or may not have been billed. It is settled at its reservation: the ledger may then
overstate spend, which errs toward stopping early, never toward overspending.

Prices are list prices per million tokens, cached from each provider's official page (see
``PRICE_SOURCES``). A model with no price entry cannot be called through a priced path — an
unknown price is not a price of zero.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

LEDGER_PATH = Path("data/spend/ledger.jsonl")

#: Partitions a call may be charged to.
DECISIONS = "decisions"
READING = "reading"
RESEARCH = "research"
PARTITIONS = (DECISIONS, READING)
ALL_PARTITIONS = (DECISIONS, READING, RESEARCH)

#: Batch API discount by provider. DeepSeek offers no batch interface, so a batch reservation for it
#: is refused rather than priced at a discount that does not exist.
BATCH_DISCOUNT = {"anthropic": Decimal("0.5"), "google": Decimal("0.5")}

IST = timezone(timedelta(hours=5, minutes=30))

#: Characters per token assumed when reserving for text. English prose runs near four characters a
#: token; filings are dense with numbers and tables, which tokenise worse. Two is deliberately
#: pessimistic: over-reserving stops a run a little early, under-reserving lets it overspend.
CHARS_PER_TOKEN_CEILING = 2

#: Tokens reserved per PDF page. Anthropic bills a PDF page as its text plus an image of it, which
#: its documentation puts at up to roughly 3,000 tokens a page.
TOKENS_PER_PDF_PAGE = 3000

PRICE_SOURCES = {
    "anthropic": "Claude API reference, model table cached 2026-06-24",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing (checked 2026-09-14)",
    "google": "https://ai.google.dev/gemini-api/docs/pricing (checked 2026-09-14)",
}


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""

    provider: str
    input_per_m: Decimal
    output_per_m: Decimal
    #: A lower rate outside peak hours, if the provider has one. Reservations always use the peak
    #: rate; settlement uses whichever rate applied when the call completed.
    offpeak_input_per_m: Decimal | None = None
    offpeak_output_per_m: Decimal | None = None


PRICES: dict[str, Price] = {
    "claude-opus-5": Price("anthropic", Decimal("5"), Decimal("25")),
    "claude-sonnet-5": Price("anthropic", Decimal("2"), Decimal("10")),
    "claude-haiku-4-5": Price("anthropic", Decimal("1"), Decimal("5")),
    "deepseek-flash": Price(
        "deepseek", Decimal("0.3"), Decimal("1.2"), Decimal("0.15"), Decimal("0.6")
    ),
    "deepseek-v4-pro": Price(
        "deepseek", Decimal("1.32"), Decimal("3.96"), Decimal("0.66"), Decimal("1.98")
    ),
    "gemini-3.1-flash-lite": Price("google", Decimal("0.25"), Decimal("1.50")),
    "gemini-3.1-pro-preview": Price("google", Decimal("2"), Decimal("12")),
}


class SpendStopError(RuntimeError):
    """A call was not made because of money. Never a refusal and never an empty reading."""


class BudgetExceededError(SpendStopError):
    """The reservation would take the partition over its monthly limit."""


class CreditExhaustedError(SpendStopError):
    """The provider reports the account has no credit left."""


class UnpricedModelError(SpendStopError):
    """No price is on file for this model, so its cost cannot be reserved."""


class NoBatchPriceError(SpendStopError):
    """The provider offers no batch price, so a batch reservation cannot be priced."""


def deepseek_peak(at: datetime) -> bool:
    """DeepSeek's peak window: 01:00-04:00 and 06:00-10:00 UTC, Monday to Friday."""
    utc = at.astimezone(UTC)
    if utc.weekday() >= 5:
        return False
    return 1 <= utc.hour < 4 or 6 <= utc.hour < 10


def price_for(model: str) -> Price:
    try:
        return PRICES[model]
    except KeyError as exc:
        raise UnpricedModelError(
            f"no price on file for {model!r}; its cost cannot be reserved, so it is not called"
        ) from exc


def cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    at: datetime | None = None,
    batch: bool = False,
) -> Decimal:
    """What a call cost, at the rate that applied when it completed."""
    p = price_for(model)
    inp, out = p.input_per_m, p.output_per_m
    if p.offpeak_input_per_m is not None and at is not None and not deepseek_peak(at):
        inp = p.offpeak_input_per_m
        out = p.offpeak_output_per_m or out
    usd = (Decimal(input_tokens) * inp + Decimal(output_tokens) * out) / Decimal(1_000_000)
    if batch:
        discount = BATCH_DISCOUNT.get(p.provider)
        if discount is None:
            raise NoBatchPriceError(f"{p.provider} has no batch price on file for {model!r}")
        usd *= discount
    return usd.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def worst_case(model: str, input_ceiling: int, max_output: int, *, batch: bool = False) -> Decimal:
    """The reservation: the peak rate, the input ceiling, and every output token allowed."""
    return cost(model, input_ceiling, max_output, at=None, batch=batch)


def text_input_ceiling(prompt: str) -> int:
    return math.ceil(len(prompt) / CHARS_PER_TOKEN_CEILING)


def pdf_input_ceiling(pdf_bytes: bytes, prompt: str = "") -> int:
    """Pages counted from the PDF's own page objects; an unreadable count reserves generously."""
    import re

    pages = len(re.findall(rb"/Type\s*/Page(?![a-z])", pdf_bytes))
    if pages == 0:
        pages = max(1, len(pdf_bytes) // 50_000)
    return pages * TOKENS_PER_PDF_PAGE + text_input_ceiling(prompt)


def month_of(at: datetime) -> str:
    """The budget month, in India's calendar — the user's month, not UTC's."""
    return at.astimezone(IST).strftime("%Y-%m")


@dataclass(frozen=True)
class Limits:
    cap_usd: Decimal
    decisions_reserve_usd: Decimal

    def limit(self, partition: str) -> Decimal:
        if partition == DECISIONS:
            return self.cap_usd
        return max(Decimal("0"), self.cap_usd - self.decisions_reserve_usd)


def limits_from_mandate() -> Limits:
    from qalpha.live import mandate

    m = mandate.load()
    return Limits(cap_usd=m.spend_cap_usd, decisions_reserve_usd=m.spend_decisions_reserve_usd)


@dataclass(frozen=True)
class Reservation:
    id: str
    partition: str
    model: str
    usd: Decimal
    month: str
    batch: bool = False


@dataclass(frozen=True)
class MonthState:
    """Settled and still-reserved spend for one month, overall and per partition."""

    month: str
    settled: dict[str, Decimal]
    reserved: dict[str, Decimal]

    def committed(self, partition: str | None = None) -> Decimal:
        keys = PARTITIONS if partition is None else (partition,)
        return sum(
            (self.settled.get(k, Decimal("0")) + self.reserved.get(k, Decimal("0")) for k in keys),
            Decimal("0"),
        )


_THREAD_LOCK = threading.Lock()


class Ledger:
    """The append-only spend record. Safe across threads and across processes."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        limits: Limits | None = None,
        job: str = "",
        job_limit_usd: Decimal | None = None,
    ) -> None:
        self._path = path
        self._limits = limits
        #: The one-time research job this ledger instance charges, and its total ceiling. Required
        #: for any ``research`` reservation; meaningless for the operating partitions.
        self.job = job
        self.job_limit_usd = job_limit_usd

    @property
    def path(self) -> Path:
        # Resolved at call time, so a test that redirects LEDGER_PATH reaches this object too.
        return LEDGER_PATH if self._path is None else self._path

    @property
    def limits(self) -> Limits:
        return self._limits if self._limits is not None else limits_from_mandate()

    # ---- the lock --------------------------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """One writer at a time: a thread lock inside this process, a lock file across processes."""
        lock_path = self.path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with _THREAD_LOCK:
            deadline = time.monotonic() + 60
            while True:
                try:
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    break
                except FileExistsError:
                    try:
                        # A lock older than two minutes belongs to a process that died holding it.
                        if time.time() - lock_path.stat().st_mtime > 120:
                            lock_path.unlink(missing_ok=True)
                            continue
                    except FileNotFoundError:
                        continue
                    if time.monotonic() > deadline:
                        raise SpendStopError(
                            f"could not take the spend lock {lock_path} within 60 s"
                        ) from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                os.close(fd)
                lock_path.unlink(missing_ok=True)

    # ---- reading ---------------------------------------------------------------------------

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line from a crash is not a spend record
        return out

    def state(self, month: str, rows: list[dict[str, Any]] | None = None) -> MonthState:
        rows = self.rows() if rows is None else rows
        reserves: dict[str, dict[str, Any]] = {}
        closed: set[str] = set()
        settled: dict[str, Decimal] = {}
        for row in rows:
            kind, rid = row.get("kind"), str(row.get("id", ""))
            if kind == "reserve":
                reserves[rid] = row
            elif kind in ("settle", "release"):
                closed.add(rid)
                if kind == "settle" and rid in reserves and reserves[rid].get("month") == month:
                    part = str(reserves[rid].get("partition"))
                    settled[part] = settled.get(part, Decimal("0")) + Decimal(str(row["usd"]))
        reserved: dict[str, Decimal] = {}
        for rid, row in reserves.items():
            if rid not in closed and row.get("month") == month:
                part = str(row.get("partition"))
                reserved[part] = reserved.get(part, Decimal("0")) + Decimal(str(row["usd"]))
        return MonthState(month=month, settled=settled, reserved=reserved)

    def open_reservations(self) -> list[dict[str, Any]]:
        rows = self.rows()
        closed = {str(r["id"]) for r in rows if r.get("kind") in ("settle", "release")}
        return [r for r in rows if r.get("kind") == "reserve" and str(r["id"]) not in closed]

    # ---- writing ---------------------------------------------------------------------------

    def _append(self, row: dict[str, Any]) -> None:
        from qalpha.live.atomic import write_text

        existing = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        write_text(self.path, existing + json.dumps(row, sort_keys=True) + "\n")

    def job_committed(self, job: str, rows: list[dict[str, Any]] | None = None) -> Decimal:
        """Everything a research job has settled or still holds, across every month."""
        rows = self.rows() if rows is None else rows
        reserves = {
            str(r["id"]): r for r in rows if r.get("kind") == "reserve" and r.get("job") == job
        }
        total = Decimal("0")
        closed: set[str] = set()
        for row in rows:
            rid = str(row.get("id", ""))
            if rid in reserves and row.get("kind") in ("settle", "release"):
                closed.add(rid)
                if row.get("kind") == "settle":
                    total += Decimal(str(row["usd"]))
        for rid, row in reserves.items():
            if rid not in closed:
                total += Decimal(str(row["usd"]))
        return total

    def reservation(self, reservation_id: str) -> Reservation | None:
        """An open reservation rebuilt from the ledger — how a batch is settled after a restart."""
        rows = self.rows()
        closed = {str(r["id"]) for r in rows if r.get("kind") in ("settle", "release")}
        if reservation_id in closed:
            return None
        for row in rows:
            if row.get("kind") == "reserve" and str(row["id"]) == reservation_id:
                return Reservation(
                    id=reservation_id,
                    partition=str(row["partition"]),
                    model=str(row["model"]),
                    usd=Decimal(str(row["usd"])),
                    month=str(row["month"]),
                    batch=bool(row.get("batch", False)),
                )
        return None

    def reserve(
        self,
        *,
        partition: str,
        model: str,
        input_ceiling: int,
        max_output: int,
        note: str = "",
        batch: bool = False,
        now: datetime | None = None,
    ) -> Reservation:
        """Reserve the worst case, or raise :class:`BudgetExceededError` having reserved nothing."""
        if partition not in ALL_PARTITIONS:
            raise ValueError(f"unknown spend partition {partition!r}")
        at = now or datetime.now(UTC)
        usd = worst_case(model, input_ceiling, max_output, batch=batch)
        month = month_of(at)
        if partition == RESEARCH:
            if not self.job or self.job_limit_usd is None:
                raise BudgetExceededError(
                    "a research call needs a named job with an explicit budget; none was given"
                )
            with self._locked():
                after = self.job_committed(self.job) + usd
                if after > self.job_limit_usd:
                    raise BudgetExceededError(
                        f"research job {self.job!r} would commit ${after:.4f} against its "
                        f"${self.job_limit_usd:.2f} budget"
                    )
                return self._write_reservation(
                    partition, model, usd, month, at, input_ceiling, max_output, batch, note
                )
        limits = self.limits
        with self._locked():
            state = self.state(month)
            total_after = state.committed() + usd
            part_after = state.committed(partition) + usd
            # Reading may never eat into what decisions have been promised. Measured against
            # everything reading has committed, so the reserve survives any mix of calls.
            if partition == READING and part_after > limits.limit(READING):
                raise BudgetExceededError(
                    f"reading would commit ${part_after:.4f} this month against its "
                    f"${limits.limit(READING):.2f} limit (the cap less "
                    f"${limits.decisions_reserve_usd:.2f} kept for decisions)"
                )
            if total_after > limits.cap_usd:
                raise BudgetExceededError(
                    f"this call would commit ${total_after:.4f} this month against the "
                    f"${limits.cap_usd:.2f} cap"
                )
            return self._write_reservation(
                partition, model, usd, month, at, input_ceiling, max_output, batch, note
            )

    def _write_reservation(
        self,
        partition: str,
        model: str,
        usd: Decimal,
        month: str,
        at: datetime,
        input_ceiling: int,
        max_output: int,
        batch: bool,
        note: str,
    ) -> Reservation:
        """Append the reserve row. The caller holds the lock."""
        reservation = Reservation(
            id=uuid.uuid4().hex, partition=partition, model=model, usd=usd, month=month, batch=batch
        )
        self._append(
            {
                "kind": "reserve",
                "id": reservation.id,
                "at": at.isoformat(timespec="seconds"),
                "month": month,
                "partition": partition,
                "job": self.job if partition == RESEARCH else "",
                "provider": price_for(model).provider,
                "model": model,
                "input_ceiling": input_ceiling,
                "max_output": max_output,
                "usd": str(usd),
                "batch": batch,
                "note": note,
            }
        )
        return reservation

    def settle(
        self,
        reservation: Reservation,
        *,
        input_tokens: int,
        output_tokens: int,
        returned_model: str = "",
        now: datetime | None = None,
    ) -> Decimal:
        """Close a reservation at what the call actually cost. Returns that cost."""
        at = now or datetime.now(UTC)
        usd = cost(reservation.model, input_tokens, output_tokens, at=at, batch=reservation.batch)
        with self._locked():
            self._append(
                {
                    "kind": "settle",
                    "id": reservation.id,
                    "at": at.isoformat(timespec="seconds"),
                    "usd": str(usd),
                    "input": input_tokens,
                    "output": output_tokens,
                    "returned_model": returned_model,
                }
            )
        return usd

    def settle_uncertain(self, reservation: Reservation, reason: str) -> None:
        """A call whose billing is unknown is counted at its reservation, not at zero."""
        with self._locked():
            self._append(
                {
                    "kind": "settle",
                    "id": reservation.id,
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "usd": str(reservation.usd),
                    "uncertain": True,
                    "reason": reason,
                }
            )

    def release(self, reservation: Reservation, reason: str) -> None:
        """Close a reservation for a call that was certainly not billed."""
        with self._locked():
            self._append(
                {
                    "kind": "release",
                    "id": reservation.id,
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "reason": reason,
                }
            )


def summary(month: str | None = None, ledger: Ledger | None = None) -> dict[str, Any]:
    """Month-to-date spend for the page and the evaluation report."""
    book = ledger or Ledger()
    m = month or month_of(datetime.now(UTC))
    state = book.state(m)
    limits = book.limits
    return {
        "month": m,
        "cap_usd": str(limits.cap_usd),
        "decisions_reserve_usd": str(limits.decisions_reserve_usd),
        "settled_usd": {p: str(state.settled.get(p, Decimal("0"))) for p in PARTITIONS},
        "reserved_usd": {p: str(state.reserved.get(p, Decimal("0"))) for p in PARTITIONS},
        "committed_usd": str(state.committed()),
        "open_reservations": len(book.open_reservations()),
    }
