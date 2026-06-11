"""Allocation layer: covariance conditioning, sector allocator, portfolio optimizer.

The funnel's last two stages (Q_alpha.md §3.1): the sector allocator sets sector-weight
boundaries, then the portfolio optimizer finds exact stock weights within them. Both are convex
min-variance problems solved with scipy (the spec deliberately drops the C++/QUBO path for v1,
§3.3). All covariance inputs pass through Ledoit-Wolf + EWMA conditioning first (§3.8).
"""

from qalpha.alloc.conditioning import Covariance, conditioned_covariance
from qalpha.alloc.optimizer import optimize_weights
from qalpha.alloc.sectors import allocate_sectors

__all__ = ["Covariance", "allocate_sectors", "conditioned_covariance", "optimize_weights"]
