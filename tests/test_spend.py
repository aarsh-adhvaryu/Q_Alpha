"""Money is reserved before a call is made, and never more than the month allows.

The failure this exists for: the API key ran out of credits halfway through a backfill, and nothing
in the system knew what it had spent until a call failed.
"""

from __future__ import annotations

import sys
import threading
import types
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from qalpha.live import spend
from qalpha.live.model_identity import (
    ModelChangedError,
    check_digest,
    check_returned,
    load_pins,
    save_pin,
)

#: A Sonnet 5 call whose worst case is exactly $1: 500,000 input tokens at $2 per million.
ONE_DOLLAR = {"model": "claude-sonnet-5", "input_ceiling": 500_000, "max_output": 0}


def _ledger(tmp_path: Path, cap: str = "10", reserve: str = "6") -> spend.Ledger:
    return spend.Ledger(
        tmp_path / "ledger.jsonl",
        limits=spend.Limits(cap_usd=Decimal(cap), decisions_reserve_usd=Decimal(reserve)),
    )


# ---- reservation arithmetic --------------------------------------------------------------------


def test_a_reservation_is_the_worst_case_and_settles_at_the_real_cost(tmp_path: Path) -> None:
    book = _ledger(tmp_path)
    r = book.reserve(
        partition=spend.DECISIONS, model="claude-opus-5", input_ceiling=70_000, max_output=16_000
    )
    assert r.usd == Decimal("0.750000")  # 70k x $5/M + 16k x $25/M
    month = r.month
    assert book.state(month).committed() == Decimal("0.75")

    paid = book.settle(r, input_tokens=35_000, output_tokens=7_500)
    assert paid == Decimal("0.362500")
    state = book.state(month)
    assert state.committed() == Decimal("0.3625"), "settling replaces the reservation, not adds"
    assert state.reserved.get(spend.DECISIONS, Decimal("0")) == 0


def test_the_cap_refuses_before_anything_is_reserved(tmp_path: Path) -> None:
    book = _ledger(tmp_path, cap="2", reserve="0")
    book.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)
    book.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)
    with pytest.raises(spend.BudgetExceededError, match="cap"):
        book.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)
    assert len(book.rows()) == 2, "a refused reservation leaves no row behind"


def test_concurrent_workers_cannot_together_exceed_the_cap(tmp_path: Path) -> None:
    """Check-then-spend lets eight workers each pass. Reserving under one lock cannot."""
    book = _ledger(tmp_path, cap="10", reserve="0")
    won: list[int] = []
    lost: list[int] = []

    def worker(i: int) -> None:
        try:
            book.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)
            won.append(i)
        except spend.BudgetExceededError:
            lost.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 10 and len(lost) == 14
    assert book.state(spend.month_of(datetime.now(UTC))).committed() == Decimal("10")


def test_reading_can_never_spend_what_decisions_were_promised(tmp_path: Path) -> None:
    """A long backfill must not leave tomorrow's review without money."""
    book = _ledger(tmp_path, cap="10", reserve="6")
    for _ in range(4):
        book.reserve(partition=spend.READING, **ONE_DOLLAR)
    with pytest.raises(spend.BudgetExceededError, match="kept for decisions"):
        book.reserve(partition=spend.READING, **ONE_DOLLAR)
    for _ in range(6):
        book.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)  # the reserve is still all there
    with pytest.raises(spend.BudgetExceededError):
        book.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)


def test_an_open_reservation_survives_a_restart(tmp_path: Path) -> None:
    """A batch submitted before a restart still counts after it — the ledger is the state."""
    first = _ledger(tmp_path, cap="3", reserve="0")
    held = first.reserve(partition=spend.DECISIONS, batch=True, **ONE_DOLLAR)
    first.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)

    restarted = _ledger(tmp_path, cap="3", reserve="0")
    assert {r["id"] for r in restarted.open_reservations()} >= {held.id}
    restarted.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)
    with pytest.raises(spend.BudgetExceededError):
        restarted.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)

    restarted.release(held, "batch expired")
    restarted.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)  # released money is usable again


