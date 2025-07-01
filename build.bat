@echo off
cd /d %~dp0
REM Script para crear un ejecutable de main.py con PyInstaller
REM Ejecuta este archivo desde la carpeta 'extra'

REM Instala PyInstaller si no está instalado
pip install pyinstaller

REM Sube a la carpeta principal del proyecto
cd ..

REM Construye el ejecutable en la carpeta principal, sin icono personalizado
pyinstaller --onefile --add-data "extra;extra" --add-data "entrada;entrada" --add-data "salida;salida" --distpath . --workpath . --specpath . --clean main.py

REM Elimina archivos temporales generados por PyInstaller
if exist main.spec del main.spec
if exist __pycache__ rmdir /s /q __pycache__

REM Mensaje final
echo.
echo El ejecutable se encuentra en la carpeta principal como main.exe
echo Copia main.exe a cualquier PC Windows y funcionará sin instalar Python.
pause
