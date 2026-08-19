# Descargador de Videos

Aplicación de escritorio para Windows que descarga videos de **YouTube, Facebook,
Instagram, TikTok, X/Twitter, Vimeo, Twitch, Dailymotion** y ~1800 sitios más,
además de enlaces directos a archivos de video. Usa [yt-dlp](https://github.com/yt-dlp/yt-dlp)
como motor y [ffmpeg](https://ffmpeg.org/) para unir pistas y convertir.

Tiene interfaz gráfica y también línea de comandos.

## Descargar

**[Descarga la última versión →](https://github.com/PabloMarmolejo/simple-video-downloader/releases/latest)**

Un solo archivo de 23 MB. No necesita Python ni instalación: doble clic y listo.
La primera vez descarga por su cuenta los dos componentes que le falten al
equipo, avisándote antes.

---

## Llevarlo a otro equipo: un solo archivo

Ejecuta una vez:

```powershell
powershell -ExecutionPolicy Bypass -File herramientas\construir_exe.ps1
```

Se genera **`DescargadorDeVideos.exe`** (23 MB) en la raiz. Ese archivo suelto es todo
lo que hay que copiar al otro equipo: por USB, por correo o por la nube. Allí:

1. Doble clic. **No hace falta Python, ni instalar nada, ni permisos de
   administrador.**
2. El programa revisa qué tiene el equipo. Si le falta ffmpeg o el motor de
   JavaScript, aparece una ventana que lo explica en una frase y ofrece
   descargarlos, con barra de progreso.
3. Se aceptan y quedan guardados junto al `.exe`. A partir de ahí abre directo.

### Dónde guarda sus cosas

El ejecutable **no crea carpetas a su lado**: ffmpeg, la sesión y las
preferencias van a `%LOCALAPPDATA%\DescargadorDeVideos`. Así puedes dejarlo
suelto en Descargas o en el escritorio sin que te llene la carpeta.

¿Lo prefieres portable, con todo junto en un USB? Crea un archivo vacío llamado
**`portable.txt`** al lado del `.exe` y guardará ahí mismo, en subcarpetas `bin`
y `datos`. El paquete que genera `construir_exe.ps1 -ConBin` ya se comporta así
por venir con su carpeta `bin`.

La primera apertura necesita internet para esa descarga (~146 MB). Para equipos
sin conexión, copia el `.exe` junto con la carpeta `bin`: así no descarga nada.

> Windows muestra el aviso de SmartScreen la primera vez, porque el `.exe` no
> está firmado digitalmente: *Más información* → *Ejecutar de todas formas*.

### Desarrollo (con Python)

Haz doble clic en **`Abrir Descargador.bat`**. La primera vez crea un entorno virtual
e instala yt-dlp, ffmpeg y deno. Requiere **Python 3.9 o superior**
(https://www.python.org/downloads/, marcando "Add python.exe to PATH").

---

## Aspecto

Arriba a la derecha, junto al selector de vista, hay un **icono de luna o sol**:
lo pulsas y la ventana cambia entre tema claro y oscuro al instante. El icono
muestra a dónde vas al pulsarlo —luna si estás en claro, sol si estás en
oscuro—, y la elección se guarda para la próxima vez.

La aplicación **abre en tema claro** la primera vez.

El color tiene significado y no es decorativo:

- **azul de acento** en la barra superior, el botón *Descargar* y la opción
  elegida — lo que hay que mirar o pulsar;
- **verde** cuando algo terminó bien, **rojo** cuando falló, **azul** mientras
  está en curso, en la misma columna de estado;
- el panel de detalles técnicos va sobre fondo oscuro en ambos temas, para que
  se lea como una consola sin competir con el resto.

Toda la paleta vive en `descargador/tema.py`: cambiar el acento de la aplicación
entera es cambiar un valor ahí.

---

## Dos vistas: Simple y Completa

Arriba a la derecha hay un selector **[ Simple ] [ Completa ]**. Se cambia con
un clic y no se pierde nada de lo que estuvieras haciendo: los enlaces, la lista
de descargas y el progreso son los mismos en ambas.

| | Simple | Completa |
|---|---|---|
| Enlaces y botón de descargar | ✅ | ✅ |
| Calidad | Tres opciones en lenguaje llano | Resoluciones exactas, MP3/M4A, kbps |
| Carpeta destino | ✅ | ✅ |
| Lista de descargas | Título, estado y progreso | + velocidad y tiempo restante |
| Listas, recortes, subtítulos, proxy… | — | ✅ |
| Sesión (cookies) | Automática | Configurable |
| Panel de detalles técnicos | — | ✅ |

La vista **Simple** es la que aparece al estrenar la aplicación. Deja fuera todo
lo que se puede decidir solo: sesión automática, compatibilidad activada, una
descarga a la vez. Y lo que no se ve, no actúa: si en la vista completa dejaste
configurado un recorte o cuatro descargas en paralelo, la vista simple los
ignora en lugar de aplicarlos por sorpresa.

Cuando algo falla en vista simple —donde el panel de detalles está oculto— sale
un aviso con el motivo y la opción de pasar a la vista completa para verlo.

---

## Uso con interfaz gráfica

Doble clic en **`DescargadorDeVideos.exe`** (o en `Abrir Descargador.bat` si
prefieres usar el Python del equipo).

1. Pega uno o varios enlaces (uno por línea). Si tenías un enlace copiado, ya
   aparece escrito al abrir.
2. Elige la calidad, o **Solo audio MP3**.
3. Pulsa **Descargar** (o `Ctrl+Enter`; `Esc` cancela).

Lo que sigue describe la vista **Completa**.

La tabla muestra el progreso de cada enlace con velocidad y tiempo restante, y
la segunda barra indica cuánto falta del lote completo.

**Doble clic en una fila abre el archivo descargado.** Con clic derecho tienes
*Abrir archivo*, *Mostrar en la carpeta*, *Copiar enlace*, *Reintentar este* y
*Quitar de la lista*. Si algo falla, el botón **Reintentar fallidos** repite solo
los que no salieron.

### Pestaña Básico

| Opción | Para qué sirve |
|---|---|
| Calidad | Desde "mejor disponible" hasta 360p, o solo audio MP3/M4A |
| Audio (kbps) | Calidad del MP3: 96 a 320 (se activa al elegir MP3) |
| Guardar en | Carpeta destino |
| Nombre del archivo | Plantilla: `Título [id]`, `Autor - Título`, `Fecha - Título`, una carpeta por autor… |
| Lista/canal completo | Baja toda la playlist en vez de solo el video del enlace |
| Subtítulos | Descarga los subtítulos disponibles |
| Miniatura | Usa la miniatura como carátula |
| Compatibilidad máxima | Deja el resultado en H.264 + AAC (ver abajo) |
| Perfil | Guarda toda la configuración con un nombre y la recupera después |

### Pestaña Avanzado

| Opción | Para qué sirve |
|---|---|
| Descargas a la vez | De 1 a 4 en paralelo |
| Límite de velocidad | Ej. `2M` para no saturar la conexión |
| Historial | No vuelve a descargar lo que ya bajaste antes |
| Recortar de… a… | Baja solo un fragmento: `1:30` a `2:45` |
| De la lista, del… al… | Rango de una playlist: del 5 al 12 |
| Subtítulos | Idioma, y si van incrustados o como `.srt` aparte |
| Proxy | Ej. `socks5://127.0.0.1:1080` |
| Avisar al terminar | Sonido al acabar la tanda |

---

## La sesión (cookies): automática

Desde 2025 YouTube rechaza con `HTTP 403` las descargas que no vienen de una
sesión real. Lo mismo pasa con contenido privado de Facebook e Instagram. La app
se encarga sola:

1. La **primera** descarga copia la sesión del navegador a un `cookies.txt`
   propio, dentro de la carpeta de la aplicación.
2. A partir de ahí usa **ese archivo**. Ya no vuelve a tocar el navegador: da
   igual que esté abierto, cerrado o desinstalado.
3. Si esa sesión caduca, lo detecta, la renueva y **reintenta la descarga**
   automáticamente.

El desplegable de la pestaña *Sesión* queda en *Automático* y no hace falta
tocarlo. El botón **Renovar sesión guardada** fuerza el paso 1 cuando quieras.

### Por qué Firefox es el que mejor funciona

En Windows, **Firefox permite leer sus cookies con el navegador abierto**. Los
basados en Chromium (Chrome, Edge, Brave) no: bloquean su base de datos mientras
corren y, desde Chrome 127, cifran las cookies con *App-Bound Encryption*, que no
se puede descifrar desde fuera del navegador —ni cerrándolo—. Si solo usas
Chrome, tienes dos salidas:

- Inicia sesión en YouTube **una vez en Firefox**; o
- exporta un `cookies.txt` (formato Netscape) con una extensión de navegador y
  selecciónalo en el campo correspondiente.

### Privacidad

El `cookies.txt` se guarda solo en tu equipo, con permisos restringidos a tu
usuario, y contiene **únicamente** cookies de sitios de video; el resto de tu
navegación se descarta al copiarlas. Aun así son credenciales de sesión: no lo
compartas (ya está en `.gitignore`). Para borrarlo, elimina el archivo.

---

## Calidad y compatibilidad

Se prefiere siempre **H.264 + AAC-LC en MP4**, que reproduce cualquier televisor,
celular o editor.

Cuando el sitio **no ofrece** ningún formato compatible —típico en los reels de
Facebook e Instagram, que van en AV1 con audio HE-AAC— la casilla
**"Compatibilidad máxima"**, activada por defecto, arregla el archivo al
terminar:

- Si el video ya viene en H.264 y solo el audio es raro, convierte **solo el
  audio**: tarda un segundo y no toca la calidad de imagen.
- Si el video viene en AV1 o VP9, lo recodifica a H.264 (esto sí tarda).
- Si ya era compatible, no hace nada.

Se conservan subtítulos, capítulos, carátula y metadatos al convertir.

Ese caso es el que produce el clásico **"se ve pero no se oye"**: el archivo
tiene su audio intacto, pero el reproductor no sabe decodificar HE-AAC o AV1.

---

## Uso desde consola

```powershell
# video en la mejor calidad
herramientas\consola.bat "https://youtu.be/XXXXXXXX"

# 1080p en una carpeta concreta
herramientas\consola.bat -f 1080 -o "D:\Videos" "https://www.facebook.com/watch/?v=123456"

# solo audio MP3 a 320 kbps
herramientas\consola.bat --mp3 --calidad-audio 320 "https://youtu.be/XXXXXXXX"

# solo un fragmento
herramientas\consola.bat --desde 1:30 --hasta 2:45 "https://youtu.be/XXXXXXXX"

# del 5 al 12 de una lista, tres a la vez
herramientas\consola.bat --playlist --desde-elemento 5 --hasta-elemento 12 --simultaneas 3 "URL"

# ver qué es un enlace sin descargarlo
herramientas\consola.bat --analizar "https://youtu.be/XXXXXXXX"

# muchos enlaces desde un archivo, sin repetir lo ya bajado
herramientas\consola.bat --lista enlaces.txt --historial
```

`herramientas\consola.bat -h` lista todas las opciones.

---

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `HTTP Error 403` o "no se descargó ningún archivo" en YouTube | Pulsa **Renovar sesión guardada**. Si no hay sesión que copiar, inicia sesión en YouTube desde Firefox o usa un `cookies.txt` |
| `Could not copy Chrome cookie database` | Normal: Chrome/Edge/Brave cifran sus cookies. La app pasa sola al siguiente navegador |
| **El video se ve pero no se oye** | Deja marcada "Compatibilidad máxima". Si aun así pasa, tu reproductor es el problema: pruébalo en VLC |
| "Requested format is not available" | Prueba "mejor calidad disponible"; suele ser falta de sesión |
| Falla un sitio que antes funcionaba | Pulsa **Actualizar yt-dlp** (los sitios cambian seguido); funciona también en el `.exe`, sin Python |
| Falta ffmpeg o el motor JS | Pulsa **Instalar componentes**: los descarga solo |
| Windows avisa de SmartScreen | El `.exe` no está firmado: *Más información* → *Ejecutar de todas formas* |
| Pediste MP3 y avisa que no hay audio | Ese video no tiene pista de audio; no es un fallo de la app |

---

## Cómo está hecho

```
DescargadorDeVideos.exe        La aplicación (se crea al empaquetar)
Abrir Descargador.bat          Abrirla con el Python del equipo
LEEME.txt                      Instrucciones de tres líneas
README.md                      Este manual

descargador/core.py            Motor: opciones de yt-dlp, hilos, cookies, conversión
descargador/componentes.py     Detecta e instala ffmpeg, deno y yt-dlp por su cuenta
descargador/tema.py            Paleta y estilos (tema claro y oscuro)
descargador/gui.py             Interfaz Tkinter (sin dependencias extra)
descargador/cli.py             Interfaz de consola

herramientas/setup.ps1         Instalador para desarrollo: venv + yt-dlp + ffmpeg
herramientas/construir_exe.ps1 Empaqueta todo en un .exe con PyInstaller
herramientas/consola.bat       Lanza la versión de consola
herramientas/lanzador.py       Punto de entrada del ejecutable

pruebas/test_core.py           40 pruebas de la lógica pura
bin/                           ffmpeg.exe, ffprobe.exe, deno.exe
datos/                         cookies.txt, config.json, historial.txt
```

La carpeta `datos/` la crea el programa solo, y ahí guarda la sesión, tus
preferencias y el historial. Si vienes de una versión anterior que los dejaba
sueltos en la raíz, se mudan solos la primera vez.

Las descargas corren en hilos aparte y se comunican con la interfaz por una cola
de eventos: la ventana nunca se congela y **Cancelar** corta al instante, incluso
durante una conversión de ffmpeg.

Para ejecutar las pruebas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s pruebas -v
```

---

## Licencia

Código propio bajo **MIT** (ver [LICENSE](LICENSE)): puedes usarlo, modificarlo
y redistribuirlo, incluso comercialmente, conservando el aviso de copyright.

Los componentes de terceros —yt-dlp, ffmpeg, deno, Python— tienen sus propias
licencias, detalladas en [TERCEROS.md](TERCEROS.md). Ahí se explica también por
qué ffmpeg (GPL v3) se descarga aparte en lugar de empaquetarse: así el código
propio puede seguir siendo MIT sin conflicto.

## Nota de uso

Descarga únicamente contenido propio, de dominio público, con licencia abierta
(como Creative Commons) o cuando tengas permiso del titular. Respeta los términos
de servicio de cada plataforma y la legislación de derechos de autor aplicable.
