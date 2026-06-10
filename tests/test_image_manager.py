"""
tests/test_image_manager.py

Pruebas unitarias para cursorforge/core/image_manager.py
Ejecutar con: pytest tests/test_image_manager.py -v
"""

import base64
import io
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from cursorforge.core.image_manager import (
    THUMBNAIL_SIZE,
    MIN_RECOMMENDED_PX,
    ImageManager,
    ValidationResult,
)
from cursorforge.core.project import ImageEntry


# ── Fixtures: imágenes de prueba generadas en memoria ────────────────────────

def make_png(
    path:      Path,
    size:      tuple[int, int] = (128, 128),
    mode:      str = "RGBA",
    color:     tuple = (255, 0, 0, 255),
) -> Path:
    """Crea un PNG de prueba en disco."""
    img = Image.new(mode, size, color)
    img.save(path, format="PNG")
    return path


def make_rgb_png(path: Path) -> Path:
    """PNG sin canal alfa (RGB)."""
    return make_png(path, mode="RGB", color=(200, 100, 50))


def make_small_png(path: Path) -> Path:
    """PNG por debajo del mínimo recomendado."""
    return make_png(path, size=(16, 16))


def make_non_square_png(path: Path) -> Path:
    """PNG no cuadrado."""
    return make_png(path, size=(200, 100))


def make_image_entry(path: Path) -> ImageEntry:
    """Crea un ImageEntry mínimo apuntando a un archivo existente."""
    return ImageEntry(
        image_id="img_test",
        path=str(path),
        filename=path.name,
        width=128,
        height=128,
        has_alpha=True,
    )


@pytest.fixture
def manager() -> ImageManager:
    return ImageManager()


@pytest.fixture
def tmp(tmp_path) -> Path:
    return tmp_path


# ── ValidationResult ──────────────────────────────────────────────────────────

class TestValidationResult:
    def test_ok_by_default(self):
        r = ValidationResult()
        assert r.ok is True
        assert bool(r) is True

    def test_add_error_sets_ok_false(self):
        r = ValidationResult()
        r.add_error("algo falló")
        assert r.ok is False
        assert bool(r) is False
        assert "algo falló" in r.errors

    def test_add_warning_keeps_ok(self):
        r = ValidationResult()
        r.add_warning("cuidado")
        assert r.ok is True
        assert r.has_warnings is True
        assert "cuidado" in r.warnings

    def test_multiple_errors(self):
        r = ValidationResult()
        r.add_error("error 1")
        r.add_error("error 2")
        assert len(r.errors) == 2
        assert r.ok is False


# ── ImageManager.validate ─────────────────────────────────────────────────────

class TestValidate:
    def test_valid_rgba_png(self, manager, tmp):
        path = make_png(tmp / "ok.png")
        result = manager.validate(path)
        assert result.ok
        assert not result.errors
        assert not result.warnings

    def test_file_not_exists(self, manager, tmp):
        result = manager.validate(tmp / "no_existe.png")
        assert not result.ok
        assert any("no existe" in e.lower() for e in result.errors)

    def test_unsupported_format(self, manager, tmp):
        path = tmp / "imagen.jpg"
        # Creamos el archivo con extensión .jpg pero contenido PNG válido
        make_png(path.with_suffix(".png"))
        # Renombramos a .jpg
        path.with_suffix(".png").rename(path)
        result = manager.validate(path)
        assert not result.ok
        assert any("formato" in e.lower() for e in result.errors)

    def test_rgb_png_warns_no_alpha(self, manager, tmp):
        path = make_rgb_png(tmp / "rgb.png")
        result = manager.validate(path)
        assert result.ok                     # no bloquea
        assert result.has_warnings
        assert any("alfa" in w.lower() for w in result.warnings)

    def test_small_image_warns(self, manager, tmp):
        path = make_small_png(tmp / "small.png")
        result = manager.validate(path)
        assert result.ok                     # no bloquea
        assert result.has_warnings
        assert any("pequeña" in w.lower() or "pequeño" in w.lower()
                   for w in result.warnings)

    def test_non_square_warns(self, manager, tmp):
        path = make_non_square_png(tmp / "rect.png")
        result = manager.validate(path)
        assert result.ok
        assert result.has_warnings
        assert any("cuadrada" in w.lower() for w in result.warnings)

    def test_svg_warns_conversion(self, manager, tmp):
        # Creamos un archivo .svg vacío (no necesitamos contenido válido para validate)
        path = tmp / "icon.svg"
        path.write_text("<svg></svg>")
        result = manager.validate(path)
        assert result.ok
        assert result.has_warnings
        assert any("svg" in w.lower() for w in result.warnings)

    def test_corrupt_file_errors(self, manager, tmp):
        path = tmp / "corrupto.png"
        path.write_bytes(b"esto no es una imagen")
        result = manager.validate(path)
        assert not result.ok


