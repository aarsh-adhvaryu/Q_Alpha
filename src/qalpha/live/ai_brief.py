"""Daily AI market brief — an LLM *narrative* layer. **Context only, never a signal.**

**Honest framing (load-bearing, do not weaken):** this is a language-model *narrative* — market
context for a human to read, nothing more. It never computes a number, never feeds the deterministic
**backtest engine** (rule (a): no new alpha without validation, the validated headline stays frozen),
and never changes a real allocation. Any discretionary idea it surfaces — **including the "likely
reaction" read** (a qualitative near-term directional lean the model reasons out from the day's
drivers) — is explicitly the model's *non-validated opinion* for the existing **satellite sleeve**
(≤8% sleeve / ≤2.5% per name), never a forecast the system trusts or acts on. Every brief opens with a
"context only, not a signal" line so it can never be mistaken for the validated system's output.

This module is an **optional, quarantined** part of the live system: it is the `ai` extra (never a
core dep), lazy-imports the SDK, and is imported only by the live/auto-pilot layer — the engine,
factors, backtest, and CI never touch it, so the product stays deterministic where it must be. Its one
consumer beyond a human reader is the auto-pilot's Book B, which acts on the machine-readable ``SIGNAL``
line via a fixed rule — the AI *supplies* the read, deterministic code *acts* on it.

**Two routes, and they are not the same brief.** ``BRIEF-1`` is Anthropic Claude Haiku with the
server-side web-search tool. ``BRIEF-2-local`` is whatever model is on this machine, reading the
headlines :mod:`qalpha.live.news` fetched and archived **this run**, citing an item id for every
claim — so each sentence can be checked against a snippet on disk. The objection to a local brief
was never the model; it was that a model with no retrieval asked for today's news produces fluent
recalled training data with today's date on it. The archive is the retrieval, and with no headlines
the local brief refuses to be written at all.

**Model (BRIEF-1):** Anthropic **Claude Haiku 4.5** with the server-side **web-search tool**, so the
brief reflects *today's* news without any RSS plumbing (Haiku was chosen over Opus deliberately — the brief
is context-only, so provider capability has nowhere to propagate; a templated news digest doesn't need
Opus-tier reasoning). Haiku is an older-tier model, so it uses the basic ``web_search_20250305`` tool
variant; thinking/effort don't apply to Haiku and a news summary needs neither, so both are omitted.
The single networked call is isolated behind an injectable :data:`GenerateFn` seam; everything else
here (:func:`build_prompt`, :func:`format_for_telegram`, parsing) is pure and unit-tested with no
network and no SDK installed.

**Fail-soft everywhere:** a missing ``ANTHROPIC_API_KEY``, an API/quota/refusal error, or an empty
response → skip (return ``None``) with a log line. The cron must never go red because the brief
hiccuped.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

# The opening line every brief must carry — the whole point is that this can never read as a signal.
CONTEXT_PREAMBLE = "🧠 AI market brief — context only, not a signal."
_DEFAULT_MODEL = "claude-haiku-4-5"  # cheap, right-sized; override via ANTHROPIC_MODEL
_MAX_OUTPUT_TOKENS = 1500  # a hard ceiling on output cost (the brief is ~500 tokens)
_MAX_SEARCHES = 4  # web search: "why Nifty moved today" + 1–3 driver follow-ups
_TELEGRAM_LIMIT = 3900  # Telegram hard-caps a message at 4096 chars; leave headroom
# NB: we deliberately do NOT set allowed_domains — most Indian-market news sites
# (economictimes/moneycontrol/livemint/reuters) block Anthropic's search crawler, so restricting to
# them 400s. The prompt steers the model to Indian-market news; open search finds crawlable sources.

# A GenerateFn takes (model, prompt) → (text, usage). Injectable so tests supply a canned response
# with no network and no anthropic SDK installed; the default wires the web-searched Haiku call.
GenerateFn = Callable[[str, str], tuple[str, dict[str, int]]]


@dataclass(frozen=True)
class BriefResult:
    """A generated brief: the Telegram-ready text, the raw model markdown, and token usage."""

    text: str  # formatted for Telegram (preamble guaranteed, truncated to the limit)
    raw: str  # the model's raw markdown (archived to reports/ai_brief.md)
    model: str
    usage: dict[str, int] = field(default_factory=dict)


def build_prompt(watchlist_lines: list[str]) -> str:
    """Build the (short, stable) prompt: a fixed markdown template request + the watchlist as context.

    Pure and deterministic. The watchlist is passed as a compact ``TICKER:SECTOR`` line list (~96
    names ≈ ~700 tokens), not a table dump, to keep input spend down.
    """
    watchlist = ", ".join(watchlist_lines)
    return (
        "You are a market-context assistant for an Indian-equity (NSE) investor. Use the web-search "
        "tool to read today's Indian market news, then write a SHORT brief. No preamble, template "
        "only.\n\n"
        f"Open with exactly this line: {CONTEXT_PREAMBLE}\n\n"
        "Then, in ≤1900 characters of Telegram-friendly markdown:\n"
        "1. **Sentiment**: 🟢/🟠/🔴 + one sentence on the day.\n"
        "2. **Drivers**: the top 2–3, each with the *why* (e.g. 'crude +4% on X → OMC margins "
        "compress, aviation/paint input costs rise').\n"
        "3. **Watchlist names affected**: from the list below, name the few most touched by the "
        "drivers.\n"
        "4. **Likely reaction** (YOUR READ, not a validated signal — qualitative reasoning, not a "
        "backtest): near-term directional lean for the index over the next 1–2 sessions "
        "(up / flat / down) with a rough magnitude band (e.g. '+0.3–0.8%') and a confidence word "
        "(low / medium / high); then the 1–2 watchlist names most likely to move and which way. Base "
        "it on how the drivers above historically tend to play out — but keep it explicitly your "
        "judgement for a human's satellite sleeve, never a recommendation the system will act on.\n"
        "5. **Discretionary ideas** (0–2, optional): tag each 'satellite sleeve rules apply'. Omit if "
        "nothing stands out.\n"
        "6. **Risk note**: one line.\n\n"
        "This is CONTEXT for a human, NOT a trade signal; never imply certainty or a recommendation "
        "the system will act on.\n\n"
        "Finally, on the VERY LAST line, emit one machine-readable tag matching your likely-reaction "
        "call, exactly in this form (no other text on that line):\n"
        "SIGNAL: lean=<up|flat|down>; band=<low>..<high>; confidence=<low|medium|high>\n"
        "(e.g. 'SIGNAL: lean=up; band=0.4..0.9; confidence=medium'). This is read by a research study "
        "that measures, forward, whether acting on your read helps — it changes no real allocation.\n\n"
        f"Watchlist (TICKER:SECTOR): {watchlist}"
    )


# ---- the local brief, over archived headlines (BRIEF-2) -------------------------------------------
#
# Everything here is pure. The headlines come from `qalpha.live.news`, which archived the bytes they
# were parsed from; the index move is computed by CODE from the benchmark panel and written above the
# model's text rather than asked for; and a brief that cites an id it was not given is REJECTED
# rather than published, because an uncheckable citation is the failure this repo already had once.

BRIEF_VERSION = "BRIEF-2-local"

#: Phrases that mean the model has stopped describing and started predicting. The web-searched brief
#: has a "likely reaction" section, labelled as its own non-validated opinion; the local one does
#: not get one. A model reading twenty headlines has no basis for a forecast, and a forecast on this
#: page would sit two inches from a basket the user is about to buy.
_FORECAST_PHRASES = (
    "likely reaction",
    "i expect",
    "we expect",
    "should rise",
    "should fall",
    "will rise",
    "will fall",
    "target price",
    "buy ",
    "sell ",
)


@dataclass(frozen=True)
class Headline:
    """One archived snippet, as the brief is allowed to see it."""

    id: str
    title: str
    source: str = ""
    when: str = ""


@dataclass(frozen=True)
class IndexMove:
    """What the benchmark actually did, computed here and never asked of a model.

    **Both dates are named.** The panel can be missing a session — 2026-09-09 is absent from the
    2026 benchmark file — so "yesterday" would be wrong and "the last two closes" is what this is.
    """

    ticker: str
    prev_date: str
    prev_close: float
    last_date: str
    last_close: float

    @property
    def pct(self) -> float:
        return (self.last_close / self.prev_close - 1.0) * 100.0 if self.prev_close else 0.0

    def sentence(self) -> str:
        gap = ""
        if self.prev_date and self.last_date:
            from datetime import date as _date

            try:
                days = (
                    _date.fromisoformat(self.last_date) - _date.fromisoformat(self.prev_date)
                ).days
                gap = " (consecutive sessions)" if days <= 1 else f" ({days} days apart)"
            except ValueError:
                gap = ""
        return (
            f"{self.ticker} closed {self.last_close:,.2f} on {self.last_date}, "
            f"{self.pct:+.2f}% from {self.prev_close:,.2f} on {self.prev_date}{gap}. "
            "It is an ETF's own close, a proxy for the index and not the index itself."
        )


def index_move(path: str, *, ticker: str = "NIFTYBEES") -> IndexMove | None:
    """The last two closes in the benchmark panel. ``None`` below two rows — **never 0.0%**.

    A benchmark window with no data once reported ``0.0%``, and flat and unknown are not the same
    market. That row is in CLAUDE.md's table.
    """
    try:
        import pandas as pd

        frame = pd.read_parquet(path)
        if "date" in frame.columns:
            frame = frame.sort_values("date")
            dates = [str(d)[:10] for d in frame["date"].tolist()[-2:]]
        else:
            frame = frame.sort_index()
            dates = [str(d)[:10] for d in frame.index.tolist()[-2:]]
        column = "adj_close" if "adj_close" in frame.columns else "close"
        closes = [float(v) for v in frame[column].tolist()[-2:]]
    except Exception:
        return None
    if len(closes) < 2 or len(dates) < 2 or not closes[0]:
        return None
    return IndexMove(
        ticker=ticker,
        prev_date=dates[0],
        prev_close=closes[0],
        last_date=dates[1],
        last_close=closes[1],
    )


def build_local_prompt(headlines: Sequence[Headline], watchlist_lines: Sequence[str]) -> str:
    """Ask for a description of the day **from these snippets only**, every claim cited.

    The index move is deliberately absent from this prompt: it is a number this system computes, and
    a model restating it in its own words is a number that can drift from the one beside it.
    """
    listing = "\n".join(
        f"[{h.id}] {h.title}" + (f" — {h.source}" if h.source else "") for h in headlines
    )
    watchlist = ", ".join(watchlist_lines)
    return (
        "You are writing a short market note for someone who owns Indian equities.\n\n"
        "You have ONLY the headlines listed below. You have no other source, no memory of today, "
        "and no access to prices. Write only what these headlines say.\n\n"
        "**Every factual sentence must end with the id of the headline it came from, like "
        "[a1b2c3d4].** A sentence you cannot cite is one you must not write. Do not use an id that "
        "is not in the list.\n\n"
        "Write four short sections in Telegram-friendly markdown, under 1500 characters:\n"
        "1. **What the headlines say** — the two or three themes actually present, each cited.\n"
        "2. **Names on the watchlist** — any of the names below that appear, and what was said "
        "about them. If none appear, say so plainly.\n"
        "3. **What is not here** — what these headlines do NOT cover, so the reader knows the "
        "shape of the gap. Sectors, or a name they hold that nothing was said about.\n"
        "4. **One line on what to watch**, phrased as a question rather than a prediction.\n\n"
        "DO NOT forecast. No price targets, no direction for tomorrow, no 'likely reaction', no "
        "buy or sell. You are describing what was published, not what will happen — a forecast "
        "from twenty headlines is invention, and this note sits beside a real decision.\n\n"
        f"Watchlist: {watchlist}\n\n"
        f"Headlines:\n{listing}\n"
    )


def parse_citations(text: str) -> set[str]:
    """Every ``[id]`` the model cited."""
    import re

    return set(re.findall(r"\[([0-9a-f]{8,32})\]", text))


def check_local_brief(text: str, ids: Sequence[str]) -> list[str]:
    """What is wrong with this brief, or ``[]``. **A brief that fails is not written.**

    Three refusals, each of them a thing that has gone wrong on this project before: an uncheckable
    citation (the veto that cited a stock quote page), an unsourced claim (a narrative with nothing
    behind it), and a forecast presented beside a basket.
    """
    problems: list[str] = []
    cited = parse_citations(text)
    known = set(ids)
    invented = sorted(cited - known)
    if invented:
        problems.append(f"cites {len(invented)} id(s) that were never supplied: {invented[:3]}")
    if not cited:
        problems.append("cites nothing, so no sentence in it can be checked")
    lowered = text.lower()
    for phrase in _FORECAST_PHRASES:
        if phrase in lowered:
            problems.append(
                f"reads as a forecast ({phrase.strip()!r}), which this note must not be"
            )
            break
    if "SIGNAL:" in text:
        problems.append("carries a SIGNAL line, which belongs to a mechanism that was retired")
    return problems


def generate_local_brief(
    headlines: Sequence[Headline],
    watchlist_lines: Sequence[str],
    *,
    generate: GenerateFn,
    model: str,
) -> BriefResult | None:
    """Write the brief here. ``None`` when there is nothing to write it from, or it failed a check.

    **No headlines, no brief.** That is the whole guard: this refuses to run rather than let a model
    answer "what happened today" out of its training data, which is the single worst failure this
    repo could ship and would look exactly like the feature working.
    """
    if not headlines:
        print("[ai-brief] no archived headlines — refusing to write a brief from memory.")
        return None
    try:
        raw, usage = generate(model, build_local_prompt(headlines, watchlist_lines))
    except Exception as exc:
        print(f"[ai-brief] local generation failed (non-fatal): {exc}")
        return None
    if not raw.strip():
        print("[ai-brief] empty response — skipping.")
        return None
    problems = check_local_brief(raw, [h.id for h in headlines])
    if problems:
        for problem in problems:
            print(f"[ai-brief] REJECTED: the brief {problem}")
        return None
    body = f"{CONTEXT_PREAMBLE}\n\n{raw.strip()}"
    return BriefResult(text=format_for_telegram(body), raw=body, model=model, usage=usage)


# ---- the per-name verdict (PLAN_TRUST_REPAIR.md PR-8) --------------------------------------------
#
# ⚠️ **This is the one place the LLM selects.** Everywhere else in this system it is context-only
# (locked discipline #3). Here the deterministic screen produces a candidate list and the model
# returns a keep/drop verdict per name; the math then sizes and executes whatever survives.
#
# Three properties make that safe enough to test with, and each is enforced in code, not by prompt:
#
# 1. **The model cannot add a name.** :func:`parse_verdicts` discards any ticker outside the
#    deterministic universe it was handed. The opportunity set is fixed before the model is asked.
# 2. **The model cannot size anything.** It returns keep/drop. Quantities come from the fixed-notional
#    basket (PR-7) and are identical to the no-AI shadow's for every name that survives.
# 3. **Absence means keep.** No verdict, an unparseable line, a failed call, no API key — the name
#    stays. The model can therefore only ever *remove* from the deterministic screen, and every
#    failure mode degrades to exactly the shadow's behaviour rather than to an empty book.
#
# **Fake money only.** This reaches the real-money advisor only on a positive System-vs-Shadow
# verdict, per the endgame contract. Real money never auto-trades — that rule is untouched.

#: One verdict line per candidate. Deliberately *not* folded into the ``SIGNAL:`` line: that line is
#: one scalar lean for the whole index, has no ticker field, and drives a different (now-retired)
#: mechanism. A per-name decision needs a per-name row.
_VERDICT_PREFIX = "VERDICT:"

#: Hosts whose documents are **primary evidence** — the exchange, the regulator, the filing itself.
#: A veto that moves money has to rest on one of these.
#:
#: **Why this list exists.** The first real veto (2026-09-03, ADANIENSOL) dropped a name for "U.S.
#: bribery charges against chairman" and cited ``stockanalysis.com/quote/nse/ADANIENSOL/`` — a stock
#: *quote page*, which evidences nothing at all. The citation rule shipped days earlier checked that
#: a URL was present, not that it supported the claim, so a well-formed link to an irrelevant page
#: passed. The underlying claim may well be true; the point is that a year from now nobody could
#: verify it from what was recorded, and verifying it is the entire purpose of the requirement.
PRIMARY_SOURCE_HOSTS = frozenset(
    {
        "nseindia.com",
        "archives.nseindia.com",
        "nsearchives.nseindia.com",
        "bseindia.com",
        "sebi.gov.in",
        "ibbi.gov.in",
        "mca.gov.in",
    }
)


def source_tier(url: str) -> str:
    """``"primary"`` for an exchange/regulator document, ``"secondary"`` for anything else fetchable.

    Deliberately host-based and deliberately short. A longer list of "reputable" outlets would be a
    judgement call smuggled into a constant; the distinction that matters is *filing versus report*,
    and only the former is something a later reader can check without trusting an intermediary.
    """
    if not url.lower().startswith(("http://", "https://")):
        return "none"
    host = url.split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")
    return (
        "primary"
        if any(host == h or host.endswith("." + h) for h in PRIMARY_SOURCE_HOSTS)
        else "secondary"
    )


_MAX_VERDICT_TOKENS = 2500  # ~15 candidates × a short reason each, plus the search preamble


@dataclass(frozen=True)
class Candidate:
    """What the deterministic screen hands the model about one name. Facts only, no ask."""

    ticker: str
    sector: str
    cheapness: float  # fractional pullback below the (continuity-corrected) 1y high
    health: str  # the §4.7 breakdown verdict: "breaking" | "watch" | "healthy"
    trailing_return: float  # 6-month return


@dataclass(frozen=True)
class NameVerdict:
    """The model's keep/drop call on one candidate, over a ~1-year horizon."""

    ticker: str
    keep: bool
    confidence: str  # "low" | "medium" | "high"
    reason: str
    #: URL the model says it read. **A DROP not cited to a PRIMARY source is demoted to KEEP** by
    #: `parse_verdicts` — a veto whose evidence cannot be re-read a year later is indistinguishable
    #: from a hallucination, and distinguishing those is the only question this experiment asks.
    source: str = ""
    #: ``"primary"`` (exchange/regulator) · ``"secondary"`` (reporting) · ``"none"``.
    source_tier: str = "none"
    #: True when the model said DROP and this was downgraded to KEEP for want of primary evidence.
    #: Recorded rather than discarded: a demoted veto is a *lead*, and the count of them is itself
    #: evidence about whether the model is finding real things it cannot cite.
    demoted: bool = False


