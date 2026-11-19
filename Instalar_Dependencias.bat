@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Instalando dependencias del Agente de Solares...
python --version >nul 2>&1
if errorlevel 1 (
  echo No encuentro Python. Instalalo con:  winget install Python.Python.3.12
  echo o desde https://www.python.org/downloads/  marcando "Add python.exe to PATH".
  pause
  exit /b 1
)
python -m pip install --user -r requirements.txt
echo.
echo Listo. Ejecuta "Ejecutar_Radar_Local.bat" para probar el radar en tu PC.
pause
