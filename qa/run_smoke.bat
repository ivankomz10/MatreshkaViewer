@echo off
rem The quick set: a few tests from every part, listed in headless\smoke.txt,
rem for checking each step without waiting for the whole quiet suite. Like
rem run_quiet.bat it builds the window in its own process and takes neither
rem the mouse nor the keyboard.
rem
rem     run_smoke.bat              the quick set
rem     run_smoke.bat -x           stop at the first failure
cd /d "%~dp0headless"

set PY=..\..\tool\.venv\Scripts\python.exe
if not exist "%PY%" (
    echo No virtual environment at %PY%
    pause
    exit /b 1
)

"%PY%" -m pytest -m smoke %*
echo.
pause
