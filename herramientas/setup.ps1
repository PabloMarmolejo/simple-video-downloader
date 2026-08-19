# Instalador del Descargador de Videos.
# Crea un entorno virtual, instala yt-dlp y descarga ffmpeg en .\bin
# Uso:  powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = 'Stop'
# El script vive en herramientas\: la raiz del proyecto es la carpeta de arriba.
$raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $raiz

Write-Host ""
Write-Host "=== Instalador del Descargador de Videos ===" -ForegroundColor Cyan
Write-Host ""

# --- 1. Python ---------------------------------------------------------------
# Nota: nada de "2>&1" al invocar ejecutables nativos; con ErrorActionPreference
# 'Stop' PowerShell 5.1 convierte esa salida en excepcion y rompe la deteccion.
$python = $null
foreach ($cmd in @('py', 'python', 'python3')) {
    $encontrado = Get-Command $cmd -ErrorAction SilentlyContinue
    if (-not $encontrado) { continue }

    $prefijo = if ($cmd -eq 'py') { @('-3') } else { @() }
    $sonda = @('-c', 'import sys; print(sys.version.split()[0])')
    $ErrorActionPreference = 'Continue'
    $version = & $encontrado.Source @prefijo @sonda
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'

    if ($codigo -eq 0 -and $version) {
        $python = @{ Exe = $encontrado.Source; Prefijo = $prefijo }
        Write-Host "Python encontrado: $version ($($encontrado.Source))" -ForegroundColor Green
        break
    }
}
if (-not $python) {
    Write-Host "No se encontro Python. Instalalo desde https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "(marca la casilla 'Add python.exe to PATH' durante la instalacion)." -ForegroundColor Red
    exit 1
}

# --- 2. Entorno virtual ------------------------------------------------------
$venv = Join-Path $raiz '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "Creando entorno virtual en .venv ..." -ForegroundColor Yellow
    & $python.Exe @($python.Prefijo) -m venv $venv
}
if (-not (Test-Path $venvPy)) {
    Write-Host "No se pudo crear el entorno virtual." -ForegroundColor Red
    exit 1
}

# --- 3. Dependencias ---------------------------------------------------------
Write-Host "Instalando / actualizando yt-dlp ..." -ForegroundColor Yellow
& $venvPy -m pip install --upgrade --disable-pip-version-check pip | Out-Null
& $venvPy -m pip install --upgrade --disable-pip-version-check yt-dlp brotli certifi
if ($LASTEXITCODE -ne 0) {
    Write-Host "Fallo la instalacion de dependencias." -ForegroundColor Red
    exit 1
}

# --- 4. ffmpeg ---------------------------------------------------------------
$bin = Join-Path $raiz 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$ffmpegExe = Join-Path $bin 'ffmpeg.exe'

if (Test-Path $ffmpegExe) {
    Write-Host "ffmpeg ya esta en .\bin" -ForegroundColor Green
} elseif (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host "ffmpeg ya esta instalado en el sistema" -ForegroundColor Green
} else {
    Write-Host "Descargando ffmpeg (aprox. 80 MB, puede tardar) ..." -ForegroundColor Yellow
    $zip = Join-Path $env:TEMP 'ffmpeg-descargador.zip'
    $tmp = Join-Path $env:TEMP 'ffmpeg-descargador'
    $urls = @(
        'https://github.com/GyanD/codexffmpeg/releases/latest/download/ffmpeg-release-essentials.zip',
        'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
    )
    $ok = $false
    foreach ($url in $urls) {
        try {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 600
            $ok = $true
            break
        } catch {
            Write-Host "  no se pudo desde $url" -ForegroundColor DarkGray
        }
    }
    if ($ok) {
        try {
            if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
            Expand-Archive -Path $zip -DestinationPath $tmp -Force
            Get-ChildItem -Path $tmp -Recurse -Include 'ffmpeg.exe', 'ffprobe.exe' |
                ForEach-Object { Copy-Item $_.FullName -Destination $bin -Force }
            Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
            Remove-Item -Force $zip -ErrorAction SilentlyContinue
            if (Test-Path $ffmpegExe) {
                Write-Host "ffmpeg instalado en .\bin" -ForegroundColor Green
            }
        } catch {
            Write-Host "No se pudo extraer ffmpeg: $_" -ForegroundColor Red
        }
    }
    if (-not (Test-Path $ffmpegExe)) {
        Write-Host ""
        Write-Host "AVISO: no se pudo instalar ffmpeg automaticamente." -ForegroundColor Yellow
        Write-Host "Alternativas:" -ForegroundColor Yellow
        Write-Host "  winget install Gyan.FFmpeg" -ForegroundColor Yellow
        Write-Host "  o descarga https://www.gyan.dev/ffmpeg/builds/ y copia" -ForegroundColor Yellow
        Write-Host "  ffmpeg.exe y ffprobe.exe a la carpeta .\bin" -ForegroundColor Yellow
        Write-Host "Sin ffmpeg funciona igual, pero la calidad maxima queda limitada" -ForegroundColor Yellow
        Write-Host "y no se puede convertir a MP3." -ForegroundColor Yellow
    }
}

# --- 5. Deno (motor de JavaScript que YouTube exige) --------------------------
$denoExe = Join-Path $bin 'deno.exe'
if (Test-Path $denoExe) {
    Write-Host "deno ya esta en .\bin" -ForegroundColor Green
} elseif ((Get-Command deno -ErrorAction SilentlyContinue) -or (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Motor de JavaScript encontrado en el sistema (deno/node)" -ForegroundColor Green
} else {
    Write-Host "Descargando deno (motor JS necesario para YouTube) ..." -ForegroundColor Yellow
    $zipD = Join-Path $env:TEMP 'deno-descargador.zip'
    $tmpD = Join-Path $env:TEMP 'deno-descargador'
    $arq = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64-pc-windows-msvc' } else { 'x86_64-pc-windows-msvc' }
    try {
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 600 `
            -Uri "https://github.com/denoland/deno/releases/latest/download/deno-$arq.zip" `
            -OutFile $zipD
        if (Test-Path $tmpD) { Remove-Item -Recurse -Force $tmpD }
        Expand-Archive -Path $zipD -DestinationPath $tmpD -Force
        Get-ChildItem -Path $tmpD -Recurse -Filter 'deno.exe' |
            ForEach-Object { Copy-Item $_.FullName -Destination $bin -Force }
        Remove-Item -Recurse -Force $tmpD -ErrorAction SilentlyContinue
        Remove-Item -Force $zipD -ErrorAction SilentlyContinue
        if (Test-Path $denoExe) { Write-Host "deno instalado en .\bin" -ForegroundColor Green }
    } catch {
        Write-Host "No se pudo instalar deno automaticamente: $_" -ForegroundColor Yellow
        Write-Host "Alternativa: winget install DenoLand.Deno" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Instalacion terminada ===" -ForegroundColor Cyan
Write-Host "Abre la aplicacion con:  .\Descargador.bat" -ForegroundColor White
Write-Host "O desde consola:         .\.venv\Scripts\python.exe -m descargador.cli URL" -ForegroundColor White
Write-Host ""
