"""Funding: the money that reached the account, and what it costs to get it wrong.

The books used to be funded from the tradebook — money that reached the *market*. Two lakh of
deposited cash therefore sat outside every comparison, and a book holding it looked identical to a
book that had never received it. These tests pin the parts of the correction that a future change
could silently undo: the record carries dates and amounts and nothing personal, the replay reports
what it actually spent, and re-funding is refused once the investor has started deciding.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from qalpha.accounting.costs import Side
from qalpha.config import Config
from qalpha.live import funding
from qalpha.live.flows import Flow
from qalpha.live.tradebook import TradebookTrade, replay_tradebook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import twin as twin_script


def _record() -> funding.Funding:
    return funding.Funding(
        movements=(
            funding.Movement(on=date(2026, 6, 14), amount=Decimal("10000"), kind="Bank Receipts"),
            funding.Movement(on=date(2026, 8, 7), amount=Decimal("-4313.85"), kind="Bank Payments"),
            funding.Movement(on=date(2026, 8, 24), amount=Decimal("500000"), kind="Bank Receipts"),
        ),
        closing_balance=Decimal("201116.94"),
        source="ledger-TEST.xlsx",
        imported_at="2026-09-14T10:00:00+00:00",
    )


def test_the_record_survives_a_round_trip_to_the_paise(tmp_path: Path) -> None:
    path = tmp_path / "funding.json"
    funding.save(_record(), path)
    back = funding.load(path)
    assert back == _record()
    assert back is not None and back.net == Decimal("505686.15")


def test_the_record_keeps_no_personal_detail(tmp_path: Path) -> None:
    """The ledger names a client id in every description. This file is committed; the ledger is not.

    A field that carried the description through would publish the account number on every push.
    """
    path = tmp_path / "funding.json"
    funding.save(_record(), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw["movements"][0]) == {"on", "amount", "kind"}
    assert set(raw) == {"source", "imported_at", "closing_balance", "movements"}


def test_an_unreadable_record_is_not_imported_rather_than_guessed_at(tmp_path: Path) -> None:
    """Unknown is never substituted: a corrupt file must not fund the books with ₹0."""
    path = tmp_path / "funding.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert funding.load(path) is None
    assert funding.load(tmp_path / "absent.json") is None


def test_two_movements_on_one_day_are_one_flow(tmp_path: Path) -> None:
    """Every book is funded with the same rupees on the same days; a day is the unit."""
    record = funding.Funding(
        movements=(
            funding.Movement(on=date(2026, 8, 24), amount=Decimal("300000"), kind="Bank Receipts"),
            funding.Movement(on=date(2026, 8, 24), amount=Decimal("200000"), kind="Bank Receipts"),
            funding.Movement(on=date(2026, 8, 25), amount=Decimal("500"), kind="Bank Receipts"),
            funding.Movement(on=date(2026, 8, 25), amount=Decimal("-500"), kind="Bank Payments"),
        ),
        closing_balance=Decimal("0"),
        source="x",
        imported_at="",
    )
    flows = record.flows()
    assert [(f.on, f.amount) for f in flows] == [(date(2026, 8, 24), Decimal("500000"))]


def test_the_replay_reports_what_the_trades_spent_not_the_sentinel(tmp_path: Path) -> None:
    """``cash`` only *sets* the closing figure. Subtracting it from the replay's working balance
    once reported ₹-999,999,494,313.85 of spending, so the number is carried explicitly."""
    trades = [
        TradebookTrade(date(2026, 6, 15), "INFY.NS", Side.BUY, Decimal("5"), Decimal("1000")),
        TradebookTrade(date(2026, 8, 28), "INFY.NS", Side.SELL, Decimal("5"), Decimal("1100")),
    ]
    result = replay_tradebook(trades, Config(), cash=Decimal("12345"))
    assert result.portfolio.cash == Decimal("12345")
    # Bought ₹5,000, sold ₹5,500: the trades returned money, net of charges and tax.
    assert Decimal("-500") < result.net_spent < Decimal("0")


def test_a_book_funded_with_the_ledger_holds_the_cash_it_did_not_spend() -> None:
    """The property the whole change exists for: deposited − spent, not ₹0 and not the deposit."""
    from qalpha.live.twin import REAL, seed_books

    trades = [TradebookTrade(date(2026, 6, 15), "INFY.NS", Side.BUY, Decimal("5"), Decimal("1000"))]
    flows = [Flow(on=date(2026, 6, 14), amount=Decimal("50000"))]
    books = seed_books(trades, Config(), flows=flows)
    twin_script.replay_real(books[REAL], trades, Config())
    spent = replay_tradebook(trades, Config()).net_spent
    assert books[REAL].portfolio.cash == Decimal("50000") - spent
    assert Decimal("44000") < books[REAL].portfolio.cash < Decimal("45000")


def test_refunding_is_refused_once_the_investor_has_decided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Re-funding changes what every comparison means. After the first decision that is a rewrite
    of a running record, so the command refuses rather than doing it quietly."""
    from qalpha.live.twin import REAL, SYSTEM, seed_books

    path = tmp_path / "funding.json"
    funding.save(_record(), path)
    monkeypatch.setattr(funding, "FUNDING_PATH", path)
    monkeypatch.setattr(twin_script.funding_record, "FUNDING_PATH", path)

    trades = [TradebookTrade(date(2026, 6, 15), "INFY.NS", Side.BUY, Decimal("5"), Decimal("1000"))]
    books = seed_books(trades, Config())
    books[SYSTEM].manager = {"last_review": "2026-09-15"}
    monkeypatch.setattr(twin_script, "load_books", lambda cfg: books)
    monkeypatch.setattr(twin_script, "_tradebook", lambda: (trades, []))
    saved: list[object] = []
    monkeypatch.setattr(twin_script, "save_books", lambda b: saved.append(b))

    assert twin_script.cmd_refund(Config()) == twin_script.ABORTED
    assert not saved, "a refused refund must not write"
    assert "has already decided" in capsys.readouterr().err

    books[SYSTEM].manager = {}
    assert twin_script.cmd_refund(Config()) == 0
    assert saved, "with nothing decided it must actually re-fund"
    assert sum((f.amount for f in books[REAL].flows), Decimal("0")) == Decimal("505686.15")


