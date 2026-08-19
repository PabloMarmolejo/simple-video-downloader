"""Autoabastecimiento: detecta y descarga lo que la aplicacion necesita.

La app depende de tres cosas externas:

* **ffmpeg** para unir pistas y convertir,
* un **motor de JavaScript** (deno o node) que YouTube exige para entregar los
  formatos buenos,
* **yt-dlp**, que envejece rapido porque los sitios cambian.

Empaquetada en un .exe no hay Python ni pip donde apoyarse, asi que este modulo
se encarga de instalarlas por su cuenta. Tambien decide donde guardar los datos:
junto al ejecutable si se puede escribir ahi, o en la carpeta del usuario si el
programa vive en un sitio protegido como Archivos de programa.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterable

NOMBRE_APP = "DescargadorDeVideos"

# Empaquetado, el modulo vive en una carpeta temporal: lo que importa es donde
# esta el .exe.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent

Progreso = Callable[[str, float], None]   # (mensaje, porcentaje 0-100)


def _escribible(carpeta: Path) -> bool:
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        prueba = carpeta / ".escritura"
        prueba.write_text("x", encoding="utf-8")
        prueba.unlink()
        return True
    except OSError:
        return False


ARCHIVOS_DATOS = ("config.json", "cookies.txt", "historial.txt")


def carpeta_datos() -> Path:
    """Donde guardar cookies, configuracion e historial.

    Van en una subcarpeta para que quien abra la carpeta del programa vea lo
    que tiene que abrir y no un monton de archivos sueltos.
    """
    if _escribible(APP_DIR):
        destino = APP_DIR / "datos"
        destino.mkdir(parents=True, exist_ok=True)
        _mudar_datos_antiguos(destino)
        return destino
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    destino = Path(base) / NOMBRE_APP if base else Path.home() / f".{NOMBRE_APP}"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _mudar_datos_antiguos(destino: Path) -> None:
    """Versiones anteriores dejaban estos archivos en la raiz."""
    for nombre in ARCHIVOS_DATOS:
        viejo = APP_DIR / nombre
        if viejo.exists() and not (destino / nombre).exists():
            try:
                viejo.replace(destino / nombre)
            except OSError:
                pass


DATOS_DIR = carpeta_datos()
PAQUETES_DIR = DATOS_DIR / "paquetes"

# ffmpeg y deno se instalan junto al programa cuando se puede escribir ahi
# (asi el conjunto es portable) y en la carpeta del usuario si no.
BIN_DIR = (APP_DIR / "bin") if DATOS_DIR.parent == APP_DIR else (DATOS_DIR / "bin")

# Se busca en ambos sitios, por si el programa cambio de ubicacion.
CARPETAS_BIN = [APP_DIR / "bin", DATOS_DIR / "bin"]


def _sufijo() -> str:
    return ".exe" if os.name == "nt" else ""


def buscar(nombre: str) -> str | None:
    """Ruta a un ejecutable: primero los nuestros, luego los del sistema."""
    for carpeta in CARPETAS_BIN:
        candidato = carpeta / f"{nombre}{_sufijo()}"
        if candidato.exists():
            return str(candidato)
    return shutil.which(nombre)


def registrar_en_path() -> None:
    """yt-dlp busca sus herramientas en el PATH; se le ponen delante."""
    extra = os.pathsep.join(str(c) for c in CARPETAS_BIN)
    os.environ["PATH"] = extra + os.pathsep + os.environ.get("PATH", "")


registrar_en_path()


# --------------------------------------------------------------- inventario

MOTORES_JS = ("deno", "node", "bun")


def hay_ffmpeg() -> bool:
    return bool(buscar("ffmpeg"))


def hay_motor_js() -> bool:
    return any(buscar(m) for m in MOTORES_JS)


def faltantes() -> list[str]:
    """Componentes que hay que instalar, en lenguaje llano."""
    pendientes = []
    if not hay_ffmpeg():
        pendientes.append("ffmpeg")
    if not hay_motor_js():
        pendientes.append("deno")
    return pendientes


DESCRIPCIONES = {
    "ffmpeg": "ffmpeg (~90 MB): une video y audio, convierte a MP3 y arregla "
              "los formatos que no reproduce Windows",
    "deno": "deno (~40 MB): motor de JavaScript que YouTube exige para "
            "entregar los formatos de buena calidad",
}


# --------------------------------------------------------------- descargas


class DescargaCancelada(Exception):
    pass


def _descargar(url: str, destino: Path, progreso: Progreso | None = None,
               parar: threading.Event | None = None, etiqueta: str = "") -> None:
    peticion = urllib.request.Request(
        url, headers={"User-Agent": f"{NOMBRE_APP}/1.0"}
    )
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        total = int(respuesta.headers.get("Content-Length") or 0)
        hechos = 0
        with open(destino, "wb") as salida:
            while True:
                if parar is not None and parar.is_set():
                    raise DescargaCancelada()
                trozo = respuesta.read(262144)
                if not trozo:
                    break
                salida.write(trozo)
                hechos += len(trozo)
                if progreso:
                    pct = (hechos / total * 100) if total else 0.0
                    progreso(f"Descargando {etiqueta} ({hechos // 1048576} MB"
                             + (f" de {total // 1048576} MB)" if total else ")"),
                             pct)


def _extraer(zip_path: Path, nombres: Iterable[str], destino: Path,
             progreso: Progreso | None = None) -> list[str]:
    """Saca del zip solo los ejecutables que interesan."""
    destino.mkdir(parents=True, exist_ok=True)
    obtenidos = []
    buscados = {n.lower() for n in nombres}
    with zipfile.ZipFile(zip_path) as z:
        for miembro in z.namelist():
            base = Path(miembro).name.lower()
            if base in buscados:
                if progreso:
                    progreso(f"Extrayendo {Path(miembro).name}...", 95.0)
                with z.open(miembro) as origen, \
                        open(destino / Path(miembro).name, "wb") as salida:
                    shutil.copyfileobj(origen, salida)
                obtenidos.append(Path(miembro).name)
    return obtenidos


URLS_FFMPEG = (
    "https://github.com/GyanD/codexffmpeg/releases/latest/download/"
    "ffmpeg-release-essentials.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
)


def _url_deno() -> str:
    arq = ("aarch64-pc-windows-msvc"
           if os.environ.get("PROCESSOR_ARCHITECTURE") == "ARM64"
           else "x86_64-pc-windows-msvc")
    return f"https://github.com/denoland/deno/releases/latest/download/deno-{arq}.zip"


def instalar(componente: str, progreso: Progreso | None = None,
             parar: threading.Event | None = None) -> tuple[bool, str]:
    """Descarga e instala un componente en la carpeta bin de la app."""
    if os.name != "nt":
        return False, (f"La instalacion automatica de {componente} solo esta "
                       "hecha para Windows; instalalo con tu gestor de paquetes.")

    if componente == "ffmpeg":
        urls, piezas = URLS_FFMPEG, ("ffmpeg.exe", "ffprobe.exe")
    elif componente == "deno":
        urls, piezas = (_url_deno(),), ("deno.exe",)
    else:
        return False, f"Componente desconocido: {componente}"

    temporal = Path(os.environ.get("TEMP", ".")) / f"{componente}-{NOMBRE_APP}.zip"
    ultimo_error = ""
    for url in urls:
        try:
            _descargar(url, temporal, progreso, parar, etiqueta=componente)
            obtenidos = _extraer(temporal, piezas, BIN_DIR, progreso)
            temporal.unlink(missing_ok=True)
            if obtenidos:
                return True, f"{componente} instalado ({', '.join(obtenidos)})."
            ultimo_error = "el archivo descargado no traia lo esperado"
        except DescargaCancelada:
            temporal.unlink(missing_ok=True)
            return False, f"{componente}: cancelado."
        except Exception as exc:  # noqa: BLE001 - red y disco fallan de mil formas
            ultimo_error = str(exc)[:200]
            temporal.unlink(missing_ok=True)

    return False, f"No se pudo instalar {componente}: {ultimo_error}"


def instalar_faltantes(progreso: Progreso | None = None,
                       parar: threading.Event | None = None) -> tuple[bool, list[str]]:
    """Instala todo lo que falte. Devuelve (todo_ok, mensajes)."""
    mensajes = []
    todo_ok = True
    pendientes = faltantes()
    for i, componente in enumerate(pendientes, 1):
        if parar is not None and parar.is_set():
            mensajes.append("Cancelado.")
            return False, mensajes
        if progreso:
            progreso(f"[{i}/{len(pendientes)}] Preparando {componente}...", 0.0)
        ok, msg = instalar(componente, progreso, parar)
        mensajes.append(msg)
        todo_ok = todo_ok and ok
    return todo_ok, mensajes


# ----------------------------------------------------------------- yt-dlp


def _finder_local(carpeta: Path):
    """Hace que el yt-dlp descargado gane al que viene dentro del .exe.

    PyInstaller resuelve sus modulos antes que el sistema de rutas normal, asi
    que sin esto la copia actualizada nunca se usaria.
    """
    from importlib.machinery import PathFinder

    class FinderYtDlp:
        @staticmethod
        def find_spec(nombre, path=None, target=None):
            if nombre.split(".")[0] != "yt_dlp":
                return None
            return PathFinder.find_spec(nombre, path or [str(carpeta)], target)

    return FinderYtDlp


def preparar_ytdlp_local() -> str:
    """Si hay una copia actualizada de yt-dlp, se usa esa. Devuelve su version."""
    destino = PAQUETES_DIR / "yt_dlp"
    if not destino.is_dir():
        return ""
    try:
        sys.meta_path.insert(0, _finder_local(PAQUETES_DIR))
        sys.path.insert(0, str(PAQUETES_DIR))
        version = (destino / "version.py").read_text(encoding="utf-8")
        for linea in version.splitlines():
            if linea.startswith("__version__"):
                return linea.split("=")[1].strip().strip("'\"")
    except (OSError, ValueError):
        pass
    return ""


def actualizar_ytdlp(progreso: Progreso | None = None) -> tuple[bool, str]:
    """Trae la ultima version de yt-dlp.

    Con Python instalado se usa pip; empaquetado no hay pip, asi que se baja la
    rueda de PyPI y se deja en la carpeta de datos, que tiene prioridad al
    importar.
    """
    if not getattr(sys, "frozen", False):
        import subprocess

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U",
                 "--disable-pip-version-check", "yt-dlp"],
                capture_output=True, text=True, timeout=600,
            )
            salida = ((proc.stdout or "") + (proc.stderr or "")).strip()
            return proc.returncode == 0, salida[-1500:]
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    try:
        if progreso:
            progreso("Consultando la ultima version de yt-dlp...", 0.0)
        peticion = urllib.request.Request(
            "https://pypi.org/pypi/yt-dlp/json",
            headers={"User-Agent": f"{NOMBRE_APP}/1.0"},
        )
        with urllib.request.urlopen(peticion, timeout=60) as respuesta:
            datos = json.load(respuesta)
        version = datos["info"]["version"]
        rueda = next(a["url"] for a in datos["urls"]
                     if a["filename"].endswith("py3-none-any.whl"))

        temporal = Path(os.environ.get("TEMP", ".")) / f"yt_dlp-{version}.whl"
        _descargar(rueda, temporal, progreso, etiqueta=f"yt-dlp {version}")

        nuevo = PAQUETES_DIR / "_nuevo"
        if nuevo.exists():
            shutil.rmtree(nuevo, ignore_errors=True)
        nuevo.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(temporal) as z:
            for miembro in z.namelist():
                if miembro.startswith("yt_dlp/"):
                    z.extract(miembro, nuevo)
        temporal.unlink(missing_ok=True)

        viejo = PAQUETES_DIR / "yt_dlp"
        if viejo.exists():
            shutil.rmtree(viejo, ignore_errors=True)
        (nuevo / "yt_dlp").replace(viejo)
        shutil.rmtree(nuevo, ignore_errors=True)

        return True, (f"yt-dlp {version} instalado. Reinicia la aplicacion para "
                      "usarlo.")
    except Exception as exc:  # noqa: BLE001
        return False, f"No se pudo actualizar yt-dlp: {exc}"
