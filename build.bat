
@echo off
cd /d %~dp0
pip install pyinstaller >nul 2>&1
setlocal enabledelayedexpansion
set RETRY=0
set MAXRETRY=5
set HAD_OLD_EXE=0
REM Comprueba si existe main.exe antes de compilar
if exist main.exe set HAD_OLD_EXE=1
:deltry
if exist main.exe (
    del /f /q main.exe >nul 2>&1
    if exist main.exe (
        echo.
        echo [ADVERTENCIA] No se pudo borrar main.exe. Asegúrate de que no esté abierto ni en uso.
        set /a RETRY+=1
        if !RETRY! lss !MAXRETRY! (
            echo Reintentando en 2 segundos... (Intento !RETRY! de !MAXRETRY!)
            timeout /t 2 >nul
            goto deltry
        ) else (
            echo [ERROR] No se pudo borrar main.exe tras varios intentos.
            echo Por favor, CIERRA el archivo main.exe y vuelve a ejecutar este script.
            pause
            exit /b 1
        )
    )
)
REM Compila el script principal con PyInstaller
pyinstaller --onefile --add-data "codigo/extra;codigo/extra" --add-data "codigo/entrada;codigo/entrada" --add-data "codigo/salida;codigo/salida" --distpath . --noconfirm --clean codigo/main.py --name main
if exist dist\main.exe move /Y dist\main.exe . >nul 2>&1
REM Limpia archivos temporales de PyInstaller
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist codigo\__pycache__ rmdir /s /q codigo\__pycache__
if exist main rmdir /s /q main
if exist main.spec del /f /q main.spec
if exist build_log.txt del /f /q build_log.txt
if not exist main.exe exit /b 1
echo.
echo Compilación finalizada. Si no hay errores, main.exe está listo.
if %HAD_OLD_EXE%==1 (
    pause
) else (
    exit /b 0
)
