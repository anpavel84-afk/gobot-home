@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "ROOT=%~dp0"
echo Monika -- real Spotpear / isolated free HOST, maximum two hours.
echo No computer microphone, paid sessions, or firmware writes.
echo Use STOP_MONIKA.cmd to return the device to LOCAL.
"%ROOT%..\GoBotHome\.venv\Scripts\python.exe" -u "%ROOT%tools\host_monika_live.py" --owner-direct-monika --seconds 7200
pause
