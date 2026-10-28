@echo off
setlocal
cd /d "%~dp0"

if not exist "..\..\salidas\exes" mkdir "..\..\salidas\exes"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

%PYTHON% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name CruzadorExcel-Windows ^
    --add-data "%CD%\data\migrations;data\migrations" ^
    --distpath build\windows ^
    --specpath build\windows ^
    --workpath build\windows\work ^
    main.py

if errorlevel 1 exit /b %errorlevel%

set "ISCC="
where ISCC >nul 2>nul && set "ISCC=ISCC"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo Error: no se encontro Inno Setup 6. Instale Inno Setup 6 o agregue ISCC.exe al PATH.
    exit /b 2
)

"%ISCC%" installer_windows.iss
if errorlevel 1 exit /b %errorlevel%

echo Instalador generado en ..\..\salidas\exes\CruzadorExcel-Setup.exe
