@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
echo Explicit sign-in to the isolated Teamflow Hermes home.
if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" (
  "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m teamflow auth
) else (
  python -m teamflow auth
)
pause
