"""The product must never import `research/` — the graduation boundary, enforced.

One repo replaced two, so the rule that used to be structural ("the product cannot import research
because it is a different repo") is now only a convention — and a convention that costs nothing to
break is not a rule. This test is the replacement.

`research/` holds ideas that have **not** passed a pre-registered test: the HMM risk state, LPPLS
bubble detection, the options hedge variant, the QUBO/QAOA track. Code graduates by *moving* into
`src/qalpha/` when its test passes — never by being imported from where it sits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PRODUCT = sorted((_ROOT / "src" / "qalpha").rglob("*.py")) + sorted(
    (_ROOT / "scripts").glob("*.py")
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def test_the_product_never_imports_research() -> None:
    """A graduated idea is one that MOVED, not one that is reached across the line."""
    assert _PRODUCT, "no product modules found — the glob is wrong, not the repo clean"
    offenders = {
        p.relative_to(_ROOT).as_posix(): sorted(
            m for m in _imported_modules(p) if m.split(".")[0] == "research"
        )
        for p in _PRODUCT
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, (
        "product code imports research/ — graduate the module by moving it into src/qalpha/ "
        f"once its pre-registered test passes:\n{offenders}"
    )


def test_research_is_present_and_is_not_on_the_product_test_path() -> None:
    """Research exists in this repo, but its suite is separate: the product suite forbids skips.

    Research legitimately skips (qiskit and hmmlearn are heavy, optional installs). Folding those
    into the product run would either force the deps into CI or reintroduce skips — and a skip reads
    as a pass in the summary, which is why `ci.yml` fails on any skip at all.
    """
    assert (_ROOT / "research").is_dir()
    assert (_ROOT / "research" / "tests").is_dir()
    cfg = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'testpaths = ["tests"]' in cfg, "the default pytest run must not collect research/"


@pytest.mark.parametrize("module", ["research.regime.risk_state", "research.quantum.qubo"])
def test_research_modules_are_not_importable_as_qalpha(module: str) -> None:
    """Research is its own top-level package — it must not masquerade as part of the product."""
    assert not module.startswith("qalpha")
