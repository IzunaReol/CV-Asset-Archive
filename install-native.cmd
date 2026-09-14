@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-native.ps1"
echo.
if errorlevel 1 (
  echo Installation failed. See the message above.
) else (
  echo Installation completed. Run start-native.cmd to start the system.
)
pause
