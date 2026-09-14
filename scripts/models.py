"""Local models: which weights are served, and which are registered.

    uv run python scripts/models.py list             # served digests beside the pinned ones
    uv run python scripts/models.py pin qwen3.5:9b   # register the digest served right now

Talks only to the Ollama server on this machine (``/api/tags``). Nothing here downloads a model or
calls a paid API.

**Pin deliberately.** Pinning says "these exact weights are the registered reader". Do it after the
model has been measured against the reference set, not before — a pin is how an unmeasured model
would otherwise slip into the corpus under a familiar tag.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.live.console import use_utf8
from qalpha.live.localmodel import DEFAULT_URL, configured
from qalpha.live.model_identity import load_pins, ollama_digests, save_pin


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="served models and their pinned digests")
    pin = sub.add_parser("pin", help="register the digest the server holds for a model now")
    pin.add_argument("model")
    args = ap.parse_args(argv)

    url = configured()[0] or DEFAULT_URL
    try:
        served = ollama_digests(url)
    except OSError as exc:
        print(f"[models] cannot reach the local model server at {url}: {exc}", file=sys.stderr)
        return 2
    pins = load_pins()

    if args.cmd == "list":
        if not served:
            print("[models] the server holds no models.")
        for name in sorted(served):
            digest = served[name]
            pinned = pins.get(name, "")
            state = (
                "pinned"
                if pinned == digest
                else ("CHANGED since pinning" if pinned else "not pinned")
            )
            print(f"  {name:<28} {digest[:12]}  {state}")
        for name in sorted(set(pins) - set(served)):
            print(f"  {name:<28} {pins[name][:12]}  pinned but NOT served")
        return 0

    model = args.model
    digest = served.get(model) or served.get(f"{model}:latest", "")
    if not digest:
        print(f"[models] the server does not hold {model!r}. Pull it first.", file=sys.stderr)
        return 2
    previous = pins.get(model, "")
    save_pin(model, digest)
    if previous and previous != digest:
        print(f"[models] {model}: re-pinned {previous[:12]} -> {digest[:12]}. Revalidate it.")
    else:
        print(f"[models] {model}: pinned {digest[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
