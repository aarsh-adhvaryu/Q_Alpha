"""A scanned filing is a hole in the corpus, and a transcription of one is weaker evidence.

``documents_for`` skips a PDF with no text layer and ``complete`` requires
``documents_read >= filings_in_window``, so a single scanned image makes a name **permanently**
incomplete — "Filings NOT read" on the buy screen for ever, through every rebuild. Nine such
documents blocked five names after the 2026-09-12 backfill.

Transcribing them closes the hole but changes what a verified quote means: checked against a
model's reading of a picture rather than against the bytes NSE served. That difference is the thing
these tests defend. It must be recorded on the document, and it must be impossible to lose.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "scripts")

from qalpha.live.atomic import write_bytes


def test_write_bytes_replaces_atomically_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "doc.txt.gz"
    write_bytes(target, gzip.compress(b"first"))
    assert gzip.decompress(target.read_bytes()) == b"first"

    write_bytes(target, gzip.compress(b"second"))
    assert gzip.decompress(target.read_bytes()) == b"second"
    assert list(target.parent.glob("*.tmp")) == [], "a temp file must never survive the write"


def test_a_failed_write_leaves_the_old_bytes_standing(tmp_path: Path) -> None:
    """The whole reason this module exists: a half-written gzip is unreadable, not merely short."""
    target = tmp_path / "doc.txt.gz"
    write_bytes(target, gzip.compress(b"the good one"))

    class Exploding(bytes):
        pass

    with pytest.raises(TypeError):
        write_bytes(target, "not bytes")  # type: ignore[arg-type]
    assert gzip.decompress(target.read_bytes()) == b"the good one"
    assert list(target.parent.glob("*.tmp")) == []


def test_only_filings_with_no_text_are_offered_for_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transcribing a document that already has a text layer would replace real bytes with a guess."""
    import ocr_scans

    monkeypatch.setattr(ocr_scans, "ARCHIVE", tmp_path)
    folder = tmp_path / "VBL"
    folder.mkdir()
    for stem, has_text in (("readable", True), ("scanned", False)):
        (folder / f"{stem}.provenance.json").write_text("{}", encoding="utf-8")
        (folder / f"{stem}.pdf").write_bytes(b"%PDF-1.4")
        if has_text:
            (folder / f"{stem}.txt.gz").write_bytes(gzip.compress(b"already extracted"))

    # An index sidecar is not a filing and must never be offered.
    index = folder / "index"
    index.mkdir()
    (index / "2026-09-12.provenance.json").write_text("{}", encoding="utf-8")
    (index / "2026-09-12.pdf").write_bytes(b"%PDF-1.4")

    found = [pdf.stem for pdf, _prov in ocr_scans.scanned_documents()]
    assert found == ["scanned"]


def test_a_transcribed_document_says_so_on_its_provenance() -> None:
    """The distinction a later reader needs, and the one that cannot be reconstructed afterwards.

    Every other quote in this corpus is checked against the bytes the exchange served. A quote
    checked against a transcription is a weaker claim. Absent ``text_source`` means the text came
    from the PDF's own text layer; ``ocr:<model>`` means it did not.
    """
    archive = Path("data/evidence/announcements")
    if not archive.exists():  # pragma: no cover - the archive is gitignored in a fresh clone
        pytest.skip("no archived filings present")
    transcribed = [
        p
        for p in archive.rglob("*.provenance.json")
        if p.parent.name != "index" and "text_source" in json.loads(p.read_text(encoding="utf-8"))
    ]
    if not transcribed:
        pytest.skip("nothing has been transcribed in this checkout")
    for prov in transcribed:
        meta = json.loads(prov.read_text(encoding="utf-8"))
        assert meta["text_source"].startswith("ocr:"), "the only non-PDF-layer source is OCR"
        # The sidecar still describes the ORIGINAL document. Transcription adds to the record; it
        # must never overwrite what was fetched.
        assert meta.get("sha256") and meta.get("bytes"), "the original document must still be named"
        assert prov.with_name(prov.name.replace(".provenance.json", ".txt.gz")).exists()
