"""Private-GitHub-gist persistence for a single text file (the cumulative tradebook master).

Streamlit Cloud has no durable local disk (a redeploy or cold-wake wipes it), and the user's **real**
trades must never go in the public repo — so the master is kept in a **private gist**. This is a thin,
stdlib-only (`urllib`), **fail-soft** wrapper: any missing token / network error returns ``None`` (or
``(None, msg)``) instead of raising, so the dashboard degrades to session-only rather than breaking.

Needs a token with the ``gist`` scope (a classic PAT, or a fine-grained token with gist read/write) in
the app's Streamlit secrets. The gist is created with ``public=False``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_API = "https://api.github.com/gists"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "qalpha-dashboard",
    }


def _select_gist(gists: list[dict[str, object]], filename: str) -> str | None:
    """Pick the most-recently-updated gist that contains ``filename``. Pure (testable)."""
    matches = []
    for g in gists:
        files = g.get("files")
        if isinstance(files, dict) and filename in files:
            matches.append(g)
    if not matches:
        return None
    matches.sort(key=lambda g: str(g.get("updated_at", "")), reverse=True)
    return str(matches[0]["id"])


def find_gist_id(token: str, filename: str) -> str | None:
    """Discover the id of the user's gist holding ``filename`` — so the **token alone** re-locates the
    saved master after a restart (no pinned id needed). ``None`` if none/unauthorised/error (fail-soft).
    """
    if not token:
        return None
    try:
        req = urllib.request.Request(f"{_API}?per_page=100", headers=_headers(token))
        with urllib.request.urlopen(req, timeout=10) as r:
            gists = json.load(r)
        return _select_gist(gists if isinstance(gists, list) else [], filename)
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def load_gist_file(token: str, gist_id: str, filename: str) -> str | None:
    """Return the content of ``filename`` in the private gist, or ``None`` (unset/missing/error)."""
    if not (token and gist_id):
        return None
    try:
        req = urllib.request.Request(f"{_API}/{gist_id}", headers=_headers(token))
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        file = data.get("files", {}).get(filename)
        if file and file.get("content") is not None:
            return str(file["content"])
        return None
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def save_gist_file(
    token: str, gist_id: str, filename: str, content: str, *, description: str = "Q-Alpha tradebook"
) -> tuple[str | None, str]:
    """Write ``content`` to ``filename`` in the gist, **creating a private gist** if ``gist_id`` is
    empty. Returns ``(gist_id, message)`` — ``gist_id`` is ``None`` on failure (fail-soft). When a gist
    is newly created, the returned id should be surfaced so the user can pin it in secrets and reuse it.
    """
    if not token:
        return None, "no gist token configured"
    files = {"files": {filename: {"content": content}}}
    try:
        if gist_id:
            req = urllib.request.Request(
                f"{_API}/{gist_id}",
                data=json.dumps(files).encode(),
                headers={**_headers(token), "Content-Type": "application/json"},
                method="PATCH",
            )
        else:
            body = {"description": description, "public": False, **files}
            req = urllib.request.Request(
                _API,
                data=json.dumps(body).encode(),
                headers={**_headers(token), "Content-Type": "application/json"},
                method="POST",
            )
        with urllib.request.urlopen(req, timeout=10) as r:
            return str(json.load(r)["id"]), "saved"
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        return None, str(exc)