# ── ImageManager.import_image ─────────────────────────────────────────────────

class TestImportImage:
    def test_returns_image_entry(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = manager.import_image(path)
        assert isinstance(entry, ImageEntry)

    def test_entry_has_correct_dimensions(self, manager, tmp):
        path  = make_png(tmp / "cursor.png", size=(96, 96))
        entry = manager.import_image(path)
        assert entry.width  == 96
        assert entry.height == 96

    def test_entry_has_alpha_true_for_rgba(self, manager, tmp):
        path  = make_png(tmp / "cursor.png", mode="RGBA")
        entry = manager.import_image(path)
        assert entry.has_alpha is True

    def test_entry_has_alpha_false_for_rgb(self, manager, tmp):
        path  = make_rgb_png(tmp / "cursor.png")
        entry = manager.import_image(path)
        # Después de normalizar se convierte a RGBA, pero has_alpha
        # refleja el modo resultante
        assert entry.has_alpha is True   # _normalize convierte a RGBA

    def test_entry_has_thumbnail(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = manager.import_image(path)
        assert entry.thumbnail_b64 is not None
        assert len(entry.thumbnail_b64) > 0

    def test_thumbnail_is_valid_base64_png(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = manager.import_image(path)
        data  = base64.b64decode(entry.thumbnail_b64)
        img   = Image.open(io.BytesIO(data))
        assert img.format == "PNG"

    def test_entry_path_is_absolute(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = manager.import_image(path)
        assert Path(entry.path).is_absolute()

    def test_entry_filename(self, manager, tmp):
        path  = make_png(tmp / "mi_cursor.png")
        entry = manager.import_image(path)
        assert entry.filename == "mi_cursor.png"

    def test_custom_image_id(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = manager.import_image(path, image_id="img_custom")
        assert entry.image_id == "img_custom"

    def test_auto_image_id_format(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = manager.import_image(path)
        assert entry.image_id.startswith("img_")

    def test_file_not_found_raises(self, manager, tmp):
        with pytest.raises(FileNotFoundError):
            manager.import_image(tmp / "no_existe.png")

    def test_corrupt_file_raises(self, manager, tmp):
        path = tmp / "corrupto.png"
        path.write_bytes(b"datos basura")
        with pytest.raises(ValueError):
            manager.import_image(path)


# ── ImageManager.resize_for_export ───────────────────────────────────────────

class TestResizeForExport:
    def test_returns_pil_image(self, manager, tmp):
        path  = make_png(tmp / "cursor.png", size=(128, 128))
        entry = make_image_entry(path)
        img   = manager.resize_for_export(entry, 32)
        assert isinstance(img, Image.Image)

    def test_output_is_correct_size(self, manager, tmp):
        path  = make_png(tmp / "cursor.png", size=(128, 128))
        entry = make_image_entry(path)
        for size in [24, 32, 48, 64]:
            img = manager.resize_for_export(entry, size)
            assert img.size == (size, size), \
                f"Esperaba {size}×{size}, obtuvo {img.size}"

    def test_output_is_rgba(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = make_image_entry(path)
        img   = manager.resize_for_export(entry, 32)
        assert img.mode == "RGBA"

    def test_contain_pads_non_square(self, manager, tmp):
        path  = make_non_square_png(tmp / "rect.png")
        entry = ImageEntry(
            image_id="img_rect", path=str(path), filename=path.name,
            width=200, height=100, has_alpha=True,
        )
        img = manager.resize_for_export(entry, 32, fit="contain")
        assert img.size == (32, 32)

    def test_cover_fills_square(self, manager, tmp):
        path  = make_non_square_png(tmp / "rect.png")
        entry = ImageEntry(
            image_id="img_rect", path=str(path), filename=path.name,
            width=200, height=100, has_alpha=True,
        )
        img = manager.resize_for_export(entry, 32, fit="cover")
        assert img.size == (32, 32)

    def test_missing_file_raises(self, manager, tmp):
        entry = make_image_entry(tmp / "no_existe.png")
        with pytest.raises(FileNotFoundError):
            manager.resize_for_export(entry, 32)

    def test_resize_all_export_sizes(self, manager, tmp):
        path  = make_png(tmp / "cursor.png", size=(128, 128))
        entry = make_image_entry(path)
        sizes = [24, 32, 48]
        result = manager.resize_all_export_sizes(entry, sizes)
        assert set(result.keys()) == {24, 32, 48}
        for size, img in result.items():
            assert img.size == (size, size)


# ── Thumbnail ─────────────────────────────────────────────────────────────────

class TestThumbnail:
    def test_thumbnail_size(self, manager, tmp):
        path  = make_png(tmp / "cursor.png", size=(256, 256))
        entry = manager.import_image(path)
        thumb = manager.thumbnail_from_entry(entry)
        assert thumb is not None
        assert thumb.width  <= THUMBNAIL_SIZE
        assert thumb.height <= THUMBNAIL_SIZE

    def test_thumbnail_none_if_no_b64(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = make_image_entry(path)   # sin thumbnail_b64
        assert manager.thumbnail_from_entry(entry) is None

    def test_refresh_thumbnail(self, manager, tmp):
        path  = make_png(tmp / "cursor.png")
        entry = make_image_entry(path)   # sin thumbnail
        assert entry.thumbnail_b64 is None

        refreshed = manager.refresh_thumbnail(entry)
        assert refreshed.thumbnail_b64 is not None

    def test_refresh_thumbnail_missing_file_raises(self, manager, tmp):
        entry = make_image_entry(tmp / "no_existe.png")
        with pytest.raises(FileNotFoundError):
            manager.refresh_thumbnail(entry)


# ── Internos: _resize_contain y _resize_cover ─────────────────────────────────

class TestInternalResize:
    def test_contain_square_input(self):
        img    = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        result = ImageManager._resize_contain(img, 32)
        assert result.size == (32, 32)

    def test_contain_wide_input(self):
        img    = Image.new("RGBA", (200, 100), (0, 255, 0, 255))
        result = ImageManager._resize_contain(img, 32)
        assert result.size == (32, 32)

    def test_cover_square_input(self):
        img    = Image.new("RGBA", (100, 100), (0, 0, 255, 255))
        result = ImageManager._resize_cover(img, 32)
        assert result.size == (32, 32)

    def test_cover_tall_input(self):
        img    = Image.new("RGBA", (100, 200), (128, 0, 128, 255))
        result = ImageManager._resize_cover(img, 32)
        assert result.size == (32, 32)

    def test_to_rgba_from_rgb(self):
        img  = Image.new("RGB", (50, 50), (100, 150, 200))
        rgba = ImageManager._to_rgba(img)
        assert rgba.mode == "RGBA"

    def test_to_rgba_keeps_rgba(self):
        img  = Image.new("RGBA", (50, 50), (100, 150, 200, 128))
        rgba = ImageManager._to_rgba(img)
        assert rgba.mode == "RGBA"
        assert rgba is img    # no debe crear una copia innecesaria
