@echo off
setlocal
cd /d "%~dp0"
echo Instalando el driver de PostgreSQL para Python...
where py >nul 2>&1
if %errorlevel%==0 (
  py -m pip install -r requirements-postgresql.txt
) else (
  python -m pip install -r requirements-postgresql.txt
)
echo.
echo Listo. Ahora configura DATABASE_URL en tu archivo .env.
pause
