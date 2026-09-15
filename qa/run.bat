@echo off
rem Run the tests against the built executable.
rem
rem They drive the real window with the real mouse and the real keyboard, so
rem while they run this machine is theirs: do not type, and do not click.
rem Nothing outside qa\sandbox is touched, and a viewer open elsewhere on
rem this machine is left alone.
rem
rem     run.bat                    everything
rem     run.bat test_flat.py       one file
rem     run.bat -k rebake          whatever matches
cd /d "%~dp0"

set PY=..\tool\.venv\Scripts\python.exe
if not exist "%PY%" (
    echo No virtual environment at %PY%
    echo Make one:  python -m venv ..\tool\.venv ^&^& ..\tool\.venv\Scripts\pip install -r ..\tool\requirements.txt comtypes pillow pytest
    pause
    exit /b 1
)

if not exist "..\MatreshkaViewer.exe" (
    echo Nothing built. Run ..\tool\build.bat first.
    pause
    exit /b 1
)

"%PY%" -m pytest %*
echo.
pause
