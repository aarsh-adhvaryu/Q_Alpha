@echo off
setlocal EnableDelayedExpansion
REM ============================================================================
REM  Q-Alpha - one click, natively on Windows. THE CLICK RUNS THE EVENING.
REM
REM  It used to start a server and nothing else, over whatever page the last run had left --
REM  so a click showed an empty account under yesterday's date while OPERATING.md said it
REM  'runs on this machine, writes one page, and opens it'. Reading that as broken was the
REM  correct reading. --autorun starts the evening as the app's first job.
REM
REM  This file sits in the repo and the desktop shortcut points straight at it.
REM  No copy step, no path baked in, no install script.
REM
REM  The version this replaced could not work that way. It lived inside WSL's
REM  filesystem at \\wsl$\<distro>\..., a path that only exists WHILE WSL IS
REM  RUNNING - while starting WSL was that file's entire job. So it had to be
REM  copied out to the Windows side with the distro and repo path baked in, by
REM  a script that had to be re-run whenever either changed. All of that was
REM  scaffolding around living in the wrong filesystem, and moving to D:\ took
REM  it with it. %~dp0 is this file's own folder, which is the repo.
REM
REM  NOTHING HERE TRADES. It reads, it decides, it shows you a page. Every order
REM  is placed by you, in Kite.
REM ============================================================================

cd /d "%~dp0"
set PORT=8787
set URL=http://127.0.0.1:%PORT%/

title Q-Alpha
echo.
echo   Q-Alpha
echo   -------
echo.

REM --- 0. Already running? A second double-click should open the page, not
REM ---    fight the first one for the port.
powershell -NoProfile -Command "try{ Invoke-WebRequest -Uri '%URL%' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  echo   Q-Alpha is already running. Opening it.
  start "" %URL%
  ping -n 3 127.0.0.1 >nul
  exit /b 0
)

REM --- 1. uv. Installed per-user, so it is often not on PATH in a fresh shell.
set "UV=uv"
where uv >nul 2>&1
if errorlevel 1 (
  if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV=%USERPROFILE%\.local\bin\uv.exe"
  ) else (
    echo   [X] uv is not installed.
    echo       In PowerShell:  irm https://astral.sh/uv/install.ps1 ^| iex
    goto :fail
  )
)

REM --- 2. Is this actually the repo? Failing here with a sentence beats
REM ---    failing inside Python with a traceback.
if not exist "scripts\local_run.py" (
  echo   [X] No scripts\local_run.py in %CD%.
  echo       This file must stay in the repo folder; the shortcut points at it.
  goto :fail
)

echo   [1/3] preparing the tools (fast unless something changed)...

REM --- 3. The toolchain, once. A bare `uv run` resolves against the base dependencies and
REM ---    UNINSTALLS the 23 dev packages on every double-click, then a later `uv sync
REM ---    --extra dev` puts them back: minutes of churn inside the window the browser is
REM ---    waiting on. --frozen uses the lockfile as it stands and needs no network.
"%UV%" sync --frozen --extra dev
if errorlevel 1 (
  echo   [X] uv could not prepare the environment ^(see the error above^).
  echo       Nothing was run. If you are offline, try again on a connection.
  goto :fail
)
set UV_NO_SYNC=1

REM --- 4. Open the browser only once the server actually answers. Opening it
REM ---    first shows a connection error on every cold start, and people learn
REM ---    to reload rather than to read the page. The window is NOT hidden:
REM ---    `start /b` shares this console, so -WindowStyle Hidden was asking to
REM ---    hide the very window the next line tells you to leave open.
echo   [2/3] starting the app...
start "" /b powershell -NoProfile -Command "$u='%URL%'; for($i=0;$i -lt 600;$i++){ try{ Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 1 | Out-Null; Start-Process $u; exit } catch { Start-Sleep -Seconds 1 } }; Write-Host ('  Q-Alpha did not answer at ' + $u + ' within 10 minutes. If there is an error above, read it; otherwise open that address yourself.')"

echo   [3/3] Q-Alpha is at %URL%
echo.
echo   Leave this window open - it IS the app. Closing it stops the server.
echo   The evening starts by itself; the page follows it and reloads when it is done.
echo   Press the buttons on the page; this window is where the work happens.
echo.
"%UV%" run python scripts/local_run.py --app --autorun --no-open --port %PORT%
set RUN_RC=%errorlevel%

if not "%RUN_RC%"=="0" (
  echo.
  echo   The app exited with %RUN_RC%. Nothing was traded.
  goto :fail
)
echo.
echo   Stopped. Nothing was traded; you place every order in Kite.
ping -n 4 127.0.0.1 >nul
exit /b 0

:fail
echo.
pause
exit /b 1
