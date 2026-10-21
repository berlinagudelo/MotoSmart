@echo off
setlocal
set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PYTHON%" (
  echo Python 3.14 no esta instalado en este equipo.
  pause
  exit /b 1
)
if not exist "%~dp0correo.configuracion.ps1" (
  echo Copia correo.configuracion.ps1.example como correo.configuracion.ps1 y configura la clave JWT y SMTP.
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0.venv\Lib\site-packages"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { . '%~dp0correo.configuracion.ps1'; if ([string]::IsNullOrWhiteSpace($env:MOTOSMART_JWT_SECRET_KEY) -or $env:MOTOSMART_JWT_SECRET_KEY.Length -lt 32) { throw 'Configura MOTOSMART_JWT_SECRET_KEY con al menos 32 caracteres.' }; if ([string]::IsNullOrWhiteSpace($env:MOTOSMART_DATABASE_URL)) { throw 'Configura MOTOSMART_DATABASE_URL con la conexión privada a PostgreSQL.' }; & '%PYTHON%' '%~dp0run_server.py'; exit $LASTEXITCODE }"
pause
