# Componentes de terceros

Este proyecto es software libre bajo licencia MIT (ver [LICENSE](LICENSE)), pero
se apoya en otros proyectos que tienen sus propias licencias. Aquí queda
constancia de cuáles son, qué licencia tienen y cómo se usan, porque no todos se
tratan igual.

## Empaquetados dentro de `DescargadorDeVideos.exe`

| Componente | Licencia | Para qué |
|---|---|---|
| [Python 3.13](https://www.python.org/) | PSF License | El intérprete y su biblioteca estándar, incluido Tkinter (Tcl/Tk, licencia estilo BSD) |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | The Unlicense (dominio público) | El motor de extracción y descarga |
| [Brotli](https://github.com/google/brotli) | MIT | Descompresión de respuestas HTTP |
| [certifi](https://github.com/certifi/python-certifi) | MPL 2.0 | Certificados raíz para las conexiones HTTPS |

El código fuente de estos componentes está disponible públicamente en los
enlaces anteriores. En el caso de certifi, la MPL 2.0 exige que ese código siga
siendo accesible, y lo está en su repositorio oficial.

## Descargados aparte, nunca empaquetados

Estos **no** viajan dentro del ejecutable: la aplicación los descarga en la
carpeta `bin` la primera vez que se abre, y los ejecuta como programas
independientes.

| Componente | Licencia | Para qué |
|---|---|---|
| [ffmpeg](https://ffmpeg.org/) (compilación de [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)) | **GPL v3** | Unir video y audio, convertir a MP3, arreglar formatos incompatibles |
| [deno](https://deno.com/) | MIT | Motor de JavaScript que YouTube exige para entregar los formatos buenos |

### Por qué importa la distinción con ffmpeg

La compilación de ffmpeg que se descarga es **GPL v3**, una licencia con efecto
contagioso: si formara parte del programa, obligaría a licenciar todo bajo GPL.

No es el caso. La aplicación **invoca ffmpeg como un proceso aparte**, igual que
lo haría escribiéndolo en una consola, y no enlaza con sus bibliotecas ni
incluye su código. Eso deja el código propio bajo MIT sin conflicto, y es la
razón por la que el instalador descarga ffmpeg en lugar de incrustarlo.

**Si repartes la aplicación junto con la carpeta `bin`** (lo que hace
`construir_exe.ps1 -ConBin`), estás distribuyendo también un binario GPL v3.
Eso es legítimo —son dos programas agrupados, no uno derivado del otro—, pero
entonces te corresponde acompañarlo de la licencia de ffmpeg y de la referencia
a su código fuente, que gyan.dev publica junto a cada compilación.

Por eso las *releases* de este repositorio incluyen **solo el ejecutable**: cada
equipo descarga ffmpeg por su cuenta desde la fuente original.

## Sobre el uso

La herramienta no rompe ninguna protección: pide los mismos formatos que
entrega el reproductor web del sitio. Descarga únicamente contenido propio, de
dominio público, con licencia abierta o con permiso del titular, y respeta los
términos de servicio de cada plataforma.
