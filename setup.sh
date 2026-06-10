#!/usr/bin/env bash
# setup.sh — configura el entorno de desarrollo de CursorForge.
# Uso: ./setup.sh
# Probado en Linux Mint 21+ y Ubuntu 22.04+

set -e  # detener si cualquier comando falla

VENV_DIR=".venv"
PYTHON_MIN="3.11"

echo "=============================="
echo "  CursorForge — setup"
echo "=============================="

# ── 1. Verificar Python ────────────────────────────────────────────────────────
echo ""
echo "[ 1/5 ] Verificando Python..."

if ! command -v python3 &> /dev/null; then
    echo "  ERROR: python3 no encontrado. Instálalo con:"
    echo "         sudo apt install python3"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED_MAJOR=3
REQUIRED_MINOR=11

ACTUAL_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
ACTUAL_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$ACTUAL_MAJOR" -lt "$REQUIRED_MAJOR" ] || \
   ([ "$ACTUAL_MAJOR" -eq "$REQUIRED_MAJOR" ] && [ "$ACTUAL_MINOR" -lt "$REQUIRED_MINOR" ]); then
    echo "  ERROR: Se requiere Python $PYTHON_MIN o superior."
    echo "         Versión detectada: $PYTHON_VERSION"
    echo "         Instala con: sudo apt install python3.11"
    exit 1
fi

echo "  OK — Python $PYTHON_VERSION"

# ── 2. Instalar dependencias del sistema ────────────────────────────────────────
echo ""
echo "[ 2/5 ] Verificando dependencias del sistema..."

SYSTEM_DEPS=("python3-gi" "python3-gi-cairo" "gir1.2-gtk-4.0" "x11-apps")
MISSING=()

for dep in "${SYSTEM_DEPS[@]}"; do
    if ! dpkg -s "$dep" &> /dev/null 2>&1; then
        MISSING+=("$dep")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "  Instalando: ${MISSING[*]}"
    sudo apt-get install -y "${MISSING[@]}"
else
    echo "  OK — dependencias del sistema presentes"
fi

# ── 3. Crear entorno virtual ───────────────────────────────────────────────────
echo ""
echo "[ 3/5 ] Configurando entorno virtual..."

if [ -d "$VENV_DIR" ]; then
    echo "  El entorno virtual ya existe, omitiendo creación."
else
    python3 -m venv "$VENV_DIR" --system-site-packages
    # --system-site-packages permite acceder a PyGObject instalado a nivel sistema
    echo "  OK — entorno virtual creado en $VENV_DIR/"
fi

# ── 4. Instalar dependencias Python ────────────────────────────────────────────
echo ""
echo "[ 4/5 ] Instalando dependencias Python..."

"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r requirements.txt --quiet

echo "  OK — dependencias instaladas"

# ── 5. Verificar xcursorgen ────────────────────────────────────────────────────
echo ""
echo "[ 5/5 ] Verificando xcursorgen..."

if ! command -v xcursorgen &> /dev/null; then
    echo "  AVISO: xcursorgen no encontrado."
    echo "         CursorForge puede instalar x11-apps automáticamente."
    echo "         O instala manualmente: sudo apt install x11-apps"
else
    XCUR_PATH=$(command -v xcursorgen)
    echo "  OK — xcursorgen en $XCUR_PATH"
fi

# ── Resultado final ────────────────────────────────────────────────────────────
echo ""
echo "=============================="
echo "  Setup completado."
echo ""
echo "  Para iniciar CursorForge:"
echo "    source .venv/bin/activate"
echo "    python main.py"
echo ""
echo "  O directamente:"
echo "    .venv/bin/python main.py"
echo "=============================="
