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

**Model:** Anthropic **Claude Haiku 4.5** with the server-side **web-search tool**, so the brief
reflects *today's* news without any RSS plumbing (Haiku was chosen over Opus deliberately — the brief
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
from collections.abc import Callable
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


def _default_generate(api_key: str) -> GenerateFn:
    """Wire the real web-searched Haiku call. Lazy-imports the anthropic SDK so the module (and the
    pure tests) load without the ``ai`` extra installed."""

    def generate(model_id: str, prompt: str) -> tuple[str, dict[str, int]]:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model_id,
            max_tokens=_MAX_OUTPUT_TOKENS,
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
