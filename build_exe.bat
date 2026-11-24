@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=..\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo No se encontro el entorno virtual en ..\.venv
  pause
  exit /b 1
)

"%PYTHON%" -m PyInstaller --noconfirm --clean --onedir --name MotoSmart --add-data "templates;templates" --add-data "static;static" --add-binary "..\.venv\Lib\site-packages\torchvision\_C_stable.pyd;torchvision" --add-binary "..\.venv\Lib\site-packages\torchvision\image_stable.pyd;torchvision" --collect-all easyocr run_server.py
if errorlevel 1 (
  echo.
  echo No se pudo generar el ejecutable.
  pause
  exit /b 1
)

echo.
echo Listo: dist\MotoSmart\MotoSmart.exe
pause
