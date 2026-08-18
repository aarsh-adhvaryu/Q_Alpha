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


def test_ai_hit_rate_book_param_selects_system_deploys() -> None:
    ds = [
        resolve_decision(_decision("SYS"), 3.0, 1.0),  # worked
        resolve_decision(_decision("SHD"), 3.0, 1.0),  # shadow → not counted for SYS
        resolve_decision(_decision("SYS"), 0.0, 1.0),  # didn't
    ]
    assert ai_hit_rate(ds, book="SYS") == (1, 2)


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

    st = load_state(tmp_path / "s.json")  # fresh state — funding is manual, no auto-deposit
    assert st["seeded"] is False and "monthly_autodeposit" not in st
    st["seeded"] = True
    save_state(st, tmp_path / "s.json")
    assert load_state(tmp_path / "s.json")["seeded"] is True


def test_apply_pending_injects_all_books_and_leaves_the_queue_for_the_caller(
    tmp_path: Path,
) -> None:
    """apply_pending credits the books; releasing the queue is a **separate, later** step.

    This test previously asserted that ``apply_pending`` cleared the queue itself — which is the T3.2
    bug written down as a specification. Clearing on read destroys anything queued in the meantime,
    and clearing before the books are persisted loses the deposit outright if the run then dies.
    """
    import json

    from qalpha.live.autopilot import (
        BOOK_NAMES,
        Book,
        apply_pending,
        clear_applied,
        load_pending,
    )

    p = tmp_path / "pending.json"
    p.write_text(json.dumps([{"amount": "50000", "reason": "IPO"}, {"amount": "10000"}]))
    books = {n: Book(name=n) for n in BOOK_NAMES}
    total, applied = apply_pending(books, p)
    assert total == Decimal("60000")
    assert all(books[n].cash == Decimal("60000") for n in BOOK_NAMES)  # equal into all three
    # The entries come back for the caller to log AFTER persisting — apply_pending never logs.
    assert [(a.amount, a.reason) for a in applied] == [
        (Decimal("50000"), "IPO"),
        (Decimal("10000"), "(from dashboard)"),
    ]
    assert len(load_pending(p)) == 2  # still queued: nothing is durable yet
    assert clear_applied(applied, p) == 0  # …released only once the caller says so
    assert load_pending(p) == []
    assert apply_pending(books, p) == (Decimal("0"), [])  # nothing left to apply


def test_manual_log_drift_flags_phantom_entries(tmp_path: Path) -> None:
    """The audit log over-counting the money actually credited must be *measurable*, not silent."""
    import json

    from qalpha.live.autopilot import manual_log_drift, manual_log_total

    p = tmp_path / "manual.json"
    assert manual_log_total(p) == Decimal("0")  # no log yet
    p.write_text(json.dumps([{"amount": "50000"}, {"amount": "50000"}, {"amount": "10000"}]))
    assert manual_log_total(p) == Decimal("110000")
    assert manual_log_drift(Decimal("110000"), p) == Decimal("0")  # log matches reality
    assert manual_log_drift(Decimal("50000"), p) == Decimal("60000")  # phantom ₹60k surfaced


# ---- the book's own window (PLAN_TRUST_REPAIR.md PR-4 — fixes T2.1) -------------------------------


def test_a_book_stamps_its_start_date_on_first_funding() -> None:
    """Before PR-4 the window was recoverable only from system_track.csv row 1."""
    from datetime import date

    from qalpha.live.autopilot import Book

    b = Book(name="BASE")
    assert b.start_date is None
    b.inject(Decimal("200000"), date(2026, 7, 10))
    assert b.start_date == date(2026, 7, 10)
    # A later top-up must not move the start date — the book began measuring when it was first funded.
    b.inject(Decimal("50000"), date(2026, 8, 3))
    assert b.start_date == date(2026, 7, 10)
    assert b.net_contributions == Decimal("250000")


def test_the_start_date_survives_a_round_trip() -> None:
    from datetime import date

    from qalpha.live.autopilot import Book

    b = Book(name="BASE")
    b.inject(Decimal("1000"), date(2026, 7, 10))
    assert Book.from_dict(b.to_dict()).start_date == date(2026, 7, 10)


