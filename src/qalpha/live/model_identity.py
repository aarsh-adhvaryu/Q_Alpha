"""Which model actually answered — recorded from the answer, never assumed from the request.

A registered version names its reader and its decider. Two ways that name can stop being true
without anything in this repository changing:

* **A provider redirects a name.** DeepSeek's own change log records retired model names being
  served by newer models. The request still says the old name; the reply says what ran.
* **A local model is re-pulled.** ``ollama pull qwen3.5:9b`` next month can fetch different weights
  under the same tag. The tag is unchanged; the digest is not.

Either is a different treatment wearing the registered label. So the model the provider **returns**
is compared with the model requested, and a local model's **digest** with the digest pinned in
``data/models/pins.json``. A mismatch stops the step — :class:`ModelChangedError` — until the model is
revalidated and re-pinned deliberately.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

PINS_PATH = Path("data/models/pins.json")


class ModelChangedError(RuntimeError):
    """The model that answered is not the model that was registered."""


def check_returned(requested: str, returned: str) -> None:
    """A reply that names a different model than the request is refused.

    An empty ``returned`` is recorded as unknown by the caller rather than treated as a match or a
    mismatch: some servers omit the field, and inventing a mismatch would stop every call to them.
    """
    if returned and returned != requested:
        raise ModelChangedError(
            f"asked for {requested!r} but {returned!r} answered; a redirected model is a different "
            "treatment — revalidate before using it"
        )


def load_pins(path: Path | None = None) -> dict[str, str]:
    target = PINS_PATH if path is None else path
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pins = raw.get("pins", {}) if isinstance(raw, dict) else {}
    return {str(k): str(v.get("digest", "")) for k, v in pins.items() if isinstance(v, dict)}


def save_pin(model: str, digest: str, path: Path | None = None) -> None:
    """Record a digest as the registered one. A deliberate act — nothing calls this implicitly."""
    from qalpha.live.atomic import write_text

    target = PINS_PATH if path is None else path
    existing: dict[str, dict[str, str]] = {}
    if target.exists():
        try:
            existing = dict(json.loads(target.read_text(encoding="utf-8")).get("pins", {}))
        except (OSError, ValueError):
            existing = {}
    existing[model] = {
        "digest": digest,
        "pinned_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    write_text(target, json.dumps({"pins": existing}, indent=2, sort_keys=True) + "\n")


def ollama_digests(chat_url: str, *, timeout: float = 5.0) -> dict[str, str]:
    """Every model the local Ollama server holds, by tag, with its digest.

    Read from ``/api/tags`` on the same host as the chat endpoint. This is a call to this machine,
    not to the network.
    """
    parts = urlsplit(chat_url)
    tags_url = f"{parts.scheme}://{parts.netloc}/api/tags"
    with urllib.request.urlopen(tags_url, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    out: dict[str, str] = {}
    for item in payload.get("models", []) or []:
        name = str(item.get("name") or item.get("model") or "")
        if name:
            out[name] = str(item.get("digest") or "")
    return out


def check_digest(model: str, served: dict[str, str], pins: dict[str, str]) -> str:
    """The served digest, if it matches the pin. Raises :class:`ModelChangedError` otherwise.

    **An unpinned model is refused**, not trusted: pinning is how a model becomes a registered
    reader, so running one that was never pinned is running an unregistered treatment.
    """
    digest = served.get(model) or served.get(f"{model}:latest", "")
    if not digest:
        raise ModelChangedError(f"the local server does not hold {model!r}")
    pinned = pins.get(model, "")
    if not pinned:
        raise ModelChangedError(
            f"{model!r} has no pinned digest. Pin it deliberately after validating it: "
            f"uv run python scripts/models.py pin {model}"
        )
    if pinned != digest:
        raise ModelChangedError(
            f"{model!r} now has digest {digest[:12]}… but {pinned[:12]}… is pinned — the weights "
            "changed under the same tag. Revalidate, then re-pin."
        )
    return digest
