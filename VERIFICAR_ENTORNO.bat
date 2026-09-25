@echo off
setlocal
title Verificar entorno - Infraestructura v22
echo ================================================================
echo Plataforma de Infraestructura v22
echo Verificacion de programas instalados
echo ================================================================
echo.
echo [Python Launcher]
where py >nul 2>&1
if %errorlevel%==0 (py --version) else (echo No encontrado: comando py)
echo.
echo [Python]
where python >nul 2>&1
if %errorlevel%==0 (python --version) else (echo No encontrado: comando python)
echo.
echo [Node.js]
where node >nul 2>&1
if %errorlevel%==0 (node --version) else (echo No encontrado: comando node)
echo.
echo [PostgreSQL psql]
where psql >nul 2>&1
if %errorlevel%==0 (psql --version) else (echo No encontrado en PATH. PostgreSQL puede estar instalado aunque psql no este en PATH.)
echo.
echo ================================================================
echo Si Python y PostgreSQL aparecen, ya tenemos la base del servidor.
echo Node queda disponible para una futura capa frontend modular.
echo ================================================================
pause
