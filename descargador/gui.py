"""Interfaz grafica (Tkinter) del descargador de videos."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from . import tema
from .componentes import DESCRIPCIONES
from .core import (
    AUTOMATICO,
    CALIDADES_AUDIO,
    FORMATOS,
    IDIOMAS_SUBS,
    NAVEGADORES,
    NAVEGADORES_AUTO,
    PLANTILLAS,
    Descargador,
    Evento,
    Opciones,
    actualizar_ytdlp,
    analizar_url,
    cargar_config,
    carpeta_descargas_por_defecto,
    cookies_cache_utiles,
    espacio_libre,
    extraer_cookies,
    faltan_componentes,
    instalar_componentes,
    fmt_eta,
    fmt_tamano,
    guardar_config,
    version_ytdlp,
)

PLACEHOLDER = (
    "Pega aqui una o mas URLs, una por linea.\n"
    "YouTube, Facebook, Instagram, TikTok, X, Vimeo, Twitch... o un enlace "
    "directo a un video."
)

MAX_LINEAS_LOG = 2000

# En la vista simple solo se ofrecen tres opciones, con nombres que se entienden
# sin saber que es un codec o una resolucion.
CALIDAD_SIMPLE = {
    "mejor": ("Video - mejor calidad disponible",
              "Video con la mejor calidad", "Ocupa mas espacio"),
    "ligero": ("Video - hasta 720p (HD)",
               "Video mas ligero", "Se descarga mas rapido"),
    "musica": ("Solo audio - MP3",
               "Solo el audio (MP3)", "Para escucharlo como musica"),
}


class Asistente(tk.Toplevel):
    """Primer arranque: explica que falta y lo descarga.

    Un equipo recien estrenado no tiene ffmpeg ni motor de JavaScript, y quien
    abre el programa no tiene por que saber que son: aqui se le dice en una
    frase y se instala solo.
    """

    def __init__(self, padre: tk.Tk, pendientes: list[str],
                 al_terminar: Callable[[], None]):
        super().__init__(padre)
        self.title("Preparar el descargador")
        self.resizable(False, False)
        self.transient(padre)
        self.al_terminar = al_terminar
        self.parar = threading.Event()
        self.cola: "queue.Queue[tuple[str, float] | tuple[str, None]]" = queue.Queue()
        self.instalando = False

        marco = ttk.Frame(self, padding=16)
        marco.pack(fill="both", expand=True)

        ttk.Label(marco, text="Falta preparar algunas cosas",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            marco, justify="left", wraplength=560,
            text=("Para descargar con buena calidad hacen falta dos programas "
                  "auxiliares. Se descargan una sola vez y quedan guardados "
                  "junto a la aplicacion; no se instala nada en el sistema."),
        ).pack(anchor="w", pady=(6, 10))

        for componente in pendientes:
            ttk.Label(marco, text="•  " + DESCRIPCIONES.get(componente, componente),
                      justify="left", wraplength=540).pack(anchor="w", pady=2)

        self.var_msg = tk.StringVar(value="")
        ttk.Label(marco, textvariable=self.var_msg).pack(anchor="w", pady=(12, 4))
        self.barra = ttk.Progressbar(marco, length=560, mode="determinate",
                                     maximum=100)
        self.barra.pack(fill="x")

        botones = ttk.Frame(marco)
        botones.pack(fill="x", pady=(14, 0))
        self.btn_ok = ttk.Button(botones, text="Descargar e instalar",
                                 command=self._instalar)
        self.btn_ok.pack(side="left")
        self.btn_no = ttk.Button(botones, text="Ahora no", command=self._cerrar)
        self.btn_no.pack(side="left", padx=8)
        ttk.Label(botones, text="Necesita conexion a internet",
                  style="Suave.TLabel").pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.after(100, self._bombear)
        self.update_idletasks()
        self._centrar(padre)
        self.grab_set()

    def _centrar(self, padre: tk.Tk) -> None:
        x = padre.winfo_rootx() + (padre.winfo_width() - self.winfo_width()) // 2
        y = padre.winfo_rooty() + (padre.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _instalar(self) -> None:
        self.instalando = True
        self.btn_ok.configure(state="disabled")
        self.btn_no.configure(text="Cancelar")

        def tarea() -> None:
            def progreso(mensaje: str, pct: float) -> None:
                self.cola.put((mensaje, pct))

            ok, mensajes = instalar_componentes(progreso, self.parar)
            for m in mensajes:
                self.cola.put((m, None))
            self.cola.put(("__fin__", 100.0 if ok else 0.0))

        threading.Thread(target=tarea, daemon=True).start()

    def _bombear(self) -> None:
        try:
            while True:
                mensaje, pct = self.cola.get_nowait()
                if mensaje == "__fin__":
                    self._terminar()
                    return
                self.var_msg.set(mensaje)
                if pct is not None:
                    self.barra["value"] = pct
        except queue.Empty:
            pass
        self.after(100, self._bombear)

    def _terminar(self) -> None:
        self.instalando = False
        self.grab_release()
        self.destroy()
        self.al_terminar()

    def _cerrar(self) -> None:
        if self.instalando:
            self.parar.set()
            self.var_msg.set("Cancelando...")
            return
        self.grab_release()
        self.destroy()
        self.al_terminar()


class App(ttk.Frame):
    def __init__(self, raiz: tk.Tk):
        self.cfg = cargar_config()
        # Al estrenar la aplicacion se abre en claro; a partir de ahi manda lo
        # que el usuario haya elegido con el boton de sol/luna.
        self.oscuro = self.cfg.get("tema", "claro") == "oscuro"
        self.p = tema.paleta(self.oscuro)
        self.estilo = tema.aplicar(raiz, self.p)

        super().__init__(raiz, padding=0, style="Fondo.TFrame")
        self.raiz = raiz
        self.grid(sticky="nsew")
        raiz.columnconfigure(0, weight=1)
        raiz.rowconfigure(0, weight=1)

        self.eventos: "queue.Queue[Evento]" = queue.Queue()
        self.descargador: Descargador | None = None
        self.datos: dict[str, dict] = {}   # url -> {fila, archivo, estado}
        self.perfiles: dict = self.cfg.get("perfiles", {})

        self._crear_variables()
        self._construir()
        self._aplicar_ajustes(self.cfg)
        # Quien estrena la aplicacion empieza en la vista simple.
        self.var_modo.set(self.cfg.get("modo", "simple"))
        self._aplicar_modo()
        self._revisar_dependencias()
        self._estado_cookies()
        self._enganchar_atajos()
        self._auto_pegar()

        self.var_cookies.trace_add("write", lambda *_: self._estado_cookies())
        self.var_ck_archivo.trace_add("write", lambda *_: self._estado_cookies())
        self.var_formato.trace_add("write", lambda *_: self._refrescar_estados())

        self.after(100, self._bombear_eventos)

    # ------------------------------------------------------------ variables
    def _crear_variables(self) -> None:
        self.var_modo = tk.StringVar(value="simple")
        self.var_calidad_simple = tk.StringVar(value="mejor")
        self.var_formato = tk.StringVar(value=list(FORMATOS)[0])
        self.var_calidad_audio = tk.StringVar(value="192")
        self.var_carpeta = tk.StringVar(value=str(carpeta_descargas_por_defecto()))
        self.var_plantilla = tk.StringVar(value=list(PLANTILLAS)[0])
        self.var_playlist = tk.BooleanVar(value=False)
        self.var_subs = tk.BooleanVar(value=False)
        self.var_subs_aparte = tk.BooleanVar(value=False)
        self.var_subs_idioma = tk.StringVar(value=list(IDIOMAS_SUBS)[0])
        self.var_thumb = tk.BooleanVar(value=False)
        self.var_compat = tk.BooleanVar(value=True)
        self.var_cookies = tk.StringVar(value=AUTOMATICO)
        self.var_ck_archivo = tk.StringVar(value="")
        self.var_ck_estado = tk.StringVar(value="")
        self.var_limite = tk.StringVar(value="")
        self.var_simultaneas = tk.IntVar(value=1)
        self.var_historial = tk.BooleanVar(value=False)
        self.var_inicio = tk.StringVar(value="")
        self.var_fin = tk.StringVar(value="")
        self.var_lista_desde = tk.StringVar(value="")
        self.var_lista_hasta = tk.StringVar(value="")
        self.var_proxy = tk.StringVar(value="")
        self.var_avisar = tk.BooleanVar(value=True)
        self.var_perfil = tk.StringVar(value="")
        self.var_estado = tk.StringVar(value="Listo.")
        self.var_version = tk.StringVar(value="")
        self.var_resumen = tk.StringVar(value="")

    # --------------------------------------------------------- construccion
    def _construir(self) -> None:
        """Dos vistas sobre los mismos datos.

        La caja de enlaces, la tabla y el progreso son los mismos en ambas: solo
        cambian las opciones que se muestran, para que cambiar de vista no
        pierda lo que se estaba haciendo.
        """
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=3)     # tabla
        self.rowconfigure(7, weight=2)     # log

        self._construir_cabecera()      # fila 0
        self._construir_enlaces()       # fila 1
        self._construir_panel_simple()  # fila 2
        self._construir_opciones()      # fila 3 (vista completa)
        self._construir_acciones()      # fila 4
        self._construir_tabla()         # fila 5
        self._construir_progreso()      # fila 6
        self._construir_log()           # fila 7
        self._construir_estado()        # fila 8

    def _construir_cabecera(self) -> None:
        """Barra de acento: da color a la ventana y ancla la identidad arriba."""
        barra = tk.Frame(self, background=self.p["acento"])
        barra.grid(row=0, column=0, sticky="ew")
        barra.columnconfigure(0, weight=1)

        titulo = tk.Label(barra, text="Descargador de Videos",
                          background=self.p["acento"],
                          foreground=self.p["sobre_acento"],
                          font=(tema.FUENTE, 13, "bold"))
        titulo.grid(row=0, column=0, sticky="w", padx=14, pady=10)

        selector = tk.Frame(barra, background=self.p["acento"])
        selector.grid(row=0, column=1, sticky="e", padx=(0, 10))
        for valor, texto in (("simple", "Simple"), ("completa", "Completa")):
            ttk.Radiobutton(selector, text=texto, value=valor,
                            variable=self.var_modo, style="Vista.TRadiobutton",
                            takefocus=False,
                            command=self._aplicar_modo).pack(side="left", padx=1)

        self.btn_tema = tk.Canvas(barra, width=30, height=30, borderwidth=0,
                                  highlightthickness=0, cursor="hand2",
                                  background=self.p["acento"])
        self.btn_tema.grid(row=0, column=2, sticky="e", padx=(0, 14))
        self.btn_tema.bind("<Button-1>", lambda _e: self._cambiar_tema())
        tema.dibujar_icono(self.btn_tema, self.p, self.oscuro)

        self.cabecera = barra
        self.cabecera_titulo = titulo
        self.cabecera_selector = selector

    # --- enlaces ---------------------------------------------------------
    def _construir_enlaces(self) -> None:
        caja = ttk.LabelFrame(self, text="Enlaces", padding=8)
        caja.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 0))
        caja.columnconfigure(0, weight=1)

        self.txt_urls = tk.Text(caja, height=4, wrap="none", undo=True)
        self.txt_urls.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(caja, orient="vertical", command=self.txt_urls.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.txt_urls.configure(yscrollcommand=scroll.set)
        self.txt_urls.configure(bg=self.p["superficie"], fg=self.p["texto"],
                                insertbackground=self.p["texto"],
                                font=(tema.FUENTE, 10),
                                relief="solid", borderwidth=1,
                                highlightthickness=0, padx=8, pady=6)
        self._color_texto = self.txt_urls.cget("foreground")
        self._poner_placeholder()
        self.txt_urls.bind("<FocusIn>", self._quitar_placeholder)
        self.txt_urls.bind("<FocusOut>", self._poner_placeholder_si_vacio)

        barra = ttk.Frame(caja)
        barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(barra, text="Pegar", command=self._pegar).pack(side="left")
        ttk.Button(barra, text="Limpiar",
                   command=self._limpiar_urls).pack(side="left", padx=6)
        # En un marco propio para poder ocultarlo entero en la vista simple.
        self.marco_analizar = ttk.Frame(barra)
        self.marco_analizar.pack(side="left")
        self.btn_analizar = ttk.Button(self.marco_analizar,
                                       text="Analizar (sin descargar)",
                                       command=self._analizar)
        self.btn_analizar.pack(side="left")
        ttk.Label(barra, text="Ctrl+Enter descarga  ·  Esc cancela",
                  style="Suave.TLabel").pack(side="right")

    # --- vista simple ----------------------------------------------------
    def _construir_panel_simple(self) -> None:
        """Lo minimo para descargar: que, y donde.

        Todo lo demas (sesion, formatos, recortes, plantillas) usa valores
        seguros por defecto y ni siquiera se muestra.
        """
        self.panel_simple = ttk.LabelFrame(self, text="Que quieres descargar",
                                           padding=10)
        self.panel_simple.grid(row=2, column=0, sticky="ew", padx=12, pady=(10, 0))
        self.panel_simple.columnconfigure(1, weight=1)

        # Cada opcion es una tarjeta: la elegida se tiñe y se enmarca en el
        # color de acento, para que se vea sin leer cual esta activa.
        self.opciones_simple: dict[str, tuple] = {}
        fila = 0
        for clave, (_, titulo, ayuda) in CALIDAD_SIMPLE.items():
            caja = tk.Frame(self.panel_simple, background=self.p["superficie"],
                            highlightthickness=1,
                            highlightbackground=self.p["borde"],
                            padx=10, pady=7)
            caja.grid(row=fila, column=0, columnspan=3, sticky="ew", pady=3)
            caja.columnconfigure(1, weight=1)

            radio = ttk.Radiobutton(caja, text=titulo, value=clave,
                                    variable=self.var_calidad_simple,
                                    style="Tarjeta.TRadiobutton",
                                    command=self._calidad_simple_cambio)
            radio.grid(row=0, column=0, sticky="w")
            pista = ttk.Label(caja, text=ayuda, style="Suave.TLabel")
            pista.grid(row=0, column=1, sticky="e")

            # Pulsar en cualquier parte de la tarjeta elige esa opcion.
            for widget in (caja, pista):
                widget.bind("<Button-1>",
                            lambda _e, c=clave: self._elegir_calidad_simple(c))

            self.opciones_simple[clave] = (caja, radio, pista)
            fila += 1

        ttk.Separator(self.panel_simple, orient="horizontal").grid(
            row=fila, column=0, columnspan=3, sticky="ew", pady=10)
        fila += 1

        ttk.Label(self.panel_simple, text="Se guarda en:").grid(row=fila, column=0,
                                                                sticky="w")
        ttk.Label(self.panel_simple, textvariable=self.var_carpeta,
                  style="Suave.TLabel").grid(row=fila, column=1, sticky="w",
                                                padx=10)
        botones = ttk.Frame(self.panel_simple)
        botones.grid(row=fila, column=2, sticky="e")
        ttk.Button(botones, text="Cambiar",
                   command=self._elegir_carpeta).pack(side="left")
        ttk.Button(botones, text="Abrir carpeta",
                   command=self._abrir_carpeta).pack(side="left", padx=6)

    def _elegir_calidad_simple(self, clave: str) -> None:
        self.var_calidad_simple.set(clave)
        self._calidad_simple_cambio()

    def _calidad_simple_cambio(self) -> None:
        """La vista simple escribe sobre las mismas opciones que la completa."""
        elegida = self.var_calidad_simple.get()
        if elegida in CALIDAD_SIMPLE:
            self.var_formato.set(CALIDAD_SIMPLE[elegida][0])
        self._resaltar_opciones()

    def _resaltar_opciones(self) -> None:
        """Tiñe la tarjeta elegida; las demas quedan neutras."""
        elegida = self.var_calidad_simple.get()
        for clave, (caja, radio, pista) in self.opciones_simple.items():
            activa = clave == elegida
            caja.configure(
                background=self.p["acento_tenue"] if activa else self.p["superficie"],
                highlightbackground=self.p["acento"] if activa else self.p["borde"],
                highlightcolor=self.p["acento"] if activa else self.p["borde"],
            )
            radio.configure(style="Elegida.TRadiobutton" if activa
                            else "Tarjeta.TRadiobutton")
            pista.configure(style="SuaveTenue.TLabel" if activa
                            else "Suave.TLabel")

    def _sincronizar_calidad_simple(self) -> None:
        """Al volver a la vista simple, refleja lo elegido en la completa."""
        actual = self.var_formato.get()
        equivalentes = {etiqueta: clave
                        for clave, (etiqueta, _, _) in CALIDAD_SIMPLE.items()}
        # Una calidad que la vista simple no ofrece (4K, M4A...) deja las tres
        # tarjetas sin marcar: se respeta lo elegido en la vista completa.
        self.var_calidad_simple.set(equivalentes.get(actual, ""))
        self._resaltar_opciones()

    # ------------------------------------------------------------ tema
    def _cambiar_tema(self) -> None:
        """Alterna claro/oscuro y lo recuerda para la proxima vez."""
        self.oscuro = not self.oscuro
        self._pintar_tema()
        self._persistir_config()
        self.var_estado.set("Tema oscuro activado." if self.oscuro
                            else "Tema claro activado.")

    def _pintar_tema(self) -> None:
        """Repinta la ventana entera sin cerrarla.

        Los estilos ttk se reconfiguran solos al aplicarlos, pero los widgets
        de tk (cabecera, tarjetas, cajas de texto) llevan sus colores encima y
        hay que repasarlos uno a uno.
        """
        self.p = tema.paleta(self.oscuro)
        self.estilo = tema.aplicar(self.raiz, self.p)

        self.cabecera.configure(background=self.p["acento"])
        self.cabecera_titulo.configure(background=self.p["acento"],
                                       foreground=self.p["sobre_acento"])
        self.cabecera_selector.configure(background=self.p["acento"])
        tema.dibujar_icono(self.btn_tema, self.p, self.oscuro)

        self._color_texto = self.p["texto"]
        self.txt_urls.configure(
            bg=self.p["superficie"], insertbackground=self.p["texto"],
            fg=(self.p["texto_apagado"] if getattr(self, "_con_placeholder", False)
                else self.p["texto"]),
        )
        self.txt_log.configure(bg=self.p["log_fondo"], fg=self.p["log_texto"])

        self.tabla.tag_configure("error", foreground=self.p["error"])
        self.tabla.tag_configure("listo", foreground=self.p["exito"])
        self.tabla.tag_configure("activo", foreground=self.p["acento"])

        self._resaltar_opciones()

    def _aplicar_modo(self) -> None:
        simple = self.var_modo.get() == "simple"

        if simple:
            self._sincronizar_calidad_simple()
            self.panel_simple.grid()
            self.panel_completo.grid_remove()
            self.caja_log.grid_remove()
            self.tabla.configure(displaycolumns=("titulo", "estado", "progreso"))
        else:
            self.panel_simple.grid_remove()
            self.panel_completo.grid()
            self.caja_log.grid()
            self.tabla.configure(displaycolumns="#all")

        # Botones que solo tienen sentido en la vista completa.
        for marco, lado in ((self.marco_analizar, "left"),
                            (self.marco_reintentar, "left"),
                            (self.marco_mantenimiento, "right")):
            if simple:
                marco.pack_forget()
            else:
                marco.pack(side=lado)

        # Sin minimo, el resto del contenido aplasta el panel de detalles
        # hasta dejarlo en una linea.
        self.rowconfigure(7, weight=0 if simple else 2,
                          minsize=0 if simple else 130)
        if getattr(self, "_modo_aplicado", None) not in (None, self.var_modo.get()):
            self.raiz.geometry("980x700" if simple else "1060x920")
        self._modo_aplicado = self.var_modo.get()

    # --- opciones --------------------------------------------------------
    def _construir_opciones(self) -> None:
        contenedor = ttk.Frame(self, style="Fondo.TFrame")
        self.panel_completo = contenedor
        contenedor.grid(row=3, column=0, sticky="ew", padx=12, pady=(8, 0))
        contenedor.columnconfigure(0, weight=1)

        pestanas = ttk.Notebook(contenedor)
        pestanas.grid(row=0, column=0, sticky="ew")
        basico = ttk.Frame(pestanas, padding=8)
        avanzado = ttk.Frame(pestanas, padding=8)
        sesion = ttk.Frame(pestanas, padding=8)
        pestanas.add(basico, text="  Basico  ")
        pestanas.add(avanzado, text="  Avanzado  ")
        pestanas.add(sesion, text="  Sesion  ")

        self._pestana_basico(basico)
        self._pestana_avanzado(avanzado)
        self._pestana_sesion(sesion)

    def _pestana_basico(self, p: ttk.Frame) -> None:
        p.columnconfigure(1, weight=1)

        ttk.Label(p, text="Calidad:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.var_formato, state="readonly",
                     values=list(FORMATOS), width=32).grid(row=0, column=1,
                                                           sticky="w", padx=6)

        self.lbl_audio = ttk.Label(p, text="Audio (kbps):")
        self.lbl_audio.grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.cmb_audio = ttk.Combobox(p, textvariable=self.var_calidad_audio,
                                      state="readonly", values=CALIDADES_AUDIO,
                                      width=6)
        self.cmb_audio.grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(p, text="Guardar en:").grid(row=1, column=0, sticky="w",
                                              pady=(8, 0))
        ttk.Entry(p, textvariable=self.var_carpeta).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=(8, 0)
        )
        ttk.Button(p, text="Examinar...", command=self._elegir_carpeta).grid(
            row=1, column=3, pady=(8, 0)
        )
        ttk.Button(p, text="Abrir carpeta", command=self._abrir_carpeta).grid(
            row=1, column=4, padx=(6, 0), pady=(8, 0)
        )

        ttk.Label(p, text="Nombre del archivo:").grid(row=2, column=0, sticky="w",
                                                      pady=(8, 0))
        ttk.Combobox(p, textvariable=self.var_plantilla, state="readonly",
                     values=list(PLANTILLAS), width=32).grid(
            row=2, column=1, sticky="w", padx=6, pady=(8, 0)
        )

        marcas = ttk.Frame(p)
        marcas.grid(row=3, column=0, columnspan=5, sticky="w", pady=(10, 0))
        ttk.Checkbutton(marcas, text="Lista/canal completo",
                        variable=self.var_playlist).pack(side="left")
        ttk.Checkbutton(marcas, text="Subtitulos",
                        variable=self.var_subs).pack(side="left", padx=10)
        ttk.Checkbutton(marcas, text="Miniatura",
                        variable=self.var_thumb).pack(side="left")
        ttk.Checkbutton(marcas, text="Compatibilidad maxima (H.264/AAC)",
                        variable=self.var_compat).pack(side="left", padx=10)

        # Perfiles
        perf = ttk.Frame(p)
        perf.grid(row=4, column=0, columnspan=5, sticky="w", pady=(10, 0))
        ttk.Label(perf, text="Perfil:").pack(side="left")
        self.cmb_perfil = ttk.Combobox(perf, textvariable=self.var_perfil,
                                       values=sorted(self.perfiles), width=24)
        self.cmb_perfil.pack(side="left", padx=6)
        ttk.Button(perf, text="Cargar", command=self._cargar_perfil).pack(side="left")
        ttk.Button(perf, text="Guardar", command=self._guardar_perfil).pack(
            side="left", padx=6)
        ttk.Button(perf, text="Borrar", command=self._borrar_perfil).pack(side="left")

    def _pestana_avanzado(self, p: ttk.Frame) -> None:
        p.columnconfigure(6, weight=1)

        ttk.Label(p, text="Descargas a la vez:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(p, from_=1, to=4, width=4,
                    textvariable=self.var_simultaneas).grid(row=0, column=1,
                                                            sticky="w", padx=6)

        ttk.Label(p, text="Limite de velocidad:").grid(row=0, column=2, sticky="w",
                                                       padx=(12, 0))
        ttk.Entry(p, textvariable=self.var_limite, width=8).grid(row=0, column=3,
                                                                 sticky="w", padx=6)
        ttk.Label(p, text="(ej. 2M)", style="Suave.TLabel").grid(row=0, column=4,
                                                                    sticky="w")

        ttk.Checkbutton(p, text="No repetir lo ya descargado (historial)",
                        variable=self.var_historial).grid(row=1, column=0,
                                                          columnspan=4, sticky="w",
                                                          pady=(8, 0))

        ttk.Label(p, text="Recortar de:").grid(row=2, column=0, sticky="w",
                                               pady=(8, 0))
        ttk.Entry(p, textvariable=self.var_inicio, width=8).grid(row=2, column=1,
                                                                 sticky="w", padx=6,
                                                                 pady=(8, 0))
        ttk.Label(p, text="a:").grid(row=2, column=2, sticky="e", pady=(8, 0))
        ttk.Entry(p, textvariable=self.var_fin, width=8).grid(row=2, column=3,
                                                              sticky="w", padx=6,
                                                              pady=(8, 0))
        ttk.Label(p, text="(mm:ss, vacio = completo)",
                  style="Suave.TLabel").grid(row=2, column=4, columnspan=2,
                                                sticky="w", pady=(8, 0))

        ttk.Label(p, text="De la lista, del:").grid(row=3, column=0, sticky="w",
                                                    pady=(8, 0))
        ttk.Entry(p, textvariable=self.var_lista_desde, width=8).grid(
            row=3, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(p, text="al:").grid(row=3, column=2, sticky="e", pady=(8, 0))
        ttk.Entry(p, textvariable=self.var_lista_hasta, width=8).grid(
            row=3, column=3, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(p, text="Subtitulos:").grid(row=4, column=0, sticky="w",
                                              pady=(8, 0))
        ttk.Combobox(p, textvariable=self.var_subs_idioma, state="readonly",
                     values=list(IDIOMAS_SUBS), width=18).grid(
            row=4, column=1, columnspan=2, sticky="w", padx=6, pady=(8, 0))
        ttk.Checkbutton(p, text="como archivo .srt aparte",
                        variable=self.var_subs_aparte).grid(row=4, column=3,
                                                            columnspan=3, sticky="w",
                                                            pady=(8, 0))

        ttk.Label(p, text="Proxy:").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(p, textvariable=self.var_proxy).grid(row=5, column=1,
                                                       columnspan=4, sticky="ew",
                                                       padx=6, pady=(8, 0))

        ttk.Checkbutton(p, text="Avisar con un sonido al terminar",
                        variable=self.var_avisar).grid(row=6, column=0,
                                                       columnspan=4, sticky="w",
                                                       pady=(8, 0))

    def _pestana_sesion(self, p: ttk.Frame) -> None:
        p.columnconfigure(1, weight=1)

        ttk.Label(p, text="Origen de la sesion:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(p, textvariable=self.var_cookies, state="readonly",
                     values=NAVEGADORES, width=24).grid(row=0, column=1, sticky="w",
                                                        padx=6)
        self.btn_ck = ttk.Button(p, text="Renovar sesion guardada",
                                 command=self._renovar_cookies)
        self.btn_ck.grid(row=0, column=2, padx=6)

        ttk.Label(p, textvariable=self.var_ck_estado,
                  style="Suave.TLabel").grid(row=1, column=0, columnspan=3,
                                                sticky="w", pady=(8, 0))

        ttk.Label(p, text="o archivo cookies.txt:").grid(row=2, column=0, sticky="w",
                                                         pady=(8, 0))
        ttk.Entry(p, textvariable=self.var_ck_archivo).grid(row=2, column=1,
                                                            sticky="ew", padx=6,
                                                            pady=(8, 0))
        marco = ttk.Frame(p)
        marco.grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Button(marco, text="Elegir...", command=self._elegir_cookies).pack(
            side="left")
        ttk.Button(marco, text="Quitar",
                   command=lambda: self.var_ck_archivo.set("")).pack(side="left",
                                                                     padx=6)

        ttk.Label(
            p,
            style="Suave.TLabel",
            text=("YouTube exige una sesion valida. La app la copia una vez y la "
                  "reutiliza: no hace falta abrir ni cerrar el navegador.\n"
                  "Firefox se deja leer abierto; Chrome, Edge y Brave cifran sus "
                  "cookies y no se pueden leer aunque los cierres."),
            justify="left",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

    # --- acciones --------------------------------------------------------
    def _construir_acciones(self) -> None:
        barra = ttk.Frame(self, style="Fondo.TFrame")
        barra.grid(row=4, column=0, sticky="ew", padx=12, pady=(10, 0))

        self.btn_descargar = ttk.Button(barra, text="Descargar",
                                        style="Acento.TButton",
                                        command=self._descargar)
        self.btn_descargar.pack(side="left")
        self.btn_cancelar = ttk.Button(barra, text="Cancelar", state="disabled",
                                       command=self._cancelar)
        self.btn_cancelar.pack(side="left", padx=6)

        # Lo que solo aparece en la vista completa va en marcos aparte.
        self.marco_reintentar = ttk.Frame(barra, style="Fondo.TFrame")
        self.marco_reintentar.pack(side="left")
        self.btn_reintentar = ttk.Button(self.marco_reintentar,
                                         text="Reintentar fallidos",
                                         state="disabled",
                                         command=self._reintentar_fallidos)
        self.btn_reintentar.pack(side="left")

        self.marco_mantenimiento = ttk.Frame(barra, style="Fondo.TFrame")
        self.marco_mantenimiento.pack(side="right")
        ttk.Button(self.marco_mantenimiento, text="Instalar componentes",
                   command=self._instalar_componentes).pack(side="right")
        ttk.Button(self.marco_mantenimiento, text="Actualizar yt-dlp",
                   command=self._actualizar_ytdlp).pack(side="right", padx=6)

    # --- tabla -----------------------------------------------------------
    def _construir_tabla(self) -> None:
        caja = ttk.LabelFrame(self, text="Descargas", padding=6)
        caja.grid(row=5, column=0, sticky="nsew", padx=12, pady=(10, 0))
        caja.columnconfigure(0, weight=1)
        caja.rowconfigure(0, weight=1)

        cols = ("titulo", "estado", "progreso", "velocidad", "eta")
        self.tabla = ttk.Treeview(caja, columns=cols, show="headings", height=7)
        for col, texto, ancho, ancla in (
            ("titulo", "Titulo / URL", 430, "w"),
            ("estado", "Estado", 150, "w"),
            ("progreso", "Progreso", 80, "center"),
            ("velocidad", "Velocidad", 90, "center"),
            ("eta", "Falta", 70, "center"),
        ):
            self.tabla.heading(col, text=texto)
            self.tabla.column(col, width=ancho, anchor=ancla)
        self.tabla.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(caja, orient="vertical", command=self.tabla.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tabla.configure(yscrollcommand=scroll.set)
        # El color dice el estado de un vistazo, sin tener que leer.
        self.tabla.tag_configure("error", foreground=self.p["error"])
        self.tabla.tag_configure("listo", foreground=self.p["exito"])
        self.tabla.tag_configure("activo", foreground=self.p["acento"])

        self.menu = tk.Menu(self.tabla, tearoff=0)
        self.menu.add_command(label="Abrir archivo", command=self._abrir_archivo)
        self.menu.add_command(label="Mostrar en la carpeta",
                              command=self._mostrar_en_carpeta)
        self.menu.add_separator()
        self.menu.add_command(label="Copiar enlace", command=self._copiar_enlace)
        self.menu.add_command(label="Reintentar este", command=self._reintentar_uno)
        self.menu.add_command(label="Quitar de la lista", command=self._quitar_fila)

        self.tabla.bind("<Double-1>", lambda _e: self._abrir_archivo())
        self.tabla.bind("<Button-3>", self._menu_contextual)

    def _construir_progreso(self) -> None:
        marco = ttk.Frame(self, style="Fondo.TFrame")
        marco.grid(row=6, column=0, sticky="ew", padx=12, pady=(8, 0))
        marco.columnconfigure(0, weight=1)
        self.barra = ttk.Progressbar(marco, mode="determinate", maximum=100)
        self.barra.grid(row=0, column=0, sticky="ew")
        self.barra_global = ttk.Progressbar(marco, mode="determinate", maximum=100,
                                            style="Global.Horizontal.TProgressbar")
        self.barra_global.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        ttk.Label(marco, textvariable=self.var_resumen, width=18, anchor="e",
                  style="Fondo.TLabel").grid(row=0, column=1, rowspan=2,
                                             padx=(8, 0))

    # --- log -------------------------------------------------------------
    def _construir_log(self) -> None:
        caja = ttk.LabelFrame(self, text="Detalles", padding=6)
        self.caja_log = caja
        caja.grid(row=7, column=0, sticky="nsew", padx=12, pady=(8, 0))
        caja.columnconfigure(0, weight=1)
        caja.rowconfigure(0, weight=1)

        # El registro tecnico va sobre fondo oscuro en ambos temas: se lee
        # como una consola y no compite con el resto de la ventana.
        self.txt_log = tk.Text(caja, height=6, wrap="word", state="disabled",
                               bg=self.p["log_fondo"], fg=self.p["log_texto"],
                               relief="flat", borderwidth=0,
                               font=("Consolas", 9), padx=8, pady=6)
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(caja, orient="vertical", command=self.txt_log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=scroll.set)

        barra = ttk.Frame(caja)
        barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(barra, text="Copiar", command=self._copiar_log).pack(side="left")
        ttk.Button(barra, text="Guardar...", command=self._guardar_log).pack(
            side="left", padx=6)
        ttk.Button(barra, text="Limpiar", command=self._limpiar_log).pack(side="left")

    def _construir_estado(self) -> None:
        barra = ttk.Frame(self, style="Estado.TFrame", padding=(14, 6))
        barra.grid(row=8, column=0, sticky="ew", pady=(10, 0))
        barra.columnconfigure(0, weight=1)
        ttk.Label(barra, textvariable=self.var_estado, style="Estado.TLabel",
                  anchor="w").grid(row=0, column=0, sticky="ew")
        ttk.Label(barra, textvariable=self.var_version, style="Estado.TLabel",
                  anchor="e").grid(row=0, column=1, sticky="e")

    # ---------------------------------------------------------------- utiles
    def _gris(self) -> str:
        return self.p["texto_suave"]

    def _enganchar_atajos(self) -> None:
        self.raiz.bind("<Control-Return>", lambda _e: self._descargar())
        self.raiz.bind("<Escape>", lambda _e: self._cancelar())
        self.raiz.bind("<Control-l>", lambda _e: self._limpiar_urls())

    def _auto_pegar(self) -> None:
        """Si el portapapeles trae un enlace, se ofrece ya escrito."""
        try:
            texto = self.raiz.clipboard_get().strip()
        except tk.TclError:
            return
        if texto.startswith(("http://", "https://")) and "\n" not in texto:
            self._quitar_placeholder()
            self.txt_urls.insert("1.0", texto + "\n")
            self.var_estado.set("Enlace tomado del portapapeles.")

    # ------------------------------------------------------------ placeholder
    def _poner_placeholder(self) -> None:
        self.txt_urls.insert("1.0", PLACEHOLDER)
        self.txt_urls.configure(foreground=self.p["texto_apagado"])
        self._con_placeholder = True

    def _poner_placeholder_si_vacio(self, _evt=None) -> None:
        if not self.txt_urls.get("1.0", "end").strip():
            self._poner_placeholder()

    def _quitar_placeholder(self, _evt=None) -> None:
        if getattr(self, "_con_placeholder", False):
            self.txt_urls.delete("1.0", "end")
            self.txt_urls.configure(foreground=self._color_texto)
            self._con_placeholder = False

    def _limpiar_urls(self) -> None:
        self.txt_urls.delete("1.0", "end")
        self._con_placeholder = False
        self._poner_placeholder()

    def _pegar(self) -> None:
        try:
            texto = self.raiz.clipboard_get()
        except tk.TclError:
            return
        self._quitar_placeholder()
        actual = self.txt_urls.get("1.0", "end").strip()
        self.txt_urls.delete("1.0", "end")
        self.txt_urls.insert("1.0", (actual + "\n" + texto).strip() + "\n")
        self.txt_urls.configure(foreground=self._color_texto)

    def _urls(self) -> list[str]:
        if getattr(self, "_con_placeholder", False):
            return []
        crudo = self.txt_urls.get("1.0", "end")
        vistas, limpias = set(), []
        for linea in crudo.splitlines():
            url = linea.strip()
            if url and url not in vistas:      # sin repetidos
                vistas.add(url)
                limpias.append(url)
        return limpias

    # ------------------------------------------------------------- ajustes
    def _recoger_ajustes(self) -> dict:
        return {
            "modo": self.var_modo.get(),
            "tema": "oscuro" if self.oscuro else "claro",
            "carpeta": self.var_carpeta.get(),
            "formato": self.var_formato.get(),
            "calidad_audio": self.var_calidad_audio.get(),
            "plantilla": self.var_plantilla.get(),
            "cookies": self.var_cookies.get(),
            "cookies_archivo": self.var_ck_archivo.get(),
            "playlist": self.var_playlist.get(),
            "subtitulos": self.var_subs.get(),
            "subs_aparte": self.var_subs_aparte.get(),
            "subs_idioma": self.var_subs_idioma.get(),
            "miniatura": self.var_thumb.get(),
            "compatibilidad": self.var_compat.get(),
            "limite": self.var_limite.get(),
            "simultaneas": self.var_simultaneas.get(),
            "historial": self.var_historial.get(),
            "inicio": self.var_inicio.get(),
            "fin": self.var_fin.get(),
            "lista_desde": self.var_lista_desde.get(),
            "lista_hasta": self.var_lista_hasta.get(),
            "proxy": self.var_proxy.get(),
            "avisar": self.var_avisar.get(),
        }

    def _aplicar_ajustes(self, d: dict) -> None:
        if (v := d.get("carpeta")):
            self.var_carpeta.set(v)
        if (v := d.get("formato")) in FORMATOS:
            self.var_formato.set(v)
        if (v := d.get("calidad_audio")) in CALIDADES_AUDIO:
            self.var_calidad_audio.set(v)
        if (v := d.get("plantilla")) in PLANTILLAS:
            self.var_plantilla.set(v)
        if (v := d.get("cookies")) in NAVEGADORES:
            self.var_cookies.set(v)
        if (v := d.get("subs_idioma")) in IDIOMAS_SUBS:
            self.var_subs_idioma.set(v)
        self.var_ck_archivo.set(d.get("cookies_archivo", ""))
        self.var_playlist.set(bool(d.get("playlist", False)))
        self.var_subs.set(bool(d.get("subtitulos", False)))
        self.var_subs_aparte.set(bool(d.get("subs_aparte", False)))
        self.var_thumb.set(bool(d.get("miniatura", False)))
        self.var_compat.set(bool(d.get("compatibilidad", True)))
        self.var_limite.set(d.get("limite", ""))
        self.var_simultaneas.set(int(d.get("simultaneas", 1) or 1))
        self.var_historial.set(bool(d.get("historial", False)))
        self.var_inicio.set(d.get("inicio", ""))
        self.var_fin.set(d.get("fin", ""))
        self.var_lista_desde.set(d.get("lista_desde", ""))
        self.var_lista_hasta.set(d.get("lista_hasta", ""))
        self.var_proxy.set(d.get("proxy", ""))
        self.var_avisar.set(bool(d.get("avisar", True)))
        self._refrescar_estados()

    def _persistir_config(self) -> None:
        datos = self._recoger_ajustes()
        datos["perfiles"] = self.perfiles
        guardar_config(datos)

    def _refrescar_estados(self) -> None:
        """La calidad de audio solo aplica al convertir a MP3."""
        solo_mp3 = FORMATOS.get(self.var_formato.get()) == "mp3"
        estado = "readonly" if solo_mp3 else "disabled"
        if hasattr(self, "cmb_audio"):
            self.cmb_audio.configure(state=estado)
            self.lbl_audio.configure(style="TLabel" if solo_mp3 else "Suave.TLabel")

    # -------------------------------------------------------------- perfiles
    def _cargar_perfil(self) -> None:
        nombre = self.var_perfil.get().strip()
        if nombre not in self.perfiles:
            messagebox.showinfo("Perfil", f"No hay un perfil llamado '{nombre}'.")
            return
        self._aplicar_ajustes(self.perfiles[nombre])
        self.var_estado.set(f"Perfil '{nombre}' cargado.")

    def _guardar_perfil(self) -> None:
        nombre = self.var_perfil.get().strip()
        if not nombre:
            messagebox.showinfo("Perfil", "Escribe un nombre para el perfil.")
            return
        self.perfiles[nombre] = self._recoger_ajustes()
        self.cmb_perfil.configure(values=sorted(self.perfiles))
        self._persistir_config()
        self.var_estado.set(f"Perfil '{nombre}' guardado.")

    def _borrar_perfil(self) -> None:
        nombre = self.var_perfil.get().strip()
        if self.perfiles.pop(nombre, None) is not None:
            self.cmb_perfil.configure(values=sorted(self.perfiles))
            self._persistir_config()
            self.var_estado.set(f"Perfil '{nombre}' borrado.")

    # --------------------------------------------------------------- sesion
    def _estado_cookies(self) -> None:
        if self.var_ck_archivo.get().strip():
            self.var_ck_estado.set("Se usara el archivo cookies.txt indicado.")
        elif self.var_cookies.get() == "Ninguno":
            self.var_ck_estado.set("Sin sesion: YouTube fallara con error 403.")
        elif cookies_cache_utiles():
            self.var_ck_estado.set(
                "Sesion guardada lista: no hace falta abrir ni cerrar nada."
            )
        else:
            self.var_ck_estado.set(
                "La primera descarga tomara la sesion del navegador y la guardara."
            )

    def _renovar_cookies(self) -> None:
        self.btn_ck.configure(state="disabled")
        self.var_estado.set("Renovando sesion guardada...")
        eleccion = self.var_cookies.get()
        candidatos = (NAVEGADORES_AUTO if eleccion in (AUTOMATICO, "Ninguno")
                      else [eleccion])

        def tarea() -> None:
            for navegador in candidatos:
                ok, msg = extraer_cookies(navegador)
                self.eventos.put(Evento(tipo="log",
                                        mensaje=("Cookies: " if ok else "Aviso: ") + msg))
                if ok:
                    self.eventos.put(Evento(tipo="cookies",
                                            mensaje=f"Sesion renovada ({navegador})."))
                    return
            self.eventos.put(Evento(
                tipo="cookies",
                mensaje="No se pudo leer la sesion de ningun navegador."))

        threading.Thread(target=tarea, daemon=True).start()

    def _elegir_cookies(self) -> None:
        elegido = filedialog.askopenfilename(
            title="Selecciona el archivo cookies.txt",
            filetypes=[("Cookies", "*.txt"), ("Todos", "*.*")],
        )
        if elegido:
            self.var_ck_archivo.set(elegido)

    # -------------------------------------------------------------- carpetas
    def _elegir_carpeta(self) -> None:
        elegida = filedialog.askdirectory(initialdir=self.var_carpeta.get() or ".")
        if elegida:
            self.var_carpeta.set(elegida)

    def _abrir_carpeta(self) -> None:
        destino = Path(self.var_carpeta.get())
        try:
            destino.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Carpeta", str(exc))
            return
        _abrir_en_sistema(destino)

    # ---------------------------------------------------------------- tabla
    def _url_seleccionada(self) -> str | None:
        seleccion = self.tabla.selection()
        if not seleccion:
            return None
        fila = seleccion[0]
        for url, datos in self.datos.items():
            if datos["fila"] == fila:
                return url
        return None

    def _menu_contextual(self, evento) -> None:
        fila = self.tabla.identify_row(evento.y)
        if fila:
            self.tabla.selection_set(fila)
            self.menu.tk_popup(evento.x_root, evento.y_root)

    def _abrir_archivo(self) -> None:
        url = self._url_seleccionada()
        archivo = (self.datos.get(url or "") or {}).get("archivo", "")
        if archivo and Path(archivo).exists():
            _abrir_en_sistema(Path(archivo))
        else:
            self._abrir_carpeta()

    def _mostrar_en_carpeta(self) -> None:
        url = self._url_seleccionada()
        archivo = (self.datos.get(url or "") or {}).get("archivo", "")
        if archivo and Path(archivo).exists() and os.name == "nt":
            subprocess.run(["explorer", "/select,", str(Path(archivo))], check=False)
        else:
            self._abrir_carpeta()

    def _copiar_enlace(self) -> None:
        url = self._url_seleccionada()
        if url:
            self.raiz.clipboard_clear()
            self.raiz.clipboard_append(url)
            self.var_estado.set("Enlace copiado.")

    def _quitar_fila(self) -> None:
        url = self._url_seleccionada()
        if url:
            self.tabla.delete(self.datos[url]["fila"])
            self.datos.pop(url, None)

    def _reintentar_uno(self) -> None:
        url = self._url_seleccionada()
        if url:
            self._lanzar([url])

    def _reintentar_fallidos(self) -> None:
        fallidos = [u for u, d in self.datos.items() if d.get("estado") == "error"]
        if not fallidos:
            messagebox.showinfo("Reintentar", "No hay descargas fallidas.")
            return
        self._lanzar(fallidos)

    # ------------------------------------------------------------- analisis
    def _analizar(self) -> None:
        urls = self._urls()
        if not urls:
            messagebox.showinfo("Sin enlaces", "Pega al menos una URL.")
            return
        self.btn_analizar.configure(state="disabled")
        self.var_estado.set("Analizando...")
        opciones = self._opciones()

        def tarea() -> None:
            for url in urls:
                try:
                    datos = analizar_url(url, opciones)
                except Exception as exc:  # noqa: BLE001
                    self.eventos.put(Evento(tipo="log",
                                            mensaje=f"Aviso: no se pudo analizar {url}: {exc}"))
                    continue
                if datos.get("es_lista"):
                    texto = (f"{datos['titulo']}: lista con {datos['elementos']} "
                             f"videos, {fmt_eta(datos['duracion'])} en total.")
                else:
                    partes = [datos.get("titulo") or url]
                    if datos.get("duracion"):
                        partes.append(f"duracion {fmt_eta(datos['duracion'])}")
                    if datos.get("tamano"):
                        partes.append(f"~{fmt_tamano(datos['tamano'])}")
                    if datos.get("sitio"):
                        partes.append(datos["sitio"])
                    texto = " · ".join(partes)
                self.eventos.put(Evento(tipo="log", mensaje="Analisis: " + texto))
            self.eventos.put(Evento(tipo="analisis", mensaje="Analisis terminado."))

        threading.Thread(target=tarea, daemon=True).start()

    # ------------------------------------------------------------- descargar
    def _opciones(self) -> Opciones:
        if self.var_modo.get() == "simple":
            # En la vista simple no se aplica nada de lo avanzado aunque haya
            # quedado configurado antes: lo que no se ve, no actua.
            return Opciones(
                carpeta=Path(self.var_carpeta.get()),
                formato=FORMATOS[self.var_formato.get()],
                compatibilidad=True,
                calidad_audio=self.var_calidad_audio.get(),
                navegador_cookies=AUTOMATICO,
            )
        return Opciones(
            carpeta=Path(self.var_carpeta.get()),
            formato=FORMATOS[self.var_formato.get()],
            playlist=self.var_playlist.get(),
            subtitulos=self.var_subs.get(),
            subs_aparte=self.var_subs_aparte.get(),
            subs_idiomas=list(IDIOMAS_SUBS[self.var_subs_idioma.get()]),
            miniatura=self.var_thumb.get(),
            compatibilidad=self.var_compat.get(),
            calidad_audio=self.var_calidad_audio.get(),
            plantilla=PLANTILLAS[self.var_plantilla.get()],
            navegador_cookies=self.var_cookies.get(),
            archivo_cookies=self.var_ck_archivo.get().strip(),
            limite_velocidad=self.var_limite.get(),
            simultaneas=int(self.var_simultaneas.get() or 1),
            usar_historial=self.var_historial.get(),
            seccion_inicio=self.var_inicio.get(),
            seccion_fin=self.var_fin.get(),
            playlist_desde=self.var_lista_desde.get(),
            playlist_hasta=self.var_lista_hasta.get(),
            proxy=self.var_proxy.get(),
        )

    def _descargar(self) -> None:
        urls = self._urls()
        if not urls:
            messagebox.showinfo("Sin enlaces", "Pega al menos una URL.")
            return
        self._lanzar(urls, limpiar=True)

    def _lanzar(self, urls: list[str], limpiar: bool = False) -> None:
        if self.descargador and self.descargador.activo:
            messagebox.showinfo("En curso", "Espera a que termine la descarga actual.")
            return

        self._persistir_config()
        libre = espacio_libre(self.var_carpeta.get())
        if libre and libre < 500 * 1024**2:
            if not messagebox.askyesno(
                "Poco espacio",
                f"Quedan {fmt_tamano(libre)} libres en ese disco. Continuar?",
            ):
                return

        if limpiar:
            self.tabla.delete(*self.tabla.get_children())
            self.datos.clear()

        for url in urls:
            if url in self.datos:
                fila = self.datos[url]["fila"]
                self.tabla.item(fila, values=(url, "En espera", "", "", ""), tags=())
                self.datos[url]["estado"] = "espera"
            else:
                etiquetas = ("par",) if len(self.datos) % 2 else ()
                fila = self.tabla.insert("", "end", tags=etiquetas,
                                         values=(url, "En espera", "", "", ""))
                self.datos[url] = {"fila": fila, "archivo": "", "estado": "espera"}

        self.total_tanda = len(urls)
        self.hechos_tanda = 0
        self.barra["value"] = 0
        self.barra_global["value"] = 0
        self.var_resumen.set(f"0/{self.total_tanda}")
        self.btn_descargar.configure(state="disabled")
        self.btn_reintentar.configure(state="disabled")
        self.btn_cancelar.configure(state="normal")
        self.var_estado.set(f"Descargando {len(urls)} elemento(s)...")

        self.descargador = Descargador(self._opciones(), self.eventos)
        self.descargador.iniciar(urls)

    def _cancelar(self) -> None:
        if self.descargador and self.descargador.activo:
            self.descargador.cancelar()
            self.var_estado.set("Cancelando...")

    # ---------------------------------------------------------- actualizar
    def _actualizar_ytdlp(self) -> None:
        self.var_estado.set("Actualizando yt-dlp...")

        def tarea() -> None:
            ok, salida = actualizar_ytdlp()
            self.eventos.put(Evento(tipo="log", mensaje=salida))
            self.eventos.put(Evento(
                tipo="aviso",
                mensaje=(f"yt-dlp actualizado (version {version_ytdlp()}). "
                         "Reinicia la app para usarla." if ok
                         else "No se pudo actualizar yt-dlp.")))

        threading.Thread(target=tarea, daemon=True).start()

    def _instalar_componentes(self) -> None:
        pendientes = faltan_componentes()
        if not pendientes:
            messagebox.showinfo("Componentes",
                                "Ya esta todo instalado: ffmpeg y motor de "
                                "JavaScript disponibles.")
            return
        self._asistente(pendientes)

    # ---------------------------------------------------------------- log
    def _log(self, texto: str) -> None:
        if not texto.strip():
            return
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", texto.rstrip() + "\n")
        # El panel no puede crecer sin limite o acaba comiendose la memoria.
        lineas = int(self.txt_log.index("end-1c").split(".")[0])
        if lineas > MAX_LINEAS_LOG:
            self.txt_log.delete("1.0", f"{lineas - MAX_LINEAS_LOG}.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _copiar_log(self) -> None:
        self.raiz.clipboard_clear()
        self.raiz.clipboard_append(self.txt_log.get("1.0", "end"))
        self.var_estado.set("Detalles copiados al portapapeles.")

    def _guardar_log(self) -> None:
        destino = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile="detalles-descargador.txt",
            filetypes=[("Texto", "*.txt")],
        )
        if not destino:
            return
        try:
            Path(destino).write_text(self.txt_log.get("1.0", "end"),
                                     encoding="utf-8")
            self.var_estado.set(f"Detalles guardados en {destino}")
        except OSError as exc:
            messagebox.showerror("Guardar", str(exc))

    def _limpiar_log(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # ------------------------------------------------------------ arranque
    def _revisar_dependencias(self) -> None:
        self.var_version.set(f"yt-dlp {version_ytdlp()}")
        pendientes = faltan_componentes()
        if not pendientes:
            self.var_estado.set("Listo para descargar.")
            return

        self._log("Faltan componentes: " + ", ".join(pendientes))
        self.var_estado.set("Faltan componentes por instalar.")
        # En cuanto la ventana este pintada se ofrece instalarlos.
        self.after(300, lambda: self._asistente(pendientes))

    def _asistente(self, pendientes: list[str]) -> None:
        Asistente(self.raiz, pendientes, self._tras_instalar)

    def _tras_instalar(self) -> None:
        pendientes = faltan_componentes()
        if pendientes:
            self.var_estado.set(
                "Sigue faltando: " + ", ".join(pendientes)
                + ". Puedes reintentar con 'Instalar componentes'."
            )
        else:
            self.var_estado.set("Todo listo para descargar.")
            self._log("Componentes instalados: la aplicacion ya puede descargar.")

    # ---------------------------------------------------------------- eventos
    def _bombear_eventos(self) -> None:
        try:
            while True:
                self._procesar(self.eventos.get_nowait())
        except queue.Empty:
            pass
        except tk.TclError:
            return          # la ventana se esta cerrando
        if self.winfo_exists():
            self.after(100, self._bombear_eventos)

    def _fila(self, url: str) -> str | None:
        return (self.datos.get(url) or {}).get("fila")

    def _procesar(self, ev: Evento) -> None:
        fila = self._fila(ev.url)

        if ev.tipo == "inicio":
            if fila:
                self.tabla.set(fila, "estado", "Iniciando")
                self.tabla.see(fila)
            self._log(f"--- {ev.url}")

        elif ev.tipo == "progreso":
            if fila:
                if ev.titulo:
                    self.tabla.set(fila, "titulo", ev.titulo)
                estado = ev.mensaje or "Descargando"
                if ev.total_items > 1:      # elemento N de una lista
                    estado = f"{estado} ({ev.indice}/{ev.total_items})"
                self.tabla.set(fila, "estado", estado)
                self.tabla.item(fila, tags=("activo",))
                self.tabla.set(fila, "progreso", f"{ev.porcentaje:.1f}%")
                self.tabla.set(fila, "velocidad", ev.velocidad)
                self.tabla.set(fila, "eta", ev.eta)
            self.barra["value"] = ev.porcentaje

        elif ev.tipo == "fin":
            self._cerrar_fila(ev, "Completado" if ev.mensaje != "omitido"
                              else "Ya lo tenias", "listo")
            if ev.archivo:
                self.datos.setdefault(ev.url, {})["archivo"] = ev.archivo
                self._log(f"Guardado: {ev.archivo}")

        elif ev.tipo == "error":
            self._cerrar_fila(ev, "Error", "error")
            self._log(ev.mensaje)
            self.ultimo_error = ev.mensaje

        elif ev.tipo == "log":
            self._log(ev.mensaje)

        elif ev.tipo == "cookies":
            self.btn_ck.configure(state="normal")
            self.var_estado.set(ev.mensaje)
            self._estado_cookies()

        elif ev.tipo == "analisis":
            self.btn_analizar.configure(state="normal")
            self.var_estado.set(ev.mensaje)

        elif ev.tipo == "aviso":
            self.var_estado.set(ev.mensaje)

        elif ev.tipo == "terminado":
            self.btn_descargar.configure(state="normal")
            self.btn_cancelar.configure(state="disabled")
            hay_fallos = any(d.get("estado") == "error" for d in self.datos.values())
            self.btn_reintentar.configure(state="normal" if hay_fallos else "disabled")
            self.barra["value"] = 0
            self.var_estado.set(ev.mensaje or "Listo.")
            if self.var_avisar.get():
                _sonar()
            if hay_fallos and self.var_modo.get() == "simple":
                self._contar_fallo()

    def _contar_fallo(self) -> None:
        """En la vista simple el panel de detalles esta oculto: se avisa aparte."""
        motivo = (getattr(self, "ultimo_error", "") or "").split("\n")[0]
        ver = messagebox.askyesno(
            "No se pudo descargar",
            f"{motivo}\n\n¿Quieres ver la vista completa, con el detalle tecnico "
            "y la opcion de reintentar?",
        )
        if ver:
            self.var_modo.set("completa")
            self._aplicar_modo()

    def _cerrar_fila(self, ev: Evento, estado: str, etiqueta: str) -> None:
        fila = self._fila(ev.url)
        if fila:
            if ev.titulo:
                self.tabla.set(fila, "titulo", ev.titulo)
            self.tabla.set(fila, "estado", estado)
            self.tabla.set(fila, "progreso", "100%" if etiqueta == "listo" else "")
            self.tabla.set(fila, "velocidad", "")
            self.tabla.set(fila, "eta", "")
            self.tabla.item(fila, tags=(etiqueta,))
        if ev.url in self.datos:
            self.datos[ev.url]["estado"] = "listo" if etiqueta == "listo" else "error"

        self.hechos_tanda = getattr(self, "hechos_tanda", 0) + 1
        total = max(getattr(self, "total_tanda", 1), 1)
        self.barra_global["value"] = self.hechos_tanda / total * 100
        self.var_resumen.set(f"{self.hechos_tanda}/{total}")


# ------------------------------------------------------------------ sistema


def _abrir_en_sistema(ruta: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(ruta)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(ruta)], check=False)
        else:
            subprocess.run(["xdg-open", str(ruta)], check=False)
    except OSError:
        pass


def _sonar() -> None:
    try:
        if os.name == "nt":
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:  # noqa: BLE001
        pass


def _preparar_dpi() -> None:
    """Sin esto la ventana se ve borrosa en pantallas 4K."""
    if os.name != "nt":
        return
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    _preparar_dpi()
    raiz = tk.Tk()
    raiz.title("Descargador de Videos")
    raiz.geometry("1040x820")
    raiz.minsize(900, 700)
    try:
        escala = raiz.winfo_fpixels("1i") / 72.0
        raiz.tk.call("tk", "scaling", escala)
    except tk.TclError:
        pass
    try:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    except tk.TclError:
        pass
    App(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
