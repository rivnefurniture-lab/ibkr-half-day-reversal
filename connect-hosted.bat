@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo Install uv from https://docs.astral.sh/uv/getting-started/installation/ and run this file again.
  pause
  exit /b 1
)

if not exist .env (
  copy .env.example .env >nul
  start "" notepad .env
  echo Add the hosted URL, access key and Databento key, save, then run this file again.
  pause
  exit /b 0
)

findstr /b "HOSTED_DASHBOARD_URL=" .env >nul
if errorlevel 1 (
  start "" notepad .env
  echo HOSTED_DASHBOARD_URL and BRIDGE_TOKEN are required in .env.
  pause
  exit /b 1
)
findstr /b "BRIDGE_TOKEN=" .env >nul
if errorlevel 1 (
  start "" notepad .env
  echo HOSTED_DASHBOARD_URL and BRIDGE_TOKEN are required in .env.
  pause
  exit /b 1
)

uv sync --extra dev
if errorlevel 1 (
  pause
  exit /b 1
)

start "Half-Day local service" /min cmd /c "uv run uvicorn halfreversal.app:app --host 127.0.0.1 --port 8765"
for /f "tokens=1,* delims==" %%A in ('findstr /b "HOSTED_DASHBOARD_URL=" .env') do set HOSTED_DASHBOARD_URL=%%B
timeout /t 2 /nobreak >nul
start "" "%HOSTED_DASHBOARD_URL%"
uv run python -m halfreversal.bridge
endlocal
