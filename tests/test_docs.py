"""The one document must stay reachable, and nothing may point at documents that no longer exist.

Old plans and prose were repeatedly mistaken for current behaviour. They are gone from the tree; the
guard is that no code, test or live document names them again, and every link in the two documents
that remain resolves.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RETIRED = ("OPERATING.md", "PROJECT.md", "STRATEGY.md", "Q_alpha.md", "PLAN_")


@pytest.mark.parametrize("doc", ["README.md", "CLAUDE.md"])
def test_every_relative_link_resolves(doc: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    broken = [
        target
        for target in re.findall(r"\]\(([^)]+)\)", text)
        if "://" not in target
        and not target.startswith("#")
        and not (ROOT / target.split("#", 1)[0]).exists()
    ]
    assert not broken, f"{doc} links to files that do not exist: {broken}"


def test_no_code_or_live_document_names_a_retired_document() -> None:
    live = [
        *ROOT.glob("src/**/*.py"),
        *ROOT.glob("scripts/*.py"),
        *ROOT.glob("tests/*.py"),
        ROOT / "README.md",
        ROOT / "CLAUDE.md",
    ]
    offenders = []
    for path in live:
        if path.name == "test_docs.py":
            continue
        text = path.read_text(encoding="utf-8")
        for name in RETIRED:
            for line in text.splitlines():
                if name in line and "git show" not in line:
                    offenders.append(f"{path.relative_to(ROOT)}: {line.strip()[:100]}")
    assert not offenders, "retired documents are still cited:\n" + "\n".join(offenders)