def build_verdict_prompt(candidates: list[Candidate]) -> str:
    """Ask for a **one-year** keep/drop view of each candidate — not tomorrow's session.

    The horizon is the point. The existing brief asks what the index does over 1–2 sessions, which is
    a question about noise; this asks whether a name that is *already* cheap and *already* flagged as
    breaking down is likely to still be a poor holding a year out. That is a question where a
    narrative read might plausibly add something over a price screen, and it is the horizon the
    verdict is scored on.

    The deterministic facts are supplied so the model does not have to guess them — and so it cannot
    substitute its own numbers for the engine's. It is told explicitly that it may only remove.
    """
    rows = "\n".join(
        f"- {c.ticker.removesuffix('.NS')} ({c.sector}): {c.cheapness * 100:.0f}% below its 1y high, "
        f"6-month return {c.trailing_return:+.0%}, breakdown test says {c.health}"
        for c in candidates
    )
    return (
        "You are screening a fixed shortlist of Indian (NSE) equities for a ~1-YEAR hold.\n\n"
        "A deterministic price screen has already chosen these names and already sized them. Your "
        "only job is to say, for each one, whether you would KEEP it in a one-year portfolio or DROP "
        "it. You cannot add names, change weights, or suggest alternatives — anything outside this "
        "list is ignored.\n\n"
        "Use the web-search tool to check for company-specific news that a price screen cannot see: "
        "governance problems, regulatory or legal action, accounting concerns, demerger or "
        "restructuring effects, a structurally broken end-market, or a credible turnaround. Ignore "
        "short-term price moves and today's market noise — those are already in the numbers below, "
        "and the horizon is a year, not a session.\n\n"
        "Default to KEEP. Only DROP a name when you found a specific, checkable reason to think the "
        "next year looks bad for that company in particular. 'It has fallen a lot' is not a reason — "
        "the screen selected these names *because* they have fallen.\n\n"
        f"Candidates:\n{rows}\n\n"
        "First, in ≤900 characters, note only the names you are dropping and why (one line each; "
        "write 'no drops' if none).\n\n"
        "Then emit one line per candidate, and nothing else after them, exactly in this form:\n"
        f"{_VERDICT_PREFIX} ticker=<TICKER>; call=<keep|drop>; confidence=<low|medium|high>; "
        "reason=<≤12 words>; source=<URL you actually read, or - for keep>\n"
        f"(e.g. '{_VERDICT_PREFIX} ticker=VEDL; call=drop; confidence=medium; reason=demerger "
        "restructuring still unresolved; source=https://www.bseindia.com/...')\n\n"
        "**A drop needs a link to the PRIMARY DOCUMENT.** That means nseindia.com, bseindia.com, "
        "sebi.gov.in, ibbi.gov.in or mca.gov.in — the filing, disclosure or order itself. News "
        "reporting *about* a filing does not count, and a stock quote or data page counts for "
        "nothing at all. A drop cited anywhere else is recorded but NOT acted on, so if you cannot "
        "find the document, say keep.\n\n"
        "Every candidate must get exactly one line. A name you say nothing about is kept."
    )


