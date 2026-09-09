"""Gate 2 — one decision path. **This file is the acceptance criterion, executable.**

> *Identical inputs and policy produce the same orders and reasons on every surface.*

It does not hold today, and the tests that assert it are `xfail(strict=True)`: they pass while the
gate is open and **fail the build the moment it closes**, which is how a specification stays honest
instead of becoming a comment nobody deletes. Closing gate 2 means deleting the xfail marks, not
rewriting the assertions.

WHAT DIVERGES, AS OF 2026-09-08

Four production surfaces call the same screen, `advise_deploy_into_weakness`, with four different
policies, and only one of them then applies the risk layer:

    surface                     spend_idle_cash   broker_prices   post-processing
    dashboard auto-brief        True (default)    yes             NONE
    dashboard Add-money         user toggle       yes             NONE
    evidence / pipeline         False             no              propose(): evidence + governor + anchor
    twin runner                 False             no              AI verdict drop, then execute

The consequence is the wrong way round. **The surface that becomes a real order — the dashboard — is
the only one with no governor, no evidence skip and no anchor.** The pipeline that has all three
never produces an order the user sees. `CLAUDE.md` states this outright: *"It does not touch the
dashboard's buy surface, which calls the screen directly."*

These tests read the call sites rather than building a portfolio fixture on purpose. A fixture test
would assert that two paths agree *on that fixture*; this asserts they are configured with the same
policy at all, which is the thing gate 2 is actually about.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCREEN = "advise_deploy_into_weakness"

#: The surfaces that produce a decision a human or a book acts on. `backtest_sip.py` is research and
#: `autopilot.py` is archived (its cron step is `if: false`), so neither is a production surface.
PRODUCTION_SURFACES = (
    # scripts/dashboard_app.py was deleted on 2026-09-09 with Streamlit. Its buy surface — the one
    # that produced real orders and the one with no risk layer — is now scripts/local_run.py, which is
    # a file-writing local run rather than a server. Four surfaces became three.
    "scripts/local_run.py",
    "scripts/evidence.py",
    "src/qalpha/live/runner.py",
    "scripts/advisor.py",
)


def _literal(node: ast.AST) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return "<dynamic>"


def _call_sites(rel: str) -> list[tuple[int, dict[str, object]]]:
    """Every call to the screen in one file, as ``(line, {kwarg: value})``."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    out: list[tuple[int, dict[str, object]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name != SCREEN:
            continue
        out.append((node.lineno, {kw.arg: _literal(kw.value) for kw in node.keywords if kw.arg}))
    return out


def _all_sites() -> dict[str, dict[str, object]]:
    return {f"{rel}:{line}": kw for rel in PRODUCTION_SURFACES for line, kw in _call_sites(rel)}


# --- the current state, recorded so it is a finding and not only a commit message ---------------
def test_the_screen_really_is_shared_which_is_the_good_news() -> None:
    """Gate 2 is not "four different screens". It is one screen driven four different ways — which
    is a much smaller job than it looks, and worth stating before the failures below."""
    sites = _all_sites()
    assert len(sites) >= 3, f"expected the screen on every surface, found {sorted(sites)}"


def test_no_surface_takes_the_dangerous_default() -> None:
    """``spend_idle_cash`` defaults to True, and ``advise_deploy`` then sets
    ``budget = portfolio.cash + amount``. Every surface must pin it False, because on this account
    the True default turned a ₹50,000 instalment into a ₹5,97,562 basket."""
    taking_default = [site for site, kw in _all_sites().items() if "spend_idle_cash" not in kw]
    assert not taking_default, f"these would deploy the whole balance: {taking_default}"


# --- the acceptance criterion, which does not hold yet ------------------------------------------
def test_every_surface_deploys_under_one_idle_cash_policy() -> None:
    """CLOSED 2026-09-08. The first of the three, and the one that was moving money.

    ``spend_idle_cash`` defaults to True, and ``advise_deploy`` then sets
    ``budget = portfolio.cash + amount``. The dashboard's auto PM brief passed ``available_cash``,
    which *is* ``portfolio.cash`` — so the account's cash was counted twice. On a ₹3,00,000 balance
    it produced **₹5,97,562 of orders** under a heading reading "Idle cash ₹3,00,000". That is the
    2026-08-24 defect verbatim, on a panel written after it was fixed elsewhere.

    A call site that passes a **variable** is exempt: the Add-money tab hands the choice to the user
    behind a checkbox that defaults to False, which is a mandate decision, not an implicit policy.
    What must never differ again is the value a surface picks up *without anyone choosing it*.
    """
    implicit = {
        site: kw.get("spend_idle_cash", True)  # the signature's default
        for site, kw in _all_sites().items()
        if kw.get("spend_idle_cash", True) != "<dynamic>"
    }
    assert implicit, "no implicit call sites found — the audit is looking at the wrong files"
    assert set(implicit.values()) == {False}, (
        f"a surface deploys idle cash without being asked to: {implicit}"
    )


