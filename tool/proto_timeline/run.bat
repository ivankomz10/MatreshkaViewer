@echo off
rem PROTOTYPE -- throwaway. Three timelines to choose between.
rem
rem     run.bat              opens on variant A
rem     run.bat --variant=C  opens on C
rem
rem Switch with the yellow bar at the bottom, or the Left and Right arrows.
rem Nothing is ever written back to the show files.
cd /d "%~dp0"

set PY=..\.venv\Scripts\python.exe
if not exist "%PY%" (
    echo No virtual environment at %PY%
    pause
    exit /b 1
)
"%PY%" proto.py %*