def test_a_legacy_book_without_a_start_date_still_loads() -> None:
    """Books written before PR-4 have no start_date key — they must not fail to load."""
    from qalpha.live.autopilot import Book

    b = Book.from_dict({"name": "BASE", "cash": "10", "holdings": {}, "net_contributions": "1000"})
    assert b.start_date is None
    assert "start_date" not in b.to_dict()  # and it is not invented on the way back out


def test_injecting_without_a_date_leaves_the_window_unknown() -> None:
    """Fail honest: no date in, no date claimed."""
    from qalpha.live.autopilot import Book

    b = Book(name="BASE")
    b.inject(Decimal("1000"))
    assert b.start_date is None


# ---- accounting integrity (PLAN_TRUST_REPAIR.md PR-6 — fixes T3.1, T3.2) --------------------------


def _queue(path: Path, *items: dict[str, str]) -> None:
    import json

    path.write_text(json.dumps(list(items), indent=2) + "\n", encoding="utf-8")


def _books() -> dict[str, Book]:
    from qalpha.live.autopilot import BOOK_NAMES

    return {n: Book(name=n) for n in BOOK_NAMES}


def test_a_deposit_queued_mid_run_survives_and_is_applied_next_time() -> None:
    """T3.2, the money-losing bug. Same failure family as the ₹50k lost in July.

    The runner used to truncate the queue to `[]` after reading it, so anything the dashboard wrote
    between the read and the write was destroyed unread.
    """
    import json
    import tempfile

    from qalpha.live.autopilot import apply_pending, clear_applied, load_pending

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pending.json"
        _queue(path, {"amount": "50000", "reason": "first", "at": "2026-08-01T10:00:00"})

        books = _books()
        total, applied = apply_pending(books, path)
        assert total == Decimal("50000")

        # …the dashboard queues another deposit while the long daily pipeline is still running.
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing.append({"amount": "25000", "reason": "mid-run", "at": "2026-08-01T10:00:30"})
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

        left = clear_applied(applied, path)
        assert left == 1
        survivors = load_pending(path)
        assert [s["reason"] for s in survivors] == ["mid-run"]

        # The next run picks it up — nothing was lost.
        total2, applied2 = apply_pending(_books(), path)
        assert total2 == Decimal("25000")
        assert clear_applied(applied2, path) == 0


def test_a_crash_before_persistence_leaves_the_deposit_queued() -> None:
    """Clearing on read meant a crash mid-pipeline emptied the queue with the money never credited.

    Applying twice is recoverable; a silently dropped deposit is not.
    """
    import tempfile

    from qalpha.live.autopilot import apply_pending, load_pending

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pending.json"
        _queue(path, {"amount": "50000", "reason": "ipo", "at": "2026-08-01T10:00:00"})
        apply_pending(_books(), path)  # …and the run dies here, before save_state/clear_applied
        assert len(load_pending(path)) == 1


def test_entry_ids_are_stable_for_legacy_entries_without_one() -> None:
    """Entries queued before ids existed must still be claimable exactly once."""
    from qalpha.live.autopilot import entry_id

    legacy = {"amount": "50000", "reason": "ipo", "at": "2026-07-12T09:25:03"}
    assert entry_id(legacy) == entry_id(dict(legacy))
    assert entry_id(legacy) != entry_id({**legacy, "at": "2026-07-12T10:00:58"})
    assert entry_id({"id": "abc123", "amount": "1"}) == "abc123"  # an explicit id always wins


def test_the_audit_log_is_append_once_on_the_entry_id() -> None:
    """T3.1's root cause: the cron re-logged the same queued deposit on every pass."""
    import tempfile

    from qalpha.live.autopilot import log_manual_injection, manual_log_total

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.json"
        assert log_manual_injection(Decimal("50000"), "ipo", path, entry_id="e1") is True
        assert log_manual_injection(Decimal("50000"), "ipo", path, entry_id="e1") is False
        assert manual_log_total(path) == Decimal("50000")
        # A genuinely different deposit still lands.
        assert log_manual_injection(Decimal("10000"), "second", path, entry_id="e2") is True
        assert manual_log_total(path) == Decimal("60000")


