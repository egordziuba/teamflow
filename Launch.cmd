@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" (
  "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m teamflow --help
) else (
  python -m teamflow --help
)
echo.
echo See README.md. Authentication is never started by this launcher.
pause