def test_the_provenance_identifies_the_export_without_naming_the_account(tmp_path: Path) -> None:
    """A Console export is named ``ledger-<client id>.xlsx``. This repository is public, and the
    funding record is tracked, so the name must not travel with it — the digest answers "which
    export produced this?" for anyone who holds the export, and tells a stranger nothing."""
    statement = tmp_path / "ledger-ZZZ999.xlsx"
    statement.write_bytes(b"whatever the broker wrote")
    line = funding.provenance(statement)
    assert line.startswith("ledger · sha256:")
    assert "ZZZ999" not in line
    # Same bytes, same provenance; different bytes, different provenance.
    assert funding.provenance(statement) == line
    statement.write_bytes(b"a later export")
    assert funding.provenance(statement) != line


def test_no_tracked_file_names_the_users_broker_account() -> None:
    """The exports are gitignored; their *names* leaked into defaults and fixtures anyway.

    A Zerodha client id is not a credential, but paired with the repository owner's name it is an
    identifier, and this repository is public. Fixtures use a fictional id; entry points find the
    exports by shape.
    """
    import subprocess

    # Assembled, so this test is not itself the match it is looking for.
    client_id = "YHK" + "037"
    root = Path(__file__).resolve().parent.parent
    hits = subprocess.run(
        [
            "git",
            "grep",
            "-lI",
            client_id,
            "--",
            "*.py",
            "*.md",
            "*.json",
            "*.csv",
            "*.yml",
            "*.toml",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert hits.stdout.strip() == "", f"client id in tracked files: {hits.stdout}"