def parse_verdicts(text: str, universe: set[str]) -> dict[str, NameVerdict]:
    """Parse ``VERDICT:`` lines, **discarding anything outside** ``universe``.

    This function is the enforcement point for "the AI cannot add a name". A ticker the model
    invented, hallucinated, or carried over from its search results is not in the deterministic
    universe and is dropped here — before any code can act on it. Matching is suffix-tolerant, since
    the prompt shows bare tickers while the system trades ``.NS`` symbols.

    Malformed lines are skipped rather than guessed at: a line we cannot read is a name with no
    verdict, and a name with no verdict is kept.
    """
    bare = {t.removesuffix(".NS"): t for t in universe}
    out: dict[str, NameVerdict] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(_VERDICT_PREFIX):
            continue
        fields: dict[str, str] = {}
        for part in stripped[len(_VERDICT_PREFIX) :].split(";"):
            key, _, value = part.partition("=")
            if value:
                fields[key.strip().lower()] = value.strip()
        raw_ticker = fields.get("ticker", "").upper().removesuffix(".NS")
        call = fields.get("call", "").lower()
        if raw_ticker not in bare or call not in {"keep", "drop"}:
            continue  # unknown name, or a call we cannot read → no verdict → the name is kept
        confidence = fields.get("confidence", "low").lower()
        source = fields.get("source", "").strip()
        tier = source_tier(source)
        if tier == "none":
            source = ""
        keep = call == "keep"
        # A veto acts only on PRIMARY evidence. Uncited, or cited to reporting rather than to the
        # filing itself, it is demoted to KEEP and recorded as a lead. The screen is the floor; the
        # model may subtract from it only with something a later reader can open and check.
        demoted = not keep and tier != "primary"
        if demoted:
            keep = True
        out[bare[raw_ticker]] = NameVerdict(
            ticker=bare[raw_ticker],
            keep=keep,
            confidence=confidence if confidence in {"low", "medium", "high"} else "low",
            reason=fields.get("reason", "")[:120],
            source=source[:500],
            source_tier=tier,
            demoted=demoted,
        )
    return out


