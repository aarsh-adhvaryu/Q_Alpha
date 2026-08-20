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


# ---- the screen decides rather than defers (2026-08-19) -----------------------------------------
#
# User's verdict on the flag-don't-veto build: "the task was simple, i provide the amount, it
# suggests the shares i buy it… if i wanted to do it at my own risk, why would i have created the
# system". He is right — a basket the system will not stand behind, shipped with a warning, is work
# handed back. The §4.7 breakdown test is now a filter, not a label.


def _wide_prices() -> tuple[PriceData, dict[str, str]]:
    """8 names: 2 in idiosyncratic decline, 6 merely pulled back or flat.

    The 3-name fixture above deliberately trips the don't-starve guard (2 survivors < 3), so the
    filter itself needs a universe wide enough to still build a basket after removing the breakers —
    which is also the realistic case: on the live watchlist ~26% of names are breaking.
    """
    paths = {
        "BREAK1.NS": _series(100, 55),  # deep, idiosyncratic → must be filtered
        "BREAK2.NS": _series(100, 58),  # deep, idiosyncratic → must be filtered
        "MILD1.NS": _series(100, 88),
        "MILD2.NS": _series(100, 90),
        "MILD3.NS": _series(100, 92),
        "FLAT1.NS": _series(100, 99),
        "FLAT2.NS": _series(100, 100),
        "FLAT3.NS": _series(100, 101),
    }
    rows = []
    for t, vals in paths.items():
        for d, v in zip(_DATES, vals, strict=True):
            rows.append({"date": d, "ticker": t, "close": v, "adj_close": v, "volume": 1000})
    sectors = {t: f"SEC{i}" for i, t in enumerate(paths)}  # one sector each → cap never binds
    return PriceData.from_long(pd.DataFrame(rows)), sectors


def _wide_advice(**kwargs):  # type: ignore[no-untyped-def]
    prices, sectors = _wide_prices()
    cfg = Config()
    return advise_deploy_into_weakness(
        Portfolio(cfg.cost, cfg.tax, cash=Decimal("0")),
        Decimal("100000"),
        list(sectors),
        sectors,
        prices,
        prices.adj_close.mean(axis=1),
        _DATES[-1].date(),
        max_sector_weight=1.0,
        **kwargs,
    )


def test_a_breaking_name_is_removed_before_ranking_not_merely_flagged() -> None:
    """DEEP falls hardest and is idiosyncratic, so it is exactly what the screen must NOT pick."""
    advice = _wide_advice()
    assert set(advice.filtered_out) == {"BREAK1.NS", "BREAK2.NS"}
    assert "BREAK1.NS" not in advice.target.index
    assert "BREAK2.NS" not in advice.target.index
    assert not any(h.level == "breaking" for h in advice.candidate_health)


def test_the_delivered_basket_carries_no_breaking_name() -> None:
    """The property the user actually asked for: what comes out is buyable without adjudication."""
    advice = _wide_advice()
    bought = {o.ticker for o in advice.deploy.buy_orders}
    assert bought  # a basket was still delivered
    assert not (bought & {"BREAK1.NS", "BREAK2.NS"})
    assert not any(h.level == "breaking" for h in advice.candidate_health)


def test_the_filter_fails_open_rather_than_returning_nothing() -> None:
    """If filtering would starve the basket, keep the full universe — some deploy beats none.

    Guards the failure mode that would make this change worse than the problem it fixes: a market
    where most names are breaking must not produce an empty recommendation.
    """
    prices = _prices()
    as_of = _DATES[-1].date()
    sector_of = {"ATHIGH.NS": "IT", "MILD.NS": "FIN", "DEEP.NS": "AUTO"}
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))

    # Only 3 names exist, so demanding 3 survivors after removing DEEP is unsatisfiable.
    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sector_of),
        sector_of,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_names=3,
        max_sector_weight=1.0,
    )
    assert advice.filtered_out == ()  # filter stood down
    assert len(advice.deploy.buy_orders) > 0  # …and a basket was still delivered


def test_the_old_behaviour_is_still_reachable_for_comparison() -> None:
    """`exclude_breaking=False` restores the label-only screen, so the change is measurable."""
    advice = _wide_advice(exclude_breaking=False)
    assert advice.filtered_out == ()
    assert "BREAK1.NS" in advice.target.index  # the label-only screen still ranks it top


def test_the_removal_is_reported_not_silent() -> None:
    """The screen decides, but it says what it decided — a silent filter is its own trust problem."""
    note = _wide_advice().filtered_note()
    assert "removed 2 names" in note
    assert "BREAK1" in note and "BREAK2" in note
    assert note in _wide_advice().render()


# ---- held names keep their slots (2026-08-20) ----------------------------------------------------
#
# User: "always investing new works but not always, if a company is good, and getting a good deal
# than why not". Correct — and without this the monthly deploy sprawls, because advise_deploy funds
# whatever is furthest below target and a name you hold zero of is always furthest below.