def test_an_uncertain_call_is_counted_at_its_reservation(tmp_path: Path) -> None:
    """A timeout after sending may have been billed: overstating stops early, never overspends."""
    book = _ledger(tmp_path)
    r = book.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)
    book.settle_uncertain(r, "ReadTimeout")
    assert book.state(r.month).committed() == Decimal("1")
    assert not book.open_reservations()


def test_the_budget_month_is_india_time(tmp_path: Path) -> None:
    late_utc = datetime(2026, 9, 30, 19, 0, tzinfo=UTC)  # already 1 October in India
    assert spend.month_of(late_utc) == "2026-10"
    book = _ledger(tmp_path)
    r = book.reserve(partition=spend.DECISIONS, now=late_utc, **ONE_DOLLAR)
    assert r.month == "2026-10"
    assert book.state("2026-09").committed() == 0


def test_an_unpriced_model_is_not_called(tmp_path: Path) -> None:
    """An unknown price is not a price of zero."""
    with pytest.raises(spend.UnpricedModelError):
        _ledger(tmp_path).reserve(
            partition=spend.READING, model="mystery-9b", input_ceiling=1, max_output=1
        )


def test_deepseek_settles_at_the_rate_that_applied_but_reserves_at_peak() -> None:
    peak = datetime(2026, 9, 14, 7, 0, tzinfo=UTC)  # Monday 07:00 UTC
    offpeak = datetime(2026, 9, 14, 13, 0, tzinfo=UTC)  # Monday 13:00 UTC = 18:30 IST
    assert spend.deepseek_peak(peak) and not spend.deepseek_peak(offpeak)
    tokens = (1_000_000, 1_000_000)
    assert spend.cost("deepseek-flash", *tokens, at=offpeak) == Decimal("0.75")
    assert spend.cost("deepseek-flash", *tokens, at=peak) == Decimal("1.5")
    assert spend.worst_case("deepseek-flash", *tokens) == Decimal("1.5")


def test_a_pdf_is_reserved_per_page_not_per_byte() -> None:
    three_pages = b"%PDF-1.7 " + b"<< /Type /Page >> " * 3 + b"<< /Type /Pages >>" + b"x" * 900_000
    assert spend.pdf_input_ceiling(three_pages) == 3 * spend.TOKENS_PER_PDF_PAGE


# ---- the real Anthropic backend, with a fake client ---------------------------------------------


