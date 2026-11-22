@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (
  echo Python environment .venv not found.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "scripts\review_wake_annotations.py"