def test_a_correction_reconciles_the_total_without_erasing_history() -> None:
    """The repair is a signed correction, not a rewrite: the erroneous rows are the evidence."""
    import json
    import tempfile

    from qalpha.live.autopilot import log_correction, log_manual_injection, manual_log_drift

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.json"
        for _ in range(3):  # the same deposit, logged three times by three cron passes
            log_manual_injection(Decimal("50000"), "ipo", path)
        assert manual_log_drift(Decimal("50000"), path) == Decimal("100000")

        log_correction(Decimal("-100000"), "duplicate cron entries", path)
        assert manual_log_drift(Decimal("50000"), path) == Decimal("0")
        entries = json.loads(path.read_text(encoding="utf-8"))
        assert len(entries) == 4  # nothing deleted
        assert sum(1 for e in entries if e.get("kind") == "correction") == 1


def test_the_committed_log_now_reconciles_against_the_books() -> None:
    """The plan's acceptance criterion: manual_log_drift(₹200,000) returns 0 (it returned 240500)."""
    from qalpha.live.autopilot import manual_log_drift

    assert manual_log_drift(Decimal("200000")) == Decimal("0")


def test_zero_and_negative_queue_entries_are_ignored_not_credited() -> None:
    import tempfile

    from qalpha.live.autopilot import apply_pending

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pending.json"
        _queue(path, {"amount": "0", "reason": "noop"}, {"amount": "-5000", "reason": "bad"})
        total, applied = apply_pending(_books(), path)
        assert total == Decimal("0")
        assert applied == []


def test_the_stale_autodeposit_state_key_is_gone() -> None:
    """T3.4: the feature was removed 2026-07-28; the key lingered in committed state."""
    import json

    root = Path(__file__).resolve().parent.parent
    state = json.loads((root / "data/autopilot/state.json").read_text(encoding="utf-8"))
    assert "monthly_autodeposit" not in state


# ---- fixed-notional baskets (PLAN_TRUST_REPAIR.md PR-7 — fixes T4.1) ------------------------------


def test_scaling_a_basket_preserves_every_name_at_a_larger_size() -> None:
    from qalpha.live.autopilot import scaled_basket

    ref = {"AAA.NS": 10, "BBB.NS": 4, "CCC.NS": 1}
    out = scaled_basket(ref, Decimal("200000"), Decimal("100000"))
    assert out == {"AAA.NS": 20, "BBB.NS": 8, "CCC.NS": 2}


def test_scaling_truncates_rather_than_rounds_up() -> None:
    """Portfolio.buy is cash-capped, so a rounded-up order would silently shrink — reintroducing the
    amount-dependence this exists to remove."""
    from qalpha.live.autopilot import scaled_basket

    ref = {"AAA.NS": 10, "BBB.NS": 3}
    assert scaled_basket(ref, Decimal("95000"), Decimal("100000")) == {"AAA.NS": 9, "BBB.NS": 2}


def test_a_name_that_rounds_below_one_share_is_reported_not_silently_dropped() -> None:
    """The caller must be able to make a *symmetric* decision about it across every book."""
    from qalpha.live.autopilot import scaled_basket

    out = scaled_basket({"AAA.NS": 10, "TINY.NS": 1}, Decimal("50000"), Decimal("100000"))
    assert out == {"AAA.NS": 5, "TINY.NS": 0}
    assert "TINY.NS" in out  # present with 0, not missing


def test_the_common_basket_is_the_executable_intersection() -> None:
    """T4.1 in one assertion: dropping a name from one book only is how the funds diverged."""
    from qalpha.live.autopilot import common_basket

    system = {"AAA.NS": 12, "BBB.NS": 3, "CCC.NS": 1}
    shadow = {"AAA.NS": 9, "BBB.NS": 2, "CCC.NS": 0}  # CCC rounds away at the smaller size
    assert common_basket(system, shadow) == {"AAA.NS", "BBB.NS"}


