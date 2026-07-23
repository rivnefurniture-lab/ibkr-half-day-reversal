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
  echo Created .env and opened it in Notepad.
  echo Add your Databento API key, save the file, then double-click start.bat again.
  pause
  exit /b 0
)

set DASHBOARD_PORT=8765
for /f "tokens=1,* delims==" %%A in ('findstr /b "DASHBOARD_PORT=" .env') do set DASHBOARD_PORT=%%B

uv sync --extra dev
if errorlevel 1 (
  pause
  exit /b 1
)

start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:%DASHBOARD_PORT%"
uv run uvicorn halfreversal.app:app --host 127.0.0.1 --port %DASHBOARD_PORT%
endlocal
