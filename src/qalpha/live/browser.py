"""Opening a URL from here, where "here" is often WSL and the browser is on Windows.

### The failure this exists for

Pressing **Log in to Zerodha** printed::

    gio: https://kite.zerodha.com/connect/login?v=3&api_key=…: Operation not supported

``webbrowser.open`` asks the desktop for its default handler. Inside WSL there is no desktop and no
handler, so it fails — and it fails *silently as far as the app is concerned*, because
``webbrowser.open`` returns ``False`` and nothing was checking. The user is left looking at a page
that says it opened Kite, and at a terminal error that names a program they have never heard of.

Windows, one process away, has a perfectly good browser.

### What it tries, and why in this order

1. **``wslview``** (from the ``wslu`` package) if it is installed — it is the tool built for exactly
   this and it handles quoting, file paths and UNC translation properly.
2. **``powershell.exe Start-Process``** — present on every WSL install by definition, since WSL runs
   on Windows. The URL is passed as a single-quoted PowerShell string, so the ``&`` in
   ``?v=3&api_key=…`` cannot be read as a command separator. That ``&`` is why this is not
   ``cmd.exe /c start``, where it would truncate the URL at the first parameter.
3. **``webbrowser``** — the normal path, which is right on a real Linux desktop or a Mac.

### It returns whether it worked

Every caller must be able to say "I could not open your browser, here is the link" rather than
claiming to have opened something. A login flow that thinks it opened Kite and did not leaves the
user waiting for a redirect that will never come.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

#: How long to wait on the helper. Launching a browser returns immediately; anything that hangs
#: past this is a broken interop layer, and blocking the app on it helps nobody.
TIMEOUT_SECONDS = 20.0


def is_wsl() -> bool:
    """True inside WSL. Checks the kernel string as well as the env var, because a service or a
    stripped shell may not carry ``WSL_DISTRO_NAME``."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _run(argv: list[str]) -> bool:
    try:
        done = subprocess.run(
            argv,
            timeout=TIMEOUT_SECONDS,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def open_url(url: str) -> bool:
    """Open ``url`` in the user's actual browser. ``False`` when nothing could.

    A local file must be passed as a ``file://`` URI, not a path: Windows cannot follow a Linux
    path, and the caller knows which it has.
    """
    if is_wsl():
        wslview = shutil.which("wslview")
        if wslview and _run([wslview, url]):
            return True
        # Single-quoted so the `&` in a Kite login URL stays part of the URL. Doubling any embedded
        # apostrophe is PowerShell's own escape for a single-quoted string.
        quoted = url.replace("'", "''")
        if _run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"Start-Process '{quoted}'",
            ]
        ):
            return True

    import webbrowser

    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def describe_failure(url: str) -> str:
    """What to tell someone whose browser did not open. The link, and how to make it work."""
    extra = (
        " (installing `wslu` gives WSL a browser command: sudo apt install wslu)"
        if is_wsl()
        else ""
    )
    return f"Could not open a browser here{extra}. Open this yourself:\n{url}"
