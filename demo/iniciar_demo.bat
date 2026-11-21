@echo off
chcp 65001 >nul
rem Abre la demo de El Taller en una base aparte (demo.sqlite3): no toca los datos reales.
cd /d "%~dp0.."
set DJANGO_DEMO=1
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
echo Preparando la demo...
python manage.py migrate --verbosity 0 || goto error
python manage.py cargar_demo --si-hace-falta || goto error
echo.
echo Demo lista. Se abre el navegador en http://127.0.0.1:8000/
echo Usuarios: ver demo\LEEME.md (contrasena de todos: demo1234). Para cerrar: Ctrl+C.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000/"
python manage.py runserver
goto :eof

:error
echo.
echo Hubo un problema: revisa el mensaje de arriba.
pause
