@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
echo Teamflow read-only observer. This does not start agents or retry tasks.
if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" (
  "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m teamflow.dashboard --open
) else (
  python -m teamflow.dashboard --open
)
if errorlevel 1 pause
