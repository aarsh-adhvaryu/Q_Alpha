#!/usr/bin/env bash
# Q-Alpha — one click. Runs the local pipeline and opens the page it writes.
#
# Put a shortcut to this on your desktop. On Windows, use deploy/Q-Alpha.bat instead, which
# calls into WSL and then opens the same file in your Windows browser.
#
# Nothing here trades. It reads, it decides, it writes a page. You place every order in Kite.
set -euo pipefail
cd "$(dirname "$0")"
# No arguments -> the app (buttons, live progress, Kite login). `--no-open` and friends still
# reach the one-shot run, which is what the Windows launcher and any cron would use.
if [ "$#" -eq 0 ]; then
  exec uv run python scripts/local_run.py --app
fi
exec uv run python scripts/local_run.py "$@"
