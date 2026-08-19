"""Punto de entrada para el ejecutable empaquetado.

PyInstaller necesita un archivo suelto que arranque la aplicacion; desde
Python normal se sigue usando `python -m descargador.gui`.
"""

from descargador.gui import main

if __name__ == "__main__":
    main()
