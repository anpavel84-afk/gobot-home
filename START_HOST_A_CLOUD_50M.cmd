@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "ROOT=%~dp0"
echo GoBot HOST-A: Owner-authorized Cloud STT pilot, Spotpear microphone.
echo Finite 180s hardware trial. Cloud only after accepted local "Monika".
echo Shared Owner budget: max 50 total reserved minutes, local estimate max USD 3.
echo Each cloud turn capped at 30s. No GPT-Live prewarm, no paid Brain.
echo No production changes, firmware writes, audio files or transcripts saved.
echo Before starting, ensure no other HOST-A pilot owns COM3 or port 18799.
set /p CONSENT=Type YES-HOST-A-CLOUD-50M: 
if /I not "%CONSENT%"=="YES-HOST-A-CLOUD-50M" (
  echo Not authorized. Nothing started.
  pause
  exit /b 1
)
"%ROOT%..\GoBotHome\.venv\Scripts\python.exe" -u "%ROOT%tools\host_a_paid_time_trial.py" --owner-cloud-grant-50m --seconds 180
echo Pilot ended; check status on PLAN. Do not auto-repeat.
pause
