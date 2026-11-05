@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    where py >nul 2>&1
    if errorlevel 1 (
        python -m venv .venv
    ) else (
        py -3 -m venv .venv
    )
    if errorlevel 1 goto failed
    if exist ".venv\.shisha-installed-win" del ".venv\.shisha-installed-win"
)

".venv\Scripts\python.exe" -c "from pathlib import Path; import sys; marker = Path('.venv/.shisha-installed-win'); sys.exit(not marker.exists() or Path('pyproject.toml').stat().st_mtime > marker.stat().st_mtime)"
if errorlevel 1 (
    echo Installing project dependencies...
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 goto failed
    type nul > ".venv\.shisha-installed-win"
)

".venv\Scripts\python.exe" -m shisha %*
if errorlevel 1 goto failed
exit /b 0

:failed
echo Startup failed. See the output above for details.
pause
exit /b 1
