"""
cursorforge/core/converter.py

Convierte imágenes PNG escaladas en archivos binarios .cursor del
formato XCursor, usando xcursorgen como backend.

Flujo por cada rol:
    1. Toma el ImageEntry asignado al rol
    2. Escala la imagen a cada resolución de exportación (via ImageManager)
    3. Guarda los PNGs temporales en disco
    4. Genera el archivo de configuración .cursor-conf
    5. Llama a xcursorgen para producir el archivo .cursor binario
    6. Crea symlinks para todos los alias del rol

No importa nada de GTK ni de UI.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

from PIL import Image

from cursorforge.core.image_manager import ImageManager
from cursorforge.core.project import (
    CursorProject,
    ImageEntry,
    RoleConfig,
    Hotspot,
)


# ─────────────────────────────────────────────────────────────────────────────
# Resultado de conversión
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConversionResult:
    """
    Resultado de convertir un rol a archivo .cursor.

    role_name  → nombre del rol convertido
    ok         → True si se generó el archivo sin errores
    output     → ruta al archivo .cursor generado (None si falló)
    aliases    → rutas a los symlinks de alias creados
    errors     → mensajes de error si ok=False
    warnings   → advertencias no bloqueantes
    """
    role_name: str
    ok:        bool             = True
    output:    Optional[Path]   = None
    aliases:   list[Path]       = field(default_factory=list)
    errors:    list[str]        = field(default_factory=list)
    warnings:  list[str]        = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class BuildResult:
    """
    Resultado de construir el tema completo.

    theme_dir    → ruta a la carpeta del tema generado
    ok           → True si todos los roles se convirtieron sin error
    conversions  → resultado individual por cada rol
    skipped      → roles omitidos por no tener imagen asignada
    """
    theme_dir:   Optional[Path]             = None
    ok:          bool                       = True
    conversions: list[ConversionResult]     = field(default_factory=list)
    skipped:     list[str]                  = field(default_factory=list)

    @property
    def failed(self) -> list[ConversionResult]:
        return [c for c in self.conversions if not c.ok]

    @property
    def succeeded(self) -> list[ConversionResult]:
        return [c for c in self.conversions if c.ok]

    def add_conversion(self, result: ConversionResult) -> None:
        self.conversions.append(result)
        if not result.ok:
            self.ok = False


# ─────────────────────────────────────────────────────────────────────────────
# Converter
# ─────────────────────────────────────────────────────────────────────────────

class Converter:
    """
    Convierte un CursorProject en un tema XCursor instalable.

    Uso:
        converter = Converter()

        # Verificar que xcursorgen está disponible
        if not converter.xcursorgen_available():
            print("Instala x11-apps: sudo apt install x11-apps")

        # Construir el tema completo en un directorio
        result = converter.build(project, output_dir=Path("~/.icons/MiTema"))
    """

    def __init__(self, image_manager: Optional[ImageManager] = None):
        self._manager = image_manager or ImageManager()

    # ── Verificación del sistema ──────────────────────────────────────────────

    def xcursorgen_available(self) -> bool:
        """True si xcursorgen está instalado y accesible en el PATH."""
        try:
            result = subprocess.run(
                ["xcursorgen", "--help"],
                capture_output=True,
                timeout=5,
            )
            # xcursorgen devuelve 1 con --help pero eso significa que existe
            return True
        except FileNotFoundError:
            return False
        except subprocess.TimeoutExpired:
            return False

    # ── Construcción del tema completo ────────────────────────────────────────

    def build(
        self,
        project:      CursorProject,
        output_dir:   Path,
        resolutions:  Optional[list[int]] = None,
        on_progress:  Optional[Callable[[str, int, int], None]] = None,
    ) -> BuildResult:
        """
        Construye el tema XCursor completo en output_dir.

        output_dir   → carpeta raíz del tema (ej: ~/.icons/MiTema)
                       Se crea si no existe.
        resolutions  → lista de tamaños px; usa project.export.resolutions si None
        on_progress  → callback(role_name, current, total) para reportar progreso

        La estructura generada es:
            output_dir/
            ├── index.theme
            └── cursors/
                ├── default        ← archivo .cursor binario
                ├── arrow          ← symlink → default
                ├── pointer        ← archivo .cursor binario
                └── ...
        """
        build_result = BuildResult()
        resolutions  = resolutions or project.export.resolutions
        output_dir   = Path(output_dir)
        cursors_dir  = output_dir / "cursors"
        cursors_dir.mkdir(parents=True, exist_ok=True)

        # Verificar xcursorgen antes de empezar
        if not self.xcursorgen_available():
            build_result.ok = False
            build_result.conversions.append(ConversionResult(
                role_name="__setup__",
                ok=False,
                errors=["xcursorgen no encontrado. Instala: sudo apt install x11-apps"],
            ))
            return build_result

        roles = list(project.roles.items())
        total = len(roles)

        for i, (role_name, role_cfg) in enumerate(roles):
            if on_progress:
                on_progress(role_name, i + 1, total)

            # Rol sin imagen: omitir, el sistema usará el fallback
            if not role_cfg.is_assigned:
                build_result.skipped.append(role_name)
                continue

            result = self._convert_role(
                role_name   = role_name,
                role_cfg    = role_cfg,
                project     = project,
                cursors_dir = cursors_dir,
                resolutions = resolutions,
            )
            build_result.add_conversion(result)

        # Generar index.theme
        self._write_index_theme(
            output_dir = output_dir,
            name       = project.meta.name,
            inherit    = project.export.inherit,
        )

        build_result.theme_dir = output_dir
        return build_result

    # ── Conversión de un rol individual ──────────────────────────────────────

    def _convert_role(
        self,
        role_name:   str,
        role_cfg:    RoleConfig,
        project:     CursorProject,
        cursors_dir: Path,
        resolutions: list[int],
    ) -> ConversionResult:
        """
        Convierte un único rol a archivo .cursor y crea sus symlinks.
        Trabaja en un directorio temporal que se limpia al terminar.
        """
        result = ConversionResult(role_name=role_name)

        # Obtener el ImageEntry del proyecto
        if role_cfg.image_id not in project.images:
            result.add_error(
                f"image_id '{role_cfg.image_id}' no encontrado en el proyecto."
            )
            return result

        entry = project.images[role_cfg.image_id]

        if not entry.exists:
            result.add_error(
                f"La imagen '{entry.filename}' ya no está en disco: {entry.path}"
            )
            return result

        with tempfile.TemporaryDirectory(prefix="cursorforge_") as tmpdir:
            tmp = Path(tmpdir)

            try:
                # 1. Escalar la imagen a cada resolución y guardar como PNG
                png_paths = self._export_pngs(
                    entry       = entry,
                    hotspot     = role_cfg.hotspot,
                    resolutions = resolutions,
                    tmp         = tmp,
                    role_name   = role_name,
                )

                # 2. Generar el archivo .cursor-conf
                conf_path = self._write_cursor_conf(
                    role_name   = role_name,
                    hotspot     = role_cfg.hotspot,
                    png_paths   = png_paths,
                    resolutions = resolutions,
                    entry       = entry,
                    tmp         = tmp,
                )

                # 3. Llamar a xcursorgen
                cursor_path = cursors_dir / role_name
                self._run_xcursorgen(conf_path, cursor_path, result)

                if result.ok:
                    result.output = cursor_path

                    # 4. Crear symlinks para los alias
                    for alias in role_cfg.aliases:
                        alias_path = cursors_dir / alias
                        self._create_symlink(alias_path, role_name, result)
                        if alias_path.exists() or alias_path.is_symlink():
                            result.aliases.append(alias_path)

            except Exception as e:
                result.add_error(f"Error inesperado al convertir '{role_name}': {e}")

        return result

    # ── Helpers de conversión ─────────────────────────────────────────────────

    def _export_pngs(
        self,
        entry:       ImageEntry,
        hotspot:     Hotspot,
        resolutions: list[int],
        tmp:         Path,
        role_name:   str,
    ) -> dict[int, Path]:
        """
        Escala la imagen a cada resolución y guarda los PNGs en tmp.
        Devuelve { tamaño_px: ruta_png }.
        """
        # Determinar el tamaño fuente para escalar el hotspot
        source_size = max(entry.width, entry.height)
        png_paths: dict[int, Path] = {}

        for size in resolutions:
            img: Image.Image = self._manager.resize_for_export(entry, size)
            png_path = tmp / f"{role_name}_{size}.png"
            img.save(png_path, format="PNG", optimize=False)
            png_paths[size] = png_path

        return png_paths

    def _write_cursor_conf(
        self,
        role_name:   str,
        hotspot:     Hotspot,
        png_paths:   dict[int, Path],
        resolutions: list[int],
        entry:       ImageEntry,
        tmp:         Path,
    ) -> Path:
        """
        Genera el archivo .cursor-conf que xcursorgen necesita.

        Formato de cada línea:
            <size> <hotspot_x> <hotspot_y> <png_path> [<delay_ms>]

        El hotspot se escala proporcionalmente para cada resolución.
        """
        source_size = max(entry.width, entry.height) or 1
        lines: list[str] = []

        for size in resolutions:
            if size not in png_paths:
                continue

            scaled = hotspot.scaled(source_size, size)
            # xcursorgen espera rutas absolutas o relativas al conf
            lines.append(
                f"{size} {scaled.x} {scaled.y} {png_paths[size]}"
            )

        conf_path = tmp / f"{role_name}.cursor-conf"
        conf_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return conf_path

    def _run_xcursorgen(
        self,
        conf_path:   Path,
        output_path: Path,
        result:      ConversionResult,
    ) -> None:
        """
        Ejecuta xcursorgen para generar el archivo .cursor binario.
        Modifica result en caso de error.
        """
        try:
            proc = subprocess.run(
                ["xcursorgen", str(conf_path), str(output_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                result.add_error(
                    f"xcursorgen falló (código {proc.returncode})"
                    + (f": {stderr}" if stderr else "")
                )
            elif proc.stderr.strip():
                # xcursorgen a veces emite warnings en stderr con returncode 0
                result.add_warning(f"xcursorgen: {proc.stderr.strip()}")

        except subprocess.TimeoutExpired:
            result.add_error("xcursorgen tardó demasiado (timeout 30s).")
        except FileNotFoundError:
            result.add_error(
                "xcursorgen no encontrado. Instala: sudo apt install x11-apps"
            )

    @staticmethod
    def _create_symlink(
        alias_path: Path,
        target_name: str,
        result: ConversionResult,
    ) -> None:
        """
        Crea un symlink alias_path → target_name.
        Si ya existe (de una instalación previa) lo reemplaza.
        """
        try:
            if alias_path.exists() or alias_path.is_symlink():
                alias_path.unlink()
            alias_path.symlink_to(target_name)
        except OSError as e:
            result.add_warning(f"No se pudo crear symlink '{alias_path.name}': {e}")

    @staticmethod
    def _write_index_theme(
        output_dir: Path,
        name:       str,
        inherit:    str = "Adwaita",
    ) -> None:
        """
        Genera el archivo index.theme requerido por el sistema de iconos.
        """
        content = (
            f"[Icon Theme]\n"
            f"Name={name}\n"
            f"Comment=Tema de cursor generado con CursorForge\n"
            f"Inherits={inherit}\n"
        )
        (output_dir / "index.theme").write_text(content, encoding="utf-8")

    # ── Utilidad: vista previa del conf (sin xcursorgen) ─────────────────────

    def preview_cursor_conf(
        self,
        project:     CursorProject,
        role_name:   str,
        resolutions: Optional[list[int]] = None,
    ) -> Optional[str]:
        """
        Devuelve el contenido del .cursor-conf que se generaría para un rol,
        sin necesitar xcursorgen ni escribir archivos en disco.
        Útil para debugging y tests.
        """
        resolutions = resolutions or project.export.resolutions

        if role_name not in project.roles:
            return None

        role_cfg = project.roles[role_name]
        if not role_cfg.is_assigned or role_cfg.image_id not in project.images:
            return None

        entry       = project.images[role_cfg.image_id]
        source_size = max(entry.width, entry.height) or 1
        lines: list[str] = []

        for size in resolutions:
            scaled = role_cfg.hotspot.scaled(source_size, size)
            lines.append(
                f"{size} {scaled.x} {scaled.y} "
                f"/tmp/cursorforge/{role_name}_{size}.png"
            )

        return "\n".join(lines)
