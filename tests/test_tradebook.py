"""Zerodha tradebook → dated FIFO Portfolio (Q_alpha.md §14 crit 4).

A fixture CSV in the Console export shape drives parse + replay; the key checks are that dated lots
make the holding period (LTCG vs STCG) exact and that an unmatched sell warns instead of crashing.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live.advisor import advise_sell
from qalpha.live.tradebook import (
    parse_tradebook,
    reconcile_positions,
    replay_tradebook,
)

# Console tradebook columns; INFY held long-term (small gain → exempt), TCS a short-term taxed gain.
_CSV = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
INFY,INE009A01021,2023-01-02,NSE,EQ,EQ,buy,FALSE,10,1500,1,1,2023-01-02 09:30:00
HDFCBANK,INE040A01034,2023-01-02,NSE,EQ,EQ,buy,FALSE,5,1600,2,2,2023-01-02 09:31:00
TCS,INE467B01029,2024-03-01,NSE,EQ,EQ,buy,FALSE,100,3000,3,3,2024-03-01 10:00:00
TCS,INE467B01029,2024-06-01,NSE,EQ,EQ,sell,FALSE,100,3500,4,4,2024-06-01 10:00:00
INFY,INE009A01021,2024-06-03,NSE,EQ,EQ,sell,FALSE,10,1800,5,5,2024-06-03 11:00:00
"""


def _trades():  # type: ignore[no-untyped-def]
    return parse_tradebook(io.StringIO(_CSV))


def test_parse_normalizes_tickers_and_sides() -> None:
    trades = _trades()
    assert len(trades) == 5
    first = trades[0]
    assert first.ticker == "INFY.NS"
    assert first.side is Side.BUY
    assert first.trade_date == date(2023, 1, 2)
    assert first.quantity == Decimal("10")
    assert first.price == Decimal("1500.00")
    assert {t.side for t in trades} == {Side.BUY, Side.SELL}


def test_replay_builds_dated_lots_and_realizes_tax() -> None:
    result = replay_tradebook(_trades(), Config(), cash=Decimal("1000"))
    assert result.n_trades == 5
    # INFY + TCS fully sold; only HDFCBANK remains open.
    assert result.portfolio.positions() == {"HDFCBANK.NS": Decimal("5")}
    assert result.portfolio.cash == Decimal("1000")
    # TCS was a ~₹50k short-term gain → taxed at 20%; INFY long-term gain sits inside the exemption.
    assert Decimal("8000") < result.realized_tax < Decimal("11000")
    assert not result.warnings


def test_dated_lot_makes_advice_long_term() -> None:
    pf = replay_tradebook(_trades(), Config(), cash=Decimal("0")).portfolio
    # HDFCBANK bought 2023-01-02; selling on 2024-06-03 is long-term (>365d) — exact only because the
    # lot is dated. A holdings-snapshot (undated) portfolio would wrongly treat it as short-term.
    advice = advise_sell(pf, "HDFCBANK.NS", Decimal("1700"), date(2024, 6, 3), Config())
    assert advice.ltcg_gain > 0
    assert advice.stcg_gain == 0


def test_reconcile_positions_flags_mismatch() -> None:
    pf = replay_tradebook(_trades(), Config()).portfolio
    assert reconcile_positions(pf, {"HDFCBANK.NS": Decimal("5")}) == []
    issues = reconcile_positions(pf, {"HDFCBANK.NS": Decimal("6")})
    assert len(issues) == 1 and "HDFCBANK.NS" in issues[0]


def test_unmatched_sell_warns_not_crashes() -> None:
    csv = (
        "symbol,trade_date,trade_type,quantity,price\n"
        "ZZZ,2024-01-01,sell,5,100\n"  # sold without a prior buy in the export
    )
    result = replay_tradebook(parse_tradebook(io.StringIO(csv)), Config())
    assert result.n_trades == 0
    assert result.portfolio.positions() == {}
    assert len(result.warnings) == 1
    assert "ZZZ.NS" in result.warnings[0]


def test_replay_applies_corporate_actions_in_timeline() -> None:
    """Crit-5 wiring: a held name that splits is reshaped at the ex-date, so the later sell matches."""
    from qalpha.accounting.corporate_actions import CorporateAction
    from qalpha.live.tradebook import TradebookTrade

    cfg = Config()
    trades = [
        TradebookTrade(date(2020, 1, 1), "X.NS", Side.BUY, Decimal("10"), Decimal("1000")),
        TradebookTrade(date(2023, 7, 1), "X.NS", Side.SELL, Decimal("20"), Decimal("600")),
    ]
    # Without the split, selling 20 when only 10 were bought can't match → a warning.
    assert replay_tradebook(trades, cfg).warnings

    # With a 2:1 split interleaved at its ex-date, 10 → 20 shares, so the sell matches cleanly.
    actions = [CorporateAction.split("X.NS", date(2023, 1, 1), Decimal("2"))]
    res = replay_tradebook(trades, cfg, corporate_actions=actions)
    assert res.warnings == []
    assert res.portfolio.positions() == {}  # all 20 (post-split) shares sold
    assert res.realized_gains and all(g.gain_type == "LTCG" for g in res.realized_gains)


def test_setoff_reconciliation_through_replay() -> None:
    """Crit-4 hardening: a multi-lot LTCG-gain + STCL-loss case nets correctly through the pipeline."""
    from qalpha.accounting.capital_gains import net_tax_total
    from qalpha.live.tradebook import TradebookTrade

    cfg = Config()
    trades = [
        TradebookTrade(date(2020, 1, 1), "A.NS", Side.BUY, Decimal("100"), Decimal("1000")),
        TradebookTrade(date(2024, 6, 1), "B.NS", Side.BUY, Decimal("100"), Decimal("1000")),
        TradebookTrade(
            date(2024, 7, 1), "A.NS", Side.SELL, Decimal("100"), Decimal("3000")
        ),  # LTCG
        TradebookTrade(date(2024, 7, 1), "B.NS", Side.SELL, Decimal("100"), Decimal("500")),  # STCL
    ]
    res = replay_tradebook(trades, cfg)
    gross = res.realized_tax  # per-lot, no set-off (a loss simply pays ₹0)
    net = net_tax_total(res.realized_gains, cfg.tax)  # §70: STCL offsets the LTCG first
    assert any(g.gain > 0 for g in res.realized_gains)  # the LTCG gain
    assert any(g.gain < 0 for g in res.realized_gains)  # the STCL loss
    assert net < gross  # the loss set-off saved tax
    assert net > 0  # LTCG above the ₹1.25L exemption is still taxed
