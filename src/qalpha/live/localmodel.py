"""The local model path — the same reading, on this machine, with no key and no network.

### What actually wants to be local, and what cannot be

Two different jobs are asked of a language model in this repo, and they have opposite requirements:

**Extraction** (:mod:`qalpha.live.extraction`) reads filings this repo has already fetched, hashed
and stored, and reports what each document *says*. It is given **no tools, deliberately**, and every
passage it returns is checked against the archived bytes by :func:`~qalpha.live.extraction.
verify_passage` before it counts. That verifier is why a smaller model is tolerable here: invention
is caught mechanically rather than trusted away. **This job goes local.**

**The brief** (:mod:`qalpha.live.ai_brief`) needs *retrieval*, and that was the whole objection: a
model on this desktop has no crawler, and one asked what happened today with nothing to read answers
from its training data — a fluent page with today's date on it, which is the single worst failure
this repo could ship, dressed as the feature.

:mod:`qalpha.live.news` now archives the day's headlines before anything reads them, so the local
brief is written **from bytes on disk**, cites an item id for every claim, and is rejected rather
than published if it cites one it was not given. **With no headlines it does not run** — the guard
survives, moved from "no local model" to "nothing to read", which is where it belonged.

### What the local path wants

- **A server on loopback speaking the OpenAI chat shape.** Ollama serves it at
  ``http://127.0.0.1:11434/v1/chat/completions``; ``llama-server`` from llama.cpp serves the same
  shape at ``:8080``. Set :data:`URL_VAR` if yours is elsewhere.
- **A model name**, in :data:`MODEL_VAR`. There is no default and there will not be one: which
  weights read a filing is part of what the extraction row records, so it must be stated, not
  guessed. An unset name is a named absence, not a fallback.
- **Roughly 16k of context.** One extraction call packs up to
  :data:`~qalpha.live.extraction.PROMPT_CHAR_BUDGET` characters of filing (~7k tokens) and asks for
  up to 3k back. An 8k model will silently truncate the tail of a batch — which is the "25 of 30
  filings read, counted as 25 of 25" defect again — so :func:`budget_for` shrinks the batch instead.

On CPU this is minutes per filing, not seconds. That is the trade being made: the run is slower and
nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: (model, prompt) -> (text, usage). Structurally identical to the seams in ``extraction`` and
#: ``ai_brief``; re-declared rather than imported so this module stays free of both.
GenerateFn = Callable[[str, str], tuple[str, dict[str, int]]]

#: Where the local server listens, and which weights it should load.
URL_VAR = "QALPHA_LOCAL_MODEL_URL"
MODEL_VAR = "QALPHA_LOCAL_MODEL"
CONTEXT_VAR = "QALPHA_LOCAL_MODEL_CONTEXT"

DEFAULT_URL = "http://127.0.0.1:11434/v1/chat/completions"
#: Ollama's default. llama.cpp's ``llama-server`` is 8080; set :data:`URL_VAR` for that.
DEFAULT_CONTEXT_TOKENS = 16_384

#: A local model is slow, and a filing batch on CPU can genuinely take minutes. This is long enough
#: not to kill honest work and short enough that a wedged server does not hang the evening's run.
#:
#: It was 900, which is exactly ``EVIDENCE_BUDGET_SECONDS`` — so ONE wedged call could spend the
#: whole evening's reading budget, and the run would stop having covered nothing. Raise
#: :data:`TIMEOUT_VAR` if a genuinely slow machine needs longer; guessing high is paid for on the
#: day something hangs.
TIMEOUT_SECONDS = 300.0
TIMEOUT_VAR = "QALPHA_LOCAL_MODEL_TIMEOUT"

#: Qwen3 and its relatives think before answering, and the thinking is charged to the same
#: ``max_tokens`` as the reply — 150 to 220 tokens on a one-line answer, against a 3,000-token cap
#: that has to hold a whole batch's worth of EVENT lines. Ollama's OpenAI-compatible route honours
#: this field; the ``/no_think`` prompt suffix and a ``think: false`` body field do NOT (verified
#: against Ollama 0.34.0). A server that has never heard of the field ignores it.
REASONING_EFFORT = "none"

#: Rough chars-per-token for English prose with numbers in it. Used only to size a batch DOWN to fit
#: a stated context, never to report a token count as if it were measured.
CHARS_PER_TOKEN = 3.5


@dataclass(frozen=True)
class Backend:
    """Which model will read the filings, and how that was decided.

    ``note`` is written for the page, not the log: whichever backend is chosen, the run says so in
    words the user reads, because "the filings were read" means something different depending on
    what read them.
    """

    generate: GenerateFn | None
    model: str
    kind: str  # "local" | "anthropic" | "none"
    note: str
    #: Document characters per call. Sized to this backend's context, not to the cloud's.
    batch_chars: int = 0
    #: The context this backend was told it has, in tokens. Zero for the cloud, whose window is not
    #: ours to state.
    context_tokens: int = 0

    @property
    def available(self) -> bool:
        return self.generate is not None


def budget_for(
    context_tokens: int, *, output_tokens: int = 3000, overhead_chars: int = 4000
) -> int:
    """How many characters of filing may go into one call at this context size.

    The instruction preamble and the reply both live in the same window as the document, so the
    document gets what is left after both. Returns at least one chunk's worth — a context too small
    for even that is a configuration to reject, not a batch to shrink to nothing.
    """
    room_tokens = max(0, context_tokens - output_tokens)
    chars = int(room_tokens * CHARS_PER_TOKEN) - overhead_chars
    return max(2_000, chars)


def configured() -> tuple[str, str, int]:
    """``(url, model, context)`` from the environment. ``model`` is ``""`` when unset.

    Hydrates ``.env`` itself rather than trusting a caller to have done it: this is read by the
    app's reader panel, which renders before anything has touched the broker.
    """
    from qalpha.live.credentials import load_env

    load_env()
    url = os.environ.get(URL_VAR, "").strip() or DEFAULT_URL
    model = os.environ.get(MODEL_VAR, "").strip()
    raw = os.environ.get(CONTEXT_VAR, "").strip()
    try:
        context = int(raw) if raw else DEFAULT_CONTEXT_TOKENS
    except ValueError:
        context = DEFAULT_CONTEXT_TOKENS
    return url, model, context


def wsl_advice() -> str:
    """What to do when the model server is on Windows and this is running in WSL.

    Ollama on Windows binds ``127.0.0.1`` on the WINDOWS side. WSL2 has its own network namespace,
    so that address is a different machine's loopback and nothing there answers — which the generic
    "nothing answered" message describes accurately and unhelpfully, since the server is running
    perfectly well two feet away.
    """
    from qalpha.live.browser import is_wsl

    if not is_wsl():
        return ""
    return (
        " You are in WSL and Ollama on Windows listens on the Windows side's own loopback, which "
        "is not this one. Two fixes: add `networkingMode=mirrored` under [wsl2] in "
        "C:\\Users\\<you>\\.wslconfig and run `wsl --shutdown` (localhost then works both "
        "ways), or set OLLAMA_HOST=0.0.0.0 on Windows and point "
        f"{URL_VAR} at the Windows host address."
    )


def lists_model(model: str, listed: Sequence[str]) -> bool:
    """Is ``model`` one of the tags this server actually has?

    Ollama reports a tag in full — ``qwen3:8b`` as itself, a model built without one as
    ``name:latest`` — while people write the short form in ``.env``. Both spellings of the same
    weights match; nothing else does, because a near-miss is exactly what produced a page saying a
    model was reading filings while every call came back 404.
    """
    wanted = {model} if ":" in model else {model, model + ":latest"}
    return bool(wanted & set(listed))


def probe(url: str, *, model: str = "", timeout: float = 5.0) -> str:
    """``""`` when this server can serve ``model``, else why it cannot.

    Checks the models listing beside the chat route rather than the chat route itself, so probing
    costs nothing and cannot be mistaken for work.

    ### Why it reads the list rather than merely pinging it

    It used to return ``""`` for any 2xx. On this machine that meant a ``.env`` naming
    ``qwen2.5:7b`` — a tag Ollama does not have — passed, the page said *"Filings read locally by
    qwen2.5:7b"*, and every extraction call came back ``404 model not found``. Underneath, the run
    degraded correctly: no events, no receipt, coverage incomplete, "Filings NOT read" on the buy
    screen. The surface said the opposite. **A label naming something that did not happen** is the
    defect this repo is built around, and here it was inside the thing that reports the reader.

    It also accepted 200s that are not model lists: Open WebUI answers ``/v1/models`` on ``:8080``
    with its own HTML, so pointing :data:`URL_VAR` there probed clean and then 405ed on every call.
    """
    listing = url.rsplit("/chat/completions", 1)[0] + "/models"
    try:
        with urllib.request.urlopen(listing, timeout=timeout) as resp:
            if not 200 <= resp.status < 300:
                return f"the server at {listing} answered {resp.status}"
            body = resp.read()
    except urllib.error.URLError as exc:
        return f"nothing answered at {listing} ({exc.reason})"
    except OSError as exc:
        return f"nothing answered at {listing} ({exc})"

    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
        listed = [str(row["id"]) for row in payload["data"]]
    except (json.JSONDecodeError, KeyError, TypeError, IndexError, UnicodeDecodeError):
        return (
            f"{listing} answered, but not with a model list — that is a web page, not a model "
            f"server. Open WebUI does exactly this on :8080; {URL_VAR} has to point at whatever "
            "actually runs the weights (Ollama is :11434)"
        )
    if not listed:
        return f"the server at {listing} has no models loaded, so there is nothing to read with"
    if model and not lists_model(model, listed):
        return (
            f"the server at {listing} does not have {model} — it lists "
            f"{', '.join(sorted(listed))}. Set {MODEL_VAR} to one of those, or build the one you "
            f"meant with `ollama create`"
        )
    return ""


def timeout_seconds() -> float:
    """The per-call ceiling, overridable for a slow machine. Never zero, never unbounded."""
    raw = os.environ.get(TIMEOUT_VAR, "").strip()
    try:
        return max(1.0, float(raw)) if raw else TIMEOUT_SECONDS
    except ValueError:
        return TIMEOUT_SECONDS


def local_generate(url: str, *, max_tokens: int = 3000, timeout: float | None = None) -> GenerateFn:
    """A :data:`GenerateFn` backed by an OpenAI-shaped chat endpoint on this machine.

    ``temperature`` is zero because this is an extraction task: the same filing should yield the
    same events on a re-run, or the audit trail is not one. Usage is reported when the server sends
    it and reported as zero when it does not — a local run costs nothing, so an absent count is
    missing information rather than a bill.

    Two things beyond the text come back in ``usage``, and both are facts about the *call* rather
    than about the filings:

    ``truncated``
        the reply hit ``max_tokens``. **A cut-off list of events is not a complete reading of the
        documents that produced it**, and a caller that counts it as one has written the "25 of 30
        filings, reported as 25 of 25" defect again with a new cause.
    ``thought``
        the model spent tokens reasoning despite :data:`REASONING_EFFORT`. Recorded rather than
        ignored: it is the difference between a token budget that fits and one that does not.
    """

    def generate(model_id: str, prompt: str) -> tuple[str, dict[str, int]]:
        body = json.dumps(
            {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": False,
                "reasoning_effort": REASONING_EFFORT,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=timeout or timeout_seconds()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        choices = payload.get("choices") or []
        if not choices:
            return "", {}
        choice = choices[0]
        message = choice.get("message", {}) or {}
        text = str(message.get("content") or "")
        usage = payload.get("usage") or {}
        return text, {
            "input": int(usage.get("prompt_tokens", 0) or 0),
            "output": int(usage.get("completion_tokens", 0) or 0),
            "truncated": 1 if str(choice.get("finish_reason") or "") == "length" else 0,
            "thought": 1 if str(message.get("reasoning") or "").strip() else 0,
        }

    return generate


def choose_backend(*, prefer_local: bool | None = None) -> Backend:
    """Decide what reads the filings, and say so.

    Preference order, and the reason for it: a configured local model wins, because the point of
    configuring one is that documents stop leaving the machine. Anthropic is the fallback **only
    when local was never asked for** — a local model that is configured but unreachable does NOT
    silently become a cloud call, because that would send filings over the network on the one
    evening the user believed nothing was.
    """
    from qalpha.live.announcements import MAX_DOCUMENT_CHARS
    from qalpha.live.extraction import PROMPT_CHAR_BUDGET

    url, model, context = configured()
    want_local = bool(model) if prefer_local is None else prefer_local
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if want_local:
        if not model:
            return Backend(
                None,
                "",
                "none",
                f"Local reading was asked for but {MODEL_VAR} is unset, so no model was named. "
                "Filings are archived and left unread.",
            )
        chars = budget_for(context)
        if chars < MAX_DOCUMENT_CHARS:
            # A window this small cannot hold one chunk, and the server would quietly drop the
            # tail while the run counted the document as read. Refuse instead.
            return Backend(
                None,
                model,
                "none",
                f"{model} was given a {context:,}-token context, which leaves room for only "
                f"{chars:,} characters of filing — less than one {MAX_DOCUMENT_CHARS:,}-character "
                f"chunk. Raise {CONTEXT_VAR} to at least 8192. Filings archived, left unread.",
            )
        why = probe(url, model=model)
        if why:
            return Backend(
                None,
                model,
                "none",
                f"Local model {model} was configured but {why}.{wsl_advice()} Filings are "
                "archived and left unread — this did NOT fall back to the cloud, because you "
                "asked for local.",
            )
        batch = min(chars, PROMPT_CHAR_BUDGET)
        return Backend(
            local_generate(url),
            model,
            "local",
            f"Filings read locally by {model} at {url} — a {context:,}-token context, up to "
            f"{batch:,} characters of filing per call, thinking off. Nothing left this machine.",
            batch_chars=batch,
            context_tokens=context,
        )

    if key:
        from qalpha.live.extraction import DEFAULT_MODEL, default_generate

        return Backend(
            default_generate(key),
            DEFAULT_MODEL,
            "anthropic",
            f"Filings read by {DEFAULT_MODEL} over the API. Document text left this machine.",
            batch_chars=PROMPT_CHAR_BUDGET,
        )

    return Backend(
        None,
        "",
        "none",
        f"No reader configured: {MODEL_VAR} is unset and there is no ANTHROPIC_API_KEY. Filings "
        "are archived and left unread — unread is not clean.",
    )
