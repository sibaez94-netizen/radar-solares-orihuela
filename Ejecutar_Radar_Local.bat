@echo off
chcp 65001 >nul
title Radar de Solares y Casas - Orihuela y Vega Baja
echo ============================================================================
echo   RADAR DE SOLARES Y CASAS A REFORMAR (ORIHUELA Y VEGA BAJA)
echo ============================================================================
echo.
echo [1/2] Buscando nuevos solares, casas de planta baja y cambios de precio...
echo       (Esto puede tardar unos 15-30 segundos mientras consulta las webs)
echo.

cd /d "%~dp0"
python main.py

echo.
echo [2/2] Abriendo el Panel Web en tu navegador...
start "" "%~dp0docs\index.html"

echo.
echo ¡Listo! Ya tienes el panel abierto en el navegador.
timeout /t 4