def survivors(basket: dict[str, int], verdicts: dict[str, NameVerdict]) -> dict[str, int]:
    """Apply verdicts to a sized basket: drop what the model dropped, **keep everything else**.

    Quantities are never touched — a surviving name is bought in exactly the quantity the
    deterministic basket assigned it, which is the same quantity the no-AI shadow buys. The only
    difference the experiment can measure is therefore which names are present.

    Absence is keep: a name with no verdict survives. With no verdicts at all this is the identity
    function, which is what makes the stubbed keep-everything run byte-identical to the shadow.
    """
    return {t: q for t, q in basket.items() if verdicts.get(t) is None or verdicts[t].keep}


def verdicts_note(verdicts: dict[str, NameVerdict], basket: dict[str, int]) -> str:
    """The audit line — what the model removed from the deterministic basket, and why."""
    dropped = [v for t, v in sorted(verdicts.items()) if not v.keep and t in basket]
    if not dropped:
        return (
            f"🤖 AI name-verdict: kept all {len(basket)} deterministic picks "
            "(no name-specific reason to drop any)."
        )
    lines = [
        f"🤖 AI name-verdict: dropped {len(dropped)} of {len(basket)} deterministic picks "
        "(it can only remove — never add a name, never change a size):"
    ]
    lines += [
        f"  - {v.ticker}: {v.reason or 'no reason given'} ({v.confidence} confidence)"
        for v in dropped
    ]
    return "\n".join(lines)


