# CursorForge

Crea temas de cursor personalizados para Linux desde tus propias imágenes.

## Características

- Modo básico: dos imágenes (normal + activo) generan automáticamente los ~30 roles del sistema
- Modo avanzado: asigna una imagen diferente a cada rol individualmente
- Editor visual de hotspot (punto de clic) por rol
- Multi-resolución: genera cursores en 24, 32, 48 y 64 px
- Instalación con un clic en `~/.icons/`
- Guarda y carga proyectos `.cursorproject`

## Requisitos

- Linux (probado en Linux Mint 21+ y Ubuntu 22.04+)
- Python 3.11 o superior
- GTK 4.0
- `xcursorgen` (paquete `x11-apps`)

## Instalación rápida

```bash
git clone https://github.com/tu-usuario/cursorforge.git
cd cursorforge
chmod +x setup.sh
./setup.sh
```

## Uso

```bash
source .venv/bin/activate
python main.py
```

## Estructura del proyecto

```
cursorforge/
├── main.py                  # punto de entrada
├── setup.sh                 # setup automático del entorno
├── requirements.txt         # dependencias Python
├── cursorforge/
│   ├── core/                # lógica sin UI
│   │   ├── project.py       # modelo de datos del proyecto
│   │   ├── image_manager.py # importación y validación de imágenes
│   │   ├── roles.py         # definición de roles y alias
│   │   ├── converter.py     # genera archivos .cursor
│   │   ├── installer.py     # instala el tema en ~/.icons/
│   │   └── exporter.py      # empaqueta el tema como .zip
│   ├── ui/                  # interfaz gráfica GTK4
│   │   ├── main_window.py
│   │   ├── panel_images.py
│   │   ├── panel_roles.py
│   │   ├── panel_hotspot.py
│   │   ├── panel_export.py
│   │   └── dialogs.py
│   └── assets/              # datos estáticos
│       ├── roles_aliases.json
│       └── default_groups.json
├── tests/
└── docs/
```

## Desarrollo

Para instalar herramientas de desarrollo adicionales (linting, type checking):

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Correr tests:

```bash
pytest tests/
```

## Licencia

MIT
