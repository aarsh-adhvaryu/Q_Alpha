"""Tests for the auto-pilot core — AI signal, deploy tilt, book accounting, ledger, persistence."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from qalpha.live.autopilot import (
    MONTHLY_DEPOSIT,
    SEED_LUMP,
    AISignal,
    Book,
    Decision,
    ai_hit_rate,
    basket_value,
    book_deploy_amount,
    deploy_fraction,
    due_decisions,
    parse_ai_signal,
    pct_return,
    resolve_decision,
    scheduled_injection,
    signal_tilt,
)

# ---- AI signal ---------------------------------------------------------------------------------


def test_parse_signal_from_brief_line() -> None:
    text = "…blah…\nSIGNAL: lean=up; band=0.4..0.9; confidence=medium"
    s = parse_ai_signal(text, "2026-07-10")
    assert s is not None
    assert s.lean == "up" and s.confidence == "medium"
    assert s.band_lo == 0.4 and s.band_hi == 0.9
    assert s.as_of == "2026-07-10"


def test_parse_signal_missing_or_malformed_is_none() -> None:
    assert parse_ai_signal("no tag here", "2026-07-10") is None
    assert parse_ai_signal("SIGNAL: lean=sideways; band=x..y; confidence=medium", "d") is None


def test_signal_round_trip() -> None:
    s = AISignal("2026-07-10", "down", "high", -0.9, -0.3)
    assert AISignal.from_dict(s.to_dict()) == s


def test_signal_tilt_rule() -> None:
    assert signal_tilt(None) == 1.0  # no signal → neutral
    assert signal_tilt(AISignal("d", "flat", "high", 0, 0)) == 1.0
    assert signal_tilt(AISignal("d", "up", "high", 0, 0)) == 1.4
    assert signal_tilt(AISignal("d", "up", "low", 0, 0)) == 1.1
    assert signal_tilt(AISignal("d", "down", "high", 0, 0)) == 0.6
    # clamp holds even if weights were extreme (they aren't, but the guard is real)
    assert 0.5 <= signal_tilt(AISignal("d", "down", "high", 0, 0)) <= 1.5


# ---- deploy sizing -----------------------------------------------------------------------------


def test_deploy_fraction_opportunistic_base_then_more_on_dips() -> None:
    assert deploy_fraction("normal") == Decimal("0.25")  # never fully idle
    assert deploy_fraction("elevated") == Decimal("0.50")
    assert deploy_fraction("deep") == Decimal("1.00")
    assert deploy_fraction("???") == Decimal("0")


def test_book_deploy_amount_a_vs_b_and_cap() -> None:
    wallet = Decimal("50000")
    # Book A, elevated → 50% = 25,000 (no AI tilt)
    assert book_deploy_amount(wallet, "elevated", None, ai=False) == Decimal("25000.00")
    # Book B, elevated + AI bullish-high (1.4×) → 25,000 × 1.4 = 35,000
    up = AISignal("d", "up", "high", 0.4, 0.9)
    assert book_deploy_amount(wallet, "elevated", up, ai=True) == Decimal("35000.00")
    # Book B, AI wary-high (0.6×) → 15,000
    dn = AISignal("d", "down", "high", -0.9, -0.4)
    assert book_deploy_amount(wallet, "elevated", dn, ai=True) == Decimal("15000.00")
    # deep + AI bullish would exceed the wallet → capped at the wallet
    assert book_deploy_amount(wallet, "deep", up, ai=True) == Decimal("50000.00")


# ---- book accounting (capital-flow-aware) ------------------------------------------------------


def test_injection_is_not_profit() -> None:
    b = Book("A")
    b.inject(Decimal("100000"))
    prices = {"X": Decimal("100")}
    assert b.value(prices) == Decimal("100000")
    assert b.profit(prices) == Decimal("0")  # cash in ≠ gain
    assert b.return_pct(prices) == 0.0


def test_buy_then_gain_shows_profit() -> None:
    b = Book("A")
    b.inject(Decimal("100000"))
    b.buy("X", 500, Decimal("100"))  # spend 50,000 → 500 shares
    up = {"X": Decimal("120")}  # shares now worth 60,000
    assert b.value(up) == Decimal("110000")  # 50,000 cash + 60,000 shares
    assert b.profit(up) == Decimal("10000")
    assert round(b.return_pct(up), 2) == 10.0


def test_second_injection_keeps_return_honest() -> None:
    b = Book("A")
    b.inject(Decimal("100000"))
    b.buy("X", 500, Decimal("100"))
    b.inject(Decimal("50000"))  # top-up — must not look like a gain
    flat = {"X": Decimal("100")}
    assert b.value(flat) == Decimal("150000")
    assert b.profit(flat) == Decimal("0")
    assert b.return_pct(flat) == 0.0


def test_buy_over_cash_raises() -> None:
    b = Book("A")
    b.inject(Decimal("1000"))
    try:
        b.buy("X", 100, Decimal("100"))  # needs 10,000
    except ValueError as e:
        assert "cannot afford" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_book_round_trip() -> None:
    b = Book("B", cash=Decimal("123.45"), holdings={"X": 3}, net_contributions=Decimal("500"))
    assert Book.from_dict(b.to_dict()) == b


# ---- decision ledger ---------------------------------------------------------------------------


def _decision(book: str = "B") -> Decision:
    return Decision(
        as_of="2026-07-10",
        book=book,
        amount="10000",
        basket={"ITC.NS": 2},
        model_rationale="deploy into elevated weakness",
        ai_insight="lean=up confidence=medium (tilt 1.25×)",
        resolve_on="2026-08-07",
    )


def test_resolve_decision_verdicts() -> None:
    d = _decision()
    assert resolve_decision(d, 3.0, 1.0).verdict == "worked"  # beat by 2 pts
    assert resolve_decision(d, 0.3, 1.0).verdict == "didn't"  # lagged by 0.7 pt
    assert resolve_decision(d, 1.2, 1.0).verdict == "flat"  # within 0.5pt tolerance
    r = resolve_decision(d, 3.0, 1.0)
    assert r.resolved and r.outcome_return_pct == 3.0 and r.benchmark_return_pct == 1.0


def test_ai_hit_rate_counts_only_resolved_book_b() -> None:
    ds = [
        resolve_decision(_decision("B"), 3.0, 1.0),  # worked
        resolve_decision(_decision("B"), 0.0, 1.0),  # didn't
        _decision("B"),  # unresolved → not counted
        resolve_decision(_decision("A"), 5.0, 1.0),  # book A → not counted
    ]
    assert ai_hit_rate(ds) == (1, 2)
    assert ai_hit_rate([]) == (0, 0)


def test_decision_round_trip() -> None:
    d = resolve_decision(_decision(), 2.1, 0.9)
    assert Decision.from_dict(d.to_dict()) == d


# ---- cash-flow schedule ------------------------------------------------------------------------


def test_first_run_seeds_and_marks_the_month() -> None:
    amount, month = scheduled_injection("2026-07-11", seeded=False, last_deposit_month=None)
    assert amount == SEED_LUMP
    assert month == "2026-07"  # the seed also counts as July's deposit → no double-fund


def test_new_month_deposits_once_then_zero() -> None:
    first, m1 = scheduled_injection("2026-08-03", seeded=True, last_deposit_month="2026-07")
    assert first == MONTHLY_DEPOSIT and m1 == "2026-08"
    again, m2 = scheduled_injection("2026-08-19", seeded=True, last_deposit_month="2026-08")
    assert again == Decimal("0") and m2 == "2026-08"  # same month → nothing more


# ---- outcome scoring helpers -------------------------------------------------------------------


def test_basket_value_marks_to_prices_and_skips_missing() -> None:
    v = basket_value(
        {"ITC.NS": 2, "TCS.NS": 1}, {"ITC.NS": Decimal("400"), "TCS.NS": Decimal("3800")}
    )
    assert v == Decimal("4600")
    assert basket_value({"X.NS": 3}, {}) == Decimal("0")  # missing price contributes 0


def test_pct_return_and_guard() -> None:
    assert pct_return(Decimal("100"), Decimal("110")) == 10.0
    assert pct_return(Decimal("0"), Decimal("110")) == 0.0  # non-positive entry guarded


def test_due_decisions_selects_unresolved_and_arrived() -> None:
    ledger = [
        Decision("2026-07-10", "A", "1", {}, "", "", resolve_on="2026-08-07"),
        Decision("2026-07-10", "B", "1", {}, "", "", resolve_on="2026-09-01"),
        resolve_decision(_decision(), 3.0, 1.0),  # already resolved → excluded
    ]
    due = due_decisions(ledger, "2026-08-10")
    assert [d.resolve_on for d in due] == ["2026-08-07"]  # only the arrived, unresolved one


# ---- shared persistence (dashboard + runner use these) -----------------------------------------


def test_books_state_round_trip_and_inject(tmp_path: Path) -> None:
    from qalpha.live.autopilot import (
        BOOK_NAMES,
        inject_all,
        load_books,
        load_state,
        save_books,
        save_state,
    )

    books = load_books(tmp_path / "b.json")  # fresh → three empty books
    assert set(books) == set(BOOK_NAMES)
    inject_all(books, Decimal("100000"))
    save_books(books, tmp_path / "b.json")
    again = load_books(tmp_path / "b.json")
    assert all(again[n].cash == Decimal("100000") for n in BOOK_NAMES)

    st = load_state(tmp_path / "s.json")  # default carries the monthly-autodeposit toggle
    assert st["monthly_autodeposit"] is True and st["seeded"] is False
    st["seeded"] = True
    save_state(st, tmp_path / "s.json")
    assert load_state(tmp_path / "s.json")["seeded"] is True
