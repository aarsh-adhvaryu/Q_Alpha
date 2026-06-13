"""Live broker layer: Kite Connect (Zerodha) auth + authenticated client (Q_alpha.md §6).

Distinct from the backtest/data layers: this is the only code that talks to the live broker. The
backtest never imports it. Secrets come from the gitignored ``.env`` via :mod:`qalpha.live.credentials`.
"""

from qalpha.live.client import authenticated_kite
from qalpha.live.credentials import KiteCredentials, load_credentials

__all__ = ["KiteCredentials", "authenticated_kite", "load_credentials"]
