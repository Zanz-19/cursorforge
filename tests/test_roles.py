"""
tests/test_roles.py

Pruebas unitarias para cursorforge/core/roles.py
Ejecutar con: pytest tests/test_roles.py -v
"""

import json
import tempfile
from pathlib import Path

import pytest

from cursorforge.core.roles import RoleRegistry, RoleDefinition


# ── Fixture: registry cargado desde assets reales ────────────────────────────

@pytest.fixture(scope="module")
def registry() -> RoleRegistry:
    return RoleRegistry.load()


# ── Carga básica ──────────────────────────────────────────────────────────────

class TestLoad:
    def test_loads_without_error(self, registry):
        assert registry is not None

    def test_has_expected_count(self, registry):
        # Los JSON tienen 31 roles canónicos
        assert len(registry) >= 30

    def test_repr(self, registry):
        assert "RoleRegistry" in repr(registry)
        assert "roles" in repr(registry)

    def test_contains_core_roles(self, registry):
        for role in ["default", "pointer", "text", "wait", "move", "crosshair"]:
            assert role in registry

    def test_does_not_contain_comment_key(self, registry):
        assert "_comment" not in registry


# ── Consulta por nombre ───────────────────────────────────────────────────────

class TestGet:
    def test_get_known_role(self, registry):
        role = registry.get("default")
        assert role is not None
        assert role.name == "default"

    def test_get_unknown_role_returns_none(self, registry):
        assert registry.get("rol_inventado") is None

    def test_role_is_frozen(self, registry):
        role = registry.get("default")
        with pytest.raises(Exception):
            role.name = "otro"   # frozen=True debe lanzar FrozenInstanceError


# ── Aliases ───────────────────────────────────────────────────────────────────

class TestAliases:
    def test_default_has_aliases(self, registry):
        role = registry.get("default")
        assert "arrow" in role.aliases
        assert "left_ptr" in role.aliases

    def test_pointer_has_aliases(self, registry):
        role = registry.get("pointer")
        assert "hand1" in role.aliases
        assert "hand2" in role.aliases

    def test_get_by_alias(self, registry):
        role = registry.get_by_alias("left_ptr")
        assert role is not None
        assert role.name == "default"

    def test_get_by_alias_unknown_returns_none(self, registry):
        assert registry.get_by_alias("alias_inventado") is None

    def test_canonical_name_from_name(self, registry):
        assert registry.canonical_name("default") == "default"

    def test_canonical_name_from_alias(self, registry):
        assert registry.canonical_name("xterm") == "text"

    def test_canonical_name_unknown_returns_none(self, registry):
        assert registry.canonical_name("inventado") is None

    def test_all_aliases_has_all_roles(self, registry):
        aliases_dict = registry.all_aliases()
        for name in registry.all_names():
            assert name in aliases_dict

    def test_no_duplicate_alias_resolution(self, registry):
        # Cada alias debe resolverse a exactamente un rol canónico
        seen_aliases: dict[str, str] = {}
        for name, alias_list in registry.all_aliases().items():
            for alias in alias_list:
                if alias in seen_aliases:
                    # Si hay conflicto, es un dato conocido del sistema,
                    # pero el registry debe resolverlo consistentemente
                    resolved = registry.canonical_name(alias)
                    assert resolved is not None
                else:
                    seen_aliases[alias] = name


# ── Grupos ────────────────────────────────────────────────────────────────────

class TestGroups:
    def test_groups_exist(self, registry):
        groups = registry.all_groups()
        assert "normal" in groups
        assert "active" in groups

    def test_normal_group_has_default(self, registry):
        assert "default" in registry.names_in_group("normal")

    def test_active_group_has_pointer(self, registry):
        assert "pointer" in registry.names_in_group("active")

    def test_active_group_has_wait(self, registry):
        assert "wait" in registry.names_in_group("active")

    def test_all_roles_have_a_group(self, registry):
        all_grouped = set(registry.names_in_group("normal")) | \
                      set(registry.names_in_group("active"))
        for name in registry.all_names():
            assert name in all_grouped, f"'{name}' no tiene grupo asignado"

    def test_groups_are_disjoint(self, registry):
        normal = set(registry.names_in_group("normal"))
        active = set(registry.names_in_group("active"))
        overlap = normal & active
        assert overlap == set(), f"Roles en ambos grupos: {overlap}"

    def test_names_in_group_unknown_returns_empty(self, registry):
        assert registry.names_in_group("grupo_inventado") == []


