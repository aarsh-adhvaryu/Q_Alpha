"""Tests for the Zerodha Tax P&L parser + criterion-4 reconciliation (qalpha.live.taxpnl)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from qalpha.config import Config
from qalpha.live.taxpnl import TaxPnL, parse_taxpnl, reconcile_gross
from qalpha.live.tradebook import parse_tradebook, replay_tradebook


def _write_taxpnl_xlsx(path: Path) -> None:
    """Build a minimal workbook mirroring Zerodha's 'Equity and Non Equity' sheet layout.

    Reproduces the awkward shape the real export has: a leading blank column, label/value pairs,
    a Charges block, and per-section [Symbol, Quantity, Buy Value, Sell Value, Realized P&L] tables
    separated from their section titles by blank rows.
    """
    rows: list[list[object]] = [
        [None, "Client ID", "YHK037"],
        [None, None, None],
        [None, "Realized Profit Breakdown", None],
        [None, "Intraday/Speculative profit", 0],
        [None, "Short Term profit", 25.25],
        [None, "Long Term profit", 0],
        [None, "Non Equity profit", 0],
        [None, None, None],
        [None, "Charges", None],
        [None, "Account Head", "Amount"],
        [None, "Brokerage - Z", 0.02],
        [None, "Securities Transaction Tax - Z", 14],
        [None, "Other Charges", None],
        [None, "Other Credits & Debits", -15.34],
        [None, None, None],
        [None, "Short Term Trades", None],
        [None, None, None],
        [None, "Symbol", "Quantity", "Buy Value", "Sell Value", "Realized P&L"],
        [None, "HDFCBANK", 5, 3927.25, 3952.5, 25.25],
        [None, None, None],
        [None, "Long Term Trades", None],
        [None, "Symbol", "Quantity", "Buy Value", "Sell Value", "Realized P&L"],
    ]
    frame = pd.DataFrame(rows)
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="Equity and Non Equity", header=False, index=False)


@pytest.fixture
def statement(tmp_path: Path) -> TaxPnL:
    path = tmp_path / "taxpnl.xlsx"
    _write_taxpnl_xlsx(path)
    return parse_taxpnl(path)


def test_parses_realized_breakdown(statement: TaxPnL) -> None:
    assert statement.client_id == "YHK037"
    assert statement.short_term_profit == Decimal("25.25")
    assert statement.long_term_profit == Decimal("0")
    assert statement.intraday_profit == Decimal("0")
    assert statement.gross_by_type["STCG"] == Decimal("25.25")


def test_parses_charges(statement: TaxPnL) -> None:
    assert statement.charges["Securities Transaction Tax - Z"] == Decimal("14")
    assert statement.charges["Other Credits & Debits"] == Decimal("-15.34")


def test_parses_per_symbol_trades(statement: TaxPnL) -> None:
    stcg = statement.trades_of("STCG")
    assert len(stcg) == 1
    trade = stcg[0]
    assert trade.symbol == "HDFCBANK"
    assert trade.quantity == Decimal("5")
    assert trade.buy_value == Decimal("3927.25")
    assert trade.sell_value == Decimal("3952.5")
    assert trade.realized_pnl == Decimal("25.25")
    assert statement.trades_of("LTCG") == []


def test_reconcile_gross_matches(statement: TaxPnL) -> None:
    result = reconcile_gross({"STCG": Decimal("25.25"), "LTCG": Decimal("0")}, statement)
    assert result.ok
    assert any("OK" in line for line in result.lines)


def test_reconcile_gross_flags_mismatch(statement: TaxPnL) -> None:
    result = reconcile_gross({"STCG": Decimal("99.00"), "LTCG": Decimal("0")}, statement)
    assert not result.ok
    assert any("MISMATCH" in line for line in result.lines)


def _write_tradebook_csv(path: Path) -> None:
    path.write_text(
        "symbol,isin,trade_date,exchange,trade_type,quantity,price,order_execution_time\n"
        "HDFCBANK,INE040A01034,2026-06-15,BSE,buy,5,785.45,2026-06-15T10:17:43\n"
        "HDFCBANK,INE040A01034,2026-06-17,NSE,sell,5,790.50,2026-06-17T10:50:48\n"
    )


def test_replay_exposes_realized_gains_for_reconciliation(tmp_path: Path) -> None:
    """The replay now carries per-lot gains; a BSE buy + NSE sell reconcile via ISIN to one lot."""
    tb = tmp_path / "tb.csv"
    _write_tradebook_csv(tb)
    trades = parse_tradebook(str(tb))
    result = replay_tradebook(trades, Config())

    assert len(result.realized_gains) == 1
    gain = result.realized_gains[0]
    assert gain.gain_type == "STCG"  # 2-day hold
    assert gain.ticker == "HDFCBANK.NS"  # BSE buy resolved to canonical NSE ticker


def test_zero_cost_replay_reproduces_gross_gain(tmp_path: Path) -> None:
    """A zero-cost replay's gain equals the gross (sell − buy) Zerodha reports as taxable profit."""
    from dataclasses import fields, replace

    tb = tmp_path / "tb.csv"
    _write_tradebook_csv(tb)
    trades = parse_tradebook(str(tb))

    cfg = Config()
    zero = replace(
        cfg.cost,
        **{
            f.name: Decimal("0")
            for f in fields(cfg.cost)
            if isinstance(getattr(cfg.cost, f.name), Decimal)
        },
    )
    gross = replay_tradebook(trades, replace(cfg, cost=zero))
    # 5 * (790.50 - 785.45) = 25.25
    assert gross.realized_gains[0].gain == Decimal("25.25")


