"""Authenticated Kite Connect client handle (Q_alpha.md §6).

The single entry point for any live-data or reporting code: returns a ``KiteConnect`` already
carrying today's access token, or raises with the exact command to re-login.
"""

from __future__ import annotations

from kiteconnect import KiteConnect

from qalpha.live.auth import get_access_token
from qalpha.live.credentials import load_credentials


def authenticated_kite(*, allow_stale: bool = False) -> KiteConnect:
    creds = load_credentials(require_secret=False)
    kite = KiteConnect(api_key=creds.api_key)
    kite.set_access_token(get_access_token(allow_stale=allow_stale))
    return kite