def anchor_preamble(text: str) -> str:
    """Make the context-only preamble the first line, stripping any pre-amble model narration.

    The web-search model sometimes emits "I'll search for…" chatter before the template. Anchor on
    the preamble: drop everything before it if it appears mid-text, or prepend it if it's missing
    entirely (the disclaimer is non-negotiable).
    """
    body = text.strip()
    idx = body.find(CONTEXT_PREAMBLE)
    if idx > 0:
        return body[idx:].strip()
    if idx < 0:
        return f"{CONTEXT_PREAMBLE}\n\n{body}"
    return body


def format_for_telegram(text: str, *, limit: int = _TELEGRAM_LIMIT) -> str:
    """Anchor the preamble (see :func:`anchor_preamble`) and fit within Telegram's length cap —
    truncating on a whitespace boundary with an ellipsis if over ``limit``."""
    body = anchor_preamble(text)
    if len(body) <= limit:
        return body
    cut = body.rfind(" ", 0, limit - 1)
    if cut <= 0:
        cut = limit - 1
    return body[:cut].rstrip() + "…"


def load_watchlist_lines(csv_path: str) -> list[str]:
    """Read the vendored Nifty-100 watchlist CSV into compact ``TICKER:SECTOR`` lines (pure I/O)."""
    import csv

    lines: list[str] = []
    with open(csv_path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            ticker = (row.get("ticker") or "").strip()
            sector = (row.get("sector") or "").strip()
            if ticker:
                lines.append(f"{ticker.removesuffix('.NS')}:{sector}")
    return lines


def _default_generate(api_key: str, *, max_tokens: int = _MAX_OUTPUT_TOKENS) -> GenerateFn:
    """Wire the real web-searched Haiku call. Lazy-imports the anthropic SDK so the module (and the
    pure tests) load without the ``ai`` extra installed.

    ``max_tokens`` differs by call: the narrative brief is ~500 tokens, a per-name verdict sheet over
    ~15 candidates needs more room (:data:`_MAX_VERDICT_TOKENS`).
    """

    def generate(model_id: str, prompt: str) -> tuple[str, dict[str, int]]:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": _MAX_SEARCHES,
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":  # safety decline → treat as empty (fail-soft skips it)
            return "", {}
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        usage = {
            "input": int(getattr(resp.usage, "input_tokens", 0) or 0),
            "output": int(getattr(resp.usage, "output_tokens", 0) or 0),
            # 1 iff the model hit the output cap (brief was cut off) — surfaced in the footer so the
            # user can see the response was complete without opening the Anthropic console.
            "truncated": 1 if resp.stop_reason == "max_tokens" else 0,
        }
        return text, usage

    return generate


def generate_verdicts(
    candidates: list[Candidate],
    *,
    generate: GenerateFn | None = None,
    model: str | None = None,
) -> tuple[dict[str, NameVerdict], str, dict[str, int]]:
    """Ask the model for a keep/drop call on each candidate. Returns ``(verdicts, raw, usage)``.

    **Fails to empty, which means fails to keep-everything.** No API key, a refusal, an exception, an
    empty body — all return ``{}``, and :func:`survivors` treats an empty verdict map as "keep all".
    The deterministic screen is the floor: the model can subtract from it or be absent, never more.
    """
    model = model or os.environ.get("ANTHROPIC_MODEL") or _DEFAULT_MODEL
    if not candidates:
        return {}, "", {}
    if generate is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("[ai-verdict] ANTHROPIC_API_KEY not set — keeping every deterministic pick.")
            return {}, "", {}
        generate = _default_generate(api_key, max_tokens=_MAX_VERDICT_TOKENS)
    try:
        raw, usage = generate(model, build_verdict_prompt(candidates))
    except Exception as exc:  # fail-soft → keep everything; never break the cron
        print(f"[ai-verdict] generation failed (non-fatal, keeping all picks): {exc}")
        return {}, "", {}
    universe = {c.ticker for c in candidates}
    verdicts = parse_verdicts(raw, universe)
    unknown = raw.count(_VERDICT_PREFIX) - len(verdicts)
    if unknown > 0:
        # Not an error — this is the guard doing its job. Worth printing so a model that keeps
        # inventing tickers is visible rather than silently filtered forever.
        print(
            f"[ai-verdict] discarded {unknown} verdict line(s) outside the deterministic universe."
        )
    return verdicts, raw, usage


def generate_brief(
    watchlist_lines: list[str],
    *,
    generate: GenerateFn | None = None,
    model: str | None = None,
) -> BriefResult | None:
    """Produce today's brief, or ``None`` if it can't (fail-soft — the caller stays green).

    ``generate`` is injected in tests (a canned response). In production it defaults to the
    web-searched Haiku call, which needs ``ANTHROPIC_API_KEY`` — absent it, this returns ``None``.
    """
    model = model or os.environ.get("ANTHROPIC_MODEL") or _DEFAULT_MODEL
    if generate is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("[ai-brief] ANTHROPIC_API_KEY not set — skipping the brief.")
            return None
        generate = _default_generate(api_key)
    try:
        raw, usage = generate(model, build_prompt(watchlist_lines))
    except Exception as exc:  # fail-soft: never break the cron on an API/quota/parse error
        print(f"[ai-brief] generation failed (non-fatal): {exc}")
        return None
    if not raw.strip():
        print("[ai-brief] empty response — skipping.")
        return None
    return BriefResult(
        text=format_for_telegram(raw), raw=anchor_preamble(raw), model=model, usage=usage
    )
