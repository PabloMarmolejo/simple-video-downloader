r"""Pruebas de la logica pura del nucleo.

Ejecutar:  .\.venv\Scripts\python.exe -m unittest discover -s pruebas -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from descargador.core import (  # noqa: E402
    Descargador,
    Opciones,
    PLANTILLA_DEFECTO,
    _ajustar_plantilla,
    _incompatibilidades,
    _rango_playlist,
    _verificar_audio,
    a_bytes,
    a_segundos,
    archivo_de,
    construir_opts,
    fmt_eta,
    fmt_tamano,
    fmt_velocidad,
    mensaje_amigable,
    resultados,
    titulo_de,
)


def opciones(**extra) -> Opciones:
    extra.setdefault("carpeta", Path("C:/tmp"))
    return Opciones(**extra)


def _limite_titulo(plantilla: str) -> int:
    """El numero de %(title).NNNB de una plantilla."""
    return int(re.search(r"%\(title\)\.(\d+)B", plantilla).group(1))


class PruebaConversiones(unittest.TestCase):
    def test_a_bytes(self):
        self.assertEqual(a_bytes("2M"), 2 * 1024**2)
        self.assertEqual(a_bytes("500K"), 500 * 1024)
        self.assertEqual(a_bytes("1.5G"), int(1.5 * 1024**3))
        self.assertEqual(a_bytes("1024"), 1024)

    def test_a_bytes_invalido(self):
        for valor in ("", "   ", "abc", "M"):
            self.assertIsNone(a_bytes(valor), valor)

    def test_a_segundos(self):
        self.assertEqual(a_segundos("90"), 90)
        self.assertEqual(a_segundos("1:30"), 90)
        self.assertEqual(a_segundos("1:00:00"), 3600)

    def test_a_segundos_invalido(self):
        self.assertIsNone(a_segundos(""))
        self.assertIsNone(a_segundos("hola"))

    def test_formatos_legibles(self):
        self.assertEqual(fmt_velocidad(1024), "1.0 KB/s")
        self.assertEqual(fmt_velocidad(None), "")
        self.assertEqual(fmt_eta(90), "1:30")
        self.assertEqual(fmt_eta(3661), "1:01:01")
        self.assertEqual(fmt_tamano(1024**2), "1.0 MB")


class PruebaCompatibilidad(unittest.TestCase):
    def test_ya_compatible_no_se_toca(self):
        medios = {"video": "h264", "audio": "aac", "perfil_audio": "LC"}
        self.assertEqual(_incompatibilidades(medios), (False, False))

    def test_he_aac_se_convierte(self):
        """El caso real de los reels: se ve pero no se oye."""
        medios = {"video": "h264", "audio": "aac", "perfil_audio": "HE-AAC"}
        self.assertEqual(_incompatibilidades(medios), (False, True))

    def test_av1_y_opus_se_convierten(self):
        medios = {"video": "av1", "audio": "opus", "perfil_audio": ""}
        self.assertEqual(_incompatibilidades(medios), (True, True))

    def test_sin_datos_no_hace_nada(self):
        self.assertEqual(_incompatibilidades({}), (False, False))

    def test_video_mudo_no_inventa_audio(self):
        medios = {"video": "av1", "subtitulos": 0}
        self.assertEqual(_incompatibilidades(medios), (True, False))


class PruebaOpciones(unittest.TestCase):
    def test_video_prefiere_h264(self):
        opts = construir_opts(opciones(formato="1080"))
        self.assertIn("avc1", opts["format"])
        self.assertEqual(opts["merge_output_format"], "mp4")

    def test_mp3_usa_la_calidad_pedida(self):
        opts = construir_opts(opciones(formato="mp3", calidad_audio="320"))
        pp = [p for p in opts["postprocessors"] if p["key"] == "FFmpegExtractAudio"]
        self.assertEqual(pp[0]["preferredquality"], "320")

    def test_plantilla_invalida_cae_en_la_de_casa(self):
        opts = construir_opts(opciones(plantilla="sin variables"))
        self.assertTrue(opts["outtmpl"]["default"].endswith(PLANTILLA_DEFECTO))

    def test_limite_de_velocidad(self):
        self.assertEqual(construir_opts(opciones(limite_velocidad="2M"))["ratelimit"],
                         2 * 1024**2)
        self.assertNotIn("ratelimit", construir_opts(opciones()))

    def test_recorte_activa_rangos(self):
        opts = construir_opts(opciones(seccion_inicio="0:30", seccion_fin="1:00"))
        self.assertIn("download_ranges", opts)
        self.assertTrue(opts["force_keyframes_at_cuts"])

    def test_sin_recorte_no_hay_rangos(self):
        self.assertNotIn("download_ranges", construir_opts(opciones()))

    def test_historial_opcional(self):
        self.assertIn("download_archive", construir_opts(opciones(usar_historial=True)))
        self.assertNotIn("download_archive", construir_opts(opciones()))

    def test_subtitulos_aparte_vs_incrustados(self):
        aparte = construir_opts(opciones(subtitulos=True, subs_aparte=True))
        claves = [p["key"] for p in aparte["postprocessors"]]
        self.assertIn("FFmpegSubtitlesConvertor", claves)
        self.assertNotIn("FFmpegEmbedSubtitle", claves)

        dentro = construir_opts(opciones(subtitulos=True))
        claves = [p["key"] for p in dentro["postprocessors"]]
        self.assertIn("FFmpegEmbedSubtitle", claves)

    def test_carpeta_larga_recorta_el_titulo_no_la_ruta(self):
        """Windows corta en 260 caracteres.

        El recorte tiene que caer sobre el titulo: si se recorta la ruta, el
        archivo acaba en otra carpeta o sin nombre.
        """
        larga = Path("C:/" + "carpeta_muy_larga/" * 12)
        ajustada = _ajustar_plantilla(larga, PLANTILLA_DEFECTO)
        self.assertLess(_limite_titulo(ajustada), 150)
        self.assertGreaterEqual(_limite_titulo(ajustada), 40)

        salida = construir_opts(opciones(carpeta=larga))["outtmpl"]["default"]
        self.assertTrue(salida.startswith(str(larga)))
        self.assertTrue(salida.endswith(".%(ext)s"))

    def test_carpeta_corta_conserva_el_limite(self):
        self.assertEqual(
            _limite_titulo(_ajustar_plantilla(Path("C:/videos"), PLANTILLA_DEFECTO)),
            150)


class PruebaRangoPlaylist(unittest.TestCase):
    def test_rango_completo(self):
        self.assertEqual(
            _rango_playlist(opciones(playlist_desde="3", playlist_hasta="10")), "3-10")

    def test_solo_desde(self):
        self.assertEqual(_rango_playlist(opciones(playlist_desde="3")), "3:")

    def test_solo_hasta(self):
        self.assertEqual(_rango_playlist(opciones(playlist_hasta="5")), "1-5")

    def test_vacio(self):
        self.assertEqual(_rango_playlist(opciones()), "")


class PruebaResultados(unittest.TestCase):
    def test_video_suelto_con_archivo(self):
        info = {"requested_downloads": [{"filepath": "C:/v.mp4"}]}
        self.assertEqual(resultados(info), (1, 1))
        self.assertEqual(archivo_de(info), "C:/v.mp4")

    def test_video_sin_archivo_es_fallo(self):
        self.assertEqual(resultados({"id": "x"}), (0, 1))

    def test_lista_parcial(self):
        info = {"entries": [
            {"requested_downloads": [{"filepath": "a.mp4"}]},
            {"id": "b"},
            {"requested_downloads": [{"filepath": "c.mp4"}]},
        ]}
        self.assertEqual(resultados(info), (2, 3))

    def test_entries_generador(self):
        """entries puede llegar como generador; no debe contarse como cero."""
        info = {"entries": iter([{"requested_downloads": [{"filepath": "a.mp4"}]}])}
        self.assertEqual(resultados(info), (1, 1))

    def test_none_no_revienta(self):
        self.assertEqual(resultados(None), (0, 0))
        self.assertEqual(archivo_de(None), "")

    def test_titulo_de_lista(self):
        info = {"playlist": "Mi lista", "entries": [{}, {}]}
        self.assertIn("2 elementos", titulo_de(info))


class PruebaRenovacionSesion(unittest.TestCase):
    """La renovacion de cookies solo debe dispararse por fallos de sesion."""

    def test_dispara_con_403(self):
        self.assertTrue(Descargador._renovable(Exception("HTTP Error 403: Forbidden")))

    def test_dispara_si_no_bajo_nada(self):
        self.assertTrue(Descargador._renovable(
            RuntimeError("No se descargo ningun archivo.")))

    def test_no_dispara_con_video_borrado(self):
        self.assertFalse(Descargador._renovable(Exception("Video unavailable")))

    def test_no_dispara_con_video_privado(self):
        self.assertFalse(Descargador._renovable(Exception("Private video")))

    def test_no_dispara_con_404(self):
        self.assertFalse(Descargador._renovable(Exception("HTTP Error 404")))


class PruebaVerificacionAudio(unittest.TestCase):
    """Pedir MP3 y recibir un MP4 no puede pasar por exito."""

    def test_mp3_correcto_no_protesta(self):
        info = {"requested_downloads": [{"filepath": "C:/musica/tema.mp3"}]}
        _verificar_audio(info, "mp3")   # no debe lanzar

    def test_mp3_que_quedo_en_mp4_falla(self):
        info = {"requested_downloads": [{"filepath": "C:/musica/tema.mp4"}]}
        with self.assertRaises(RuntimeError) as caso:
            _verificar_audio(info, "mp3")
        self.assertIn("MP3", str(caso.exception))

    def test_sin_archivo_no_revienta(self):
        _verificar_audio({"id": "x"}, "mp3")
        _verificar_audio(None, "mp3")


class PruebaMensajes(unittest.TestCase):
    def test_traduce_403(self):
        self.assertIn("sesion", mensaje_amigable(Exception("HTTP Error 403")).lower())

    def test_desconocido_se_recorta(self):
        largo = mensaje_amigable(Exception("x" * 900))
        self.assertLessEqual(len(largo), 400)


if __name__ == "__main__":
    unittest.main()
