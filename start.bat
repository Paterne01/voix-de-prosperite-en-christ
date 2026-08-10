@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
start "Voix de Prosperite" http://127.0.0.1:8765
python app.py
