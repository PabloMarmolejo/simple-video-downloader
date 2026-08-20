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
# $script:habiaCandidato distingue dos fracasos que se arreglan distinto: no
# tener Python, o tenerlo y que Windows no deje ejecutarlo.
$script:habiaCandidato = $false

function Buscar-Python {
    foreach ($cmd in @('py', 'python', 'python3')) {
        $encontrado = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $encontrado) { continue }
        $script:habiaCandidato = $true

        $prefijo = if ($cmd -eq 'py') { @('-3') } else { @() }
        $sonda = @('-c', 'import sys; print(sys.version.split()[0])')

        # Cuando Windows impide ejecutar el archivo, el fallo no es salida del
        # programa sino de PowerShell al lanzarlo, asi que no lo calla ninguna
        # redireccion: hay que capturarlo como excepcion.
        $version = $null
        $codigo = 1
        try {
            $ErrorActionPreference = 'Stop'
            $version = & $encontrado.Source @prefijo @sonda 2>$null
            $codigo = $LASTEXITCODE
        } catch {
            $codigo = 1
        } finally {
            $ErrorActionPreference = 'Stop'
        }

        if ($codigo -eq 0 -and $version) {
            Write-Host "Python encontrado: $version ($($encontrado.Source))" -ForegroundColor Green
            return @{ Exe = $encontrado.Source; Prefijo = $prefijo }
        }
    }
    return $null
}

$python = Buscar-Python

if (-not $python) {
    # Se instala con winget, que ya viene en Windows 10 y 11: asi quien estrena
    # el programa no tiene que buscar nada a mano. --force porque puede haber un
    # Python instalado que Windows rechaza, y hace falta el firmado de python.org.
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        if ($script:habiaCandidato) {
            Write-Host "Hay un Python instalado que Windows no deja ejecutar." -ForegroundColor Yellow
            Write-Host "Probando con la version firmada de python.org ..." -ForegroundColor Yellow
        } else {
            Write-Host "No hay Python en este equipo. Instalandolo con winget ..." -ForegroundColor Yellow
        }
        Write-Host "(son unos 30 MB; Windows puede pedirte confirmacion)" -ForegroundColor DarkGray

        $ErrorActionPreference = 'Continue'
        winget install --id Python.Python.3.13 --exact --source winget --force `
               --accept-source-agreements --accept-package-agreements
        $ErrorActionPreference = 'Stop'

        # winget cambia el PATH del sistema, no el de esta ventana: hay que
        # releerlo para encontrar el Python que acaba de instalar.
        $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('PATH', 'User')
        $python = Buscar-Python
    }
}

if (-not $python) {
    Write-Host ""
    if ($script:habiaCandidato) {
        # Sintoma tipico del Control Inteligente de Aplicaciones de Windows 11.
        Write-Host "Windows esta bloqueando la ejecucion de Python." -ForegroundColor Red
        Write-Host ""
        Write-Host "Casi siempre es el Control Inteligente de Aplicaciones, que" -ForegroundColor Yellow
        Write-Host "solo permite programas con firma digital. Para comprobarlo:" -ForegroundColor Yellow
        Write-Host "  Seguridad de Windows > Control de aplicaciones y navegador" -ForegroundColor White
        Write-Host "  > Control inteligente de aplicaciones" -ForegroundColor White
        Write-Host ""
        Write-Host "Si esta activado, este programa no puede funcionar en este" -ForegroundColor Yellow
        Write-Host "equipo: tambien bloquea ffmpeg, que no tiene firma. Apagarlo" -ForegroundColor Yellow
        Write-Host "es irreversible sin reinstalar Windows. Lee la seccion" -ForegroundColor Yellow
        Write-Host "correspondiente del README antes de decidir." -ForegroundColor Yellow
    } else {
        Write-Host "No se pudo preparar Python automaticamente." -ForegroundColor Red
        Write-Host "Instalalo desde https://www.python.org/downloads/ marcando la" -ForegroundColor Red
        Write-Host "casilla 'Add python.exe to PATH', y vuelve a ejecutar este archivo." -ForegroundColor Red
    }
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
    # Los adjuntos de GitHub llevan la version en el nombre, asi que hay que
    # preguntar cual es el ultimo: su CDN va diez veces mas rapido que el
    # servidor propio del autor, que queda como respaldo.
    $urls = @()
    try {
        $rel = Invoke-RestMethod -UseBasicParsing -TimeoutSec 30 `
            -Uri 'https://api.github.com/repos/GyanD/codexffmpeg/releases/latest'
        $adjunto = $rel.assets | Where-Object { $_.name -like '*essentials_build.zip' } |
                   Select-Object -First 1
        if ($adjunto) { $urls += $adjunto.browser_download_url }
    } catch {
        Write-Host "  no se pudo consultar la ultima version en GitHub" -ForegroundColor DarkGray
    }
    $urls += 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
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
