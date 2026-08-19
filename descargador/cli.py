"""Version de linea de comandos del descargador.

Ejemplos:
    python -m descargador.cli "https://youtu.be/XXXX"
    python -m descargador.cli -f 1080 -o D:/Videos url1 url2
    python -m descargador.cli --mp3 --calidad-audio 320 "https://youtu.be/XXXX"
    python -m descargador.cli --lista enlaces.txt --playlist --simultaneas 3
    python -m descargador.cli --desde 1:30 --hasta 2:45 "https://youtu.be/XXXX"
"""

from __future__ import annotations

import argparse
import queue
import sys
from pathlib import Path

from .core import (
    AUTOMATICO,
    CALIDADES_AUDIO,
    IDIOMAS_SUBS,
    PLANTILLA_DEFECTO,
    Descargador,
    Opciones,
    analizar_url,
    carpeta_descargas_por_defecto,
    ffmpeg_path,
    fmt_eta,
    fmt_tamano,
    motores_js,
    version_ytdlp,
)

# Alias comodos en consola -> valores que entiende el nucleo.
ORIGENES_COOKIES = {"auto": AUTOMATICO, "no": "Ninguno", "ninguno": "Ninguno"}


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="descargador",
        description="Descarga videos de YouTube, Facebook, Instagram, TikTok, X, "
                    "Vimeo y ~1800 sitios mas (motor: yt-dlp).",
    )
    p.add_argument("urls", nargs="*", help="una o mas URLs")
    p.add_argument("-o", "--salida", metavar="CARPETA",
                   default=str(carpeta_descargas_por_defecto()),
                   help="carpeta destino (por defecto: %(default)s)")
    p.add_argument("-f", "--formato", default="best",
                   choices=["best", "2160", "1440", "1080", "720", "480", "360",
                            "mp3", "m4a"],
                   help="calidad maxima de video o solo audio (por defecto: best)")
    p.add_argument("--mp3", action="store_true", help="atajo de --formato mp3")
    p.add_argument("--calidad-audio", default="192", choices=CALIDADES_AUDIO,
                   help="kbps del MP3 (por defecto: %(default)s)")
    p.add_argument("--plantilla", default=PLANTILLA_DEFECTO, metavar="PATRON",
                   help="plantilla de nombre al estilo yt-dlp")

    p.add_argument("--playlist", action="store_true",
                   help="descargar la lista/canal completo, no solo el video")
    p.add_argument("--desde-elemento", default="", metavar="N",
                   help="primer elemento de la lista a bajar")
    p.add_argument("--hasta-elemento", default="", metavar="N",
                   help="ultimo elemento de la lista a bajar")

    p.add_argument("--desde", default="", metavar="TIEMPO",
                   help="recortar: inicio, p.ej. 1:30")
    p.add_argument("--hasta", default="", metavar="TIEMPO",
                   help="recortar: fin, p.ej. 2:45")

    p.add_argument("--subtitulos", action="store_true",
                   help="descargar subtitulos e incrustarlos")
    p.add_argument("--subs-aparte", action="store_true",
                   help="guardar los subtitulos como .srt en vez de incrustarlos")
    p.add_argument("--subs-idioma", default=list(IDIOMAS_SUBS)[0],
                   choices=list(IDIOMAS_SUBS),
                   help="idiomas de subtitulos (por defecto: %(default)s)")
    p.add_argument("--miniatura", action="store_true",
                   help="incrustar la miniatura como caratula")
    p.add_argument("--sin-compatibilidad", action="store_true",
                   help="no convertir a H.264/AAC: deja el archivo tal cual lo "
                        "entrega el sitio (AV1, VP9 u Opus pueden no reproducirse)")

    p.add_argument("--cookies", default="auto", metavar="ORIGEN",
                   help="de donde sacar la sesion: 'auto' (por defecto), un "
                        "navegador concreto (firefox, chrome, edge, brave...) "
                        "o 'no' para no usar ninguna")
    p.add_argument("--cookies-archivo", default="", metavar="ARCHIVO",
                   help="usar un cookies.txt exportado en vez del navegador")

    p.add_argument("--simultaneas", type=int, default=1, choices=[1, 2, 3, 4],
                   help="descargas en paralelo (por defecto: 1)")
    p.add_argument("--limite", default="", metavar="VELOCIDAD",
                   help="limite de descarga, p.ej. 2M")
    p.add_argument("--historial", action="store_true",
                   help="no volver a descargar lo que ya esta en historial.txt")
    p.add_argument("--proxy", default="", metavar="URL",
                   help="proxy, p.ej. socks5://127.0.0.1:1080")

    p.add_argument("--lista", metavar="ARCHIVO",
                   help="archivo de texto con una URL por linea")
    p.add_argument("--analizar", action="store_true",
                   help="solo mostrar datos del enlace, sin descargar")
    p.add_argument("-v", "--verboso", action="store_true",
                   help="mostrar todos los mensajes del motor de descarga")
    p.add_argument("--version", action="store_true",
                   help="mostrar la version de yt-dlp en uso")
    return p