# ---- Zerodha renamed its row headings (2026-08-29, found on real money) -------------------------
#
# Between the FY2026-27 Q1 and Q1-Q2 exports Zerodha changed "Short Term profit" to "Equity Short
# Term profit" and "Short Term Trades" to "Equity Short Term". Exact matching found nothing, the
# profit defaulted to Decimal("0"), and the reconciliation panel told the user
# "STCG: ours ₹25.25 vs Zerodha ₹0.00 — MISMATCH — do not rely on the tax figures" about a statement
# that said ₹25.25. Correct arithmetic, wrong on screen — the same family as the seven label defects
# of 2026-08-28, except this one cried wolf instead of hiding a problem.


def _rows_new_format() -> list[list[object]]:
    """The Q1-Q2 layout: every equity heading gained an 'Equity ' prefix; 'Non Equity' row dropped."""
    return [
        [None, "Client ID", "YHK037"],
        [None, None, None],
        [None, "Realized Profit Breakdown", None],
        [None, "Equity Intraday/Speculative profit", 0],
        [None, "Equity Short Term profit", 25.25],
        [None, "Equity Long Term profit", 0],
        [None, None, None],
        [None, "Equity Short Term", None],
        [None, None, None],
        [None, "Symbol", "Quantity", "Buy Value", "Sell Value", "Realized P&L"],
        [None, "HDFCBANK", 5, 3927.25, 3952.5, 25.25],
    ]


def _write_rows(path: Path, rows: list[list[object]]) -> None:
    pd.DataFrame(rows).to_excel(path, sheet_name="Equity and Non Equity", header=False, index=False)


def test_the_renamed_equity_headings_still_parse(tmp_path: Path) -> None:
    """The exact defect: a renamed heading must not read as ₹0.00."""
    p = tmp_path / "new.xlsx"
    _write_rows(p, _rows_new_format())
    st = parse_taxpnl(p)
    assert st.short_term_profit == Decimal("25.25")
    assert st.long_term_profit == Decimal("0")
    assert [t.symbol for t in st.trades_of("STCG")] == ["HDFCBANK"]


def test_the_renamed_format_reconciles(tmp_path: Path) -> None:
    """End to end: the file that produced a false MISMATCH must now reconcile to ₹0.00."""
    p = tmp_path / "new.xlsx"
    _write_rows(p, _rows_new_format())
    result = reconcile_gross({"STCG": Decimal("25.25"), "LTCG": Decimal("0")}, parse_taxpnl(p))
    assert result.ok, result.lines


def test_an_unreadable_statement_refuses_to_grade_rather_than_reporting_zero(
    tmp_path: Path,
) -> None:
    """The structural fix: absent is NOT zero.

    If a future rename defeats the parser again, the panel must say it could not read the file —
    never present a parse failure as Zerodha's number. Mirrors ``_benchmark_covers`` refusing to
    grade the GO scorecard on a stale benchmark.
    """
    p = tmp_path / "future.xlsx"
    _write_rows(
        p,
        [
            [None, "Client ID", "YHK037"],
            [None, "Realized Profit Breakdown", None],
            [None, "Cash Segment Short Term gains", 25.25],  # a rename we do not know
        ],
    )
    st = parse_taxpnl(p)
    assert "short_term" in st.missing and "long_term" in st.missing

    result = reconcile_gross({"STCG": Decimal("25.25"), "LTCG": Decimal("0")}, st)
    assert not result.ok
    blob = " ".join(result.lines)
    assert "CANNOT RECONCILE" in blob
    assert "PARSE failure, not a tax discrepancy" in blob
    # It must NOT claim Zerodha reported zero — that is the defect being closed.
    assert "₹0.00" not in blob


def test_a_present_zero_is_still_a_real_zero(tmp_path: Path) -> None:
    """Guard the other direction: a genuine ₹0 must reconcile, not be mistaken for missing."""
    p = tmp_path / "zero.xlsx"
    _write_rows(
        p,
        [
            [None, "Client ID", "YHK037"],
            [None, "Realized Profit Breakdown", None],
            [None, "Equity Short Term profit", 0],
            [None, "Equity Long Term profit", 0],
        ],
    )
    st = parse_taxpnl(p)
    assert st.missing == ("intraday", "non_equity")  # not the two that matter
    assert reconcile_gross({"STCG": Decimal("0"), "LTCG": Decimal("0")}, st).ok
