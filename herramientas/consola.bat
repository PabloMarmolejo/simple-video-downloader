@echo off
rem Version de consola del descargador.
rem
rem Ejemplos (desde la raiz del proyecto):
rem    herramientas\consola.bat "https://youtu.be/XXXX"
rem    herramientas\consola.bat -f 1080 "https://www.facebook.com/watch/?v=123"
rem    herramientas\consola.bat --mp3 --calidad-audio 320 "https://youtu.be/XXXX"
setlocal
cd /d "%~dp0.."

set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
)
"%PY%" -m descargador.cli %*
endlocal
