@echo off
REM ============================================================================
REM  Q-Alpha (developer) — one click: WSL, the editor, and a terminal in the repo.
REM
REM  Use Q-Alpha.bat for the daily run. This one is for working ON the system:
REM  it opens VS Code attached to WSL at the repo, and leaves a shell there too.
REM ============================================================================

set DISTRO=Ubuntu
set REPO=/home/aarsh/q-alpha/Q_Alpha

where wsl >nul 2>&1 || (echo WSL is not installed. Run: wsl --install & pause & exit /b 1)
wsl -d %DISTRO% -e true >nul 2>&1 || (echo Could not start %DISTRO%. Check: wsl --list --verbose & pause & exit /b 1)

REM VS Code's WSL remote. `code` is on PATH once VS Code is installed with the
REM "Add to PATH" option; the WSL extension is what makes --remote work.
where code >nul 2>&1
if errorlevel 1 (
  echo VS Code's "code" command is not on PATH - skipping the editor.
  echo   In VS Code: Ctrl+Shift+P -^> "Shell Command: Install 'code' command in PATH"
) else (
  start "" code --remote wsl+%DISTRO% "%REPO%"
)

start "" wt -d \\wsl$\%DISTRO%%REPO% 2>nul || start "" wsl -d %DISTRO% --cd "%REPO%"
exit /b 0
