"""Transcribe scanned filings that carry no text layer, so they stop being permanent holes.

**Why this exists.** ``documents_for`` skips a filing whose PDF yields no text, and
``AnnouncementCoverage.complete`` requires ``documents_read >= filings_in_window``. A scanned image
therefore makes a name **permanently incomplete**: the buy screen reads "Filings NOT read" for it
for ever, no matter how many times the corpus is rebuilt. Nine such documents blocked five names
after the 2026-09-12 backfill.

**What it changes, stated plainly.** Every other quote in this corpus is checked against the bytes
NSE served. A quote checked against a transcription is checked against **a model's reading of an
image** — a weaker claim, and one a later reader must be able to tell apart. So the provenance
sidecar gains ``text_source``:

* absent        — the text came from the PDF's own text layer (every document before this)
* ``ocr:<model>`` — the text is a transcription, and the guarantee is correspondingly weaker

The hash and byte length still describe the original PDF, so the archived document is unchanged and
the transcription is an addition to it, never a replacement.

    uv run python scripts/ocr_scans.py --dry-run     # list what has no text layer
    uv run python scripts/ocr_scans.py               # transcribe them
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.live.console import use_utf8
from qalpha.live.credentials import load_env
from qalpha.live.extraction import corpus_reader

ARCHIVE = Path("data/evidence/announcements")

#: Faithful transcription, not summary — the output is what quotes get verified against, so a
#: paraphrase here would let an unverifiable passage into the corpus wearing a verified label.
PROMPT = (
    "Transcribe this document to plain text, exactly as written.\n\n"
    "Rules:\n"
    "- Reproduce the wording VERBATIM. Do not summarise, correct, reorder or explain.\n"
    "- Keep numbers, names, dates and currency symbols exactly as they appear.\n"
    "- Preserve paragraph breaks. Render a table as readable lines.\n"
    "- If part of the page is illegible, write [illegible] there rather than guessing.\n"
    "- Output the transcription only — no preamble, no commentary."
)

#: A transcription of a filing is a few thousand tokens; a long scanned annexure can be more.
MAX_OUTPUT_TOKENS = 16_000


def scanned_documents() -> list[tuple[Path, Path]]:
    """Every archived filing that has provenance and a PDF but no text. ``(pdf, provenance)``."""
    out: list[tuple[Path, Path]] = []
    for prov in sorted(ARCHIVE.rglob("*.provenance.json")):
        if prov.parent.name == "index":
            continue
        stem = prov.name.removesuffix(".provenance.json")
        pdf = prov.parent / f"{stem}.pdf"
        text = prov.parent / f"{stem}.txt.gz"
        if pdf.exists() and not text.exists():
            out.append((pdf, prov))
    return out


def transcribe(pdf: Path, model: str, api_key: str) -> str:
    """One document, transcribed. Raises on failure — the caller reports and moves on."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=300.0)
    payload = base64.standard_b64encode(pdf.read_bytes()).decode("ascii")
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": payload,
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("the model declined to transcribe this document")
    text = "".join(
        str(getattr(b, "text", "")) for b in resp.content if getattr(b, "type", None) == "text"
    )
    if resp.stop_reason == "max_tokens":
        # A cut-off transcription is a partial document, and a quote verified against it would
        # attest to a filing nobody read the end of.
        raise RuntimeError(
            f"transcription hit the {MAX_OUTPUT_TOKENS}-token cap; document too long"
        )
    return text.strip()


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    load_env()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="list the documents, transcribe nothing")
    args = ap.parse_args(argv)

    import gzip
    import os

    from qalpha.live.atomic import write_bytes

    pending = scanned_documents()
    if not pending:
        print("[ocr] every archived filing already has text.")
        return 0
    print(f"[ocr] {len(pending)} filing(s) with no text layer:")
    for pdf, _prov in pending:
        print(f"  {pdf.parent.name:<12} {pdf.stem}  {pdf.stat().st_size:>9,}b")
    if args.dry_run:
        return 0

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print(
            "[ocr] ANTHROPIC_API_KEY is set in neither the environment nor .env.", file=sys.stderr
        )
        return 2
    model = corpus_reader()
    print(f"[ocr] transcribing with {model}. The PDFs leave this machine.")

    done = failed = 0
    for pdf, prov_path in pending:
        try:
            text = transcribe(pdf, model, key)
        except Exception as exc:
            print(f"  {pdf.parent.name:<12} {pdf.stem}  FAILED - {type(exc).__name__}: {exc}")
            failed += 1
            continue
        if len(text) < 40:
            print(f"  {pdf.parent.name:<12} {pdf.stem}  FAILED - transcription too short to be one")
            failed += 1
            continue
        write_bytes(pdf.with_suffix(".txt.gz"), gzip.compress(text.encode("utf-8")))
        meta = json.loads(prov_path.read_text(encoding="utf-8"))
        # THE POINT OF THE WHOLE SCRIPT. Without this a later reader cannot tell a quote checked
        # against NSE's bytes from one checked against a model's reading of a picture.
        meta["text_source"] = f"ocr:{model}"
        write_bytes(prov_path, (json.dumps(meta, indent=1) + "\n").encode("utf-8"))
        print(f"  {pdf.parent.name:<12} {pdf.stem}  transcribed {len(text):,} chars")
        done += 1
    print(f"[ocr] {done} transcribed, {failed} failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
