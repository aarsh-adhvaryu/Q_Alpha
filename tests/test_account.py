"""Track 1 — the reconciled account, and the base every other book is seeded from.

The twin's ``REAL`` book held **nothing**: ₹3,04,144 of cash and zero open lots, while the actual
Zerodha account held eight names worth ₹2,93,197. The value the dashboard printed for REAL came from
a different code path, which is why its holdings chart said "nothing priced yet" beneath a
valuation. "Start every book from a copy of my actual account" needed a copy of the account, and
there was none.

These pin the three ways a replay can disagree with the broker, because they are different facts
with different consequences and collapsing them is how a book that does not match reality becomes
the base for a decision.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from qalpha.accounting.costs import Side
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.account import ReconciledAccount, reconcile
from qalpha.live.session import snapshot_from
from qalpha.live.tradebook import TradebookTrade

CFG = Config()
AS_OF = date(2026, 9, 9)
CASH = Decimal("201117")


def _buy(ticker: str, qty: str, price: str, on: date = date(2026, 8, 29)) -> TradebookTrade:
    return TradebookTrade(
        trade_date=on,
        ticker=ticker,
        side=Side.BUY,
        quantity=Decimal(qty),
        price=Decimal(price),
        exec_time="10:00:00",
        trade_id=f"{ticker}-{qty}-{on}",
    )


def test_a_replay_that_matches_the_broker_tallies_and_is_tax_exact() -> None:
    trades = [_buy("VBL.NS", "147", "414.23"), _buy("TCS.NS", "10", "2340.04")]
    acct = reconcile(trades, {"VBL.NS": Decimal("147"), "TCS.NS": Decimal("10")}, CASH, CFG, AS_OF)

    assert acct.tallies and acct.blocking == ()
    assert acct.dated and acct.tax_exact
    assert acct.portfolio.positions() == {"VBL.NS": Decimal("147"), "TCS.NS": Decimal("10")}
    assert "match your broker account exactly" in acct.report()


def test_a_stock_bought_in_kite_is_named_and_does_not_block_the_run() -> None:
    """THE "I added a stock" case, and it is normal. Refusing to run until a CSV arrives would make
    the system useless on exactly the day something changed — so it is a loud caveat, not a stop."""
    trades = [_buy("VBL.NS", "147", "414.23")]
    acct = reconcile(
        trades, {"VBL.NS": Decimal("147"), "HDFCBANK.NS": Decimal("25")}, CASH, CFG, AS_OF
    )

    assert acct.broker_only == ("HDFCBANK.NS",)
    assert not acct.tallies
    assert acct.blocking == (), "a new purchase must not stop the run"
    assert not acct.tax_exact, "but its tax cannot be computed without a purchase date"
    assert "HDFCBANK" in acct.report() and "upload a tradebook" in acct.report()


def test_a_quantity_disagreement_blocks_because_the_lots_are_wrong() -> None:
    """Same name, different count — a corporate action or a missing trade. The lots are wrong, so
    the tax computed from them is wrong, and nothing should be decided on it."""
    trades = [_buy("VBL.NS", "147", "414.23")]
    acct = reconcile(trades, {"VBL.NS": Decimal("294")}, CASH, CFG, AS_OF)

    assert acct.mismatched and "ledger 147 vs broker 294" in acct.mismatched[0]
    assert acct.blocking, "a book that does not match the broker is not a base for a decision"


def test_the_ledger_holding_something_the_broker_does_not_also_blocks() -> None:
    trades = [_buy("VBL.NS", "147", "414.23"), _buy("TCS.NS", "10", "2340.04")]
    acct = reconcile(trades, {"VBL.NS": Decimal("147")}, CASH, CFG, AS_OF)

    assert acct.tradebook_only == ("TCS.NS",)
    assert acct.blocking


def test_no_tradebook_means_undated_lots_and_no_exact_tax() -> None:
    """The broker's holdings give a blended average and no purchase dates. That is enough to value a
    position and nowhere near enough to tax one — FIFO needs to know which shares were bought when."""
    acct = reconcile([], {}, CASH, CFG, AS_OF)
    assert not acct.dated and not acct.tax_exact
    assert acct.tallies, "an empty ledger against an unqueried broker is not a disagreement"
    assert "estimate" in acct.report()


# --- the bridge into the run -------------------------------------------------------------------
def test_the_snapshot_carries_the_accounts_blocking_reasons() -> None:
    """A book that does not tally must not silently become the base for a decision."""
    from datetime import UTC, datetime

    trades = [_buy("VBL.NS", "147", "414.23")]
    bad = reconcile(trades, {"VBL.NS": Decimal("294")}, CASH, CFG, AS_OF)
    snap = snapshot_from(
        bad,
        budget=Decimal("50000"),
        universe=("VBL.NS",),
        taken_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    assert not snap.usable
    assert any("disagree" in m for m in snap.missing_critical)


def test_the_snapshot_takes_the_mandates_budget_not_the_broker_balance() -> None:
    """₹2,01,117 sits in the account and one instalment is deployable. The snapshot must carry the
    allowance, or every book downstream sizes against several months of future contributions."""
    from datetime import UTC, datetime

    good = reconcile(
        [_buy("VBL.NS", "147", "414.23")], {"VBL.NS": Decimal("147")}, CASH, CFG, AS_OF
    )
    snap = snapshot_from(
        good,
        budget=Decimal("50000"),
        universe=("VBL.NS",),
        taken_at=datetime(2026, 9, 9, tzinfo=UTC),
    )
    assert snap.usable
    assert snap.cash == CASH, "the balance is recorded"
    assert snap.budget == Decimal("50000"), "but the budget is the mandate's"
    assert snap.holdings == {"VBL.NS": 147}


def test_undated_lots_are_a_caveat_on_the_snapshot_not_a_stop() -> None:
    from datetime import UTC, datetime

    acct = reconcile([], {}, CASH, CFG, AS_OF)
    snap = snapshot_from(
        acct, budget=Decimal("50000"), universe=(), taken_at=datetime(2026, 9, 9, tzinfo=UTC)
    )
    assert snap.usable, "an undated book can still be valued and monitored"
    assert any("undated" in s for s in snap.stale), "and the caveat travels with it"


# --- found in review 2026-09-09 -----------------------------------------------------------------
def test_a_stock_bought_in_kite_is_actually_in_the_copied_portfolio() -> None:
    """FOUND IN REVIEW, and it falsified the claim this module was built on.

    The reconciler named HDFCBANK as ``broker_only`` and then handed downstream a portfolio
    containing only VBL. So "if I buy a stock in Kite it appears" was false: it could not be valued,
    could not be monitored, and did not count toward concentration. Naming a thing is not carrying
    it.

    It is carried now as an undated lot at the broker's average cost — exact value, unknown tax.
    """
    acct = reconcile(
        [_buy("VBL.NS", "147", "414.23")],
        {"VBL.NS": Decimal("147"), "HDFCBANK.NS": Decimal("25")},
        CASH,
        CFG,
        AS_OF,
        broker_costs={"HDFCBANK.NS": Decimal("1900")},
    )
    assert acct.portfolio.positions() == {"VBL.NS": Decimal("147"), "HDFCBANK.NS": Decimal("25")}
    assert acct.broker_only == ("HDFCBANK.NS",)
    assert acct.undated_tickers == ("HDFCBANK.NS",)
    assert not acct.tax_exact, "its tax is unknown, and that is tracked per name"
    assert "HDFCBANK" in acct.report()


def test_a_holding_with_no_broker_cost_is_carried_rather_than_dropped() -> None:
    """A missing average price is not a reason to lose the position. Value is wrong until a
    tradebook arrives; quantity, concentration and monitoring are right immediately."""
    acct = reconcile(
        [_buy("VBL.NS", "147", "414.23")],
        {"VBL.NS": Decimal("147"), "HDFCBANK.NS": Decimal("25")},
        CASH,
        CFG,
        AS_OF,
    )
    assert acct.portfolio.positions()["HDFCBANK.NS"] == Decimal("25")


def test_an_unmatched_sale_makes_the_tax_inexact_even_when_quantities_agree() -> None:
    """FOUND IN REVIEW. A sale the replay could not match means part of the HISTORY is missing, and
    history is what FIFO consumes — but the remaining quantities can still agree with the broker
    perfectly, so ``tallies`` says nothing about it. ``tax_exact`` was True."""
    sale = TradebookTrade(
        trade_date=date(2026, 9, 1),
        ticker="OLDCO.NS",
        side=Side.SELL,
        quantity=Decimal("10"),
        price=Decimal("100"),
        exec_time="10:00:00",
        trade_id="sale",
    )
    acct = reconcile(
        [_buy("VBL.NS", "147", "414.23"), sale], {"VBL.NS": Decimal("147")}, CASH, CFG, AS_OF
    )
    assert acct.replay_warnings, "the engine warned"
    assert acct.tallies, "and the quantities still agree"
    assert not acct.tax_exact, "but the tax history is incomplete, so nothing may call it exact"


# --- was the broker actually asked? --------------------------------------------------------------
#
# `tallies` answers "were any disagreements found", which is vacuously yes when nothing was
# compared. With no session and no trades the page printed
#
#     Account   reconciled ✓
#     ✓ Reconstructed holdings match your broker account exactly.
#
# directly above a log line reading "Account NOT checked against the broker — no session this run".
# A tick on this surface means it is safe to act on.
def test_an_unchecked_broker_is_not_a_confirmation() -> None:
    """THE ONE THIS BLOCK EXISTS FOR. Agreement was not found — it was not looked for."""
    acct = reconcile([], {}, CASH, CFG, AS_OF, broker_checked=False)
    assert acct.tallies, "no disagreements were found, which is still true"
    assert not acct.broker_confirmed, "but nothing was compared, so nothing is confirmed"
    assert acct.broker_state == "unchecked"


def test_the_report_says_it_was_not_checked_rather_than_showing_a_tick() -> None:
    text = reconcile([], {}, CASH, CFG, AS_OF, broker_checked=False).report()
    assert "match your broker account exactly" not in text
    assert "was NOT asked this run" in text
    assert "it was not looked for" in text


def test_a_checked_and_matching_account_still_gets_its_tick() -> None:
    """The fix must not take the confirmation away from runs that earned it."""
    trades = [_buy("VBL.NS", "147", "414.23")]
    acct = reconcile(trades, {"VBL.NS": Decimal("147")}, CASH, CFG, AS_OF)
    assert acct.broker_confirmed and acct.broker_state == "confirmed"
    assert "match your broker account exactly" in acct.report()


def test_a_disagreement_is_still_distinct_from_not_looking() -> None:
    """Three states, because there are three."""
    trades = [_buy("VBL.NS", "147", "414.23")]
    acct = reconcile(trades, {"VBL.NS": Decimal("100")}, CASH, CFG, AS_OF)
    assert acct.broker_state == "disagrees"
    assert not acct.broker_confirmed


def test_checked_is_the_default_so_existing_callers_are_unchanged() -> None:
    assert reconcile([], {}, CASH, CFG, AS_OF).broker_checked is True


def _unchecked_account(**kw: object) -> ReconciledAccount:
    cfg = Config()
    return ReconciledAccount(
        as_of=date(2026, 9, 12),
        portfolio=Portfolio(cfg.cost, cfg.tax, cash=Decimal("0")),
        cash=Decimal("0"),
        dated=True,
        **kw,  # type: ignore[arg-type]
    )


def test_an_unreached_broker_is_not_a_broker_that_disagreed() -> None:
    """With no session every held name looks 'missing', and that is not what it means.

    `broker_quantities` arrives empty, so every replayed ticker has ``theirs == 0`` and is filed as
    ``tradebook_only``. The gate then recited all of them as *"held in the ledger but not at the
    broker"* — the account telling the user his shares are gone when nobody had asked. This is the
    iron rule (unknown is never substituted) on the surface that decides whether it is safe to act.
    """
    unchecked = _unchecked_account(tradebook_only=("INFY.NS", "TCS.NS"), broker_checked=False)
    assert unchecked.broker_state == "unchecked"
    assert unchecked.blocking, "an unconfirmed ledger must still block — only the reason changes"
    reason = " ".join(unchecked.blocking)
    assert "not reached" in reason
    assert "INFY" not in reason and "TCS" not in reason, (
        "names were recited as discrepancies by a run that never compared them"
    )


def test_a_broker_that_was_asked_and_disagreed_still_names_the_names() -> None:
    """The other half: when the comparison really happened, the gate must still be specific."""
    checked = _unchecked_account(tradebook_only=("INFY.NS",), broker_checked=True)
    assert checked.broker_state == "disagrees"
    assert "INFY" in " ".join(checked.blocking)