def test_only_a_surface_with_a_broker_passes_broker_prices() -> None:
    """MIS-SPECIFIED WHEN I WROTE IT, corrected 2026-09-09.

    The original asserted every surface must pass ``broker_prices`` identically. That is not
    achievable and not desirable: ``broker_prices`` marks holdings the watchlist panel cannot price —
    IPO allotments, off-panel names — and only the dashboard has a Kite session to ask. The cron and
    the CLI have no broker; passing broker marks from a process with no broker is impossible, not
    merely undone.

    The real property is narrower: **the surface that has a broker uses it, and the ones that do not
    are not pretending to.** The genuine risk it was reaching for — the twin undervaluing a holding
    its panel cannot price — is a different defect, fixed separately by merging the price panels in
    ``_twin_prices`` rather than taking the first that yields anything.
    """
    sites = _all_sites()
    with_broker = {s for s, kw in sites.items() if "broker_prices" in kw}
    # The dashboard was the only surface with a live Kite session and it is gone. The local runner
    # marks from the price panel and reports every name it cannot price, which is the same property
    # reached a different way — so NO surface passing broker prices is now the correct state.
    assert not with_broker, f"no surface holds a broker session any more: {sorted(with_broker)}"


@pytest.mark.xfail(
    strict=True,
    reason="GATE 2 OPEN, and still the one that matters: the surface that produces the orders you "
    "place — now scripts/local_run.py — applies neither the evidence skip, nor the governor, nor the "
    "anchor. Blocked on a policy decision, not on engineering: PLAN_SYSTEM gate 2 wants one "
    "proposal function everywhere, CLAUDE.md's iron rule says the buy list is flagged and never "
    "vetoed, and propose() vetoes.",
)
def test_the_surface_that_becomes_a_real_order_runs_the_risk_layer() -> None:
    runner_src = (ROOT / "scripts/local_run.py").read_text(encoding="utf-8")
    assert "propose(" in runner_src or "from qalpha.live.pipeline import" in runner_src, (
        "the local run reaches the screen without passing through live/pipeline.py"
    )


def test_the_auto_brief_never_proposes_more_than_the_cash_it_names() -> None:
    """The caller test for the defect above, on the shape of account that produced it.

    Eleven tests passed on ``advise_deploy`` while its scheduled caller fed it a doubled budget,
    because every one of them supplied the amount directly. This one calls it the way the dashboard
    does — ``amount = portfolio.cash``, all cash, nothing held, which is exactly the parked-SIP
    account — and asserts the orders cannot exceed the money that exists.
    """
    import numpy as np
    import pandas as pd

    from qalpha.backtest.portfolio import Portfolio
    from qalpha.config import Config
    from qalpha.data.prices import PriceData
    from qalpha.live.deploy import advise_deploy_into_weakness

    cfg = Config()
    cash = Decimal("300000")
    portfolio = Portfolio(cfg.cost, cfg.tax, cash=cash)

    dates = pd.bdate_range("2024-09-01", "2026-09-01")
    tickers = [f"N{i}.NS" for i in range(6)]
    rng = np.random.default_rng(7)
    adj = pd.DataFrame(
        {t: 1000 * np.exp(np.cumsum(rng.normal(-0.0003, 0.01, len(dates)))) for t in tickers},
        index=dates,
    )
    prices = PriceData(adj, adj.copy(), adj.copy() * 0 + 1_000_000)

    advice = advise_deploy_into_weakness(
        portfolio,
        cash,  # the dashboard passes portfolio.cash as the amount
        tickers,
        {t: ("TECH" if i % 2 else "FIN") for i, t in enumerate(tickers)},
        prices,
        pd.Series(np.linspace(100, 105, len(dates)), index=dates),
        dates[-1].date(),
        max_names=cfg.deploy_policy.max_names_default,
        spend_idle_cash=False,
    )
    spent = advice.deploy.total_deployed
    assert spent <= cash, (
        f"the basket costs ₹{spent:,.0f} against ₹{cash:,.0f} in the account "
        f"({float(spent / cash):.2f}× the money that exists)"
    )
    # A wrinkle worth recording rather than asserting away: with a hard budget equal to the account's
    # cash, ``held_back`` reports that same ₹3,00,000 — it means "portfolio.cash was not added ON TOP
    # of amount", not "this money went unspent". The orders above are funded by ``amount``. The field
    # is not shown in the PM brief; if it ever is, it needs relabelling before it reaches a screen.
    assert advice.deploy.held_back == cash


def test_every_surface_reads_weakness_from_the_same_market() -> None:
    """CLOSED 2026-09-09.

    ``market_weakness`` classifies the index's drawdown from its rolling 1-year high, and that
    drawdown decides the deploy tranche. The CLI fed it an equal-weighted mean of 95 watchlist names
    while the dashboard passed the real Nifty TRI — a different market, so the same account on the
    same day could sit in "normal" on one surface and "elevated" on the other.

    A labelled fallback is allowed and is not the defect: a missing benchmark panel must not take
    the CLI down. What must be true is that the benchmark is the PRIMARY source, and that any
    fallback announces that it changes the answer.
    """
    cli = (ROOT / "scripts/advisor.py").read_text(encoding="utf-8")
    assert "_load_benchmark_series()" in cli, "the CLI must take the real index first"
    if "adj_close.mean(axis=1)" in cli:
        fallback = cli[cli.index("_load_benchmark_series()") : cli.index("adj_close.mean(axis=1)")]
        assert "except" in fallback, (
            "the mean may only ever be a fallback, never the primary source"
        )
        assert "DIFFERENT market" in cli, "a silent fallback to another market is the defect itself"
