"""Secrets, loaded from the gitignored ``.env`` at the repo root.

Secrets never live in code or ``config.py``: they come from environment variables, hydrated from a
local ``.env`` by python-dotenv.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# live/credentials.py -> live -> qalpha -> src -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]

_ENV_LOADED = False


def load_env() -> None:
    """Load ``<repo>/.env`` into the process once. Harmless (and silent) if the file is absent.

    **Anything that reads a QALPHA_* or ANTHROPIC_* variable must call this first.** It used to be
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
