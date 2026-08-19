@echo off
setlocal
cd /d "%~dp0"

rem Abre la aplicacion usando el Python del equipo (modo desarrollo).
rem Si prefieres no depender de Python, construye el ejecutable con:
rem    powershell -ExecutionPolicy Bypass -File herramientas\construir_exe.ps1

set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo Primera ejecucion: instalando lo necesario...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0herramientas\setup.ps1"
    if not exist "%PY%" (
        echo.
        echo No se pudo completar la instalacion. Revisa los mensajes de arriba.
        pause
        exit /b 1
    )
)

if exist "%PYW%" (
    start "" "%PYW%" -m descargador.gui
) else (
    "%PY%" -m descargador.gui
)
endlocal
