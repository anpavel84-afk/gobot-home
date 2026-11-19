@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "ROOT=%~dp0"
echo Spotpear microphone live OFFLINE Vosk dictation. No computer mic.
echo No audio or transcript files, no paid calls, no firmware changes.
echo This test owns HOST-A port 18799 and COM3. STOP_MONIKA.cmd first.
echo Type YES-SPOTPEAR-MIC to confirm recording-free live analysis.
set /p CONSENT=Consent: 
if /I not "%CONSENT%"=="YES-SPOTPEAR-MIC" (
  echo Consent not given - exiting.
  pause
  exit /b 1
)
"%ROOT%..\GoBotHome\.venv\Scripts\python.exe" -u "%ROOT%tools\host_spotpear_dictation.py" --owner-approved-mic --seconds 600
echo Done; device returned to LOCAL if serial permits.
pause
