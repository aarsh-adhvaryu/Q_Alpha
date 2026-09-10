@echo off
setlocal EnableDelayedExpansion
REM ============================================================================
REM  Q-Alpha — one click, from the Windows desktop.
REM
REM  Right-click this file -> Send to -> Desktop (create shortcut). Then one
REM  double-click: it starts WSL if it is asleep, runs the pipeline inside it,
REM  and opens the page it wrote in your Windows browser.
REM
REM  NOTHING HERE TRADES. It reads, it decides, it writes a page. Every order is
REM  placed by you, in Kite.
REM ============================================================================

set DISTRO=Ubuntu
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
wsl -d %DISTRO% -e bash -lc "cd '%REPO%' && ./qalpha.sh --no-open"
set RUN_RC=%errorlevel%
echo.

REM --- 4. Open the page even if the run reported a problem. A page that says
REM ---    what went wrong is more useful than a console that closed.
for /f "delims=" %%p in ('wsl -d %DISTRO% -e wslpath -w "%REPO%/data/session/qalpha.html" 2^>nul') do set PAGE=%%p
if defined PAGE (
  if exist "!PAGE!" (
    echo   [3/3] opening the page...
    start "" "!PAGE!"
  )
)

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
