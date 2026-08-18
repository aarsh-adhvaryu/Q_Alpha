"""Tests for the deploy-in-weakness engine (qalpha.live.deploy)."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction
from qalpha.accounting.costs import Side
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.live.deploy import (
    advise_deploy_into_weakness,
    cheapness_scores,
    deploy_target,
    market_weakness,
)
from qalpha.live.price_integrity import (
    excluded_from_tilt,
    rebase_starts,
    unexplained_gaps,
)

_DATES = pd.bdate_range("2023-01-02", periods=300)


def _series(peak: float, last: float) -> list[float]:
    """A price path that rises to ``peak`` mid-window then ends at ``last`` (controls the pullback)."""
    up = list(pd.Series(range(150)).apply(lambda i: 50 + (peak - 50) * i / 149))
    down = list(pd.Series(range(150)).apply(lambda i: peak + (last - peak) * i / 149))
    return up + down


def _prices() -> PriceData:
    # ATHIGH ends at its high; MILD ends 20% below; DEEP ends 40% below.
    paths = {
        "ATHIGH.NS": _series(100, 100),
        "MILD.NS": _series(100, 80),
        "DEEP.NS": _series(100, 60),
    }
    rows = []
    for t, vals in paths.items():
        for d, v in zip(_DATES, vals, strict=True):
            rows.append({"date": d, "ticker": t, "close": v, "adj_close": v, "volume": 1000})
    return PriceData.from_long(pd.DataFrame(rows))


def _index_ending_at(last: float) -> pd.Series:
    """A flat-100 index that ends at ``last`` (so the drawdown from the 1y high is 1 - last/100)."""
    idx = pd.bdate_range("2023-01-02", periods=252)
    return pd.Series([100.0] * 251 + [last], index=idx)


def test_market_weakness_levels() -> None:
    as_of = pd.bdate_range("2023-01-02", periods=252)[-1].date()
    assert market_weakness(_index_ending_at(97.0), as_of).level == "normal"  # -3%
    assert market_weakness(_index_ending_at(92.0), as_of).level == "elevated"  # -8%
    assert market_weakness(_index_ending_at(85.0), as_of).level == "deep"  # -15%


def test_cheapness_scores_track_pullback() -> None:
    prices = _prices()
    as_of = _DATES[-1].date()
    scores = cheapness_scores(prices, ["ATHIGH.NS", "MILD.NS", "DEEP.NS"], as_of)
    assert scores["ATHIGH.NS"] < 0.01
    assert 0.18 < scores["MILD.NS"] < 0.22  # ~20% below high
    assert 0.38 < scores["DEEP.NS"] < 0.42  # ~40% below high


def test_deploy_target_tilts_to_cheaper_and_sums_to_one() -> None:
    """A deeper fall earns a larger position — but that is only half the property (PR-3 / T1.4).

    Asserting the drawdown ordering *alone* is what let the advisor recommend falling knives with a
    green test suite: "further down ⇒ buy more" is exactly the behaviour that needed a second
    opinion, not a guarantee. The ordering still holds — it is the deliberate tilt — but the
    companion assertion below pins the thing that was missing: the delivered basket must also carry
    the system's own breakdown verdict on those names, so a deeper fall that is *idiosyncratic*
    arrives flagged rather than silently sized up.
    """
    cheap = {"ATHIGH.NS": 0.0, "MILD.NS": 0.2, "DEEP.NS": 0.4}
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    target = deploy_target(list(cheap), sector_of, cheap, tilt=1.0, max_sector_weight=1.0)
    assert abs(float(target.sum()) - 1.0) < 1e-9
    assert target["DEEP.NS"] > target["MILD.NS"] > target["ATHIGH.NS"]


def test_the_deeper_fall_is_sized_up_and_flagged_at_the_same_time() -> None:
    """The companion to the ordering above: sized larger AND carrying its own health verdict."""
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sector_of),
        sector_of,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_sector_weight=1.0,
    )
    assert advice.target["DEEP.NS"] > advice.target["ATHIGH.NS"]  # the tilt, unchanged
    verdicts = {h.ticker: h for h in advice.candidate_health}
    assert set(verdicts) == set(advice.target.index)  # every recommended name carries a verdict
    # DEEP fell hardest and lags the cross-section → the detector says so, beside the bigger position.
    assert verdicts["DEEP.NS"].level == "breaking"
    assert verdicts["ATHIGH.NS"].level == "healthy"
    assert verdicts["DEEP.NS"].trailing_return < verdicts["ATHIGH.NS"].trailing_return


def test_deploy_target_max_names_concentrates() -> None:
    cheap = {f"S{i}.NS": i / 100 for i in range(20)}  # 20 names, varying cheapness
    sectors = {t: f"SEC{i % 5}" for i, t in enumerate(cheap)}
    target = deploy_target(list(cheap), sectors, cheap, tilt=1.0, max_names=8)
    assert len(target) == 8  # concentrated to the top 8
    assert abs(float(target.sum()) - 1.0) < 1e-9  # still a full allocation


def test_deploy_target_caps_sector_weight() -> None:
    # 4 FIN + one each of IT/AUTO/FMCG → 4 sectors, so a 30% cap is feasible (4·0.30 ≥ 1).
    fin = ["A.NS", "B.NS", "C.NS", "D.NS"]
    names = [*fin, "E.NS", "F.NS", "G.NS"]
    cheap = dict.fromkeys(names, 0.0)
    sectors = {**dict.fromkeys(fin, "FIN"), "E.NS": "IT", "F.NS": "AUTO", "G.NS": "FMCG"}
    target = deploy_target(names, sectors, cheap, tilt=0.0, max_sector_weight=0.30)
    assert float(target[fin].sum()) <= 0.30 + 1e-6  # FIN capped despite holding 4 of 7 names
    assert abs(float(target.sum()) - 1.0) < 1e-9


def _flat_prices(last: dict[str, float]) -> PriceData:
    """A PriceData where each ticker sits flat at its given price for the whole window."""
    rows = []
    for t, p in last.items():
        for d in _DATES:
            rows.append({"date": d, "ticker": t, "close": p, "adj_close": p, "volume": 1000})
    return PriceData.from_long(pd.DataFrame(rows))


def test_anti_dominance_drops_names_too_pricey_for_a_small_deploy() -> None:
    # 4 cheap names + 1 very pricey one; a small deploy must not blow on the pricey share.
    prices = _flat_prices({"A.NS": 100, "B.NS": 100, "C.NS": 100, "D.NS": 100, "PRICEY.NS": 50_000})
    as_of = _DATES[-1].date()
    sector_of = {"A.NS": "IT", "B.NS": "FIN", "C.NS": "AUTO", "D.NS": "FMCG", "PRICEY.NS": "METAL"}
    index_close = prices.adj_close.mean(axis=1)
    pf = Portfolio(Config().cost, Config().tax, cash=Decimal("5000"))
    advice = advise_deploy_into_weakness(
        pf,
        Decimal("5000"),
        list(sector_of),
        sector_of,
        prices,
        index_close,
        as_of,
        max_name_fraction=0.20,  # cap = ₹1,000 → PRICEY (₹50k) excluded
    )
    bought = {o.ticker for o in advice.deploy.buy_orders}
    assert "PRICEY.NS" not in bought  # one share would swallow the deploy → dropped
    assert "PRICEY.NS" not in advice.target.index
    assert bought  # the cheap names still get deployed


def test_advise_deploy_into_weakness_is_buys_only() -> None:
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    index_close = prices.adj_close.mean(axis=1)
    pf = Portfolio(Config().cost, Config().tax, cash=Decimal("100000"))
    advice = advise_deploy_into_weakness(
        pf, Decimal("50000"), list(sector_of), sector_of, prices, index_close, as_of
    )
    assert all(o.side is Side.BUY for o in advice.deploy.buy_orders)
    assert advice.deploy.naive_tax >= advice.deploy.tax_saved  # buys realize ₹0 tax
    assert abs(float(advice.target.sum()) - 1.0) < 1e-9
    # The deepest-pulled-back name should head the cheapest list.
    assert advice.cheapest[0][0] == "DEEP.NS"
    # A watchlist-only book has nothing off-list → the render is unchanged (no ℹ️ line).
    assert advice.off_watchlist == ()
    assert advice.off_watchlist_note() == ""
    assert "ℹ️" not in advice.render()


def _book_with_off_watchlist_name(cash: Decimal) -> tuple[Portfolio, Decimal]:
    """A book holding 100 shares of IPO.NS @ ₹500 — a name the watchlist panel cannot price."""
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=cash + Decimal("50000"))
    pf.buy(_DATES[-1].date(), "IPO.NS", Decimal("100"), Decimal("500"))
    return pf, Decimal("50000")  # 100 x 500 = ₹50,000 of off-watchlist value


def test_off_watchlist_holding_is_shown_and_excluded_from_sizing() -> None:
    """An IPO/off-index holding must be visible in the advice but never steer or receive money."""
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    index_close = prices.adj_close.mean(axis=1)
    pf, off_value = _book_with_off_watchlist_name(Decimal("100000"))

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("50000"),
        list(sector_of),
        sector_of,
        prices,
        index_close,
        as_of,
        broker_prices={"IPO.NS": Decimal("500")},
    )

    # Shown: named, valued, and flagged as excluded.
    assert advice.off_watchlist == (("IPO.NS", off_value),)
    note = advice.off_watchlist_note()
    assert "IPO.NS" in note and "50,000" in note and "excluded" in note
    assert note in advice.render()
    # Excluded: never bought, and it does not inflate the per-name ₹ targets.
    assert all(o.ticker != "IPO.NS" for o in advice.deploy.buy_orders)
    assert advice.deploy.buy_orders  # the watchlist names still get deployed


def test_off_watchlist_exclusion_shrinks_targets_vs_counting_it() -> None:
    """Sizing is over the core book only — proof: the same book without the off-list lot buys the same."""
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    index_close = prices.adj_close.mean(axis=1)
    cfg = Config()

    with_off, _ = _book_with_off_watchlist_name(Decimal("100000"))
    # Same cash as the off-list book after its buy costs — so the ONLY difference is the lot itself.
    core_only = Portfolio(cfg.cost, cfg.tax, cash=with_off.cash)

    a = advise_deploy_into_weakness(
        with_off,
        Decimal("50000"),
        list(sector_of),
        sector_of,
        prices,
        index_close,
        as_of,
        broker_prices={"IPO.NS": Decimal("500")},
    )
    b = advise_deploy_into_weakness(
        core_only, Decimal("50000"), list(sector_of), sector_of, prices, index_close, as_of
    )
    # The off-list lot is withdrawn capital → identical buy plan to a book that never held it.
    assert {o.ticker: o.quantity for o in a.deploy.buy_orders} == {
        o.ticker: o.quantity for o in b.deploy.buy_orders
    }


def test_off_watchlist_unpriced_name_is_listed_not_dropped() -> None:
    """No price anywhere → listed as unpriced (fail-loud), never silently omitted."""
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    index_close = prices.adj_close.mean(axis=1)
    pf, _ = _book_with_off_watchlist_name(Decimal("100000"))

    advice = advise_deploy_into_weakness(  # no broker_prices → IPO.NS cannot be marked
        pf, Decimal("50000"), list(sector_of), sector_of, prices, index_close, as_of
    )
    assert advice.off_watchlist == (("IPO.NS", None),)
    assert "unpriced: IPO.NS" in advice.off_watchlist_note()


# ---- price continuity (PLAN_TRUST_REPAIR.md PR-2 — fixes T1.1) -----------------------------------


def _prices_with_a_demerger() -> PriceData:
    """ARTIFACT steps down 65% in one session; SLIDER grinds down 40% honestly over the window.

    This is the exact shape of the real defect: on ``adj_close``, VEDL's 2026-04-30 demerger and a
    genuine year-long decline are indistinguishable to a 1-year-high rule.
    """
    n = len(_DATES)
    step_at = 200
    paths = {
        "ATHIGH.NS": _series(100, 100),
        "SLIDER.NS": _series(100, 60),  # ends ~40% below its high — a real decline
        "ARTIFACT.NS": [100.0] * step_at + [35.0] * (n - step_at),  # a demerger, not a crash
    }
    rows = []
    for t, vals in paths.items():
        for d, v in zip(_DATES, vals, strict=True):
            rows.append({"date": d, "ticker": t, "close": v, "adj_close": v, "volume": 1000})
    return PriceData.from_long(pd.DataFrame(rows))


def test_an_artifact_no_longer_outranks_a_genuine_decline() -> None:
    """The defect in one assertion: unguarded, the demerger reads as the cheapest name on the list."""
    prices = _prices_with_a_demerger()
    as_of = _DATES[-1].date()
    names = ["ATHIGH.NS", "SLIDER.NS", "ARTIFACT.NS"]

    unguarded = cheapness_scores(prices, names, as_of)
    assert unguarded["ARTIFACT.NS"] > unguarded["SLIDER.NS"]  # 65% "off" beats a real 40% fall

    gaps = unexplained_gaps(prices.adj_close, names, as_of)
    guarded = cheapness_scores(
        prices, names, as_of, rebase_from=rebase_starts(gaps), no_tilt=excluded_from_tilt(gaps)
    )
    # Re-based to its post-gap window the artifact is flat — it never fell, it got smaller.
    assert guarded["ARTIFACT.NS"] < 0.01
    assert guarded["SLIDER.NS"] > guarded["ARTIFACT.NS"]
    # The genuine decline is untouched: the guard corrects a basis, it does not damp the tilt.
    assert guarded["SLIDER.NS"] == unguarded["SLIDER.NS"]
    assert guarded["ATHIGH.NS"] == unguarded["ATHIGH.NS"]


def test_the_advisor_stops_overweighting_the_artifact_and_says_why() -> None:
    """End-to-end: the artifact's target weight falls below the genuinely-cheap name's."""
    prices = _prices_with_a_demerger()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "SLIDER.NS": "FIN", "ARTIFACT.NS": "MTL"}
    index_close = prices.adj_close.mean(axis=1)
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))

    # max_sector_weight=1.0: with one name per sector the 0.30 cap is infeasible and flattens every
    # weight to 1/3, which would mask the very tilt under test.
    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sector_of),
        sector_of,
        prices,
        index_close,
        as_of,
        max_sector_weight=1.0,
    )
    assert advice.target["SLIDER.NS"] > advice.target["ARTIFACT.NS"]
    # And the advice explains itself rather than quietly changing its mind.
    assert [g.ticker for g in advice.price_gaps] == ["ARTIFACT.NS"]
    note = advice.price_gaps_note()
    assert "ARTIFACT.NS" in note and "demerger" in note
    assert note in advice.render()


def test_a_known_split_does_not_trigger_the_guard() -> None:
    """A real, understood action must not be reported to the user as a data defect."""
    prices = _prices_with_a_demerger()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "SLIDER.NS": "FIN", "ARTIFACT.NS": "MTL"}
    index_close = prices.adj_close.mean(axis=1)
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sector_of),
        sector_of,
        prices,
        index_close,
        as_of,
        known_actions={
            "ARTIFACT.NS": [
                CorporateAction.split("ARTIFACT.NS", _DATES[200].date(), Decimal("2.857"))
            ]
        },
    )
    assert advice.price_gaps == ()
    assert advice.price_gaps_note() == ""


def test_a_clean_watchlist_is_completely_unchanged_by_the_guard() -> None:
    """No gaps anywhere → byte-identical advice. The guard must cost nothing on healthy data."""
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    index_close = prices.adj_close.mean(axis=1)
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sector_of),
        sector_of,
        prices,
        index_close,
        as_of,
        max_sector_weight=1.0,
    )
    assert advice.price_gaps == ()
    assert advice.price_gaps_note() == ""
    # The delivered target is exactly what the pre-PR-2 path produced: same cheapness, same weights.
    unguarded = deploy_target(
        list(sector_of),
        sector_of,
        cheapness_scores(prices, list(sector_of), as_of),
        tilt=1.0,
        max_sector_weight=1.0,
    )
    assert advice.target.to_dict() == unguarded.to_dict()


# ---- candidate health + the sector cap (PLAN_TRUST_REPAIR.md PR-3 — fixes T1.2, T1.4) ------------


def test_the_advisor_reports_the_breakdown_verdict_it_used_to_contradict() -> None:
    """T1.2 in one test: the detector and the advisor now speak on the same page, same day."""
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sector_of),
        sector_of,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_sector_weight=1.0,
    )
    note = advice.candidate_health_note()
    assert "DEEP.NS" in note
    assert "🔴" in note
    assert "review-for-exit" in note
    assert note in advice.render()  # it reaches the rendered advice, not just the object


def test_the_health_verdict_annotates_but_never_vetoes() -> None:
    """User's locked decision: flag, don't veto. A 🔴 name stays in the basket, with its verdict."""
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sector_of),
        sector_of,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_sector_weight=1.0,
    )
    breaking = {h.ticker for h in advice.candidate_health if h.level == "breaking"}
    assert breaking  # something is flagged
    assert breaking <= set(advice.target.index)  # ...and it is still being recommended
    assert breaking <= {o.ticker for o in advice.deploy.buy_orders}  # ...and still bought


def test_the_note_reports_the_universe_base_rate_for_scale() -> None:
    """A mostly-red table is uninterpretable without knowing how red the universe is."""
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sector_of),
        sector_of,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_sector_weight=1.0,
    )
    assert advice.universe_breaking_rate is not None
    assert 0.0 <= advice.universe_breaking_rate <= 1.0
    assert "of the whole watchlist" in advice.candidate_health_note()


def test_the_sector_cap_binds_on_the_basket_actually_delivered() -> None:
    """T1.4: the cap was applied *before* truncation, so the delivered top-N could breach it.

    Six IT names dominate the cheapness ranking; concentrating into the top 4 used to hand over an
    all-IT basket while the code advertised a 30% sector cap.
    """
    names = [f"IT{i}.NS" for i in range(6)] + [f"FIN{i}.NS" for i in range(3)]
    sector_of = {t: ("IT" if t.startswith("IT") else "FIN") for t in names}
    # The IT names are the cheapest, so they take the whole top of the ranking.
    cheap = {t: (0.5 - 0.01 * i if t.startswith("IT") else 0.05) for i, t in enumerate(names)}

    target = deploy_target(names, sector_of, cheap, tilt=1.0, max_sector_weight=0.30, max_names=4)
    by_sector: dict[str, float] = {}
    for t, w in target.items():
        by_sector[sector_of[str(t)]] = by_sector.get(sector_of[str(t)], 0.0) + float(w)
    assert len(target) == 4
    assert abs(sum(by_sector.values()) - 1.0) < 1e-9
    # Two sectors survive the cut, so the cap is feasible at 30/70 → IT is held to its share.
    assert by_sector["IT"] <= 0.75  # was 1.00 (a 100% IT basket) before the re-cap
    assert by_sector["FIN"] > 0.0  # the other sector is not squeezed out entirely


def test_an_infeasible_cap_after_truncation_degrades_gracefully() -> None:
    """Truncating to names from a single sector makes the cap unsatisfiable — must not raise."""
    names = [f"IT{i}.NS" for i in range(5)]
    sector_of = dict.fromkeys(names, "IT")
    cheap = {t: 0.5 - 0.01 * i for i, t in enumerate(names)}
    target = deploy_target(names, sector_of, cheap, tilt=1.0, max_sector_weight=0.30, max_names=3)
    assert len(target) == 3
    assert abs(float(target.sum()) - 1.0) < 1e-9
