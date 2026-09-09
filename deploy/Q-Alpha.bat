@echo off
REM Q-Alpha — double-click this from the Windows desktop.
REM
REM It runs the pipeline inside WSL and opens the page it writes in your Windows browser.
REM Edit DISTRO and REPO below if yours differ, then put a shortcut to this file on the desktop.
REM
REM Nothing here trades. You place every order in Kite.

set DISTRO=Ubuntu
set REPO=/home/aarsh/q-alpha/Q_Alpha

echo Running Q-Alpha...
wsl -d %DISTRO% -e bash -lc "cd %REPO% && uv run python scripts/local_run.py --no-open"
if errorlevel 1 (
  echo.
  echo The run failed. The message above says why; nothing was traded either way.
  pause
  exit /b 1
)

REM Open the page it just wrote, translating the WSL path to a Windows one.
for /f "delims=" %%p in ('wsl -d %DISTRO% -e wslpath -w "%REPO%/data/session/qalpha.html"') do set PAGE=%%p
start "" "%PAGE%"
