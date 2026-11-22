@echo off
setlocal
cd /d "%~dp0.."
"local\wakeword26b\venv\Scripts\python.exe" "local\wakeword26b\prepare_b10_manifest.py"
if errorlevel 1 pause
