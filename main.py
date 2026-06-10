"""
CursorForge — punto de entrada principal.
Ejecutar desde la raíz del proyecto con el entorno virtual activo:
    python main.py
"""

import sys


def main():
    # Verificar versión de Python
    if sys.version_info < (3, 11):
        print("Error: CursorForge requiere Python 3.11 o superior.")
        print(f"       Versión detectada: {sys.version}")
        sys.exit(1)

    # Verificar dependencias antes de importar la UI
    try:
        import gi  # noqa: F401
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError):
        print("Error: PyGObject (GTK4) no está instalado o no se encontró.")
        print("       Ejecuta: ./setup.sh  para instalar las dependencias.")
        sys.exit(1)

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("Error: Pillow no está instalado.")
        print("       Ejecuta: ./setup.sh  para instalar las dependencias.")
        sys.exit(1)

    # Iniciar la aplicación
    from cursorforge.ui.main_window import CursorForgeApp
    app = CursorForgeApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
