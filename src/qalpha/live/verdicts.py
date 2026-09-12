"""Turn a deterministic basket into the AI's keep/drop calls — the twin's one AI treatment (PR-8).

**Why this module exists.** ``runner.step`` takes ``Market.ai_verdicts`` already decided: verdicts are
*injected, never fetched*, so a step stays pure and replayable and an AI outage degrades ``SYSTEM``
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

### AI-V2 — what changed, and why it is a different treatment

``basket_verdicts`` (PR-8c) asks a web-searching model *should this be kept or dropped*. The
judgement is the model's, and its "citation" is a hostname: a URL on ``nseindia.com`` passed whether
or not the page said anything about the claim, which is how the first real veto came to cite a stock
**quote page**. `PR-8c` patched that by demoting anything not on a primary host — a rule about where
a link points, not about what it says.

:func:`event_verdicts` replaces the question. It asks nothing. The filings and headlines were already
read by :mod:`qalpha.live.extraction` and :mod:`qalpha.live.news`, whose every claim carries a quote
**checked against archived bytes**, and this is a rule over those rows: drop a name when a verified,
current-version, high-materiality event of a veto-shaped type sits in the window. No model call, no
key, no search, and a drop a reader can re-open a year from now.

**Only a filing can drop.** A headline that matches produces a *lead* — recorded, demoted, not acted
on — because a snippet read by an 8B model is secondary evidence, which is exactly the distinction
PR-8c drew and the reason it exists. Widening that is `AI-V2.1` and needs its own registration.

Registered in ``reports/PREREGISTRATION_AI_V2.md``. It changes ``SYSTEM`` only; ``CORE_V1`` does
not consult verdicts and its clock is untouched.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qalpha.data.prices import PriceData
    from qalpha.live.ai_brief import NameVerdict

#: The AI treatment identifier, recorded on every verdict row. **Bump it whenever the rule, the
#: event types, the window or the evidence version changes** — a label spanning two rules makes every
#: row under it unusable, which is what cost run 2 its first four days.
#:
#: PR-8b (2026-08-30): a DROP required a ``source=`` URL to be present.
#: PR-8c (2026-09-05): a DROP acted only on a PRIMARY host; anything else was demoted to a lead.
#: AI-V2 (2026-09-11): no model is asked. A DROP is deterministic policy over verified events whose
#:   quotes were checked against archived bytes — see the module docstring.
AI_PROMPT_VERSION = "AI-V2"

#: Event types that can remove a name from a fake-money basket. **Deliberately short.**
#:
#: Each is a fact about the company's standing rather than about its business doing badly: a
#: regulator or court acting, insolvency, an auditor leaving, a downgrade, promoters pledging more.
#: Results, guidance and operational news are not here — the screen already prices those, and this
#: layer exists for the things a price cannot show.
VETO_TYPES: tuple[str, ...] = (
    "regulatory_action",
    "insolvency",
    "auditor_change",
    "credit_rating",
    "promoter_pledge",
)

#: How far back an event still speaks for today's basket.
VETO_WINDOW_DAYS = 30


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


def _veto_rows(
    path: Path, *, kind: str, version_field: str, version: str, since: str
) -> list[dict[str, object]]:
    """Verified, current-version, veto-shaped, recent rows — at their **current revision**.

    The revision rule is not decoration: nine of the news log's first 99 lines were re-reads that
    superseded a higher materiality, and a reader counting lines saw three times the flags the
    record holds. :func:`qalpha.live.flags._rows` is the one reader that gets this right.
    """
    from qalpha.live.flags import _rows

    return [
        row
        for row in _rows(path)
        if row.get("kind") == kind
        and row.get("verified")
        and row.get(version_field) == version
        and str(row.get("materiality", "")).lower() == "high"
        and str(row.get("event_type", "")) in VETO_TYPES
        and str(row.get("as_of", "")) >= since
    ]


def event_verdicts(
    basket: Mapping[str, int] | Sequence[str],
    *,
    as_of: date,
    lookback_days: int = VETO_WINDOW_DAYS,
    events_path: Path | None = None,
    news_path: Path | None = None,
) -> dict[str, NameVerdict]:
    """Keep/drop from the evidence already on file. **No model is asked; nothing is fetched.**

    A name is dropped when a verified, current-version, high-materiality **filing** event of a
    veto-shaped type falls inside the window. A matching **headline** produces a demoted lead
    instead: it is recorded, it is visible, and it does not act — the same rule PR-8c applied to a
    secondary source, for the same reason.

    Absence is keep, as it has always been: a name this returns nothing for survives untouched, so
    every failure path degrades ``SYSTEM`` to exactly ``TWIN_NO_AI`` rather than to an empty book.
    """
    from qalpha.live.ai_brief import NameVerdict, source_tier
    from qalpha.live.extraction import EVENT_LOG, EXTRACTION_VERSION
    from qalpha.live.news import NEWS_EVENTS, NEWS_VERSION

    wanted = {t.removesuffix(".NS"): t for t in basket}
    if not wanted:
        return {}
    since = (as_of - timedelta(days=lookback_days)).isoformat()
    out: dict[str, NameVerdict] = {}

    for row in _veto_rows(
        events_path or EVENT_LOG,
        kind="event",
        version_field="extraction_version",
        version=EXTRACTION_VERSION,
        since=since,
    ):
        ticker = wanted.get(str(row.get("ticker", "")).removesuffix(".NS"))
        if ticker is None:
            continue
        url = str(row.get("doc_url", ""))
        out[ticker] = NameVerdict(
            ticker=ticker,
            keep=False,
            confidence="rule",
            reason=(
                f"{row.get('event_type')} (high) in a filing disseminated "
                f"{str(row.get('disseminated_at', ''))[:10]}"
            )[:120],
            source=url[:500],
            source_tier=source_tier(url),
            demoted=False,
        )

    for row in _veto_rows(
        news_path or NEWS_EVENTS,
        kind="news",
        version_field="news_version",
        version=NEWS_VERSION,
        since=since,
    ):
        bare = str(row.get("ticker", "")).removesuffix(".NS")
        ticker = wanted.get(bare)
        # A FILING ALREADY SPOKE. Its verdict stands; a headline cannot strengthen or weaken it.
        if ticker is None or ticker in out or str(row.get("stance", "")) != "negative":
            continue
        link = str(row.get("link", ""))
        out[ticker] = NameVerdict(
            ticker=ticker,
            keep=True,  # demoted: a snippet is secondary evidence and does not act
            confidence="rule",
            reason=f"lead only — {row.get('event_type')} reported by {row.get('source') or 'a feed'}"[
                :120
            ],
            source=link[:500],
            source_tier=source_tier(link),
            demoted=True,
        )
    return out


def verdict_calls(verdicts: Mapping[str, NameVerdict]) -> dict[str, str]:
    """Flatten to the ``ticker -> "keep"|"drop"`` map ``Market.ai_verdicts`` expects.

    A ticker absent from this map is kept by ``runner._deploy``, which is the fail-soft contract:
    silence from the model is never an instruction.
    """
    return {t: ("keep" if v.keep else "drop") for t, v in verdicts.items()}
