@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul || (echo Python 3.12 ou plus recent est requis. Installez-le puis relancez ce fichier.& pause & exit /b 1)
if not exist .venv py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist config.json copy config.example.json config.json
if not exist assets mkdir assets
echo.
echo Installation terminee. Lancez start.bat puis ouvrez http://127.0.0.1:8765
echo Pour activer le planning, executez ensuite scripts\register_tasks.ps1 dans PowerShell.
pause
