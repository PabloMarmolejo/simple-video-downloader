"""Paleta y estilos de la interfaz.

Tkinter no pinta gradientes, sombras ni esquinas redondeadas, asi que el color
tiene que hacer todo el trabajo: una barra de acento arriba, tarjetas blancas
sobre un fondo suave, y estados con significado (acento = en curso, verde =
listo, rojo = error).

El tema 'clam' es la base porque es el unico de ttk que deja cambiar todos los
colores; los nativos de Windows ignoran la mitad de los ajustes.
"""

from __future__ import annotations

import tkinter as tk
from math import cos, pi, sin
from tkinter import ttk

FUENTE = "Segoe UI"

PALETA_CLARA = {
    "fondo": "#f4f5f7",
    "superficie": "#ffffff",
    "superficie_alt": "#fafbfc",
    "borde": "#dfe3e8",
    "borde_fuerte": "#c7cdd6",
    "texto": "#1c2430",
    "texto_suave": "#667085",
    "texto_apagado": "#98a2b3",
    "acento": "#2f6df6",
    "acento_hover": "#1f57d6",
    "acento_tenue": "#eef3ff",
    "sobre_acento": "#ffffff",
    "encabezado": "#eef1f5",
    "seleccion": "#dce7ff",
    "exito": "#1f8a4c",
    "error": "#c0392b",
    "log_fondo": "#1c2430",
    "log_texto": "#b8c2d0",
}

PALETA_OSCURA = {
    "fondo": "#14171c",
    "superficie": "#1c2027",
    "superficie_alt": "#191d23",
    "borde": "#2c333d",
    "borde_fuerte": "#39424e",
    "texto": "#e6e9ee",
    "texto_suave": "#9aa4b2",
    "texto_apagado": "#6b7686",
    "acento": "#4d84ff",
    "acento_hover": "#6f9dff",
    "acento_tenue": "#1a2436",
    "sobre_acento": "#0d1117",
    "encabezado": "#232830",
    "seleccion": "#24354f",
    "exito": "#82c98d",
    "error": "#e06c75",
    "log_fondo": "#0f1216",
    "log_texto": "#b8c2d0",
}


def paleta(oscuro: bool) -> dict:
    return dict(PALETA_OSCURA if oscuro else PALETA_CLARA)


def dibujar_icono(lienzo: tk.Canvas, p: dict, oscuro: bool) -> None:
    """Pinta el sol o la luna sobre la barra de acento.

    Se dibuja a mano en vez de usar un emoji: asi hereda el color de la barra,
    se ve igual en cualquier equipo y no depende de las fuentes instaladas.
    El icono muestra a que tema se va al pulsar, no en cual se esta.
    """
    lienzo.delete("all")
    lienzo.configure(background=p["acento"], highlightthickness=0)
    color = p["sobre_acento"]
    cx = cy = 15

    if oscuro:
        # Estamos en oscuro: se ofrece el sol.
        r = 5
        lienzo.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
        for i in range(8):
            angulo = i * pi / 4
            x1, y1 = cx + cos(angulo) * (r + 2.5), cy + sin(angulo) * (r + 2.5)
            x2, y2 = cx + cos(angulo) * (r + 5.5), cy + sin(angulo) * (r + 5.5)
            lienzo.create_line(x1, y1, x2, y2, fill=color, width=2,
                               capstyle="round")
    else:
        # Estamos en claro: se ofrece la luna. El creciente sale de tapar un
        # circulo con otro del color de la barra.
        r = 8
        lienzo.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
        lienzo.create_oval(cx - r + 5, cy - r - 3, cx + r + 5, cy + r - 3,
                           fill=p["acento"], outline="")


