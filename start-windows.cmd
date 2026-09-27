@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start.ps1" -SkipBuild %*
if errorlevel 1 (
  echo.
  echo 启动失败，请先运行 deploy-windows.cmd 或查看上方错误信息。
  pause
  exit /b 1
)
echo.
echo 启动完成。
pause
