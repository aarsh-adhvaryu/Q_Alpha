#!/usr/bin/env bash
# Install the Q-Alpha desktop shortcut on Windows. Run this from inside WSL:
#
#     ./deploy/install-windows.sh
#
# ### Why an installer, rather than "make a shortcut to deploy/Q-Alpha.bat"
#
# That was the first instruction and it produced "Missing Shortcut". The launcher lived inside WSL's
# own filesystem, at \\wsl$\<distro>\..., and **that path only exists while WSL is running** — while
# starting WSL is the launcher's entire job. Windows could not reach the file it needed in order to
# wake the thing the file lives on.
#
# So the launcher is COPIED to the Windows side, where it is always reachable, with this machine's
# real distro name and repo path written into it. Nothing is guessed: both are read from the running
# environment, not assumed.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_LINUX="$(pwd)"

DISTRO="${WSL_DISTRO_NAME:-}"
if [ -z "$DISTRO" ]; then
  echo "Not running inside WSL (WSL_DISTRO_NAME is unset). Run this from your WSL shell." >&2
  exit 1
fi

WIN_USER="$(/mnt/c/Windows/System32/cmd.exe /c "echo %USERNAME%" 2>/dev/null | tr -d '\r\n')"
if [ -z "$WIN_USER" ] || [ ! -d "/mnt/c/Users/$WIN_USER" ]; then
  echo "Could not find your Windows user directory (got '$WIN_USER')." >&2
  exit 1
fi
WIN_HOME="/mnt/c/Users/$WIN_USER"
INSTALL_DIR="$WIN_HOME/Q-Alpha"
DESKTOP="$WIN_HOME/Desktop"
[ -d "$DESKTOP" ] || DESKTOP="$WIN_HOME/OneDrive/Desktop"
if [ ! -d "$DESKTOP" ]; then
  echo "Could not find your Desktop under $WIN_HOME." >&2
  exit 1
fi

echo "  distro   $DISTRO"
echo "  repo     $REPO_LINUX"
echo "  install  $INSTALL_DIR"
echo "  desktop  $DESKTOP"
echo

mkdir -p "$INSTALL_DIR"
for name in Q-Alpha Q-Alpha-dev; do
  # Bake this machine's values in, so the copy on the Windows side needs no editing and cannot
  # drift from the checkout it launches.
  sed -e "s|^set DISTRO=.*|set DISTRO=$DISTRO|" \
      -e "s|^set REPO=.*|set REPO=$REPO_LINUX|" \
      "deploy/$name.bat" > "$INSTALL_DIR/$name.bat"
  printf '  wrote %s.bat\n' "$name"
done

# The shortcut targets the WINDOWS copy. A .lnk to \\wsl$\... is unreachable whenever WSL is
# stopped, which is exactly when you need the launcher most.
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command "
  \$ws = New-Object -ComObject WScript.Shell
  foreach (\$n in @('Q-Alpha','Q-Alpha-dev')) {
    \$lnk = \$ws.CreateShortcut(\"\$env:USERPROFILE\Desktop\\\$n.lnk\")
    \$lnk.TargetPath = \"\$env:USERPROFILE\Q-Alpha\\\$n.bat\"
    \$lnk.WorkingDirectory = \"\$env:USERPROFILE\Q-Alpha\"
    \$lnk.Description = 'Q-Alpha - run and open today''s page. Places no orders.'
    \$lnk.Save()
  }
" >/dev/null 2>&1 || {
  echo
  echo "  Could not create the shortcut automatically. The launchers are installed; make the"
  echo "  shortcut by hand: open $INSTALL_DIR in Explorer, right-click Q-Alpha.bat,"
  echo "  Send to -> Desktop (create shortcut)."
  exit 0
}

echo
echo "  Done. Double-click Q-Alpha on your desktop."
echo "  Re-run this after moving the repo or changing distro; nothing here is hard-coded."
