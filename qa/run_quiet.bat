@echo off
rem The quiet tests: they build the window inside their own process and call
rem what the buttons call. They do NOT take the mouse or the keyboard, so this
rem is the one to run while you are working.
rem
rem They run the source in ..\tool rather than the built .exe, so they cannot
rem notice anything the build does to it. For that, run.bat.
rem
rem     run_quiet.bat                  everything
rem     run_quiet.bat -k snapshot      whatever matches
cd /d "%~dp0headless"

set PY=..\..\tool\.venv\Scripts\python.exe
if not exist "%PY%" (
    echo No virtual environment at %PY%
    pause
    exit /b 1
)

"%PY%" -m pytest %*
echo.
pause
