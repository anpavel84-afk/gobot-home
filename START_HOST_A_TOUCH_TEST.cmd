@echo off
setlocal
chcp 65001 >nul
set "HOST_A_ROOT=%~dp0"
set "PLAN_PY=%HOST_A_ROOT%..\GoBotHome\.venv\Scripts\python.exe"
if not exist "%PLAN_PY%" (
  echo Python for GoBot PLAN is missing. No test was started.
  pause
  exit /b 3
)
echo ==============================================================
echo HOST-A RC1 -- hardware touch and Russian local time trial
echo Installed firmware is NOT changed; no paid providers are used.
echo Stand next to Spotpear. Verify microphone and speaker yourself.
echo Type ДА at the prompt only when physically present.
echo The session ends automatically and returns to LOCAL mode.
echo ==============================================================
"%PLAN_PY%" -u "%HOST_A_ROOT%tools\host_rc1_human_trial.py" --run
set "RESULT=%ERRORLEVEL%"
echo.
echo HOST-A trial returned status %RESULT%.
echo See private run\host-a for numeric report; no speech recording.
pause
exit /b %RESULT%
