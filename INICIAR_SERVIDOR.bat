@echo off
setlocal
cd /d "%~dp0"
title Infraestructura Empresa Demo v22
where py >nul 2>&1
if %errorlevel%==0 (
  py app.py
) else (
  python app.py
)
pause
