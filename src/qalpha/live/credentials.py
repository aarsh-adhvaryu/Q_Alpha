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


def _ensure_env_loaded() -> None:
    """Load ``<repo>/.env`` once. Harmless (and silent) if the file is absent."""
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
    _ensure_env_loaded()
    api_key = os.environ.get("KITE_API_KEY", "").strip()
    api_secret = os.environ.get("KITE_API_SECRET", "").strip()
    access_token = os.environ.get("KITE_ACCESS_TOKEN", "").strip() or None
    if not api_key:
        raise RuntimeError("KITE_API_KEY is not set (copy .env.example to .env and fill it in).")
    if require_secret and not api_secret:
        raise RuntimeError("KITE_API_SECRET is not set (copy .env.example to .env and fill it in).")
    return KiteCredentials(api_key=api_key, api_secret=api_secret, access_token=access_token)
