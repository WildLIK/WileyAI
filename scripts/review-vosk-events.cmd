@echo off
setlocal
cd /d "%~dp0.."
"local\wakeword26b\venv\Scripts\python.exe" "local\wakeword26b\review_b10_vosk.py"
if errorlevel 1 pause