def test_two_books_at_different_sizes_trade_identical_tickers() -> None:
    """**The property whose absence voided run 1** — the plan's acceptance criterion for PR-7.

    The AI tilt changes deploy *size*. It must not change *which names* are held, at any size.
    """
    from qalpha.live.autopilot import common_basket, scaled_basket

    reference = {f"N{i}.NS": 20 - i for i in range(15)}
    for system_amt, shadow_amt in (
        (Decimal("50000"), Decimal("40000")),  # a ×1.25 AI tilt
        (Decimal("30000"), Decimal("60000")),  # and the other direction
        (Decimal("100000"), Decimal("100000")),  # neutral
    ):
        s = scaled_basket(reference, system_amt)
        h = scaled_basket(reference, shadow_amt)
        tradable = common_basket(s, h)
        system_exec = {t: s[t] for t in tradable}
        shadow_exec = {t: h[t] for t in tradable}
        assert set(system_exec) == set(shadow_exec)  # identical composition, always
        if system_amt != shadow_amt:
            assert system_exec != shadow_exec  # …and size still differs, or the study measures zero


def test_a_zero_or_negative_deploy_yields_an_empty_tradable_set() -> None:
    from qalpha.live.autopilot import common_basket, scaled_basket

    ref = {"AAA.NS": 10}
    assert scaled_basket(ref, Decimal("0")) == {"AAA.NS": 0}
    assert common_basket(scaled_basket(ref, Decimal("0")), ref) == set()


# ---- the re-seed (PLAN_TRUST_REPAIR.md PR-7 — fixes T4.2) -----------------------------------------


def test_the_reseeded_books_start_identical_and_empty() -> None:
    """Ground zero means ground zero: same start date, no holdings, no history, nothing inherited."""
    import json

    root = Path(__file__).resolve().parent.parent
    system = json.loads((root / "data/paper/adaptive_book.json").read_text(encoding="utf-8"))
    shadow = json.loads((root / "data/paper/shadow_book.json").read_text(encoding="utf-8"))
    assert system == shadow
    assert system["portfolio"]["lots"] == []
    assert system["equity_curve"] == []
    assert system["start_date"] == shadow["start_date"]


def test_the_reseeded_books_carry_none_of_the_artifact_names() -> None:
    """T4.2: run 1's books held VEDL 69/57 and TRENT 6/5, bought on phantom discounts."""
    import json

    root = Path(__file__).resolve().parent.parent
    for name in ("adaptive_book.json", "shadow_book.json"):
        book = json.loads((root / "data/paper" / name).read_text(encoding="utf-8"))
        held = {lot["ticker"] for lot in book["portfolio"]["lots"]}
        assert "VEDL.NS" not in held and "TRENT.NS" not in held


def test_all_three_books_restart_on_identical_cash_flows() -> None:
    import json

    root = Path(__file__).resolve().parent.parent
    state = json.loads((root / "data/autopilot/state.json").read_text(encoding="utf-8"))
    baseline = json.loads((root / "data/autopilot/baseline_book.json").read_text(encoding="utf-8"))
    contributed = {Decimal(v) for v in state["contributed"].values()}
    assert len(contributed) == 1  # System and Shadow funded identically
    assert Decimal(baseline["net_contributions"]) == contributed.pop()  # …and so is the Baseline
    assert baseline["start_date"] == state["reseeded_on"]


def test_the_void_run_is_archived_not_deleted() -> None:
    """A pre-registered study's data is published, never quietly removed."""
    root = Path(__file__).resolve().parent.parent
    archives = list((root / "data/autopilot/archive").glob("forward_run_1_*"))
    assert archives, "the confounded run must be archived"
    kept = {p.name for p in archives[0].iterdir()}
    assert {"adaptive_book.json", "shadow_book.json", "system_track.csv"} <= kept


def test_the_go_book_was_not_touched_by_the_reseed() -> None:
    """Rule (a): the criterion-6 clock keeps running. Pillar 1 accrues on its existing marks."""
    import json

    root = Path(__file__).resolve().parent.parent
    go = json.loads((root / "data/paper/book.json").read_text(encoding="utf-8"))
    assert go["start_date"] == "2026-06-12"  # unchanged since the run began
    assert len(go["equity_curve"]) >= 45  # the marks that are the criterion-6 evidence
