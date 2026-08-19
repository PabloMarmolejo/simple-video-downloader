"""Nucleo del descargador: envuelve yt-dlp con una API simple y cancelable."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from . import componentes
from .componentes import APP_DIR, DATOS_DIR, buscar as _exe

# Una copia de yt-dlp descargada por la propia app manda sobre la empaquetada.
VERSION_YTDLP_LOCAL = componentes.preparar_ytdlp_local()

CONFIG_PATH = DATOS_DIR / "config.json"
COOKIES_CACHE = DATOS_DIR / "cookies.txt"
HISTORIAL_PATH = DATOS_DIR / "historial.txt"
BIN_DIR = componentes.BIN_DIR


# ---------------------------------------------------------------- utilidades


def ffmpeg_path() -> str | None:
    """Carpeta con ffmpeg: primero el que traemos en ./bin, luego el del sistema."""
    encontrado = _exe("ffmpeg")
    return str(Path(encontrado).parent) if encontrado else None


def motores_js() -> dict[str, dict]:
    """Motores de JavaScript disponibles.

    YouTube exige resolver retos en JS para entregar los formatos buenos; sin
    un motor solo quedan formatos degradados o directamente ninguno.
    """
    motores: dict[str, dict] = {}
    for nombre in ("deno", "node", "bun"):
        ruta = _exe(nombre)
        if ruta:
            motores[nombre] = {"path": ruta}
    return motores


def espacio_libre(carpeta: str | Path) -> int:
    """Bytes libres en el disco de esa carpeta (0 si no se puede saber)."""
    ruta = Path(carpeta)
    while not ruta.exists() and ruta != ruta.parent:
        ruta = ruta.parent
    try:
        return shutil.disk_usage(ruta).free
    except OSError:
        return 0


def fmt_tamano(bytes_: float | None) -> str:
    if not bytes_:
        return ""
    unidades = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while bytes_ >= 1024 and i < len(unidades) - 1:
        bytes_ /= 1024
        i += 1
    return f"{bytes_:.1f} {unidades[i]}"


# -------------------------------------------------------------------- cookies


def _proteger_archivo(ruta: Path) -> None:
    """Deja el archivo accesible solo para el usuario actual.

    Contiene credenciales de sesion: no tiene por que leerlo el resto de
    cuentas del equipo.
    """
    if os.name != "nt":
        try:
            ruta.chmod(0o600)
        except OSError:
            pass
        return
    usuario = os.environ.get("USERNAME")
    if not usuario:
        return
    try:
        subprocess.run(
            ["icacls", str(ruta), "/inheritance:r", "/grant:r", f"{usuario}:F"],
            capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def extraer_cookies(navegador: str, destino: Path = COOKIES_CACHE) -> tuple[bool, str]:
    """Copia la sesion del navegador a un cookies.txt propio de la app.

    Hacerlo una sola vez evita depender del navegador en cada descarga: el
    archivo sirve aunque despues este abierto, cerrado o desinstalado. Se
    escribe primero en un temporal y solo se reemplaza el bueno si todo salio
    bien, para no quedarse sin sesion por un intento fallido.
    """
    try:
        from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser
    except ImportError:
        return False, "yt-dlp no esta instalado."

    try:
        jar = extract_cookies_from_browser(navegador)
    except Exception as exc:  # noqa: BLE001 - cada navegador falla a su manera
        return False, _motivo_cookies(navegador, exc)

    filtrado = YoutubeDLCookieJar()
    total = 0
    for cookie in jar:
        dominio = (cookie.domain or "").lstrip(".")
        if any(dominio == d or dominio.endswith("." + d) for d in DOMINIOS_SESION):
            filtrado.set_cookie(cookie)
            total += 1

    if not total:
        return False, (
            f"{navegador}: no hay sesion guardada de sitios de video. "
            "Inicia sesion en ese navegador o usa otro."
        )

    temporal = destino.with_name(destino.name + ".nuevo")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        filtrado.save(str(temporal), ignore_discard=True, ignore_expires=True)
        temporal.replace(destino)
        _proteger_archivo(destino)
    except OSError as exc:
        temporal.unlink(missing_ok=True)
        return False, f"No se pudo guardar {destino.name}: {exc}"

    return True, f"{total} cookies guardadas desde {navegador}."


def _motivo_cookies(navegador: str, exc: Exception) -> str:
    texto = str(exc)
    if "Could not copy" in texto or "Permission denied" in texto:
        return (
            f"{navegador}: esta abierto y bloquea su base de cookies. "
            "Firefox si se deja leer con el navegador abierto."
        )
    if "decrypt" in texto.lower() or "v20" in texto:
        return (
            f"{navegador}: cookies cifradas por el propio navegador "
            "(App-Bound Encryption); usa Firefox o un cookies.txt exportado."
        )
    return f"{navegador}: {texto[:200]}"


def cookies_cache_utiles(clave: str = "youtube.com") -> bool:
    """True si el cookies.txt propio existe y sigue vigente."""
    if not COOKIES_CACHE.exists():
        return False
    try:
        from yt_dlp.cookies import YoutubeDLCookieJar

        jar = YoutubeDLCookieJar(str(COOKIES_CACHE))
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:  # noqa: BLE001
        return False

    margen = time.time() + 3600
    return any(
        clave in (c.domain or "") and (not c.expires or c.expires > margen)
        for c in jar
    )


def preparar_cookies(
    op: "Opciones",
    avisar: Callable[[str], None] | None = None,
    forzar: bool = False,
) -> str | None:
    """Decide que archivo de cookies usar y lo genera si hace falta.

    Con forzar=True se ignora el cache y se vuelve a leer del navegador; el
    cache anterior se conserva hasta que la nueva extraccion tenga exito.
    """

    def log(msg: str) -> None:
        if avisar:
            avisar(msg)

    # 1. Archivo indicado por el usuario: manda sobre todo lo demas.
    if op.archivo_cookies:
        if Path(op.archivo_cookies).exists():
            return op.archivo_cookies
        log(f"Aviso: no existe el archivo de cookies {op.archivo_cookies}")

    if op.navegador_cookies == "Ninguno":
        return None

    candidatos = (
        NAVEGADORES_AUTO
        if op.navegador_cookies == AUTOMATICO
        else [op.navegador_cookies]
    )

    # 2. El cache evita tocar el navegador en cada descarga.
    if not forzar and cookies_cache_utiles():
        log("Usando las cookies guardadas de la app (cookies.txt).")
        return str(COOKIES_CACHE)

    for candidato in candidatos:
        ok, msg = extraer_cookies(candidato)
        log(("Cookies: " if ok else "Aviso: ") + msg)
        if ok:
            return str(COOKIES_CACHE)

    # 3. Si no se pudo refrescar, el cache viejo es mejor que nada.
    if cookies_cache_utiles():
        log("No se pudo refrescar la sesion; se usara la guardada.")
        return str(COOKIES_CACHE)

    log(
        "Aviso: no se pudo obtener sesion de ningun navegador. YouTube "
        "seguramente falle. Ver README (seccion Sesion)."
    )
    return None


# --------------------------------------------------------------------- medios


def analizar_medios(ruta: str | Path) -> dict:
    """Codecs reales del archivo, segun ffprobe."""
    ffprobe = _exe("ffprobe")
    if not ffprobe or not Path(ruta).exists():
        return {}
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,profile,disposition", "-of", "json",
             str(ruta)],
            capture_output=True, text=True, timeout=120,
        )
        datos = json.loads(proc.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}

    medios: dict[str, Any] = {"subtitulos": 0}
    for flujo in datos.get("streams", []):
        tipo = flujo.get("codec_type")
        if tipo == "video" and "video" not in medios:
            medios["video"] = flujo.get("codec_name", "")
        elif tipo == "audio" and "audio" not in medios:
            medios["audio"] = flujo.get("codec_name", "")
            medios["perfil_audio"] = flujo.get("profile", "") or ""
        elif tipo == "subtitle":
            medios["subtitulos"] += 1
    return medios


def _incompatibilidades(medios: dict) -> tuple[bool, bool]:
    """(hay que recodificar video, hay que recodificar audio).

    Compatible = H.264 + AAC-LC, que reproduce cualquier equipo. Los casos
    tipicos que fallan son AV1/VP9 (imagen) y HE-AAC u Opus (sonido): muchos
    reproductores, televisores y editores muestran el video pero se quedan
    mudos.
    """
    if not medios:
        return False, False
    video = medios.get("video", "")
    audio = medios.get("audio", "")
    perfil = (medios.get("perfil_audio") or "").upper()

    conv_video = bool(video) and video not in ("h264",)
    conv_audio = bool(audio) and (audio != "aac" or "LC" not in perfil or "HE" in perfil)
    return conv_video, conv_audio


def _correr_cancelable(
    orden: list[str], parar: threading.Event | None = None, timeout: int = 7200
) -> tuple[int, str]:
    """Ejecuta un proceso vigilando la peticion de cancelar."""
    creacion = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        orden, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=creacion,
    )
    limite = time.monotonic() + timeout
    while proc.poll() is None:
        if parar is not None and parar.is_set():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return -1, "cancelado"
        if time.monotonic() > limite:
            proc.kill()
            return -1, "se agoto el tiempo"
        time.sleep(0.2)
    _, err = proc.communicate()
    return proc.returncode, err or ""


def convertir_compatible(
    ruta: str | Path,
    avisar: Callable[[str], None] | None = None,
    parar: threading.Event | None = None,
) -> str:
    """Deja el archivo en H.264 + AAC-LC recodificando solo lo necesario.

    Si el video ya viene en H.264 solo se toca el audio, que es casi
    instantaneo; recodificar la imagen solo ocurre cuando el origen no ofrecia
    ningun formato compatible. Se conservan subtitulos, capitulos, caratula y
    metadatos.
    """
    ruta = Path(ruta)
    ffmpeg = _exe("ffmpeg")
    if not ffmpeg or not ruta.exists():
        return str(ruta)

    medios = analizar_medios(ruta)
    conv_video, conv_audio = _incompatibilidades(medios)
    if not (conv_video or conv_audio):
        return str(ruta)

    def log(msg: str) -> None:
        if avisar:
            avisar(msg)

    partes = []
    if conv_video:
        partes.append(f"video {medios.get('video', '?')} -> H.264")
    if conv_audio:
        partes.append(f"audio {medios.get('audio', '?')} -> AAC-LC")
    log("Compatibilidad: convirtiendo " + " y ".join(partes) + "...")

    destino = ruta.with_name(ruta.stem + ".compat.mp4")

    def construir(con_subs: bool) -> list[str]:
        # "-map 0 -c copy" conserva todo (subtitulos, caratula, capitulos) y
        # solo se sobreescribe el codec de la pista concreta que lo necesita.
        orden = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-i", str(ruta), "-map", "0", "-dn", "-ignore_unknown",
                 "-c", "copy"]
        if conv_video:
            orden += ["-c:v:0", "libx264", "-crf", "20", "-preset", "veryfast",
                      "-pix_fmt", "yuv420p"]
        if conv_audio:
            orden += ["-c:a:0", "aac", "-profile:a", "aac_low", "-b:a", "192k"]
        orden += ["-c:s", "mov_text"] if con_subs else ["-sn"]
        orden += ["-movflags", "+faststart", str(destino)]
        return orden

    codigo, err = _correr_cancelable(construir(True), parar)

    # Los subtitulos de imagen (DVD/PGS) no caben en MP4: se reintenta sin ellos.
    if codigo != 0 and not (parar and parar.is_set()):
        codigo, err = _correr_cancelable(construir(False), parar)
        if codigo == 0 and medios.get("subtitulos"):
            log("Aviso: los subtitulos no eran compatibles con MP4 y se omitieron.")

    if parar is not None and parar.is_set():
        destino.unlink(missing_ok=True)
        return str(ruta)

    if codigo != 0 or not destino.exists():
        log("Aviso: la conversion fallo; se deja el archivo original. "
            + err.strip()[:200])
        destino.unlink(missing_ok=True)
        return str(ruta)

    try:
        final = ruta.with_suffix(".mp4")
        ruta.unlink(missing_ok=True)
        destino.replace(final)
        log(f"Compatibilidad: listo -> {final.name}")
        return str(final)
    except OSError as exc:
        log(f"Aviso: no se pudo reemplazar el original ({exc}).")
        return str(destino)


# ------------------------------------------------------------------- ajustes


def carpeta_descargas_por_defecto() -> Path:
    for nombre in ("Downloads", "Descargas"):
        candidata = Path.home() / nombre
        if candidata.is_dir():
            return candidata / "Videos descargados"
    return Path.home() / "Videos descargados"


def cargar_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def guardar_config(datos: dict) -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


# ------------------------------------------------------------------ opciones

# Etiqueta visible -> identificador interno
FORMATOS: dict[str, str] = {
    "Video - mejor calidad disponible": "best",
    "Video - hasta 2160p (4K)": "2160",
    "Video - hasta 1440p (2K)": "1440",
    "Video - hasta 1080p (Full HD)": "1080",
    "Video - hasta 720p (HD)": "720",
    "Video - hasta 480p (ligero)": "480",
    "Video - hasta 360p (minimo)": "360",
    "Solo audio - MP3": "mp3",
    "Solo audio - M4A (sin reconvertir)": "m4a",
}

CALIDADES_AUDIO = ["320", "256", "192", "128", "96"]

PLANTILLA_DEFECTO = "%(title).150B [%(id)s].%(ext)s"
PLANTILLAS = {
    "Titulo [id]": PLANTILLA_DEFECTO,
    "Titulo solo": "%(title).150B.%(ext)s",
    "Autor - Titulo": "%(uploader)s - %(title).120B.%(ext)s",
    "Fecha - Titulo": "%(upload_date>%Y-%m-%d)s - %(title).120B.%(ext)s",
    "Carpeta por autor": "%(uploader)s/%(title).150B.%(ext)s",
}

IDIOMAS_SUBS = {
    "Espanol e ingles": ["es", "es-419", "en"],
    "Solo espanol": ["es", "es-419"],
    "Solo ingles": ["en"],
    "Todos": ["all"],
}

AUTOMATICO = "Automatico (recomendado)"
NAVEGADORES = [AUTOMATICO, "firefox", "chrome", "edge", "brave", "opera",
               "vivaldi", "Ninguno"]

# Orden en que el modo automatico intenta obtener la sesion. Firefox va primero
# porque es el unico que se deja leer con el navegador abierto: los basados en
# Chromium bloquean su base de datos mientras corren y ademas cifran las cookies
# con App-Bound Encryption, que no es descifrable desde fuera del navegador.
NAVEGADORES_AUTO = ["firefox", "chrome", "edge", "brave", "opera", "vivaldi"]

# Solo se guardan cookies de los sitios de video: no tiene por que acabar en el
# archivo la sesion del banco del usuario.
DOMINIOS_SESION = (
    "youtube.com", "google.com", "facebook.com", "instagram.com", "fbcdn.net",
    "tiktok.com", "twitter.com", "x.com", "vimeo.com", "twitch.tv",
    "dailymotion.com", "reddit.com", "linkedin.com", "soundcloud.com",
)


@dataclass
class Opciones:
    carpeta: Path
    formato: str = "best"            # valor de FORMATOS
    playlist: bool = False           # descargar la lista/canal completo
    subtitulos: bool = False         # bajar subtitulos si existen
    subs_aparte: bool = False        # guardarlos como .srt en vez de incrustar
    subs_idiomas: list[str] = field(default_factory=lambda: ["es", "es-419", "en"])
    miniatura: bool = False          # incrustar caratula
    compatibilidad: bool = True      # dejar el resultado en H.264 + AAC-LC
    calidad_audio: str = "192"       # kbps al convertir a MP3
    plantilla: str = PLANTILLA_DEFECTO
    navegador_cookies: str = AUTOMATICO
    archivo_cookies: str = ""        # alternativa: cookies.txt exportado
    limite_velocidad: str = ""       # p.ej. "2M"; vacio = sin limite
    simultaneas: int = 1             # descargas en paralelo
    usar_historial: bool = False     # no repetir lo ya descargado
    seccion_inicio: str = ""         # recorte, p.ej. "1:30"
    seccion_fin: str = ""
    playlist_desde: str = ""         # rango de la lista, p.ej. "3"
    playlist_hasta: str = ""
    proxy: str = ""
    reintentos: int = 5


def construir_opts(
    op: Opciones,
    hooks: list[Callable] | None = None,
    archivo_cookies: str | None = None,
) -> dict:
    """Traduce nuestras Opciones a la configuracion que entiende yt-dlp."""
    plantilla = op.plantilla.strip() or PLANTILLA_DEFECTO
    if "%(" not in plantilla:            # plantilla invalida: mejor la de casa
        plantilla = PLANTILLA_DEFECTO
    salida = str(op.carpeta / _ajustar_plantilla(op.carpeta, plantilla))

    opts: dict[str, Any] = {
        "outtmpl": {"default": salida},
        "noplaylist": not op.playlist,
        "ignoreerrors": "only_download",
        "retries": op.reintentos,
        "fragment_retries": op.reintentos,
        "concurrent_fragment_downloads": 4,
        "continuedl": True,
        "windowsfilenames": os.name == "nt",
        "noprogress": True,       # el progreso lo reportamos por hooks
        "quiet": True,
        "progress_hooks": hooks or [],
        "postprocessors": [],
    }

    carpeta_ff = ffmpeg_path()
    if carpeta_ff:
        opts["ffmpeg_location"] = carpeta_ff

    # YouTube: motor de JavaScript + solver de retos "n"/firma. Sin ambos,
    # solo se obtienen formatos degradados o errores 403.
    motores = motores_js()
    if motores:
        opts["js_runtimes"] = motores
    opts["remote_components"] = ["ejs:github"]

    f = op.formato
    if f == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"].append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": op.calidad_audio or "192",
            }
        )
    elif f == "m4a":
        opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
    else:
        # Se prefiere H.264 + AAC: es lo que reproduce cualquier equipo, TV o
        # editor. AV1/VP9 solo si no hay alternativa a esa resolucion.
        if f == "best":
            opts["format"] = (
                "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/"
                "bv*[ext=mp4]+ba[ext=m4a]/"
                "bv*+ba/b[ext=mp4]/b"
            )
        else:
            h = int(f)
            opts["format"] = (
                f"bv*[height<=?{h}][vcodec^=avc1]+ba[acodec^=mp4a]/"
                f"bv*[height<=?{h}][ext=mp4]+ba[ext=m4a]/"
                f"bv*[height<=?{h}]+ba/"
                f"b[height<=?{h}][ext=mp4]/b[height<=?{h}]/b"
            )
        opts["merge_output_format"] = "mp4"

    if op.subtitulos and f not in ("mp3", "m4a"):
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = [*op.subs_idiomas, "-live_chat"]
        if op.subs_aparte:
            opts["postprocessors"].append(
                {"key": "FFmpegSubtitlesConvertor", "format": "srt",
                 "when": "before_dl"}
            )
        else:
            opts["postprocessors"].append(
                {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False}
            )

    if op.miniatura:
        opts["writethumbnail"] = True
        opts["postprocessors"].append(
            {"key": "EmbedThumbnail", "already_have_thumbnail": False}
        )

    # Metadatos siempre: titulo, autor, fecha, capitulos.
    opts["postprocessors"].append(
        {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True}
    )

    # Las cookies llegan siempre como archivo ya resuelto (ver preparar_cookies):
    # asi el navegador se lee una sola vez y no en cada descarga.
    if archivo_cookies and Path(archivo_cookies).exists():
        opts["cookiefile"] = archivo_cookies

    limite = a_bytes(op.limite_velocidad)
    if limite:
        opts["ratelimit"] = limite

    if op.usar_historial:
        opts["download_archive"] = str(HISTORIAL_PATH)

    if op.proxy.strip():
        opts["proxy"] = op.proxy.strip()

    rango = _rango_playlist(op)
    if rango:
        opts["playlist_items"] = rango

    inicio, fin = a_segundos(op.seccion_inicio), a_segundos(op.seccion_fin)
    if inicio is not None or fin is not None:
        try:
            from yt_dlp.utils import download_range_func

            opts["download_ranges"] = download_range_func(
                None, [(inicio or 0, fin if fin is not None else float("inf"))]
            )
            opts["force_keyframes_at_cuts"] = True
        except ImportError:
            pass

    return opts


def _ajustar_plantilla(carpeta: Path, plantilla: str) -> str:
    """Recorta el titulo lo justo para no pasar del limite de ruta de Windows.

    No sirve la opcion trim_file_name de yt-dlp: esa recorta la ruta entera,
    asi que con carpetas largas destroza el destino en vez del nombre.
    """
    if "%(title)." not in plantilla:
        return plantilla
    margen = 250 - len(str(carpeta)) - 40   # 40: id, extension y sufijos
    limite = max(40, min(150, margen))
    return re.sub(r"%\(title\)\.\d+B", f"%(title).{limite}B", plantilla)


def _rango_playlist(op: Opciones) -> str:
    """Rango de la lista en la notacion de yt-dlp: '3-10', '3:' o '1-10'."""
    desde, hasta = op.playlist_desde.strip(), op.playlist_hasta.strip()
    if desde and hasta:
        return f"{desde}-{hasta}"
    if desde:
        return f"{desde}:"
    if hasta:
        return f"1-{hasta}"
    return ""


def a_bytes(texto: str) -> int | None:
    """'2M' -> 2097152. Devuelve None si esta vacio o no se entiende."""
    texto = (texto or "").upper().replace("B", "").strip()
    if not texto:
        return None
    multiplicadores = {"K": 1024, "M": 1024**2, "G": 1024**3}
    try:
        if texto[-1] in multiplicadores:
            return int(float(texto[:-1]) * multiplicadores[texto[-1]])
        return int(float(texto))
    except ValueError:
        return None


def a_segundos(texto: str) -> float | None:
    """'1:30' -> 90. Acepta segundos sueltos, mm:ss y hh:mm:ss."""
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        partes = [float(p) for p in texto.split(":")]
    except ValueError:
        return None
    total = 0.0
    for parte in partes:
        total = total * 60 + parte
    return total


# --------------------------------------------------------------- descargador


class CanceladoPorUsuario(Exception):
    """Se lanza desde el hook de progreso para abortar la descarga en curso."""


class YaDescargado(Exception):
    """El historial dice que ese video ya se habia bajado antes."""


@dataclass
class Evento:
    """Mensaje que el worker envia a la interfaz."""

    tipo: str  # inicio | progreso | fin | error | log | terminado | cookies
    url: str = ""
    titulo: str = ""
    porcentaje: float = 0.0
    velocidad: str = ""
    eta: str = ""
    mensaje: str = ""
    archivo: str = ""
    indice: int = 0        # elemento actual dentro de una lista
    total_items: int = 0   # elementos de la lista


class Descargador:
    """Procesa una lista de URLs en hilos aparte y reporta por una cola."""

    def __init__(self, opciones: Opciones, eventos: "queue.Queue[Evento]"):
        self.opciones = opciones
        self.eventos = eventos
        self._cancelar = threading.Event()
        self._maestro: threading.Thread | None = None
        self._cola: "queue.Queue[str]" = queue.Queue()
        self._lock_cookies = threading.Lock()
        self._lock_cuenta = threading.Lock()
        self._cookies: str | None = None
        self._cookies_renovadas = False
        self._exitos = 0
        self._fallos = 0

    # -- control ----------------------------------------------------------
    def iniciar(self, urls: Iterable[str]) -> None:
        lista = [u.strip() for u in urls if u.strip()]
        self._cancelar.clear()
        self._maestro = threading.Thread(
            target=self._dirigir, args=(lista,), daemon=True
        )
        self._maestro.start()

    def cancelar(self) -> None:
        self._cancelar.set()

    @property
    def activo(self) -> bool:
        return self._maestro is not None and self._maestro.is_alive()

    # -- interno ----------------------------------------------------------
    def _emitir(self, **kwargs) -> None:
        self.eventos.put(Evento(**kwargs))

    def _avisar(self, mensaje: str) -> None:
        self._emitir(tipo="log", mensaje=mensaje)

    def _hacer_hook(self, url: str) -> Callable[[dict], None]:
        """Un hook por descarga: con varias en paralelo no puede haber estado
        compartido o los porcentajes se mezclarian entre filas."""

        def hook(d: dict) -> None:
            if self._cancelar.is_set():
                raise CanceladoPorUsuario()

            info = d.get("info_dict") or {}
            indice = info.get("playlist_index") or 0
            total = info.get("n_entries") or 0
            estado = d.get("status")

            if estado == "downloading":
                bytes_total = (d.get("total_bytes")
                               or d.get("total_bytes_estimate") or 0)
                hechos = d.get("downloaded_bytes") or 0
                pct = (hechos / bytes_total * 100) if bytes_total else 0.0
                self._emitir(
                    tipo="progreso", url=url, titulo=info.get("title", ""),
                    porcentaje=pct, velocidad=fmt_velocidad(d.get("speed")),
                    eta=fmt_eta(d.get("eta")), indice=indice, total_items=total,
                )
            elif estado == "finished":
                self._emitir(
                    tipo="progreso", url=url, porcentaje=100.0,
                    mensaje="Procesando (uniendo pistas)...",
                    indice=indice, total_items=total,
                )

        return hook

    def _opts_para(self, url: str) -> dict:
        opts = construir_opts(
            self.opciones, hooks=[self._hacer_hook(url)], archivo_cookies=self._cookies
        )
        opts["logger"] = _Logger(self._emitir)
        return opts

    def _renovar_cookies(self) -> str | None:
        """Refresca la sesion una sola vez aunque fallen varias descargas."""
        with self._lock_cookies:
            if self._cookies_renovadas:
                return self._cookies
            self._cookies_renovadas = True
            self._avisar("Aviso: la sesion guardada no sirvio; renovandola...")
            self._cookies = preparar_cookies(
                self.opciones, avisar=self._avisar, forzar=True
            )
            return self._cookies

    def _descargar_una(self, yt_dlp, url: str, opts: dict) -> dict:
        """Descarga una URL y verifica que realmente salio algun archivo."""
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # ignoreerrors evita que un fallo tumbe el lote, pero tambien se traga
        # los errores: sin esta comprobacion un fracaso pasaria por exito.
        logrados, _ = resultados(info)
        if logrados == 0:
            # Con el historial activo, "sin archivos" suele significar que ya
            # se habia bajado antes, no que algo fallara.
            if self.opciones.usar_historial and (info is None or _ya_en_historial(info)):
                raise YaDescargado("Ya estaba descargado (historial activo).")
            raise RuntimeError(
                "No se descargo ningun archivo. " + SUGERENCIA_COOKIES
                + " Revisa el detalle de arriba para el motivo exacto."
            )

        if self.opciones.formato in ("mp3", "m4a"):
            _verificar_audio(info, self.opciones.formato)
        elif self.opciones.compatibilidad:
            self._asegurar_compatibilidad(url, info)
        return info

    def _asegurar_compatibilidad(self, url: str, info: Any) -> None:
        """Revisa cada archivo bajado y lo convierte si no es reproducible."""
        if not isinstance(info, dict):
            return
        for elemento in info.get("entries") or [info]:
            if self._cancelar.is_set():
                return
            archivo = archivo_de(elemento)
            if not archivo:
                continue
            if any(_incompatibilidades(analizar_medios(archivo))):
                self._emitir(
                    tipo="progreso", url=url, porcentaje=100.0,
                    mensaje="Convirtiendo para que se vea y escuche en todos lados...",
                )
                nuevo = convertir_compatible(
                    archivo, avisar=self._avisar, parar=self._cancelar
                )
                _reemplazar_ruta(elemento, nuevo)

    @staticmethod
    def _renovable(exc: Exception) -> bool:
        """True si el fallo apunta claramente a sesion vencida o ausente.

        Se mantiene estrecho a proposito: un video borrado o privado no debe
        disparar la renovacion de cookies.
        """
        texto = str(exc).lower()
        senales = (
            "403", "sign in", "sign-in", "login required", "not a bot",
            "no se descargo ningun archivo", "requested format is not available",
        )
        return any(s in texto for s in senales)

    def _procesar_url(self, yt_dlp, url: str) -> None:
        self._emitir(tipo="inicio", url=url, titulo=url)
        try:
            try:
                info = self._descargar_una(yt_dlp, url, self._opts_para(url))
            except (CanceladoPorUsuario, YaDescargado):
                raise
            except Exception as exc:  # noqa: BLE001
                # Si la sesion guardada caduco, se renueva una vez y se reintenta.
                if not self._renovable(exc) or self._cancelar.is_set():
                    raise
                if not self._renovar_cookies():
                    raise
                info = self._descargar_una(yt_dlp, url, self._opts_para(url))

            logrados, totales = resultados(info)
            titulo = titulo_de(info) or url
            if totales > 1:
                titulo = f"{titulo} - {logrados}/{totales} descargados"
            with self._lock_cuenta:
                self._exitos += 1
            self._emitir(tipo="fin", url=url, titulo=titulo, archivo=archivo_de(info))

        except CanceladoPorUsuario:
            self._emitir(tipo="error", url=url, mensaje="Cancelado por el usuario.")
        except YaDescargado as exc:
            with self._lock_cuenta:
                self._exitos += 1
            self._emitir(tipo="fin", url=url, titulo=str(exc), mensaje="omitido")
        except Exception as exc:  # noqa: BLE001 - yt-dlp lanza de todo
            with self._lock_cuenta:
                self._fallos += 1
            self._emitir(tipo="error", url=url, mensaje=mensaje_amigable(exc))

    def _trabajador(self, yt_dlp) -> None:
        while not self._cancelar.is_set():
            try:
                url = self._cola.get_nowait()
            except queue.Empty:
                return
            self._procesar_url(yt_dlp, url)

    def _dirigir(self, urls: list[str]) -> None:
        try:
            import yt_dlp
        except ImportError:
            self._emitir(
                tipo="error",
                mensaje="Falta yt-dlp. Ejecuta setup.ps1 o: pip install -U yt-dlp",
            )
            self._emitir(tipo="terminado", mensaje="Sin dependencias.")
            return

        try:
            self.opciones.carpeta.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._emitir(tipo="error", mensaje=f"No se puede usar la carpeta: {exc}")
            self._emitir(tipo="terminado", mensaje="Carpeta invalida.")
            return

        libre = espacio_libre(self.opciones.carpeta)
        if libre and libre < 1024**3:
            self._avisar(
                f"Aviso: quedan solo {fmt_tamano(libre)} libres en ese disco."
            )

        self._cookies = preparar_cookies(self.opciones, avisar=self._avisar)

        for url in urls:
            self._cola.put(url)

        cuantos = max(1, min(self.opciones.simultaneas, 4, len(urls)))
        hilos = [
            threading.Thread(target=self._trabajador, args=(yt_dlp,), daemon=True)
            for _ in range(cuantos)
        ]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        if self._cancelar.is_set():
            mensaje = f"Cancelado: {self._exitos} completado(s)."
        else:
            mensaje = f"Listo: {self._exitos} completado(s), {self._fallos} con error."
        self._emitir(tipo="terminado", mensaje=mensaje)


class _Logger:
    """Redirige los mensajes de yt-dlp a la cola de eventos."""

    def __init__(self, emitir: Callable[..., None]):
        self._emitir = emitir

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            return
        if msg.strip():
            self._emitir(tipo="log", mensaje=msg)

    def info(self, msg: str) -> None:
        self._emitir(tipo="log", mensaje=msg)

    def warning(self, msg: str) -> None:
        self._emitir(tipo="log", mensaje=f"Aviso: {msg}")

    def error(self, msg: str) -> None:
        self._emitir(tipo="log", mensaje=f"Error: {msg}")


# -------------------------------------------------------------------- helpers


def titulo_de(info: Any) -> str:
    if isinstance(info, dict):
        if info.get("title"):
            return str(info["title"])
        entradas = info.get("entries") or []
        if entradas:
            nombre = info.get("playlist") or info.get("id") or "Lista"
            return f"{nombre} ({len(entradas)} elementos)"
    return ""


def resultados(info: Any) -> tuple[int, int]:
    """(archivos obtenidos, elementos procesados) de un extract_info."""
    if not isinstance(info, dict):
        return 0, 0
    entradas = info.get("entries")
    if entradas is not None:
        # entries puede venir como generador ya consumido: se materializa una
        # sola vez para no contar cero por error.
        items = [e for e in list(entradas) if isinstance(e, dict)]
        return sum(1 for e in items if archivo_de(e)), max(len(items), 1)
    return (1 if archivo_de(info) else 0), 1


def archivo_de(info: Any) -> str:
    if isinstance(info, dict):
        pedidos = info.get("requested_downloads") or []
        if pedidos and isinstance(pedidos[0], dict):
            return pedidos[0].get("filepath", "")
        return info.get("filepath", "") or ""
    return ""


def _reemplazar_ruta(info: Any, nueva: str) -> None:
    """Deja constancia del archivo final tras convertirlo."""
    if not isinstance(info, dict) or not nueva:
        return
    pedidos = info.get("requested_downloads") or []
    if pedidos and isinstance(pedidos[0], dict):
        pedidos[0]["filepath"] = nueva
    else:
        info["filepath"] = nueva


def _verificar_audio(info: Any, formato: str) -> None:
    """Comprueba que 'solo audio' entrego de verdad un archivo de audio.

    Si el origen no tiene pista de audio, yt-dlp deja el video sin convertir y
    la descarga pasaria por buena aunque no sea lo que se pidio.
    """
    if not isinstance(info, dict):
        return
    for elemento in info.get("entries") or [info]:
        archivo = archivo_de(elemento)
        if not archivo:
            continue
        if Path(archivo).suffix.lower().lstrip(".") == formato:
            continue
        medios = analizar_medios(archivo)
        if medios and not medios.get("audio"):
            raise RuntimeError(
                "Ese video no tiene pista de audio, asi que no se puede "
                f"obtener un {formato.upper()}. Se guardo el archivo tal cual."
            )
        raise RuntimeError(
            f"No se pudo convertir a {formato.upper()} (quedo como "
            f"{Path(archivo).suffix or 'sin extension'}). Revisa que ffmpeg "
            "este instalado: ejecuta setup.ps1."
        )


def _ya_en_historial(info: Any) -> bool:
    """Distingue 'ya lo tenias' de 'fallo la descarga'."""
    if not HISTORIAL_PATH.exists() or not isinstance(info, dict):
        return False
    ident = info.get("id") or ""
    if not ident:
        return False
    try:
        return ident in HISTORIAL_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def fmt_velocidad(bps: float | None) -> str:
    if not bps:
        return ""
    unidades = ["B/s", "KB/s", "MB/s", "GB/s"]
    i = 0
    while bps >= 1024 and i < len(unidades) - 1:
        bps /= 1024
        i += 1
    return f"{bps:.1f} {unidades[i]}"


def fmt_eta(segundos: float | None) -> str:
    if not segundos:
        return ""
    segundos = int(segundos)
    m, s = divmod(segundos, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


SUGERENCIA_COOKIES = (
    "Si es YouTube o contenido privado, pulsa 'Renovar sesion guardada'; "
    "si no hay ninguna sesion que copiar, inicia sesion en Firefox o usa un "
    "archivo cookies.txt exportado."
)


def mensaje_amigable(exc: Exception) -> str:
    texto = str(exc)
    pistas = [
        ("ffmpeg", "Falta ffmpeg: ejecuta setup.ps1 para instalarlo en ./bin."),
        ("Sign in to confirm", f"El sitio pide sesion. {SUGERENCIA_COOKIES}"),
        ("login required", f"Contenido privado. {SUGERENCIA_COOKIES}"),
        (
            "Could not copy Chrome cookie database",
            "No se pudieron leer las cookies de ese navegador (esta abierto y "
            "cifra su base). Usa Firefox o un archivo cookies.txt exportado.",
        ),
        (
            "403",
            "El servidor rechazo la descarga (403). En YouTube suele ser sesion "
            f"vencida. {SUGERENCIA_COOKIES}",
        ),
        (
            "Requested format is not available",
            "No hay formatos con esa calidad; prueba 'mejor calidad disponible' "
            f"o revisa la sesion. {SUGERENCIA_COOKIES}",
        ),
        ("Private video", "El video es privado."),
        ("Video unavailable", "El video no esta disponible (borrado o restringido)."),
        ("HTTP Error 404", "URL no encontrada (404)."),
        ("Unsupported URL", "Ese enlace no esta soportado por yt-dlp."),
        ("rate-limit", "El sitio esta limitando las peticiones; espera un poco."),
        ("No space left", "El disco se quedo sin espacio."),
    ]
    bajo = texto.lower()
    for clave, amigable in pistas:
        if clave.lower() in bajo:
            return f"{amigable}\n  ({texto.strip()[:300]})"
    return texto.strip()[:400]


# ------------------------------------------------- consultas sin descargar


def analizar_url(url: str, op: Opciones | None = None) -> dict:
    """Datos de una URL sin descargar nada: titulo, duracion, tamano estimado."""
    import yt_dlp

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": not (op.playlist if op else False),
        "extract_flat": "in_playlist",
    }
    motores = motores_js()
    if motores:
        opts["js_runtimes"] = motores
    opts["remote_components"] = ["ejs:github"]

    if op is not None:
        cookies = preparar_cookies(op)
        if cookies:
            opts["cookiefile"] = cookies

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}

    entradas = info.get("entries")
    if entradas is not None:
        items = [e for e in list(entradas) if isinstance(e, dict)]
        return {
            "titulo": info.get("title") or info.get("id") or "Lista",
            "es_lista": True,
            "elementos": len(items),
            "duracion": sum(e.get("duration") or 0 for e in items),
            "tamano": 0,
        }
    return {
        "titulo": info.get("title") or "",
        "es_lista": False,
        "elementos": 1,
        "duracion": info.get("duration") or 0,
        "tamano": info.get("filesize") or info.get("filesize_approx") or 0,
        "autor": info.get("uploader") or "",
        "sitio": info.get("extractor_key") or "",
    }


def actualizar_ytdlp(progreso=None) -> tuple[bool, str]:
    """Actualiza yt-dlp (con pip, o bajando la rueda si estamos empaquetados)."""
    return componentes.actualizar_ytdlp(progreso)


def version_ytdlp() -> str:
    try:
        import yt_dlp

        return yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        return "?"


def faltan_componentes() -> list[str]:
    """Que le falta a este equipo para poder descargar en condiciones."""
    return componentes.faltantes()


def instalar_componentes(progreso=None, parar=None) -> tuple[bool, list[str]]:
    """Descarga ffmpeg y el motor JS que falten, sin necesitar Python ni pip."""
    return componentes.instalar_faltantes(progreso, parar)