def _hold(portfolio: Portfolio, ticker: str, qty: int, price: float, on) -> None:  # type: ignore[no-untyped-def]
    from qalpha.accounting.tax_lots import TaxLot

    portfolio.ledger.add_lot(
        TaxLot(
            ticker=ticker,
            acquisition_date=on,
            quantity_original=Decimal(qty),
            buy_price=Decimal(str(price)),
        )
    )


def test_a_still_healthy_holding_keeps_its_slot_against_a_cheaper_newcomer() -> None:
    """The rule in one test: add to what is still good rather than buying a fresher name."""
    prices, sectors = _wide_prices()
    as_of = _DATES[-1].date()
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    # Hold the *least* discounted healthy name — on cheapness alone it would rank last.
    _hold(pf, "FLAT3.NS", 10, 101.0, _DATES[0].date())

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sectors),
        sectors,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_names=2,
        max_sector_weight=1.0,
    )
    assert "FLAT3.NS" in advice.target.index, (
        "a healthy holding was displaced by a cheaper newcomer"
    )
    assert len(advice.target) == 2  # …and the roster stays capped


def test_a_holding_that_breaks_down_loses_its_slot() -> None:
    """Stickiness is not loyalty: the slot is held only while the name still passes the screen."""
    prices, sectors = _wide_prices()
    as_of = _DATES[-1].date()
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    _hold(pf, "BREAK1.NS", 10, 55.0, _DATES[0].date())  # in idiosyncratic decline

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sectors),
        sectors,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_names=2,
        max_sector_weight=1.0,
    )
    assert "BREAK1.NS" in advice.filtered_out
    assert "BREAK1.NS" not in advice.target.index  # replaced, not topped up
    assert len(advice.target) == 2


def test_spare_slots_still_go_to_new_names() -> None:
    """Holding one name must not stop the screen diversifying into the remaining slots."""
    prices, sectors = _wide_prices()
    as_of = _DATES[-1].date()
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    _hold(pf, "FLAT3.NS", 10, 101.0, _DATES[0].date())

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sectors),
        sectors,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_names=4,
        max_sector_weight=1.0,
    )
    assert len(advice.target) == 4
    assert len(set(advice.target.index) - {"FLAT3.NS"}) == 3  # 3 newcomers filled the rest


def test_repeated_deploys_do_not_grow_the_portfolio_without_bound() -> None:
    """The sprawl property, asserted directly.

    Simulated on real price history, five monthly deploys previously produced 19–20 distinct names
    (~40 in a year), each a stranded lot that never got topped up again. The roster must instead
    stay at the size the user asked for.
    """
    prices, sectors = _wide_prices()
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    index = prices.adj_close.mean(axis=1)
    held: set[str] = set()

    for offset in (60, 40, 20, 0):  # four deploys spread across the window
        as_of = _DATES[len(_DATES) - 1 - offset].date()
        advice = advise_deploy_into_weakness(
            pf,
            Decimal("50000"),
            list(sectors),
            sectors,
            prices,
            index,
            as_of,
            max_names=3,
            max_sector_weight=1.0,
        )
        for o in advice.deploy.buy_orders:
            _hold(pf, o.ticker, int(o.quantity), float(o.price), as_of)
            held.add(o.ticker)

    # Without stickiness this drifts well past the cap as each deploy re-ranks. A little churn is
    # legitimate (a name breaking down frees its slot), so allow one replacement, not unbounded growth.
    assert len(held) <= 4, f"portfolio sprawled to {len(held)} names on a 3-name roster: {held}"


def test_every_healthy_holding_stays_eligible_for_new_money() -> None:
    """User's idea: balance the book with the inflow rather than the sell button (2026-08-20).

    ``max_names`` caps how many *new* names may be opened, not how many existing positions may be
    topped up. Without that, a holding which slips out of the fresh ranking is stranded forever at
    whatever weight it happened to reach — measured on 13 years of history, that tail was three
    positions under 2%, the smallest at 0.7%.
    """
    prices, sectors = _wide_prices()
    as_of = _DATES[-1].date()
    cfg = Config()
    pf = Portfolio(cfg.cost, cfg.tax, cash=Decimal("0"))
    # Hold four healthy names while the roster only has room to open one.
    for t in ("FLAT1.NS", "FLAT2.NS", "FLAT3.NS", "MILD3.NS"):
        _hold(pf, t, 10, 100.0, _DATES[0].date())

    advice = advise_deploy_into_weakness(
        pf,
        Decimal("100000"),
        list(sectors),
        sectors,
        prices,
        prices.adj_close.mean(axis=1),
        as_of,
        max_names=1,
        max_sector_weight=1.0,
    )
    for t in ("FLAT1.NS", "FLAT2.NS", "FLAT3.NS", "MILD3.NS"):
        assert t in advice.target.index, f"{t} was stranded — healthy holdings must stay fundable"
    # …and a name that broke down is still evicted, cap or no cap.
    assert not ({"BREAK1.NS", "BREAK2.NS"} & set(advice.target.index))
