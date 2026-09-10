"""Kite Connect (Zerodha) credentials, loaded from the gitignored ``.env`` (Q_alpha.md §6).

Secrets never live in code or ``config.py`` — they come from environment variables, optionally
hydrated from a local ``.env`` by python-dotenv. See ``.env.example`` for the shape. The access
token is *not* stored here long-term; it is minted daily by :mod:`qalpha.live.auth`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# live/credentials.py -> live -> qalpha -> src -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]

_ENV_LOADED = False


def load_env() -> None:
    """Load ``<repo>/.env`` into the process once. Harmless (and silent) if the file is absent.

    **Anything that reads a QALPHA_* or KITE_* variable must call this first.** It used to be
    private and called only from :func:`load_credentials`, so a surface that read ``os.environ``
    directly saw whatever the shell happened to export — nothing, when launched from a shortcut.
    The app's own reader panel then said *"QALPHA_LOCAL_MODEL is unset"* and told the user to go
    and set a variable they had already set, while a run moments later read it correctly because
    the run touches the broker and the broker loads credentials. Two surfaces, one fact, different
    answers depending on what else had happened to run first.
    """
    global _ENV_LOADED
    if not _ENV_LOADED:
        load_dotenv(REPO_ROOT / ".env")
        _ENV_LOADED = True


@dataclass(frozen=True)
class KiteCredentials:
    api_key: str
    api_secret: str
    access_token: str | None = None

    @property
    def has_session(self) -> bool:
        return bool(self.access_token)


def load_credentials(*, require_secret: bool = True) -> KiteCredentials:
    """Read Kite app credentials from the environment (``.env`` hydrated automatically).

    ``require_secret=False`` is for read paths that only need the api_key plus an already-minted
    access token (the secret is only used at login time to exchange the request_token).
    """
    load_env()
    api_key = os.environ.get("KITE_API_KEY", "").strip()
    api_secret = os.environ.get("KITE_API_SECRET", "").strip()
    access_token = os.environ.get("KITE_ACCESS_TOKEN", "").strip() or None
    if not api_key:
        raise RuntimeError("KITE_API_KEY is not set (copy .env.example to .env and fill it in).")
    if require_secret and not api_secret:
        raise RuntimeError("KITE_API_SECRET is not set (copy .env.example to .env and fill it in).")
    return KiteCredentials(api_key=api_key, api_secret=api_secret, access_token=access_token)
