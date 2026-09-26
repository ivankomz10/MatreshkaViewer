@echo off
rem PROTOTYPE -- throwaway. The timeline, on the real shows.
rem
rem Nothing is ever written back to the show files.
cd /d "%~dp0"

set PY=..\.venv\Scripts\python.exe
if not exist "%PY%" (
    echo No virtual environment at %PY%
    pause
    exit /b 1
)
"%PY%" proto.py %*
