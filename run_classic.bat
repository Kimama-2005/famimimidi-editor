@echo off
rem Famimimidi editor (classic tkinter UI, kept as a fallback)
cd /d "%~dp0"
python -m famimimidi
if errorlevel 1 pause
