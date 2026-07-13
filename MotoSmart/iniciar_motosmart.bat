@echo off
setlocal
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON%" (
  echo Python 3.14 no esta instalado en este equipo.
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0.venv\Lib\site-packages"
"%PYTHON%" "%~dp0run_server.py"
pause
