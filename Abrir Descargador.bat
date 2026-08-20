@echo off
setlocal
cd /d "%~dp0"

rem Abre la aplicacion. La primera vez prepara todo lo que haga falta
rem (Python incluido) y despues arranca directo.

set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo.
    echo  Primera vez: preparando el programa. Tarda un par de minutos.
    echo  Se descargan Python, yt-dlp y ffmpeg. Deja la ventana abierta.
    echo.
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
