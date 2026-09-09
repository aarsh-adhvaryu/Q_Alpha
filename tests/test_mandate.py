"""The mandate — gate 1's "store the budget and risk limits once".

The limits used to live in three kinds of place and two of them were not storage: ``0.30`` and
``0.20`` were **default arguments** of ``advise_deploy_into_weakness``, and the monthly instalment
was a sentence in OPERATING.md that no code had ever read. These tests pin the values (so this
refactor cannot quietly move a limit) and the reserved-cash rule (so the buy screen cannot go back
to proposing next month's money).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from qalpha.live.mandate import Mandate, load_mandate


def test_the_defaults_are_the_values_already_in_force() -> None:
    """This refactor must change no number. Each of these is the value it replaced, in place."""
    m = Mandate()
    assert m.max_name_fraction == 0.20, "advise_deploy_into_weakness's default"
    assert m.max_sector_weight == 0.30, "advise_deploy_into_weakness's default"
    assert m.idle_cash_floor == Decimal("5000"), "cfg.deploy_policy.idle_cash_floor"
    assert m.monthly_budget == Decimal("50000"), 'OPERATING.md §1 — "Type 50000"'


def test_one_instalment_is_proposed_however_much_cash_is_sitting_there() -> None:
    """The live account on 2026-09-09 held ₹2,01,117, of which one instalment is this month's.

    The dashboard sized a basket against the whole balance because nothing in the system knew the
    difference — ``advisor.py:664``: "SIP instalment and cash waiting to be deployed look identical
    from here; only the person who put it there knows which is which."
    """
    m = Mandate()
    assert m.deployable(Decimal("201117")) == Decimal("50000")
    assert m.reserved(Decimal("201117")) == Decimal("151117")


def test_a_balance_smaller_than_one_instalment_is_spent_whole() -> None:
    m = Mandate()
    assert m.deployable(Decimal("12000")) == Decimal("12000")
    assert m.reserved(Decimal("12000")) == Decimal("0")


def test_below_the_floor_nothing_is_deployable_and_nothing_is_pretended() -> None:
    """A token basket built from ₹900 is worse than no advice: it pays a round trip to do nothing."""
    m = Mandate()
    assert m.deployable(Decimal("900")) == Decimal("0")
    assert m.reserved(Decimal("900")) == Decimal("900")


def test_deployable_plus_reserved_is_always_the_balance() -> None:
    """The two figures are shown side by side on the page. If they do not add up, one of them is a
    lie, and the reader has no way to tell which."""
    m = Mandate()
    for cash in ("0", "900", "5000", "49999", "50000", "50001", "201117", "5000000"):
        c = Decimal(cash)
        assert m.deployable(c) + m.reserved(c) == c


def test_a_missing_mandate_file_is_the_documented_default_not_an_error(tmp_path: Path) -> None:
    assert load_mandate(tmp_path / "absent.json") == Mandate()


def test_a_customised_mandate_is_read(tmp_path: Path) -> None:
    p = tmp_path / "mandate.json"
    p.write_text(json.dumps({"monthly_budget": "25000", "max_names": 3}), encoding="utf-8")
    m = load_mandate(p)
    assert m.monthly_budget == Decimal("25000")
    assert m.max_names == 3
    assert m.max_sector_weight == 0.30, "unspecified fields keep the default"


def test_a_cap_written_as_a_percentage_is_refused(tmp_path: Path) -> None:
    """``max_name_fraction: 20`` means "20%" to a human and "2000%" to the code — which does not
    tighten the cap, it removes it. Silently accepting it is the direction that loses money."""
    p = tmp_path / "mandate.json"
    p.write_text(json.dumps({"max_name_fraction": 20, "max_sector_weight": 0}), encoding="utf-8")
    m = load_mandate(p)
    assert m.max_name_fraction == 0.20, "20 is not a fraction; the default must survive"
    assert m.max_sector_weight == 0.30, "0 would forbid every basket; the default must survive"


def test_a_corrupt_mandate_falls_back_rather_than_taking_the_page_down(tmp_path: Path) -> None:
    p = tmp_path / "mandate.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_mandate(p) == Mandate()


def test_the_buy_surface_sizes_against_the_mandate_not_the_balance() -> None:
    """The caller, not just the function. The defect was never in the arithmetic — it was that the
    dashboard passed ``portfolio.cash`` and nothing looked at a budget."""
    import inspect
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import dashboard_app

    src = inspect.getsource(dashboard_app._advisor_with_safety)
    assert "mandate.deployable(" in src, "the auto brief must size against one instalment"
    assert "_auto_pm_brief(portfolio, benchmark, available_cash" not in src, (
        "the whole balance must not reach the brief again"
    )
