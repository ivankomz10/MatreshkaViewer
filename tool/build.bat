@echo off
rem Build a single executable and place it NEXT TO this folder, one level up.
rem The baked scene travels inside it; the HAP files are chosen at run time.
rem The spec does the building: --exclude-module only reaches Python modules,
rem and most of the weight is Qt DLLs that PySide6 ships regardless.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment missing. Run:  python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "baked\scene_mesh.npz" (
    echo No baked scene. Run this first:
    echo    blender -b ..\Prepare.blend --factory-startup -P bake_mesh.py -- baked
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m pip install --quiet --upgrade pyinstaller || goto :error

.venv\Scripts\pyinstaller.exe ^
    --noconfirm ^
    --distpath ".." ^
    --workpath "build" ^
    build.spec || goto :error

echo.
echo Built: %~dp0..\MatreshkaViewer.exe
pause
exit /b 0

:error
echo Build failed.
pause
exit /b 1