def _fake_anthropic(monkeypatch: pytest.MonkeyPatch, create: Any) -> list[dict[str, Any]]:
    """Install a fake ``anthropic`` module whose client calls ``create``."""
    calls: list[dict[str, Any]] = []

    class APIStatusError(Exception):
        def __init__(self, message: str, status_code: int) -> None:
            super().__init__(message)
            self.message = message
            self.status_code = status_code

    def recorded(**kw: Any) -> Any:
        calls.append(kw)
        return create(**kw)

    fake = types.ModuleType("anthropic")
    fake.APIStatusError = APIStatusError  # type: ignore[attr-defined]
    fake.Anthropic = lambda **_kw: types.SimpleNamespace(  # type: ignore[attr-defined]
        messages=types.SimpleNamespace(create=recorded)
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return calls


def _reply(model: str = "claude-sonnet-5", text: str = "EVENT: x") -> Any:
    return types.SimpleNamespace(
        model=model,
        stop_reason="end_turn",
        usage=types.SimpleNamespace(input_tokens=1_000, output_tokens=200),
        content=[types.SimpleNamespace(type="text", text=text)],
    )


def test_a_call_over_budget_is_never_sent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from qalpha.live.extraction import default_generate

    calls = _fake_anthropic(monkeypatch, lambda **kw: _reply())
    book = _ledger(tmp_path, cap="0.01", reserve="0")
    generate = default_generate("sk-test", partition="decisions", ledger=book)
    with pytest.raises(spend.BudgetExceededError):
        generate("claude-sonnet-5", "x" * 100_000)
    assert calls == [], "no request may leave the machine once the budget refuses it"


def test_a_successful_call_is_settled_at_what_it_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from qalpha.live.extraction import default_generate

    _fake_anthropic(monkeypatch, lambda **kw: _reply())
    book = _ledger(tmp_path)
    text, usage = default_generate("sk-test", ledger=book)("claude-sonnet-5", "read this")
    assert text == "EVENT: x" and usage["input"] == 1_000
    settle = [r for r in book.rows() if r["kind"] == "settle"]
    assert settle and settle[0]["usd"] == "0.004000"  # 1k x $2/M + 200 x $10/M
    assert settle[0]["returned_model"] == "claude-sonnet-5"
    assert not book.open_reservations()


def test_credit_exhaustion_is_a_spend_stop_and_the_money_is_released(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from qalpha.live.extraction import default_generate

    def broke(**kw: Any) -> Any:
        raise sys.modules["anthropic"].APIStatusError(  # type: ignore[attr-defined]
            "Your credit balance is too low to access the Anthropic API.", 400
        )

    _fake_anthropic(monkeypatch, broke)
    book = _ledger(tmp_path)
    with pytest.raises(spend.CreditExhaustedError):
        default_generate("sk-test", ledger=book)("claude-sonnet-5", "read this")
    assert not book.open_reservations()
    assert book.state(spend.month_of(datetime.now(UTC))).committed() == 0, "nothing was billed"


def test_credit_exhaustion_never_counts_as_a_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two refusals retire a document for ever. Running out of money must never do that."""
    from qalpha.live import extraction

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_extraction import _doc

    def out_of_credit(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        raise spend.CreditExhaustedError("no credit left")

    doc = _doc()
    result = extraction.extract([doc], generate=out_of_credit, model="claude-sonnet-5", workers=1)
    assert result.usage["failed_batches"] >= 1
    assert result.usage["refused_batches"] == 0
    assert doc.provenance.sha256 in result.unread


def test_a_redirected_model_stops_the_call_but_its_cost_is_still_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from qalpha.live.extraction import default_generate

    _fake_anthropic(monkeypatch, lambda **kw: _reply(model="claude-some-newer-model"))
    book = _ledger(tmp_path)
    with pytest.raises(ModelChangedError):
        default_generate("sk-test", ledger=book)("claude-sonnet-5", "read this")
    assert [r["kind"] for r in book.rows()] == ["reserve", "settle"], "it answered, so it was paid"


# ---- model identity -----------------------------------------------------------------------------


def test_the_returned_model_must_be_the_requested_one() -> None:
    check_returned("deepseek-flash", "deepseek-flash")
    check_returned("deepseek-flash", "")  # not reported: unknown, recorded by the caller
    check_returned("qwen3.5-9b-16k", "qwen3.5-9b-16k:latest")  # Ollama's default tag, same weights
    with pytest.raises(ModelChangedError):
        check_returned("qwen3.5-9b-16k", "qwen3.5-9b-16k:q8")
    with pytest.raises(ModelChangedError):
        check_returned("deepseek-flash", "deepseek-v4.1-flash")


def test_pins_round_trip_and_digests_must_match(tmp_path: Path) -> None:
    path = tmp_path / "pins.json"
    save_pin("qwen3.5:9b", "sha256:aaa", path)
    pins = load_pins(path)
    assert pins == {"qwen3.5:9b": "sha256:aaa"}
    assert check_digest("qwen3.5:9b", {"qwen3.5:9b": "sha256:aaa"}, pins) == "sha256:aaa"
    with pytest.raises(ModelChangedError, match="changed under the same tag"):
        check_digest("qwen3.5:9b", {"qwen3.5:9b": "sha256:bbb"}, pins)
    with pytest.raises(ModelChangedError, match="no pinned digest"):
        check_digest("gemma4:12b", {"gemma4:12b": "sha256:ccc"}, pins)
    with pytest.raises(ModelChangedError, match="does not hold"):
        check_digest("qwen3.6:35b", {}, pins)


def test_the_monthly_summary_reports_settled_and_reserved_per_partition(tmp_path: Path) -> None:
    book = _ledger(tmp_path)
    r = book.reserve(partition=spend.READING, **ONE_DOLLAR)
    book.reserve(partition=spend.DECISIONS, **ONE_DOLLAR)
    book.settle(r, input_tokens=250_000, output_tokens=0)
    out = spend.summary(r.month, ledger=book)
    assert out["settled_usd"][spend.READING] == "0.500000"
    assert out["reserved_usd"][spend.DECISIONS] == "1.000000"
    assert out["open_reservations"] == 1