def aplicar(raiz: tk.Tk, p: dict) -> ttk.Style:
    """Configura todos los estilos ttk a partir de la paleta."""
    estilo = ttk.Style(raiz)
    try:
        estilo.theme_use("clam")
    except tk.TclError:
        pass

    raiz.configure(background=p["fondo"])

    # --- base ---------------------------------------------------------
    estilo.configure(
        ".",
        background=p["superficie"], foreground=p["texto"],
        fieldbackground=p["superficie"], bordercolor=p["borde"],
        lightcolor=p["superficie"], darkcolor=p["superficie"],
        troughcolor=p["encabezado"], focuscolor=p["acento"],
        font=(FUENTE, 9),
    )

    # Lo que va directamente sobre el fondo de la ventana, no dentro de una
    # tarjeta, lleva el sufijo Fondo.
    estilo.configure("TFrame", background=p["superficie"])
    estilo.configure("Fondo.TFrame", background=p["fondo"])
    estilo.configure("TLabel", background=p["superficie"], foreground=p["texto"])
    estilo.configure("Fondo.TLabel", background=p["fondo"], foreground=p["texto"])
    estilo.configure("Suave.TLabel", background=p["superficie"],
                     foreground=p["texto_suave"])
    estilo.configure("SuaveFondo.TLabel", background=p["fondo"],
                     foreground=p["texto_suave"])
    estilo.configure("Titulo.TLabel", background=p["superficie"],
                     foreground=p["texto"], font=(FUENTE, 10, "bold"))
    # Para el texto que cae sobre la tarjeta ya teñida de la opcion elegida.
    estilo.configure("SuaveTenue.TLabel", background=p["acento_tenue"],
                     foreground=p["texto_suave"])

    # --- tarjetas -----------------------------------------------------
    estilo.configure("TLabelframe", background=p["superficie"],
                     bordercolor=p["borde"], relief="solid", borderwidth=1)
    estilo.configure("TLabelframe.Label", background=p["superficie"],
                     foreground=p["texto_suave"], font=(FUENTE, 9, "bold"))

    # --- botones ------------------------------------------------------
    estilo.configure("TButton", background=p["superficie"], foreground=p["texto"],
                     bordercolor=p["borde_fuerte"], relief="solid", borderwidth=1,
                     padding=(12, 5), font=(FUENTE, 9))
    estilo.map("TButton",
               background=[("pressed", p["encabezado"]),
                           ("active", p["acento_tenue"]),
                           ("disabled", p["superficie"])],
               foreground=[("disabled", p["texto_apagado"])],
               bordercolor=[("active", p["acento"])])

    # El boton principal es el unico relleno de color: no hay duda de donde
    # hay que pulsar.
    estilo.configure("Acento.TButton", background=p["acento"],
                     foreground=p["sobre_acento"], bordercolor=p["acento"],
                     font=(FUENTE, 10, "bold"), padding=(24, 7))
    estilo.map("Acento.TButton",
               background=[("pressed", p["acento_hover"]),
                           ("active", p["acento_hover"]),
                           ("disabled", p["encabezado"])],
               foreground=[("disabled", p["texto_apagado"])],
               bordercolor=[("disabled", p["borde"])])

    # --- selector de vista, sobre la barra de acento --------------------
    estilo.configure("Vista.TRadiobutton", background=p["acento"],
                     foreground=p["sobre_acento"], font=(FUENTE, 9),
                     padding=(14, 4), relief="flat", borderwidth=0,
                     indicatorsize=0, anchor="center")
    estilo.map("Vista.TRadiobutton",
               background=[("selected", p["superficie"]),
                           ("active", p["acento_hover"])],
               foreground=[("selected", p["acento"])])

    # --- casillas y radios ---------------------------------------------
    for nombre, fondo in (("TCheckbutton", p["superficie"]),
                          ("TRadiobutton", p["superficie"]),
                          ("Tarjeta.TRadiobutton", p["superficie"]),
                          ("Elegida.TRadiobutton", p["acento_tenue"])):
        estilo.configure(nombre, background=fondo, foreground=p["texto"],
                         indicatorcolor=p["encabezado"],
                         indicatorrelief="flat", indicatormargin=(0, 0, 6, 0),
                         bordercolor=p["borde_fuerte"],
                         lightcolor=p["borde_fuerte"], darkcolor=p["borde_fuerte"],
                         focuscolor=fondo, padding=(2, 3))
        estilo.map(nombre,
                   background=[("active", fondo)],
                   indicatorcolor=[("selected", p["acento"]),
                                   ("pressed", p["acento_hover"])],
                   bordercolor=[("selected", p["acento"])])
    estilo.configure("Elegida.TRadiobutton", font=(FUENTE, 9, "bold"))

    # --- campos ---------------------------------------------------------
    for nombre in ("TEntry", "TCombobox", "TSpinbox"):
        estilo.configure(nombre, fieldbackground=p["superficie"],
                         background=p["superficie"], foreground=p["texto"],
                         bordercolor=p["borde_fuerte"], arrowcolor=p["texto_suave"],
                         insertcolor=p["texto"], padding=4)
        estilo.map(nombre,
                   bordercolor=[("focus", p["acento"])],
                   fieldbackground=[("readonly", p["superficie"]),
                                    ("disabled", p["encabezado"])],
                   foreground=[("disabled", p["texto_apagado"])])

    # La lista desplegable del combo es un Listbox de tk: no la alcanza ttk.
    raiz.option_add("*TCombobox*Listbox.background", p["superficie"])
    raiz.option_add("*TCombobox*Listbox.foreground", p["texto"])
    raiz.option_add("*TCombobox*Listbox.selectBackground", p["acento"])
    raiz.option_add("*TCombobox*Listbox.selectForeground", p["sobre_acento"])

    # --- pestañas -------------------------------------------------------
    estilo.configure("TNotebook", background=p["fondo"], borderwidth=0,
                     tabmargins=(0, 0, 0, 0))
    estilo.configure("TNotebook.Tab", background=p["encabezado"],
                     foreground=p["texto_suave"], bordercolor=p["borde"],
                     padding=(20, 8), font=(FUENTE, 9))
    estilo.map("TNotebook.Tab",
               background=[("selected", p["superficie"])],
               foreground=[("selected", p["acento"])],
               font=[("selected", (FUENTE, 9, "bold"))])

    # --- tabla ----------------------------------------------------------
    estilo.configure("Treeview", background=p["superficie"],
                     fieldbackground=p["superficie"], foreground=p["texto"],
                     bordercolor=p["borde"], rowheight=24, borderwidth=0)
    estilo.map("Treeview",
               background=[("selected", p["seleccion"])],
               foreground=[("selected", p["texto"])])
    estilo.configure("Treeview.Heading", background=p["encabezado"],
                     foreground=p["texto_suave"], relief="flat",
                     font=(FUENTE, 9, "bold"), padding=(6, 6))
    estilo.map("Treeview.Heading", background=[("active", p["encabezado"])])

    # --- progreso y barras ----------------------------------------------
    # El nombre lleva la orientacion a proposito: ttk busca el diseño como
    # "Horizontal.<estilo>" y un estilo derivado sin ella no existe.
    estilo.configure("Horizontal.TProgressbar", background=p["acento"],
                     troughcolor=p["borde"], bordercolor=p["borde"],
                     lightcolor=p["acento"], darkcolor=p["acento"], thickness=10)
    estilo.configure("Global.Horizontal.TProgressbar",
                     background=p["acento_hover"], troughcolor=p["borde"],
                     bordercolor=p["borde"], lightcolor=p["acento_hover"],
                     darkcolor=p["acento_hover"], thickness=6)

    estilo.configure("TScrollbar", background=p["encabezado"],
                     troughcolor=p["superficie"], bordercolor=p["borde"],
                     arrowcolor=p["texto_suave"])
    estilo.map("TScrollbar", background=[("active", p["borde_fuerte"])])

    estilo.configure("TSeparator", background=p["borde"])

    # --- barra de estado -------------------------------------------------
    estilo.configure("Estado.TFrame", background=p["encabezado"])
    estilo.configure("Estado.TLabel", background=p["encabezado"],
                     foreground=p["texto_suave"])
    estilo.configure("Exito.TLabel", background=p["encabezado"],
                     foreground=p["exito"])

    return estilo
