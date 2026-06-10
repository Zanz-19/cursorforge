"""
tests/test_converter.py

Pruebas unitarias para cursorforge/core/converter.py

Como xcursorgen no está disponible en todos los entornos de CI/test,
las pruebas que lo necesitan usan mocks. El resto verifica la lógica
interna (generación de conf, escalado de hotspot, symlinks, etc.)
sin depender de binarios del sistema.

Ejecutar con: pytest tests/test_converter.py -v
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from cursorforge.core.converter import (
    BuildResult,
    ConversionResult,
    Converter,
)
from cursorforge.core.image_manager import ImageManager
from cursorforge.core.project import (
    CursorProject,
    Hotspot,
    ImageEntry,
    RoleConfig,
)
from cursorforge.core.roles import RoleRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_png(path: Path, size: tuple = (128, 128)) -> Path:
    img = Image.new("RGBA", size, (255, 0, 0, 255))
    img.save(path, format="PNG")
    return path


def make_project_with_image(tmp: Path) -> tuple[CursorProject, str]:
    """Crea un proyecto mínimo con una imagen asignada a 'default'."""
    registry = RoleRegistry.load()
    project  = CursorProject.new(
        name         = "TestTema",
        role_names   = registry.all_names(),
        role_aliases = registry.all_aliases(),
    )

    png_path = make_png(tmp / "cursor.png")
    manager  = ImageManager()
    entry    = manager.import_image(png_path, image_id="img_001")
    project.add_image(entry)

    # Asignar solo 'default' y 'pointer' para los tests
    project.assign_role("default", "img_001", Hotspot(0, 0))
    project.assign_role("pointer", "img_001", Hotspot(12, 4))

    return project, "img_001"


@pytest.fixture
def converter() -> Converter:
    return Converter()


@pytest.fixture
def tmp(tmp_path) -> Path:
    return tmp_path


# ── ConversionResult ──────────────────────────────────────────────────────────

class TestConversionResult:
    def test_ok_by_default(self):
        r = ConversionResult(role_name="default")
        assert r.ok is True
        assert bool(r) is True

    def test_add_error_sets_ok_false(self):
        r = ConversionResult(role_name="default")
        r.add_error("algo falló")
        assert r.ok is False
        assert "algo falló" in r.errors

    def test_add_warning_keeps_ok(self):
        r = ConversionResult(role_name="default")
        r.add_warning("aviso")
        assert r.ok is True
        assert "aviso" in r.warnings


# ── BuildResult ───────────────────────────────────────────────────────────────

class TestBuildResult:
    def test_ok_by_default(self):
        b = BuildResult()
        assert b.ok is True

    def test_add_failed_conversion_sets_ok_false(self):
        b = BuildResult()
        r = ConversionResult(role_name="default", ok=False)
        r.add_error("error")
        b.add_conversion(r)
        assert b.ok is False

    def test_failed_and_succeeded_lists(self):
        b = BuildResult()
        good = ConversionResult(role_name="default", ok=True)
        bad  = ConversionResult(role_name="pointer", ok=False)
        bad.add_error("x")
        b.add_conversion(good)
        b.add_conversion(bad)
        assert len(b.succeeded) == 1
        assert len(b.failed)    == 1
        assert b.failed[0].role_name == "pointer"


# ── Converter.xcursorgen_available ────────────────────────────────────────────

class TestXcursorgenAvailable:
    def test_returns_bool(self, converter):
        result = converter.xcursorgen_available()
        assert isinstance(result, bool)

    def test_false_when_not_in_path(self, converter):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert converter.xcursorgen_available() is False

    def test_true_when_available(self, converter):
        mock_result = MagicMock()
        mock_result.returncode = 1   # xcursorgen --help devuelve 1
        with patch("subprocess.run", return_value=mock_result):
            assert converter.xcursorgen_available() is True

    def test_false_on_timeout(self, converter):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("x", 5)):
            assert converter.xcursorgen_available() is False


# ── Converter._write_index_theme ─────────────────────────────────────────────

class TestWriteIndexTheme:
    def test_creates_index_theme(self, tmp):
        Converter._write_index_theme(tmp, name="MiTema", inherit="Adwaita")
        index = tmp / "index.theme"
        assert index.exists()

    def test_content_has_name(self, tmp):
        Converter._write_index_theme(tmp, name="MiTema", inherit="Adwaita")
        content = (tmp / "index.theme").read_text()
        assert "MiTema" in content

    def test_content_has_inherit(self, tmp):
        Converter._write_index_theme(tmp, name="X", inherit="Yaru")
        content = (tmp / "index.theme").read_text()
        assert "Yaru" in content

    def test_content_has_icon_theme_section(self, tmp):
        Converter._write_index_theme(tmp, name="X", inherit="A")
        content = (tmp / "index.theme").read_text()
        assert "[Icon Theme]" in content


# ── Converter._write_cursor_conf ─────────────────────────────────────────────

class TestWriteCursorConf:
    def test_creates_conf_file(self, tmp):
        converter = Converter()
        png_paths = {
            32: tmp / "default_32.png",
            48: tmp / "default_48.png",
        }
        # Crear los PNGs de prueba
        for p in png_paths.values():
            make_png(p, (32, 32))

        entry = ImageEntry(
            image_id="img_001", path=str(tmp / "cursor.png"),
            filename="cursor.png", width=128, height=128, has_alpha=True,
        )
        conf = converter._write_cursor_conf(
            role_name   = "default",
            hotspot     = Hotspot(0, 0),
            png_paths   = png_paths,
            resolutions = [32, 48],
            entry       = entry,
            tmp         = tmp,
        )
        assert conf.exists()
        assert conf.suffix == ".cursor-conf" or conf.name.endswith("cursor-conf")

    def test_conf_content_has_correct_sizes(self, tmp):
        converter = Converter()
        png_paths = {32: tmp / "default_32.png", 48: tmp / "default_48.png"}
        for p in png_paths.values():
            make_png(p)

        entry = ImageEntry(
            image_id="img_001", path=str(tmp / "src.png"),
            filename="src.png", width=128, height=128, has_alpha=True,
        )
        conf = converter._write_cursor_conf(
            role_name   = "default",
            hotspot     = Hotspot(64, 64),
            png_paths   = png_paths,
            resolutions = [32, 48],
            entry       = entry,
            tmp         = tmp,
        )
        content = conf.read_text()
        assert "32 " in content
        assert "48 " in content

    def test_hotspot_scales_proportionally(self, tmp):
        """Hotspot en centro de 128px debe escalar a centro de 32px (16,16)."""
        converter = Converter()
        png_paths = {32: tmp / "default_32.png"}
        make_png(png_paths[32])

        entry = ImageEntry(
            image_id="img_001", path=str(tmp / "src.png"),
            filename="src.png", width=128, height=128, has_alpha=True,
        )
        conf = converter._write_cursor_conf(
            role_name   = "default",
            hotspot     = Hotspot(64, 64),   # centro de 128px
            png_paths   = png_paths,
            resolutions = [32],
            entry       = entry,
            tmp         = tmp,
        )
        content = conf.read_text().strip()
        # Línea esperada: "32 16 16 /ruta/default_32.png"
        parts = content.split()
        assert parts[0] == "32"
        assert parts[1] == "16"   # 64 * 32/128 = 16
        assert parts[2] == "16"


# ── Converter._create_symlink ─────────────────────────────────────────────────

class TestCreateSymlink:
    def test_creates_symlink(self, tmp):
        target_name = "default"
        alias_path  = tmp / "arrow"
        result      = ConversionResult(role_name="default")

        Converter._create_symlink(alias_path, target_name, result)

        assert alias_path.is_symlink()
        assert os.readlink(alias_path) == target_name

    def test_replaces_existing_symlink(self, tmp):
        alias_path = tmp / "arrow"
        alias_path.symlink_to("old_target")

        result = ConversionResult(role_name="default")
        Converter._create_symlink(alias_path, "default", result)

        assert os.readlink(alias_path) == "default"

    def test_warns_on_permission_error(self, tmp):
        alias_path = tmp / "arrow"
        result     = ConversionResult(role_name="default")

        with patch("pathlib.Path.symlink_to", side_effect=OSError("permiso")):
            Converter._create_symlink(alias_path, "default", result)

        assert result.ok is True            # warning, no error
        assert result.warnings             # hay al menos un warning


# ── Converter._export_pngs ────────────────────────────────────────────────────

class TestExportPngs:
    def test_generates_pngs_for_each_resolution(self, tmp):
        converter = Converter()
        png_src   = make_png(tmp / "src.png", (128, 128))
        entry = ImageEntry(
            image_id="img_001", path=str(png_src),
            filename="src.png", width=128, height=128, has_alpha=True,
        )
        resolutions = [24, 32, 48]
        png_paths = converter._export_pngs(
            entry=entry, hotspot=Hotspot(0, 0),
            resolutions=resolutions, tmp=tmp, role_name="default",
        )
        assert set(png_paths.keys()) == {24, 32, 48}
        for size, path in png_paths.items():
            assert path.exists()
            img = Image.open(path)
            assert img.size == (size, size)

    def test_output_pngs_are_rgba(self, tmp):
        converter = Converter()
        png_src   = make_png(tmp / "src.png")
        entry = ImageEntry(
            image_id="img_001", path=str(png_src),
            filename="src.png", width=128, height=128, has_alpha=True,
        )
        png_paths = converter._export_pngs(
            entry=entry, hotspot=Hotspot(0, 0),
            resolutions=[32], tmp=tmp, role_name="default",
        )
        img = Image.open(png_paths[32])
        assert img.mode == "RGBA"


# ── Converter.preview_cursor_conf ────────────────────────────────────────────

class TestPreviewCursorConf:
    def test_returns_string_for_assigned_role(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        conf = converter.preview_cursor_conf(project, "default", [32, 48])
        assert conf is not None
        assert "32" in conf
        assert "48" in conf

    def test_returns_none_for_unknown_role(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        assert converter.preview_cursor_conf(project, "rol_inventado") is None

    def test_returns_none_for_unassigned_role(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        # 'text' no fue asignado en el fixture
        assert converter.preview_cursor_conf(project, "text") is None

    def test_hotspot_in_conf(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        # pointer tiene hotspot (12, 4) en imagen de 128px
        # Para size=128: scaled = (12, 4)
        conf = converter.preview_cursor_conf(project, "pointer", [128])
        assert conf is not None
        parts = conf.split()
        assert parts[0] == "128"
        assert parts[1] == "12"
        assert parts[2] == "4"


# ── Converter.build (con mock de xcursorgen) ──────────────────────────────────

class TestBuild:
    def _mock_xcursorgen(self, *args, **kwargs):
        """Mock de subprocess.run que simula xcursorgen exitoso."""
        cmd = args[0] if args else kwargs.get("args", [])
        if "xcursorgen" in str(cmd):
            # Crear el archivo de salida vacío para simular éxito
            output_path = Path(cmd[-1])
            output_path.touch()
            mock = MagicMock()
            mock.returncode = 0
            mock.stderr = ""
            return mock
        return MagicMock(returncode=0, stderr="")

    def test_skips_unassigned_roles(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        output_dir = tmp / "tema"

        with patch("subprocess.run", side_effect=self._mock_xcursorgen):
            result = converter.build(project, output_dir, resolutions=[32])

        # Solo 'default' y 'pointer' fueron asignados
        assert "text" in result.skipped
        assert "wait" in result.skipped

    def test_creates_cursors_dir(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        output_dir = tmp / "MiTema"

        with patch("subprocess.run", side_effect=self._mock_xcursorgen):
            converter.build(project, output_dir, resolutions=[32])

        assert (output_dir / "cursors").is_dir()

    def test_creates_index_theme(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        output_dir = tmp / "MiTema"

        with patch("subprocess.run", side_effect=self._mock_xcursorgen):
            converter.build(project, output_dir, resolutions=[32])

        assert (output_dir / "index.theme").exists()

    def test_build_fails_without_xcursorgen(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        output_dir = tmp / "MiTema"

        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = converter.build(project, output_dir, resolutions=[32])

        assert result.ok is False

    def test_on_progress_callback(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        output_dir = tmp / "MiTema"
        calls: list[tuple] = []

        def on_progress(role, current, total):
            calls.append((role, current, total))

        with patch("subprocess.run", side_effect=self._mock_xcursorgen):
            converter.build(project, output_dir, resolutions=[32],
                            on_progress=on_progress)

        assert len(calls) > 0
        # Verificar que current y total tienen sentido
        for _, current, total in calls:
            assert 1 <= current <= total

    def test_conversion_result_has_role_name(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        output_dir = tmp / "MiTema"

        with patch("subprocess.run", side_effect=self._mock_xcursorgen):
            result = converter.build(project, output_dir, resolutions=[32])

        role_names = [c.role_name for c in result.conversions]
        assert "default" in role_names
        assert "pointer" in role_names

    def test_missing_image_produces_error(self, tmp):
        project, _ = make_project_with_image(tmp)
        converter  = Converter()
        output_dir = tmp / "MiTema"

        # Apuntar 'default' a un image_id que no existe en el proyecto
        project.roles["default"].image_id = "img_fantasma"

        with patch("subprocess.run", side_effect=self._mock_xcursorgen):
            result = converter.build(project, output_dir, resolutions=[32])

        failed = [c for c in result.conversions if c.role_name == "default"]
        assert failed and not failed[0].ok
