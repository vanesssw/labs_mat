@echo off
rem Zapusk graficheskogo interfeisa arhivatora LR2 (dvoinoi shchelchok po etomu failu)
cd /d "%~dp0"
python gui.py
if errorlevel 1 pause
