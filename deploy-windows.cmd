@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\deploy.ps1" %*
if errorlevel 1 (
  echo.
  echo 部署失败，请查看上方错误信息。
  pause
  exit /b 1
)
echo.
echo 部署完成。
pause
