"""The accounting acceptance scenario: one book, everything that can happen to it, no manual edit.

README step A says this step is done when *"one scenario with a deposit, dividend, corporate action,
partial sale, tax, missing quote and restart reconciles with no manual edit."* This is that scenario,
run through the production entry points rather than around them.

It is one test on purpose. Each of these has been correct in isolation before and wrong in
combination: a dividend that moved a cost basis, a split that broke FIFO order, a missing quote read
as zero, a restart that lost the cash. What matters is that they compose.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from qalpha.accounting.corporate_actions import CorporateAction, CorporateActionType
from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live.flows import Flow
from qalpha.live.tradebook import TradebookTrade, replay_tradebook
from qalpha.live.twin import (
    REAL,
    SYSTEM,
    credit_actions,
    load_books,
    mark,
    save_books,
    seed_books,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import twin as twin_script

# ---- the world -----------------------------------------------------------------------------------

DEPOSITS = [
    Flow(on=date(2026, 1, 5), amount=Decimal("100000")),
    Flow(on=date(2026, 4, 1), amount=Decimal("50000")),  # a second deposit, mid-life
]

TRADES = [
    # Bought before every action, so each one lands on a real holding.
    TradebookTrade(date(2026, 1, 6), "SPLITCO.NS", Side.BUY, Decimal("100"), Decimal("500")),
    TradebookTrade(date(2026, 1, 6), "PAYER.NS", Side.BUY, Decimal("200"), Decimal("150")),
    TradebookTrade(date(2026, 1, 6), "DARK.NS", Side.BUY, Decimal("50"), Decimal("100")),
    # A second lot, so the partial sale below has to pick the older one.
    TradebookTrade(date(2026, 4, 2), "PAYER.NS", Side.BUY, Decimal("100"), Decimal("180")),
    # The partial sale: 250 of 300 PAYER, leaving the newer lot partly intact.
    TradebookTrade(date(2026, 6, 10), "PAYER.NS", Side.SELL, Decimal("250"), Decimal("210")),
]

ACTIONS = [
    # A dividend on the ex-date, before that day's trades: income, never a lot.
    CorporateAction(
        ticker="PAYER.NS",
        ex_date=date(2026, 3, 2),
        action_type=CorporateActionType.DIVIDEND,
        amount_per_share=Decimal("4"),
    ),
    # A 5:1 split: share count ×5, cost per share ÷5, total cost and acquisition date preserved.
    CorporateAction(
        ticker="SPLITCO.NS",
        ex_date=date(2026, 3, 10),
        action_type=CorporateActionType.SPLIT,
        ratio=Decimal("5"),
    ),
]

#: What the "broker" says is held at the end — the independent check on the replay.
STATEMENT = {"SPLITCO.NS": Decimal("500"), "PAYER.NS": Decimal("50"), "DARK.NS": Decimal("50")}

#: DARK has no quote anywhere. It is held, it is real, and it has no value on this page.
PRICES = {"SPLITCO.NS": Decimal("110"), "PAYER.NS": Decimal("205")}


@pytest.fixture
def books(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr("qalpha.live.twin.TWIN_STATE", tmp_path / "books.json")
    monkeypatch.setattr(twin_script, "_actions", lambda: list(ACTIONS))
    monkeypatch.setattr("qalpha.live.twin.load_off_market", lambda *a, **k: [])
    seeded = seed_books(TRADES, Config(), flows=DEPOSITS)
    twin_script.replay_real(seeded[REAL], TRADES, Config())
    return seeded  # type: ignore[return-value]


# ---- the scenario ----------------------------------------------------------------------------------


def test_the_whole_scenario_reconciles_with_no_manual_edit(
    books: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = books[REAL]
    portfolio = real.portfolio  # type: ignore[attr-defined]

    # 1. The corporate action reshaped the lots, and the broker's share count is reproduced exactly.
    held = portfolio.positions()
    assert held == STATEMENT, "the replay must reproduce the statement without a manual adjustment"

    # 2. The split preserved total cost and the acquisition date — it is not a purchase.
    lots = portfolio.ledger.open_lots("SPLITCO.NS")
    assert sum(lt.quantity_remaining for lt in lots) == Decimal("500")
    assert all(lt.acquisition_date == date(2026, 1, 6) for lt in lots), (
        "a split does not restart the holding period — the §2(42A) clock runs from the original buy"
    )
    cost = sum(lt.cost_basis_per_share * lt.quantity_remaining for lt in lots)
    unsplit = replay_tradebook(TRADES, Config()).portfolio.ledger.open_lots("SPLITCO.NS")
    assert cost == sum(lt.cost_basis_per_share * lt.quantity_remaining for lt in unsplit), (
        "total cost is unchanged by a split; only the per-share figure moves"
    )

    # 3. The dividend was income: cash, and not one paise on any lot.
    payer_cost = sum(
        lt.cost_basis_per_share * lt.quantity_remaining
        for lt in portfolio.ledger.open_lots("PAYER.NS")
    )
    no_actions = replay_tradebook(TRADES, Config())
    payer_cost_without = sum(
        lt.cost_basis_per_share * lt.quantity_remaining
        for lt in no_actions.portfolio.ledger.open_lots("PAYER.NS")
    )
    assert payer_cost == payer_cost_without, "a dividend must never move a cost basis"

    # 4. The partial sale realized tax, FIFO, on the older lot first.
    with_actions = replay_tradebook(TRADES, Config(), corporate_actions=ACTIONS)
    assert with_actions.realized_gains, "a sale must realize gains, not vanish"
    assert with_actions.realized_tax >= 0
    consumed = sum(g.quantity for g in with_actions.realized_gains)
    assert consumed == Decimal("250")
    assert with_actions.realized_gains[0].acquisition_date == date(2026, 1, 6), (
        "FIFO: the January lot is consumed before the April one"
    )

    # 5. The cash is the deposits, less what the trades spent, plus the dividend — one arithmetic.
    dividend = Decimal("200") * Decimal("4")  # 200 PAYER held into the 2 March ex-date
    deposited = sum((f.amount for f in DEPOSITS), Decimal("0"))
    assert portfolio.cash == deposited - with_actions.net_spent
    assert with_actions.net_spent < no_actions.net_spent, (
        "the dividend is money in: it must reduce what the trades net out to"
    )
    assert no_actions.net_spent - with_actions.net_spent == dividend

    # 6. A held name with no quote is unpriced, not zero.
    marked = mark(real, PRICES, date(2026, 6, 30))  # type: ignore[arg-type]
    priced = Decimal("500") * PRICES["SPLITCO.NS"] + Decimal("50") * PRICES["PAYER.NS"]
    assert marked.value == portfolio.cash + priced, (
        "DARK contributes nothing because it has no price — it must not contribute a zero either"
    )
    assert portfolio.ledger.quantity_held("DARK.NS") == Decimal("50"), (
        "and it is still held: an unpriced holding is not a sold one"
    )

    # 7. Restart: everything survives the file, to the paise.
    save_books(books, tmp_path / "books.json")  # type: ignore[arg-type]
    reloaded = load_books(Config(), tmp_path / "books.json")
    back = reloaded[REAL]
    assert back.portfolio.cash == portfolio.cash
    assert back.portfolio.positions() == STATEMENT
    assert back.flows == real.flows  # type: ignore[attr-defined]
    assert mark(back, PRICES, date(2026, 6, 30)).value == marked.value


def test_a_deciding_book_is_credited_once_and_only_forward(books: dict[str, object]) -> None:
    """SYSTEM has its own holdings once it starts deciding, so it has no replay to recompute from.

    The watermark is the whole safety of that path: a dividend credited twice is indistinguishable,
    afterwards, from a dividend that was larger.
    """
    system = books[SYSTEM]
    # Its own holdings, replayed WITHOUT the actions: this book is about to be credited them.
    system.portfolio = replay_tradebook(TRADES, Config()).portfolio  # type: ignore[attr-defined]
    system.actions_through = date(2026, 3, 1)  # type: ignore[attr-defined]
    before = system.portfolio.cash  # type: ignore[attr-defined]

    notes = credit_actions(system, ACTIONS, through=date(2026, 6, 30))  # type: ignore[arg-type]
    after_once = system.portfolio.cash  # type: ignore[attr-defined]
    assert len(notes) == 2, "both the dividend and the split fell inside the window"
    # 300 PAYER were held by the time the replay finished, but entitlement is the holding on the
    # ex-date — which this path reads from the book as it stands, not as it stood in March. That is
    # why a book with a replay uses the replay: the watermark path is only ever run forward, on
    # actions that have not happened yet.
    assert after_once > before
    assert system.portfolio.ledger.quantity_held("SPLITCO.NS") == Decimal("500")  # type: ignore[attr-defined]

    # Run the same evening again — a retried job must change nothing.
    assert credit_actions(system, ACTIONS, through=date(2026, 6, 30)) == []  # type: ignore[arg-type]
    assert system.portfolio.cash == after_once  # type: ignore[attr-defined]

    # And an action before the watermark is never reached back for.
    assert system.actions_through == date(2026, 6, 30)  # type: ignore[attr-defined]


def test_an_untracked_book_is_moved_forward_and_credited_nothing(
    books: dict[str, object],
) -> None:
    """A book with no watermark and no history must not retroactively receive a year of dividends.

    It may already have them by another path; crediting them again is unrecoverable, while crediting
    nothing is visible in the next reconciliation.
    """
    system = books[SYSTEM]
    system.actions_through = None  # type: ignore[attr-defined]
    system.stepped_through = None  # type: ignore[attr-defined]
    system.flows = []  # type: ignore[attr-defined]
    cash = system.portfolio.cash  # type: ignore[attr-defined]

    assert credit_actions(system, ACTIONS, through=date(2026, 6, 30)) == []  # type: ignore[arg-type]
    assert system.portfolio.cash == cash  # type: ignore[attr-defined]
    assert system.actions_through == date(2026, 6, 30)  # type: ignore[attr-defined]
