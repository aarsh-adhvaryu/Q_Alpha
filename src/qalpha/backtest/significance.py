"""How big must a difference be before it means anything? — the noise floor (PLAN_REDESIGN §5).

**Forward run 1 was voided for want of this number.** Its System − Shadow of ₹1,541 sat under ₹1,964
of one day's rounding noise, and nobody knew until afterwards, because no bar had been computed in
advance. GO criterion 3 now requires the live gap to clear a floor established *here*, before the
comparison is read.

**Two different questions, deliberately separated.**

1. :func:`null_gaps` — *what does a system with no skill produce?* The screen is replaced by random
   selection from the same universe, with the same sizing, cadence, costs and taxes. Everything
   about the machinery is held constant and only the *choosing* is destroyed, so the spread of
   (random − baseline) is what luck alone looks like. Its high percentile is the bar.
2. :func:`stationary_bootstrap_index` — *how much does the answer depend on the path history
   happened to take?* Resamples the return series in blocks, preserving fat tails and volatility
   clustering, both of which an i.i.d. draw destroys and both of which decide whether a strategy
   survives.

**Why not GBM.** Lognormal returns with constant volatility have no fat tails, no volatility
clustering and no regimes — precisely the features that matter. Simulating from GBM and tuning
against it fits a system to a market that does not exist. The stationary bootstrap keeps the
empirical distribution, which is the honest alternative.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import numpy as np

#: Politis–Romano expected block length, in trading days. ~1 month keeps volatility clustering and
#: momentum/reversal structure intact; much shorter degenerates toward i.i.d. and destroys both.
DEFAULT_MEAN_BLOCK = 20

#: The bar a live gap must clear. One-sided: the question is whether the system is *ahead* by more
#: than luck explains, not whether it differs in either direction.
DEFAULT_PERCENTILE = 95.0


def stationary_bootstrap_index(
    n: int, *, rng: np.random.Generator, mean_block: int = DEFAULT_MEAN_BLOCK
) -> np.ndarray:
    """Indices for one stationary-bootstrap resample of a length-``n`` series (Politis–Romano 1994).

    Blocks start at a uniformly random point and continue with probability ``1 − 1/mean_block``,
    wrapping at the end, so block lengths are Geometric with mean ``mean_block``. Wrapping is what
    makes the resample *stationary* — every observation is equally likely to appear at any position,
    with no edge effects to bias the tails.
    """
    if n <= 0:
        return np.empty(0, dtype=int)
    p = 1.0 / max(1, mean_block)
    out = np.empty(n, dtype=int)
    idx = int(rng.integers(0, n))
    for i in range(n):
        out[i] = idx
        # New block with probability p, else continue this one (wrapping) — Geometric lengths.
        idx = int(rng.integers(0, n)) if rng.random() < p else (idx + 1) % n
    return out


def noise_floor(
    gaps: Sequence[float] | Sequence[Decimal], *, percentile: float = DEFAULT_PERCENTILE
) -> Decimal:
    """The bar: the ``percentile`` of the no-skill gap distribution.

    A live gap **at or below** this is not a result — a system with no skill produces gaps this
    large at least ``100 − percentile``% of the time. Returned as ``Decimal`` because it is compared
    against rupees.
    """
    if not gaps:
        raise ValueError(
            "no null draws — a noise floor computed from nothing is worse than none, because it "
            "would let any gap through"
        )
    values = np.array([float(g) for g in gaps], dtype=float)
    return Decimal(str(round(float(np.percentile(values, percentile)), 2)))


def summarise_null(gaps: Sequence[float] | Sequence[Decimal]) -> str:
    """Human-readable shape of the null, so the floor is a finding rather than a magic number."""
    if not gaps:
        return "No null draws."
    v = np.array([float(g) for g in gaps], dtype=float)
    return (
        f"{len(v)} no-skill draws · median ₹{np.median(v):,.0f} · "
        f"p05 ₹{np.percentile(v, 5):,.0f} · p95 ₹{np.percentile(v, 95):,.0f} · "
        f"max ₹{v.max():,.0f}\n"
        f"A gap inside ±₹{np.percentile(v, 95):,.0f} is produced by luck alone at least 5% of the "
        "time, so it is not evidence."
    )


__all__ = [
    "DEFAULT_MEAN_BLOCK",
    "DEFAULT_PERCENTILE",
    "noise_floor",
    "stationary_bootstrap_index",
    "summarise_null",
]
