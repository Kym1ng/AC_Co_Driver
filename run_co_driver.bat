@echo off
setlocal

rem AI Co-Driver launcher: starts sniffer + debug_sub in two consoles.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python venv not found at .venv\Scripts\python.exe
  echo Please create it first:
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

set "PYTHON=.venv\Scripts\python.exe"

echo Starting sniffer (telemetry publisher) in its own window...
start "AC Co-Driver - Sniffer" cmd /k ""%PYTHON%" sniffer.py"

echo Starting debug subscriber (raw telemetry viewer) in its own window...
start "AC Co-Driver - DebugSub" cmd /k ""%PYTHON%" debug_sub.py"

echo.
echo All processes started.
echo - Make sure Assetto Corsa is running and you are on track.
echo - Close the 'AC Co-Driver - Sniffer' and 'AC Co-Driver - DebugSub' windows with Ctrl+C when done.
pause

endlocal

