"""Regime track — bubble / crash detection.

Held to the Q-Alpha iron rule (see ``PREREGISTRATION.md``): any usefulness claim must clear a bar
fixed *before* results, and must ultimately beat "always deploy" net of cost + tax. Wired to a
**deploy throttle + human alert only — never auto-sell** (selling realises tax; the asymmetry is the
whole point).

- ``lppls`` — Log-Periodic Power Law Singularity (Sornette): the principled *bubble* detector.
"""

from research.regime.lppls import (
    LPPLSFit,
    confidence_indicator,
    fit_lppls,
    lppls_filter_ok,
)

__all__ = ["LPPLSFit", "confidence_indicator", "fit_lppls", "lppls_filter_ok"]
