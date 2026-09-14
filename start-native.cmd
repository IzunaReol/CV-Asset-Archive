@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-native.ps1"
echo.
if errorlevel 1 (
  echo Startup failed. See the message above.
) else (
  echo The system is ready at http://localhost:5173
)
pause
