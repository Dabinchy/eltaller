@echo off
chcp 65001 >nul
rem Borra la demo (sólo la base de demo y sus archivos) y la vuelve a cargar.
cd /d "%~dp0.."
set DJANGO_DEMO=1
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
python manage.py migrate --verbosity 0 || goto error
python manage.py cargar_demo --reiniciar || goto error
echo.
echo Demo cargada de nuevo. Para abrirla: demo\iniciar_demo.bat
pause
goto :eof

:error
echo.
echo Hubo un problema: revisa el mensaje de arriba.
pause
