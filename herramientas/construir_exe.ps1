# Empaqueta la aplicacion en un unico .exe que no necesita Python.
#
# Uso (desde la raiz del proyecto):
#   powershell -ExecutionPolicy Bypass -File herramientas\construir_exe.ps1
#
# Deja DescargadorDeVideos.exe (~23 MB) en la raiz. Ese archivo suelto es todo
# lo que hay que copiar a otro equipo: al abrirlo por primera vez detecta que le
# falta ffmpeg y el motor de JavaScript y los descarga solo.
#
# Con -ConBin recuerda que, para equipos sin internet, hay que llevarse tambien
# la carpeta bin (~350 MB en total).

param([switch]$ConBin)

$ErrorActionPreference = 'Stop'
# El script vive en herramientas\: la raiz del proyecto es la carpeta de arriba.
$raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $raiz

Write-Host ""
Write-Host "=== Empaquetando el Descargador de Videos ===" -ForegroundColor Cyan

$venvPy = Join-Path $raiz '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "Falta el entorno virtual. Ejecuta primero setup.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "Instalando PyInstaller (solo la primera vez) ..." -ForegroundColor Yellow
$ErrorActionPreference = 'Continue'
& $venvPy -m pip install --upgrade --disable-pip-version-check pyinstaller | Out-Null
$ErrorActionPreference = 'Stop'

$nombre = 'DescargadorDeVideos'
Write-Host "Construyendo $nombre.exe (tarda unos minutos) ..." -ForegroundColor Yellow

# Los restos de la construccion van a una carpeta temporal: el ejecutable
# terminado se deja en la raiz, que es donde la gente lo va a buscar.
$temporal = Join-Path $env:TEMP "construir-$nombre"

$ErrorActionPreference = 'Continue'
& $venvPy -m PyInstaller `
    --noconfirm --clean --onefile --windowed `
    --name $nombre `
    --collect-all yt_dlp `
    --exclude-module pytest `
    --distpath $temporal `
    --workpath (Join-Path $temporal 'trabajo') `
    --specpath $temporal `
    (Join-Path $raiz 'herramientas\lanzador.py')
$codigo = $LASTEXITCODE
$ErrorActionPreference = 'Stop'

$construido = Join-Path $temporal "$nombre.exe"
if ($codigo -ne 0 -or -not (Test-Path $construido)) {
    Write-Host "No se pudo construir el ejecutable." -ForegroundColor Red
    exit 1
}

$exe = Join-Path $raiz "$nombre.exe"
Move-Item -Path $construido -Destination $exe -Force
Remove-Item -Recurse -Force $temporal -ErrorAction SilentlyContinue

if ($ConBin) {
    Write-Host "ffmpeg y deno ya estan en .\bin, junto al ejecutable." -ForegroundColor Yellow
}

$tamano = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ""
Write-Host "=== Listo ===" -ForegroundColor Cyan
Write-Host "Ejecutable: $exe ($tamano MB)" -ForegroundColor White
if ($ConBin) {
    Write-Host "Para repartirlo sin internet, copia el .exe junto con la" -ForegroundColor White
    Write-Host "carpeta bin. Si no, basta con el .exe suelto." -ForegroundColor White
} else {
    Write-Host "Reparte solo ese archivo. Al abrirlo por primera vez descarga" -ForegroundColor White
    Write-Host "lo que le falte al equipo (necesita internet esa primera vez)." -ForegroundColor White
}
Write-Host ""
Write-Host "Nota: al ser un .exe sin firma digital, Windows puede mostrar el" -ForegroundColor Yellow
Write-Host "aviso de SmartScreen la primera vez: 'Mas informacion' > 'Ejecutar'." -ForegroundColor Yellow
Write-Host ""
