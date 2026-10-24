@echo off
chcp 65001 >nul
title Tinka - Generador estadistico
cd /d "%~dp0"

where python >nul 2>nul || (
  echo No se encontro Python. Instala Python 3.10+ desde https://www.python.org/
  pause & exit /b 1
)

echo ============================================
echo  1/3  Actualizando resultados (Tinka, Kabala, Gana Diario)
echo ============================================
python -u src\scraper.py
if errorlevel 1 echo [aviso] La descarga fallo; se usara la base existente.

echo.
echo ============================================
echo  2/3  Recalculando el modelo predictivo
echo ============================================
python -u src\modelo.py
if errorlevel 1 ( echo Error al construir el modelo. & pause & exit /b 1 )

echo.
echo ============================================
echo  3/3  Iniciando la web (se abre en el navegador)
echo ============================================
python -u src\servidor.py 8765
pause
