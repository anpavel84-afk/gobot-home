@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
if not exist "%ROOT%run\host-a\monika-live\owner.lock" (
  echo Monika stand is not running.
  pause
  exit /b 0
)
> "%ROOT%run\host-a\monika-live\STOP" echo OWNER_STOP
echo Stop requested. The current COM3 owner will send HOST_OFF and release COM3.
echo This does not stop production Brain, reflash the board, or alter NVS.
pause
