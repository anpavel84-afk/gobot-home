@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "ROOT=%~dp0"
echo.
echo =======================================================
echo GoBot HOST-A / Browser Voice Lab (PLAN)
echo Browser URL: http://127.0.0.1:18811/
echo Browser microphone -> shared local Monika Vosk, MOCK STT.
echo Cloud API/paid sessions disabled, Spotpear and COM3 free.
echo Stop: Ctrl+C in this window.
echo =======================================================
echo.
if not exist "%ROOT%..\GoBotHome\.venv\Scripts\python.exe" (
 echo Main PLAN Python venv missing. Cannot start Browser Lab.
 pause
 exit /b 1
)
"%ROOT%..\GoBotHome\.venv\Scripts\python.exe" -u "%ROOT%tools\host_a_browser_voice_lab.py"
echo Browser Lab stopped. Check the console for errors.
pause
