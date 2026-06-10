"""
tests/test_project.py

Pruebas unitarias para cursorforge/core/project.py
Ejecutar con: pytest tests/test_project.py -v
"""

import json
import tempfile
from pathlib import Path

import pytest

from cursorforge.core.project import (
    AnimationFrame,
    BasicMapping,
    CursorProject,
    ExportConfig,
    FORMAT_VERSION,
    Hotspot,
    ImageEntry,
    ProjectMeta,
    RoleConfig,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

SAMPLE_ROLES = ["default", "pointer", "text", "wait", "move"]
SAMPLE_ALIASES = {
    "default": ["arrow", "left_ptr"],
    "pointer": ["hand1", "hand2"],
    "text":    ["xterm"],
    "wait":    ["watch"],
    "move":    ["fleur"],
}


def make_image(image_id="img_0001", path="/tmp/cursor.png") -> ImageEntry:
    return ImageEntry(
        image_id=image_id,
        path=path,
        filename="cursor.png",
        width=128,
        height=128,
        has_alpha=True,
    )


def make_project() -> CursorProject:
    return CursorProject.new(
        name="TestTema",
        author="Jose",
        role_names=SAMPLE_ROLES,
        role_aliases=SAMPLE_ALIASES,
    )


# ── Hotspot ───────────────────────────────────────────────────────────────────

class TestHotspot:
    def test_defaults(self):
        h = Hotspot()
        assert h.x == 0 and h.y == 0

    def test_serialization(self):
        h = Hotspot(x=10, y=20)
        d = h.to_dict()
        h2 = Hotspot.from_dict(d)
        assert h2.x == 10 and h2.y == 20

    def test_scaled(self):
        h = Hotspot(x=64, y=64)        # centro de imagen 128×128
        scaled = h.scaled(128, 32)
        assert scaled.x == 16 and scaled.y == 16

    def test_scaled_zero_source(self):
        h = Hotspot(x=10, y=10)
        scaled = h.scaled(0, 32)       # no debe lanzar ZeroDivisionError
        assert scaled.x == 0 and scaled.y == 0


# ── RoleConfig ────────────────────────────────────────────────────────────────

class TestRoleConfig:
    def test_defaults(self):
        r = RoleConfig()
        assert r.image_id is None
        assert not r.is_assigned
        assert not r.is_animated

    def test_assigned(self):
        r = RoleConfig(image_id="img_001")
        assert r.is_assigned

    def test_animated(self):
        frames = [AnimationFrame("img_001", 100), AnimationFrame("img_002", 100)]
        r = RoleConfig(frames=frames)
        assert r.is_animated
        assert r.is_assigned

    def test_serialization_roundtrip(self):
        r = RoleConfig(
            image_id="img_001",
            hotspot=Hotspot(5, 10),
            override=True,
            aliases=["arrow", "left_ptr"],
        )
        r2 = RoleConfig.from_dict(r.to_dict())
        assert r2.image_id  == "img_001"
        assert r2.hotspot.x == 5
        assert r2.hotspot.y == 10
        assert r2.override  is True
        assert r2.aliases   == ["arrow", "left_ptr"]

    def test_animated_serialization(self):
        frames = [AnimationFrame("img_001", 80)]
        r  = RoleConfig(frames=frames)
        r2 = RoleConfig.from_dict(r.to_dict())
        assert r2.is_animated
        assert r2.frames[0].image_id == "img_001"
        assert r2.frames[0].delay_ms == 80


# ── ImageEntry ────────────────────────────────────────────────────────────────

class TestImageEntry:
    def test_serialization_roundtrip(self):
        img  = make_image()
        img2 = ImageEntry.from_dict(img.to_dict())
        assert img2.image_id  == img.image_id
        assert img2.path      == img.path
        assert img2.has_alpha is True

    def test_exists_false_for_fake_path(self):
        img = make_image(path="/ruta/que/no/existe.png")
        assert not img.exists


# ── CursorProject: creación ───────────────────────────────────────────────────

class TestCursorProjectNew:
    def test_new_has_all_roles(self):
        p = make_project()
        for role in SAMPLE_ROLES:
            assert role in p.roles

    def test_aliases_populated(self):
        p = make_project()
        assert "arrow" in p.roles["default"].aliases
        assert "hand1" in p.roles["pointer"].aliases

    def test_all_roles_unassigned(self):
        p = make_project()
        assert set(p.unassigned_roles) == set(SAMPLE_ROLES)
        assert p.assigned_roles == []

    def test_repr(self):
        p = make_project()
        assert "TestTema" in repr(p)


# ── CursorProject: gestión de imágenes ───────────────────────────────────────

class TestImageManagement:
    def test_add_image(self):
        p   = make_project()
        img = make_image()
        p.add_image(img)
        assert img.image_id in p.images

    def test_remove_image_desasigns_roles(self):
        p   = make_project()
        img = make_image()
        p.add_image(img)
        # Asignar manualmente
        p.roles["default"].image_id = img.image_id
        p.remove_image(img.image_id)
        assert img.image_id not in p.images
        assert p.roles["default"].image_id is None

    def test_remove_image_clears_basic_mapping(self):
        p   = make_project()
        img = make_image()
        p.add_image(img)
        p.basic_mapping.normal_image_id = img.image_id
        p.remove_image(img.image_id)
        assert p.basic_mapping.normal_image_id is None

    def test_missing_images_empty_when_all_ok(self):
        p   = make_project()
        # path existe porque usamos /tmp que siempre existe
        img = make_image(path="/tmp")
        p.add_image(img)
        assert p.missing_images == []

    def test_missing_images_detects_broken_path(self):
        p   = make_project()
        img = make_image(path="/ruta/falsa/cursor.png")
        p.add_image(img)
        assert img.image_id in p.missing_images


# ── CursorProject: gestión de roles ──────────────────────────────────────────

class TestRoleManagement:
    def test_assign_role(self):
        p   = make_project()
        img = make_image()
        p.add_image(img)
        p.assign_role("default", img.image_id, Hotspot(0, 0))
        assert p.roles["default"].image_id == img.image_id
        assert p.roles["default"].override is True
        assert "default" in p.assigned_roles

    def test_assign_unknown_role_raises(self):
        p = make_project()
        with pytest.raises(KeyError):
            p.assign_role("rol_inventado", "img_001")

    def test_set_hotspot(self):
        p = make_project()
        p.set_hotspot("pointer", 12, 4)
        assert p.roles["pointer"].hotspot.x == 12
        assert p.roles["pointer"].hotspot.y == 4

    def test_set_hotspot_unknown_role_raises(self):
        p = make_project()
        with pytest.raises(KeyError):
            p.set_hotspot("rol_inventado", 0, 0)

    def test_apply_basic_mapping_respects_override(self):
        p   = make_project()
        img_a = make_image("img_a")
        img_b = make_image("img_b")
        img_c = make_image("img_c")
        p.add_image(img_a)
        p.add_image(img_b)
        p.add_image(img_c)

        # Override manual en 'default'
        p.assign_role("default", img_c.image_id)

        p.apply_basic_mapping(
            normal_image_id = img_a.image_id,
            active_image_id = img_b.image_id,
            normal_roles    = ["default", "text", "move"],
            active_roles    = ["pointer", "wait"],
        )
        # 'default' tiene override → no se sobreescribe
        assert p.roles["default"].image_id == img_c.image_id
        # 'text' no tiene override → sí se sobreescribe
        assert p.roles["text"].image_id == img_a.image_id
        assert p.roles["pointer"].image_id == img_b.image_id

    def test_clear_overrides(self):
        p   = make_project()
        img = make_image()
        p.add_image(img)
        p.assign_role("default", img.image_id)
        assert p.roles["default"].override is True
        p.clear_overrides()
        assert p.roles["default"].override is False


# ── CursorProject: guardado y carga ──────────────────────────────────────────

class TestSaveLoad:
    def test_save_creates_file(self):
        p = make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "mi_tema.cursorproject"
            saved = p.save(fpath)
            assert saved.exists()
            assert saved.suffix == ".cursorproject"

    def test_save_adds_extension_if_missing(self):
        p = make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "mi_tema"   # sin extensión
            saved = p.save(fpath)
            assert saved.suffix == ".cursorproject"

    def test_save_without_path_raises(self):
        p = make_project()
        with pytest.raises(ValueError):
            p.save()

    def test_roundtrip(self):
        p   = make_project()
        img = make_image()
        p.add_image(img)
        p.assign_role("default", img.image_id, Hotspot(3, 7))
        p.mode = "advanced"

        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "test.cursorproject"
            p.save(fpath)

            p2 = CursorProject.load(fpath)

        assert p2.meta.name             == "TestTema"
        assert p2.mode                  == "advanced"
        assert img.image_id in p2.images
        assert p2.roles["default"].image_id      == img.image_id
        assert p2.roles["default"].hotspot.x     == 3
        assert p2.roles["default"].hotspot.y     == 7
        assert p2.roles["default"].override is True
        assert p2.roles["default"].aliases        == ["arrow", "left_ptr"]

    def test_load_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            CursorProject.load("/ruta/que/no/existe.cursorproject")

    def test_load_wrong_version_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "bad.cursorproject"
            with open(fpath, "w") as f:
                json.dump({"version": "9.9"}, f)
            with pytest.raises(ValueError, match="no compatible"):
                CursorProject.load(fpath)

    def test_saved_json_is_readable(self):
        """El archivo guardado debe ser JSON válido y legible."""
        p = make_project()
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "test.cursorproject"
            p.save(fpath)
            with open(fpath, "r") as f:
                data = json.load(f)
        assert data["version"] == FORMAT_VERSION
        assert "meta"   in data
        assert "roles"  in data
        assert "images" in data

    def test_is_saved_flag(self):
        p = make_project()
        assert not p.is_saved
        with tempfile.TemporaryDirectory() as tmpdir:
            p.save(Path(tmpdir) / "t.cursorproject")
        assert p.is_saved

    def test_generate_image_id_unique(self):
        # Con hex de 4 chars (65 536 combinaciones) y 20 generaciones,
        # la probabilidad de colisión es < 0.3%. Verificamos formato y
        # que en un lote pequeño no haya duplicados.
        ids = [CursorProject.generate_image_id() for _ in range(20)]
        assert all(i.startswith("img_") for i in ids)
        assert all(len(i) == 8 for i in ids)   # "img_" + 4 hex
        assert len(set(ids)) == len(ids)        # sin duplicados en lote pequeño