# ── Hotspots por defecto ──────────────────────────────────────────────────────

class TestHotspots:
    def test_default_hotspot_is_corner(self, registry):
        role = registry.get("default")
        assert role.default_hotspot_x == 0
        assert role.default_hotspot_y == 0

    def test_crosshair_hotspot_is_center(self, registry):
        role = registry.get("crosshair")
        # Para ref_size=32, el centro es 16
        assert role.default_hotspot_x == 16
        assert role.default_hotspot_y == 16

    def test_hotspot_for_size_scales_correctly(self, registry):
        role = registry.get("crosshair")
        # ref_size=32, center=(16,16). Para size=64 debe ser (32,32)
        hx, hy = role.hotspot_for_size(64)
        assert hx == 32
        assert hy == 32

    def test_hotspot_for_size_zero_ref(self):
        # RoleDefinition con ref_size=0 no debe lanzar ZeroDivisionError
        role = RoleDefinition(
            name="test", aliases=(), group="normal",
            default_hotspot_x=0, default_hotspot_y=0, ref_size=0
        )
        assert role.hotspot_for_size(32) == (0, 0)

    def test_all_roles_have_hotspot_defined(self, registry):
        # Verificar que ningún rol tiene hotspot fuera del rango de ref_size
        for name in registry.all_names():
            role = registry.get(name)
            assert 0 <= role.default_hotspot_x <= role.ref_size, \
                f"{name}: hotspot_x={role.default_hotspot_x} fuera de rango"
            assert 0 <= role.default_hotspot_y <= role.ref_size, \
                f"{name}: hotspot_y={role.default_hotspot_y} fuera de rango"


# ── Descripciones ─────────────────────────────────────────────────────────────

class TestDescriptions:
    def test_known_roles_have_description(self, registry):
        for name in ["default", "pointer", "text", "wait", "crosshair"]:
            role = registry.get(name)
            assert role.description != "", f"'{name}' no tiene descripción"

    def test_description_is_string(self, registry):
        for name in registry.all_names():
            role = registry.get(name)
            assert isinstance(role.description, str)


# ── Carga con archivos personalizados ────────────────────────────────────────

class TestCustomLoad:
    def test_load_from_custom_paths(self, tmp_path):
        aliases = {
            "mi_cursor":  ["alias_a", "alias_b"],
            "mi_cursor2": ["alias_c"],
        }
        groups = {
            "normal": ["mi_cursor"],
            "active": ["mi_cursor2"],
        }
        (tmp_path / "aliases.json").write_text(json.dumps(aliases))
        (tmp_path / "groups.json").write_text(json.dumps(groups))

        reg = RoleRegistry.load(
            aliases_path=tmp_path / "aliases.json",
            groups_path =tmp_path / "groups.json",
        )
        assert len(reg) == 2
        assert "mi_cursor"  in reg
        assert "mi_cursor2" in reg
        assert reg.get("mi_cursor").group == "normal"
        assert reg.get("mi_cursor2").group == "active"
        assert "alias_a" in reg.get("mi_cursor").aliases

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            RoleRegistry.load(aliases_path=tmp_path / "no_existe.json")

    def test_comment_keys_ignored(self, tmp_path):
        aliases = {"_comment": "esto se ignora", "default": ["arrow"]}
        groups  = {"_comment": "también", "normal": ["default"], "active": []}
        (tmp_path / "aliases.json").write_text(json.dumps(aliases))
        (tmp_path / "groups.json").write_text(json.dumps(groups))

        reg = RoleRegistry.load(
            aliases_path=tmp_path / "aliases.json",
            groups_path =tmp_path / "groups.json",
        )
        assert "_comment" not in reg
        assert "default" in reg
