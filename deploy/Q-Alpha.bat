@echo off
setlocal EnableDelayedExpansion
REM ============================================================================
REM  Q-Alpha — one click, from the Windows desktop.
REM
REM  DO NOT shortcut this file where it sits. It lives inside WSL's filesystem,
REM  at \\wsl$\<distro>\..., and that path only exists WHILE WSL IS RUNNING —
REM  while starting WSL is this file's entire job. A .lnk to it fails with
REM  "Missing Shortcut" on exactly the occasions you need it.
REM
REM  Run  ./deploy/install-windows.sh  from WSL instead. It copies this to the
REM  Windows side with your real distro and repo path baked in, and makes the
REM  shortcut. Then one double-click: WSL wakes, the pipeline runs, the page opens.
REM
REM  NOTHING HERE TRADES. It reads, it decides, it writes a page. Every order is
REM  placed by you, in Kite.
REM ============================================================================

set DISTRO=Ubuntu-24.04
set REPO=/home/aarsh/q-alpha/Q_Alpha

title Q-Alpha
echo.
echo   Q-Alpha - starting
echo   ------------------

REM --- 1. Is WSL even installed? A missing feature and a stopped distro are
REM ---    different problems and only one of them is fixed by waiting.
where wsl >nul 2>&1
if errorlevel 1 (
  echo   [X] WSL is not installed on this machine.
  echo       Open PowerShell as Administrator and run:  wsl --install
  goto :fail
)

REM --- 2. Wake the distro. `wsl -d X true` starts it if it is not running;
REM ---    doing this first means the real run's errors are about the run.
echo   [1/3] waking %DISTRO%...
wsl -d %DISTRO% -e true >nul 2>&1
if errorlevel 1 (
  echo   [X] Could not start the "%DISTRO%" distro.
  echo       Check the name with:  wsl --list --verbose
  echo       Then edit DISTRO at the top of this file to match.
  goto :fail
)

REM --- 3. Is the repo where this file says it is? Failing here with a clear
REM ---    message beats failing inside Python with a traceback.
wsl -d %DISTRO% -e test -f "%REPO%/scripts/local_run.py"
if errorlevel 1 (
  echo   [X] No Q-Alpha at %REPO% inside WSL.
  echo       Edit REPO at the top of this file to your checkout path.
  goto :fail
)

echo   [2/3] running the pipeline...
echo.
REM The app: buttons, live progress, the Kite login, token status. It serves on loopback inside
REM WSL and Windows can reach it at the same address, so the browser opens on this side.
start "" http://127.0.0.1:8787/
wsl -d %DISTRO% -e bash -lc "cd '%REPO%' && ./qalpha.sh --app --no-open --port 8787"
set RUN_RC=%errorlevel%
echo.

REM --- 4. The app runs until you close this window; the browser was opened above.
if not "%RUN_RC%"=="0" (
  echo.
  echo   The run reported a problem ^(exit %RUN_RC%^). The page above, if it
  echo   opened, says what it could and could not check. Nothing was traded.
  goto :fail
)

echo.
echo   Done. Nothing was traded; you place every order in Kite.
timeout /t 3 >nul
exit /b 0

:fail
echo.
pause
exit /b 1
