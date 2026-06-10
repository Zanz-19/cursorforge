"""
cursorforge/core/image_manager.py

Gestión de imágenes fuente: importación, validación, escalado
y generación de thumbnails.

Toda operación con Pillow vive aquí. El resto de la app trabaja
con ImageEntry (project.py) y llama a este módulo cuando necesita
leer o transformar píxeles.

No importa nada de GTK ni de UI.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError

from cursorforge.core.project import (
    CursorProject,
    ImageEntry,
)

# ── Constantes ────────────────────────────────────────────────────────────────

THUMBNAIL_SIZE     = 64          # px — tamaño del thumbnail en base64
MIN_RECOMMENDED_PX = 48          # por debajo de esto se advierte al usuario
SUPPORTED_FORMATS  = {".png", ".svg", ".webp", ".bmp", ".gif"}

# Tamaños de exportación estándar (también definidos en ExportConfig)
EXPORT_SIZES = [24, 32, 48, 64]


# ─────────────────────────────────────────────────────────────────────────────
# Resultado de validación
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """
    Resultado de validar una imagen antes de importarla.

    ok       → True si la imagen es usable (puede tener warnings)
    errors   → problemas que impiden el uso (bloquean la importación)
    warnings → advertencias que no bloquean pero el usuario debe ver
    """
    ok:       bool        = True
    errors:   list[str]   = field(default_factory=list)
    warnings: list[str]   = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def __bool__(self) -> bool:
        return self.ok


# ─────────────────────────────────────────────────────────────────────────────
# ImageManager
# ─────────────────────────────────────────────────────────────────────────────

class ImageManager:
    """
    Maneja todas las operaciones sobre imágenes fuente.

    No guarda estado propio: opera sobre objetos ImageEntry y
    devuelve resultados. El estado del proyecto vive en CursorProject.

    Uso típico:
        manager = ImageManager()

        # Validar antes de importar
        result = manager.validate(path)
        if result.ok:
            entry = manager.import_image(path)
            project.add_image(entry)
    """

    # ── Validación ────────────────────────────────────────────────────────────

    def validate(self, path: str | Path) -> ValidationResult:
        """
        Valida una imagen antes de importarla.
        No modifica nada, solo informa.
        """
        result = ValidationResult()
        path = Path(path)

        # Existencia
        if not path.exists():
            result.add_error(f"El archivo no existe: {path}")
            return result

        # Extensión reconocida
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_FORMATS:
            result.add_error(
                f"Formato no soportado: '{suffix}'. "
                f"Usa: {', '.join(sorted(SUPPORTED_FORMATS))}"
            )
            return result

        # SVG: no se puede abrir con Pillow directamente
        if suffix == ".svg":
            result.add_warning(
                "Los archivos SVG se convierten a PNG automáticamente. "
                "Requiere 'cairosvg' instalado."
            )
            return result

        # Intentar abrir con Pillow
        try:
            img = Image.open(path)
            img.verify()            # detecta archivos corruptos
            img = Image.open(path)  # re-abrir tras verify()
        except UnidentifiedImageError:
            result.add_error("El archivo no es una imagen válida o está corrupto.")
            return result
        except Exception as e:
            result.add_error(f"No se pudo abrir la imagen: {e}")
            return result

        width, height = img.size

        # Canal alfa
        if img.mode not in ("RGBA", "LA", "PA"):
            result.add_warning(
                f"La imagen está en modo '{img.mode}' y no tiene canal alfa. "
                "El cursor tendrá fondo opaco. Se recomienda un PNG con transparencia."
            )

        # Resolución mínima recomendada
        min_dim = min(width, height)
        if min_dim < MIN_RECOMMENDED_PX:
            result.add_warning(
                f"La imagen es muy pequeña ({width}×{height} px). "
                f"Se recomienda al menos {MIN_RECOMMENDED_PX}×{MIN_RECOMMENDED_PX} px "
                "para evitar pérdida de calidad al escalar."
            )

        # Imagen no cuadrada
        if width != height:
            result.add_warning(
                f"La imagen no es cuadrada ({width}×{height} px). "
                "Se recortará o ajustará al exportar."
            )

        return result

    # ── Importación ───────────────────────────────────────────────────────────

    def import_image(
        self,
        path:     str | Path,
        image_id: Optional[str] = None,
    ) -> ImageEntry:
        """
        Importa una imagen y construye un ImageEntry listo para
        agregar al proyecto con project.add_image().

        Lanza:
            FileNotFoundError  si el archivo no existe
            ValueError         si el archivo no es una imagen válida
        """
        path = Path(path).resolve()

        if not path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {path}")

        img = self._open_image(path)
        img = self._normalize(img)    # convierte a RGBA, cuadra si es necesario

        width, height = img.size
        has_alpha     = img.mode == "RGBA"
        thumbnail_b64 = self._make_thumbnail_b64(img)
        img_id        = image_id or CursorProject.generate_image_id()

        return ImageEntry(
            image_id      = img_id,
            path          = str(path),
            filename      = path.name,
            width         = width,
            height        = height,
            has_alpha     = has_alpha,
            thumbnail_b64 = thumbnail_b64,
        )

    # ── Escalado para exportación ─────────────────────────────────────────────

    def resize_for_export(
        self,
        entry:   ImageEntry,
        size:    int,
        fit:     str = "contain",
    ) -> Image.Image:
        """
        Carga la imagen de un ImageEntry y la escala al tamaño de exportación.

        size → tamaño objetivo en px (ej: 32)
        fit  → "contain" (escala manteniendo aspecto, rellena con transparencia)
               "cover"   (escala y recorta al cuadrado exacto)

        Devuelve una imagen PIL RGBA lista para guardar como PNG.

        Lanza FileNotFoundError si la imagen ya no está en disco.
        """
        path = Path(entry.path)
        if not path.exists():
            raise FileNotFoundError(
                f"La imagen fuente ya no está en disco: {path}"
            )

        img = self._open_image(path)
        img = self._to_rgba(img)

        if fit == "cover":
            img = self._resize_cover(img, size)
        else:
            img = self._resize_contain(img, size)

        return img

    def resize_all_export_sizes(
        self,
        entry: ImageEntry,
        sizes: list[int] = None,
        fit:   str = "contain",
    ) -> dict[int, Image.Image]:
        """
        Devuelve un dict { tamaño_px: imagen_PIL } para todos los
        tamaños de exportación solicitados.
        """
        sizes = sizes or EXPORT_SIZES
        return {
            size: self.resize_for_export(entry, size, fit)
            for size in sizes
        }

    # ── Thumbnail ─────────────────────────────────────────────────────────────

    def thumbnail_from_entry(self, entry: ImageEntry) -> Optional[Image.Image]:
        """
        Devuelve la imagen PIL del thumbnail de un ImageEntry,
        decodificando desde base64. None si no hay thumbnail.
        """
        if not entry.thumbnail_b64:
            return None
        data = base64.b64decode(entry.thumbnail_b64)
        return Image.open(io.BytesIO(data))

    def refresh_thumbnail(self, entry: ImageEntry) -> ImageEntry:
        """
        Regenera el thumbnail de un ImageEntry leyendo la imagen de disco.
        Devuelve un nuevo ImageEntry con el thumbnail actualizado.
        Útil si la imagen en disco fue modificada externamente.
        """
        path = Path(entry.path)
        if not path.exists():
            raise FileNotFoundError(f"Imagen no encontrada: {path}")

        img      = self._open_image(path)
        img      = self._normalize(img)
        thumb_b64 = self._make_thumbnail_b64(img)

        # Construimos un nuevo entry (ImageEntry es un dataclass mutable)
        from dataclasses import replace
        return replace(entry, thumbnail_b64=thumb_b64)

    # ── Internos ──────────────────────────────────────────────────────────────

    def _open_image(self, path: Path) -> Image.Image:
        """Abre una imagen desde disco, con manejo de errores claro."""
        try:
            img = Image.open(path)
            img.load()      # fuerza la decodificación completa
            return img
        except UnidentifiedImageError:
            raise ValueError(
                f"El archivo no es una imagen reconocida: {path.name}"
            )
        except Exception as e:
            raise ValueError(f"No se pudo abrir '{path.name}': {e}")

    def _normalize(self, img: Image.Image) -> Image.Image:
        """
        Lleva la imagen a un estado canónico:
        - Convierte a RGBA (preserva o agrega canal alfa)
        - Descompone frames animados (toma el primero)
        """
        # GIF animado u otro formato multi-frame: tomar el frame 0
        if hasattr(img, "n_frames") and img.n_frames > 1:
            img.seek(0)

        return self._to_rgba(img)

    @staticmethod
    def _to_rgba(img: Image.Image) -> Image.Image:
        """Convierte cualquier modo a RGBA."""
        if img.mode == "RGBA":
            return img
        if img.mode == "P":
            # Paleta con posible transparencia
            img = img.convert("RGBA")
        elif img.mode in ("L", "LA"):
            img = img.convert("RGBA")
        elif img.mode == "RGB":
            img = img.convert("RGBA")
        else:
            img = img.convert("RGBA")
        return img

    @staticmethod
    def _resize_contain(img: Image.Image, size: int) -> Image.Image:
        """
        Escala la imagen para que quepa en un cuadrado de `size`×`size`
        manteniendo la proporción. El espacio sobrante queda transparente.
        """
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

        w, h   = img.size
        scale  = size / max(w, h)
        nw, nh = round(w * scale), round(h * scale)
        resized = img.resize((nw, nh), Image.LANCZOS)

        offset_x = (size - nw) // 2
        offset_y = (size - nh) // 2
        canvas.paste(resized, (offset_x, offset_y), resized)
        return canvas

    @staticmethod
    def _resize_cover(img: Image.Image, size: int) -> Image.Image:
        """
        Escala y recorta la imagen para cubrir exactamente `size`×`size`.
        Puede cortar los bordes si la imagen no es cuadrada.
        """
        w, h  = img.size
        scale = size / min(w, h)
        nw, nh = round(w * scale), round(h * scale)
        resized = img.resize((nw, nh), Image.LANCZOS)

        left   = (nw - size) // 2
        top    = (nh - size) // 2
        return resized.crop((left, top, left + size, top + size))

    @staticmethod
    def _make_thumbnail_b64(img: Image.Image) -> str:
        """
        Genera un thumbnail PNG de THUMBNAIL_SIZE×THUMBNAIL_SIZE
        codificado en base64, listo para guardar en el JSON del proyecto.
        """
        thumb = img.copy()
        thumb.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.LANCZOS)

        # Centrar en canvas cuadrado
        canvas = Image.new("RGBA", (THUMBNAIL_SIZE, THUMBNAIL_SIZE), (0, 0, 0, 0))
        tw, th = thumb.size
        ox = (THUMBNAIL_SIZE - tw) // 2
        oy = (THUMBNAIL_SIZE - th) // 2
        canvas.paste(thumb, (ox, oy), thumb if thumb.mode == "RGBA" else None)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("ascii")
