@echo off
setlocal EnableDelayedExpansion
REM ============================================================================
REM  Q-Alpha - one click, from the Windows desktop.
REM
REM  DO NOT shortcut this file where it sits. It lives inside WSL's filesystem,
REM  at \\wsl$\<distro>\..., and that path only exists WHILE WSL IS RUNNING -
REM  while starting WSL is this file's entire job. A .lnk to it fails with
REM  "Missing Shortcut" on exactly the occasions you need it.
REM
REM  Run  ./deploy/install-windows.sh  from WSL instead. It copies this to the
REM  Windows side with your real distro and repo path baked in, and makes the
REM  shortcut. Then one double-click: WSL wakes, the app starts, the page opens.
REM
REM  NOTHING HERE TRADES. It reads, it decides, it shows you a page. Every order
REM  is placed by you, in Kite.
REM ============================================================================

set DISTRO=Ubuntu-24.04
set REPO=/home/aarsh/q-alpha/Q_Alpha
set PORT=8787
set URL=http://127.0.0.1:%PORT%/

title Q-Alpha
echo.
echo   Q-Alpha
echo   -------
echo.

REM --- 0. Already running? Then this is a second double-click, not a start.
REM ---    Binding the port again would fail with a traceback about an address
REM ---    in use, which says nothing about what is actually going on.
powershell -NoProfile -Command "try{Invoke-WebRequest -Uri '%URL%' -UseBasicParsing -TimeoutSec 2|Out-Null;exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
  echo   Q-Alpha is already running. Opening it.
  start "" %URL%
  ping -n 3 127.0.0.1 >nul
  exit /b 0
)

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

REM --- 4. Open the browser ONLY ONCE THE APP ANSWERS. This used to fire before
REM ---    the server existed, so a cold start - WSL waking, uv resolving, pandas
REM ---    importing - showed a connection error. "Not up yet" and "broken" look
REM ---    identical in a browser, and the first one is what you always saw.
REM ---    The waiter runs beside the server and gives up after 120s rather than
REM ---    hanging forever with nothing on screen.
echo   [2/3] starting the app...
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$u='%URL%'; for($i=0;$i -lt 120;$i++){ try{ Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 1 | Out-Null; Start-Process $u; exit } catch { Start-Sleep -Seconds 1 } }"

echo   [3/3] Q-Alpha is at %URL%
echo.
echo   Leave this window open - it IS the app. Closing it stops the server.
echo   Press the buttons on the page; this window is where the work happens.
echo.
wsl -d %DISTRO% -e bash -lc "cd '%REPO%' && ./qalpha.sh --app --no-open --port %PORT%"
set RUN_RC=%errorlevel%

REM Ctrl-C and closing the browser both end up here with a non-zero code on some
REM shells, so this does not call a normal stop a failure. A real crash prints
REM its traceback above, which is more use than anything this line could add.
echo.
if not "%RUN_RC%"=="0" (
  echo   Q-Alpha stopped ^(exit %RUN_RC%^). If that was not you, the output above
  echo   says why. Nothing was traded either way.
  goto :fail
)
echo   Q-Alpha stopped. Nothing was traded; you place every order in Kite.
ping -n 4 127.0.0.1 >nul
exit /b 0

:fail
echo.
pause
exit /b 1
