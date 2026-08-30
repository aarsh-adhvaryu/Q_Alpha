"""Turn a deterministic basket into the AI's keep/drop calls — the twin's one AI treatment (PR-8).

**Why this module exists.** ``runner.step`` takes ``Market.ai_verdicts`` already decided: verdicts are
*injected, never fetched*, so a step stays pure and replayable and an AI outage degrades ``TWIN_FULL``
to exactly ``TWIN_NO_AI`` instead of to nothing. Something outside the runner therefore has to do the
asking, and before this module the twin cron simply never did — ``Market`` was constructed without
``ai_verdicts``, so ``policy.use_ai and market.ai_verdicts`` was False on every book, every day, and
the four twins were byte-identical by construction. The AI ablation was wired and starved.

**The guards are structural, not prompted** (unchanged from PR-8): the model is shown a fixed
shortlist the deterministic screen already chose and already sized; ``parse_verdicts`` discards any
ticker outside that universe, so it cannot add a name; nothing here returns a quantity, so it cannot
size; and every failure path — no ``ai`` extra, no API key, a refusal, an unparseable line — returns
an empty map, which downstream means *keep everything*. The screen is the floor. The model can only
subtract from it, or be absent.

Fake money only. Nothing in this path can reach the real account.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qalpha.data.prices import PriceData
    from qalpha.live.ai_brief import NameVerdict


def basket_verdicts(
    basket: Mapping[str, int],
    sectors: Mapping[str, str],
    prices: PriceData,
    as_of: date,
) -> tuple[dict[str, NameVerdict], str, dict[str, int]]:
    """Ask the AI for a keep/drop call on ``basket``. Returns ``(verdicts, raw_text, token_usage)``.

    The candidates carry the **deterministic facts** — continuity-corrected cheapness, the §4.7
    breakdown verdict, the 6-month return — so the model reasons about company-specific news it can
    look up rather than re-deriving numbers the engine already owns. The ``ai`` extra is optional, so
    every import here is lazy: without it, or without a key, this returns no verdicts and the
    deterministic basket stands untouched.
    """
    if not basket:
        return {}, "", {}
    from qalpha.live.ai_brief import Candidate, generate_verdicts
    from qalpha.live.deploy import cheapness_scores
    from qalpha.live.position_health import position_health
    from qalpha.live.price_integrity import (
        excluded_from_tilt,
        rebase_starts,
        unexplained_gaps,
    )

    tickers = sorted(basket)
    gaps = unexplained_gaps(prices.adj_close, tickers, as_of)
    rebase, exclude = rebase_starts(gaps), excluded_from_tilt(gaps)
    cheap = cheapness_scores(prices, tickers, as_of, rebase_from=rebase, no_tilt=exclude)
    health = {
        h.ticker: h
        for h in position_health(
            prices.adj_close, tickers, as_of, rebase_from=rebase, exclude=exclude
        ).holdings
    }
    candidates = [
        Candidate(
            ticker=t,
            sector=str(sectors.get(t, "?")),
            cheapness=cheap.get(t, 0.0),
            health=health[t].level if t in health else "unknown",
            trailing_return=health[t].trailing_return if t in health else 0.0,
        )
        for t in tickers
    ]
    return generate_verdicts(candidates)


def verdict_calls(verdicts: Mapping[str, NameVerdict]) -> dict[str, str]:
    """Flatten to the ``ticker -> "keep"|"drop"`` map ``Market.ai_verdicts`` expects.

    A ticker absent from this map is kept by ``runner._deploy``, which is the fail-soft contract:
    silence from the model is never an instruction.
    """
    return {t: ("keep" if v.keep else "drop") for t, v in verdicts.items()}