def preparar_consola() -> None:
    """Evita que un emoji del titulo tumbe la descarga.

    La consola de Windows usa cp1252 y revienta con UnicodeEncodeError al
    imprimir caracteres que no estan en esa tabla, cosa habitual en titulos de
    redes sociales.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def reunir_urls(args) -> list[str]:
    urls = list(args.urls)
    if args.lista:
        ruta = Path(args.lista)
        if not ruta.exists():
            print(f"No existe el archivo: {ruta}", file=sys.stderr)
            return []
        urls += [
            l.strip()
            for l in ruta.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
    vistas, limpias = set(), []
    for url in urls:
        if url not in vistas:
            vistas.add(url)
            limpias.append(url)
    return limpias


def construir_opciones(args) -> Opciones:
    return Opciones(
        carpeta=Path(args.salida),
        formato="mp3" if args.mp3 else args.formato,
        playlist=args.playlist,
        subtitulos=args.subtitulos or args.subs_aparte,
        subs_aparte=args.subs_aparte,
        subs_idiomas=list(IDIOMAS_SUBS[args.subs_idioma]),
        miniatura=args.miniatura,
        compatibilidad=not args.sin_compatibilidad,
        calidad_audio=args.calidad_audio,
        plantilla=args.plantilla,
        navegador_cookies=ORIGENES_COOKIES.get(args.cookies.lower(), args.cookies),
        archivo_cookies=args.cookies_archivo,
        limite_velocidad=args.limite,
        simultaneas=args.simultaneas,
        usar_historial=args.historial,
        seccion_inicio=args.desde,
        seccion_fin=args.hasta,
        playlist_desde=args.desde_elemento,
        playlist_hasta=args.hasta_elemento,
        proxy=args.proxy,
    )


def mostrar_analisis(urls: list[str], opciones: Opciones) -> int:
    for url in urls:
        try:
            d = analizar_url(url, opciones)
        except Exception as exc:  # noqa: BLE001
            print(f"{url}\n   no se pudo analizar: {exc}", file=sys.stderr)
            continue
        print(f"\n{d.get('titulo') or url}")
        if d.get("es_lista"):
            print(f"   lista con {d['elementos']} videos, "
                  f"{fmt_eta(d['duracion'])} en total")
        else:
            if d.get("autor"):
                print(f"   autor: {d['autor']}")
            if d.get("duracion"):
                print(f"   duracion: {fmt_eta(d['duracion'])}")
            if d.get("tamano"):
                print(f"   tamano aprox: {fmt_tamano(d['tamano'])}")
            if d.get("sitio"):
                print(f"   sitio: {d['sitio']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    preparar_consola()
    args = construir_parser().parse_args(argv)

    if args.version:
        print(f"yt-dlp {version_ytdlp()}")
        return 0

    urls = reunir_urls(args)
    if not urls:
        construir_parser().print_help()
        return 1

    opciones = construir_opciones(args)

    if args.analizar:
        return mostrar_analisis(urls, opciones)

    if not ffmpeg_path():
        print("Aviso: no se encontro ffmpeg; la calidad puede quedar limitada y "
              "no se podra convertir. Ejecuta setup.ps1.", file=sys.stderr)
    if not motores_js():
        print("Aviso: no hay motor de JavaScript (deno/node); YouTube puede "
              "fallar o dar baja calidad. Ejecuta setup.ps1.", file=sys.stderr)

    eventos: "queue.Queue" = queue.Queue()
    descargador = Descargador(opciones, eventos)
    descargador.iniciar(urls)

    errores = 0
    ultima_linea = 0
    try:
        while True:
            ev = eventos.get()
            if ev.tipo == "inicio":
                print(f"\n>> {ev.url}", flush=True)
            elif ev.tipo == "progreso":
                cuenta = (f" [{ev.indice}/{ev.total_items}]"
                          if ev.total_items > 1 else "")
                linea = (f"   {ev.porcentaje:5.1f}%  {ev.velocidad:>10}  "
                         f"faltan {ev.eta or '--'}{cuenta}   {ev.mensaje}")
                relleno = " " * max(0, ultima_linea - len(linea))
                ultima_linea = len(linea)
                print(linea + relleno, end="\r", flush=True)
            elif ev.tipo == "fin":
                print(f"\n   OK: {ev.titulo}")
                if ev.archivo:
                    print(f"   -> {ev.archivo}")
                sys.stdout.flush()
            elif ev.tipo == "error":
                errores += 1
                sys.stdout.flush()
                print(f"\n   ERROR: {ev.mensaje}", file=sys.stderr, flush=True)
            elif ev.tipo == "log":
                # Sin -v solo se muestran avisos y errores del motor.
                if args.verboso or ev.mensaje.startswith(("Aviso:", "Error:")):
                    sys.stdout.flush()
                    print(f"\n   {ev.mensaje.strip()}", file=sys.stderr, flush=True)
            elif ev.tipo == "terminado":
                print(f"\n{ev.mensaje}", flush=True)
                break
    except KeyboardInterrupt:
        descargador.cancelar()
        print("\nCancelado.", file=sys.stderr)
        return 130

    return 1 if errores else 0


if __name__ == "__main__":
    raise SystemExit(main())
