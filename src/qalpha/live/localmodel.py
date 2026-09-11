"""The local model path — the same reading, on this machine, with no key and no network.

### What actually wants to be local, and what cannot be

Two different jobs are asked of a language model in this repo, and they have opposite requirements:

**Extraction** (:mod:`qalpha.live.extraction`) reads filings this repo has already fetched, hashed
and stored, and reports what each document *says*. It is given **no tools, deliberately**, and every
passage it returns is checked against the archived bytes by :func:`~qalpha.live.extraction.
verify_passage` before it counts. That verifier is why a smaller model is tolerable here: invention
is caught mechanically rather than trusted away. **This job goes local.**

**The brief** (:mod:`qalpha.live.ai_brief`) is built on Anthropic's *server-side web search*. A model
running on this desktop has no crawler and no search index, so there is nothing for a local backend
to be a drop-in for. Pointing the brief at a local model would produce a fluent page of remembered
training data with today's date on it — the single worst failure this repo has, dressed as the
feature. **This job does not go local**; it runs with a key or it says it did not run.

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
from collections.abc import Callable
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
TIMEOUT_SECONDS = 900.0

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


def probe(url: str, *, timeout: float = 5.0) -> str:
    """``""`` when a server answers at ``url``, else why it did not.

    Checks the models listing beside the chat route rather than the chat route itself, so probing
    costs nothing and cannot be mistaken for work. A server that is up but has not loaded the model
    still answers here — that failure surfaces on the first real call, where it belongs.
    """
    listing = url.rsplit("/chat/completions", 1)[0] + "/models"
    try:
        with urllib.request.urlopen(listing, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return ""
            return f"the server at {listing} answered {resp.status}"
    except urllib.error.URLError as exc:
        return f"nothing answered at {listing} ({exc.reason})"
    except OSError as exc:
        return f"nothing answered at {listing} ({exc})"


def local_generate(
    url: str, *, max_tokens: int = 3000, timeout: float = TIMEOUT_SECONDS
) -> GenerateFn:
    """A :data:`GenerateFn` backed by an OpenAI-shaped chat endpoint on this machine.

    ``temperature`` is zero because this is an extraction task: the same filing should yield the
    same events on a re-run, or the audit trail is not one. Usage is reported when the server sends
    it and reported as zero when it does not — a local run costs nothing, so an absent count is
    missing information rather than a bill.
    """

    def generate(model_id: str, prompt: str) -> tuple[str, dict[str, int]]:
        body = json.dumps(
            {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        choices = payload.get("choices") or []
        if not choices:
            return "", {}
        text = str(choices[0].get("message", {}).get("content") or "")
        usage = payload.get("usage") or {}
        return text, {
            "input": int(usage.get("prompt_tokens", 0) or 0),
            "output": int(usage.get("completion_tokens", 0) or 0),
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
        why = probe(url)
        if why:
            return Backend(
                None,
                model,
                "none",
                f"Local model {model} was configured but {why}.{wsl_advice()} Filings are "
                "archived and left unread — this did NOT fall back to the cloud, because you "
                "asked for local.",
            )
        return Backend(
            local_generate(url),
            model,
            "local",
            f"Filings read locally by {model} at {url}. Nothing left this machine.",
            batch_chars=min(chars, PROMPT_CHAR_BUDGET),
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
