"""Cumulative tradebook master: de-dupe stacked exports + CSV round-trip (qalpha.live.tradebook_store)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from qalpha.accounting.costs import Side
from qalpha.live.tradebook import TradebookTrade
from qalpha.live.tradebook_store import (
    merge_trades,
    trades_from_master_csv,
    trades_to_master_csv,
)


def _t(
    ticker: str,
    qty: str,
    price: str,
    d: date = date(2026, 6, 1),
    side: Side = Side.BUY,
    trade_id: str = "",
    exec_time: str = "",
) -> TradebookTrade:
    return TradebookTrade(
        trade_date=d,
        ticker=ticker,
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        exec_time=exec_time,
        trade_id=trade_id,
    )


def test_merge_dedupes_by_trade_id() -> None:
    existing = [_t("INFY.NS", "5", "1500", trade_id="T1")]
    incoming = [
        _t("INFY.NS", "5", "1500", trade_id="T1"),  # same trade re-exported → ignored
        _t("TCS.NS", "3", "4000", trade_id="T2"),  # genuinely new
    ]
    merged, added = merge_trades(existing, incoming)
    assert added == 1
    assert {t.trade_id for t in merged} == {"T1", "T2"}


def test_merge_composite_fallback_when_no_trade_id() -> None:
    # Older exports without a trade_id → identical field-tuples are treated as the same trade.
    existing = [_t("INFY.NS", "5", "1500")]
    incoming = [_t("INFY.NS", "5", "1500"), _t("INFY.NS", "2", "1500")]  # dup + a different qty
    merged, added = merge_trades(existing, incoming)
    assert added == 1
    assert len(merged) == 2


def test_merge_is_sorted_chronologically() -> None:
    merged, _ = merge_trades(
        [_t("A.NS", "1", "10", d=date(2026, 3, 1), trade_id="b")],
        [_t("A.NS", "1", "10", d=date(2026, 1, 1), trade_id="a")],
    )
    assert [t.trade_date for t in merged] == [date(2026, 1, 1), date(2026, 3, 1)]


def test_two_overlapping_exports_stack_without_double_counting() -> None:
    # Export 1 covers T1,T2; export 2 (a later pull) re-includes T2 and adds T3.
    export1 = [_t("INFY.NS", "5", "1500", trade_id="T1"), _t("TCS.NS", "3", "4000", trade_id="T2")]
    export2 = [_t("TCS.NS", "3", "4000", trade_id="T2"), _t("BEL.NS", "10", "410", trade_id="T3")]
    master, added1 = merge_trades([], export1)
    master, added2 = merge_trades(master, export2)
    assert added1 == 2
    assert added2 == 1  # only T3 is new
    assert {t.trade_id for t in master} == {"T1", "T2", "T3"}


def test_csv_round_trip_preserves_trades_and_does_not_double_suffix() -> None:
    trades = [
        _t(
            "INFY.NS", "5", "1500.50", side=Side.BUY, trade_id="T1", exec_time="2026-06-01 09:15:04"
        ),
        _t("TCS.NS", "3", "4000", side=Side.SELL, d=date(2026, 7, 1), trade_id="T2"),
    ]
    restored = trades_from_master_csv(trades_to_master_csv(trades))
    assert (
        restored == trades
    )  # exact round-trip, incl. the already-canonical .NS ticker (no ".NS.NS")
    assert all(t.ticker.count(".NS") == 1 for t in restored)


def test_empty_master_csv_is_empty_list() -> None:
    assert trades_from_master_csv("") == []
    assert trades_from_master_csv("   \n") == []


# --- gist auto-discovery (so a reboot re-locates the saved master by the token alone) -------------


def test_select_gist_picks_most_recent_match_by_filename() -> None:
    from qalpha.live.gist_store import _select_gist

    gists = [
        {"id": "old", "updated_at": "2026-06-01T00:00:00Z", "files": {"tradebook_master.csv": {}}},
        {"id": "new", "updated_at": "2026-07-01T00:00:00Z", "files": {"tradebook_master.csv": {}}},
        {"id": "other", "updated_at": "2026-08-01T00:00:00Z", "files": {"notes.txt": {}}},
    ]
    assert _select_gist(gists, "tradebook_master.csv") == "new"


def test_select_gist_returns_none_when_no_file_matches() -> None:
    from qalpha.live.gist_store import _select_gist

    assert _select_gist([{"id": "x", "files": {"other.csv": {}}}], "tradebook_master.csv") is None
    assert _select_gist([], "tradebook_master.csv") is None
