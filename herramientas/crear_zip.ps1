# Empaqueta el proyecto en un ZIP repartible que NO contiene ejecutables.
#
# Uso (desde la raiz del proyecto):
#   powershell -ExecutionPolicy Bypass -File herramientas\crear_zip.ps1
#
# Deja DescargadorDeVideos-codigo.zip en la raiz. Es la alternativa al .exe para
# equipos donde Windows bloquea programas sin firma digital: dentro solo viaja
# codigo, y quien lo abra ejecuta Python (firmado) en lugar de un binario ajeno.

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $raiz

Write-Host ""
Write-Host "=== Empaquetando el codigo ===" -ForegroundColor Cyan

$nombre = 'DescargadorDeVideos-codigo'
$temporal = Join-Path $env:TEMP "zip-$nombre"
if (Test-Path $temporal) { Remove-Item -Recurse -Force $temporal }
New-Item -ItemType Directory -Force -Path $temporal | Out-Null

# Lo que ve quien descomprime: el lanzador arriba y el codigo en su carpeta.
$sueltos = @('Abrir Descargador.bat', 'LEEME.txt', 'README.md', 'LICENSE',
             'TERCEROS.md')
foreach ($archivo in $sueltos) {
    if (Test-Path $archivo) { Copy-Item $archivo -Destination $temporal }
    else { Write-Host "  falta $archivo" -ForegroundColor Yellow }
}

Copy-Item 'descargador' -Destination $temporal -Recurse
# El instalador y la version de consola; el empaquetador del .exe y los
# bocetos de diseno no le sirven a quien solo quiere usar el programa.
New-Item -ItemType Directory -Force -Path (Join-Path $temporal 'herramientas') | Out-Null
foreach ($archivo in @('setup.ps1', 'consola.bat', 'requirements.txt')) {
    Copy-Item (Join-Path 'herramientas' $archivo) `
              -Destination (Join-Path $temporal 'herramientas')
}

# Nada de cachés de Python: solo ensucian el ZIP.
Get-ChildItem -Path $temporal -Recurse -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force

$destino = Join-Path $raiz "$nombre.zip"
if (Test-Path $destino) { Remove-Item -Force $destino }
Compress-Archive -Path (Join-Path $temporal '*') -DestinationPath $destino -Force
Remove-Item -Recurse -Force $temporal

$tamano = [math]::Round( (Get-Item $destino).Length / 1KB , 0 )
Write-Host ""
Write-Host "=== Listo ===" -ForegroundColor Cyan
Write-Host "Archivo: $destino ($tamano KB)" -ForegroundColor White
Write-Host "Quien lo reciba descomprime y abre 'Abrir Descargador.bat'." -ForegroundColor White
Write-Host ""
