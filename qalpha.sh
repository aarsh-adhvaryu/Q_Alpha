#!/usr/bin/env bash
# Q-Alpha — one click. Runs the local pipeline and opens the page it writes.
#
# Put a shortcut to this on your desktop. On Windows, use deploy/Q-Alpha.bat instead, which
# calls into WSL and then opens the same file in your Windows browser.
#
# Nothing here trades. It reads, it decides, it writes a page. You place every order in Kite.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run python scripts/local_run.py "$@"
