"""
cursorforge/core/roles.py

Carga, consulta y valida los roles de cursor del sistema.

Este módulo es el puente entre los archivos JSON de assets y el
resto de la aplicación. Centraliza todo lo que se necesita saber
sobre los roles: cuáles existen, sus alias, su grupo en modo básico,
y sus hotspots por defecto recomendados.

No importa nada de GTK ni de UI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Ruta base de assets relativa a este archivo
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_ALIASES_FILE = _ASSETS_DIR / "roles_aliases.json"
_GROUPS_FILE  = _ASSETS_DIR / "default_groups.json"


# ─────────────────────────────────────────────────────────────────────────────
# Hotspots por defecto recomendados para cada rol
# Expresados como porcentaje (0.0–1.0) del tamaño de la imagen,
# para que sean independientes de la resolución.
# ─────────────────────────────────────────────────────────────────────────────

# (x_pct, y_pct) → 0.0 = borde izquierdo/superior, 1.0 = borde derecho/inferior
_DEFAULT_HOTSPOT_PCT: dict[str, tuple[float, float]] = {
    # Puntero: punta superior izquierda
    "default":       (0.0,  0.0),
    "context-menu":  (0.0,  0.0),
    "help":          (0.0,  0.0),
    # Mano: punta del dedo índice (~12% desde izq, ~8% desde arriba)
    "pointer":       (0.12, 0.08),
    "grab":          (0.12, 0.08),
    "grabbing":      (0.12, 0.08),
    "copy":          (0.12, 0.08),
    "alias":         (0.12, 0.08),
    "no-drop":       (0.12, 0.08),
    # Texto: centro horizontal, mitad superior
    "text":          (0.5,  0.5),
    "vertical-text": (0.5,  0.5),
    # Espera / progreso: centro
    "wait":          (0.5,  0.5),
    "progress":      (0.5,  0.5),
    # Cruceta y celda: centro exacto
    "crosshair":     (0.5,  0.5),
    "cell":          (0.5,  0.5),
    # Mover: centro
    "move":          (0.5,  0.5),
    "all-scroll":    (0.5,  0.5),
    # No permitido: centro
    "not-allowed":   (0.5,  0.5),
    # Zoom: centro
    "zoom-in":       (0.5,  0.5),
    "zoom-out":      (0.5,  0.5),
    # Redimensionar horizontal: centro izquierdo
    "col-resize":    (0.5,  0.5),
    "ew-resize":     (0.5,  0.5),
    "e-resize":      (1.0,  0.5),
    "w-resize":      (0.0,  0.5),
    # Redimensionar vertical: centro superior
    "row-resize":    (0.5,  0.5),
    "ns-resize":     (0.5,  0.5),
    "n-resize":      (0.5,  0.0),
    "s-resize":      (0.5,  1.0),
    # Redimensionar diagonal
    "ne-resize":     (1.0,  0.0),
    "nw-resize":     (0.0,  0.0),
    "se-resize":     (1.0,  1.0),
    "sw-resize":     (0.0,  1.0),
}


# ─────────────────────────────────────────────────────────────────────────────
# Dataclass: RoleDefinition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoleDefinition:
    """
    Descripción estática de un rol de cursor del sistema.
    Es inmutable (frozen=True): los datos de definición no cambian
    durante la ejecución; lo que cambia es la configuración del usuario
    en RoleConfig (project.py).

    name              → nombre canónico X11 (ej: "default", "pointer")
    aliases           → nombres alternativos usados por apps/toolkits
    group             → "normal" | "active" (para modo básico)
    default_hotspot_x → hotspot X recomendado en píxeles (para imagen de ref_size)
    default_hotspot_y → hotspot Y recomendado en píxeles
    ref_size          → tamaño de referencia para los hotspots (px)
    description       → texto corto para mostrar en la UI
    """
    name:              str
    aliases:           tuple[str, ...]
    group:             str               # "normal" | "active"
    default_hotspot_x: int
    default_hotspot_y: int
    ref_size:          int               # tamaño base de referencia (px)
    description:       str = ""

    def hotspot_for_size(self, size: int) -> tuple[int, int]:
        """
        Devuelve el hotspot escalado para un tamaño de exportación dado.
        Útil cuando el usuario no ha ajustado el hotspot manualmente.
        """
        if self.ref_size == 0:
            return (0, 0)
        factor = size / self.ref_size
        return (round(self.default_hotspot_x * factor),
                round(self.default_hotspot_y * factor))


# ─────────────────────────────────────────────────────────────────────────────
# Clase principal: RoleRegistry
# ─────────────────────────────────────────────────────────────────────────────

class RoleRegistry:
    """
    Registro completo de los roles de cursor del sistema.

    Carga los datos desde los JSON de assets y provee métodos de
    consulta que usan el resto de módulos del core y la UI.

    Uso:
        registry = RoleRegistry.load()
        role = registry.get("default")
        normal_roles = registry.names_in_group("normal")
    """

    def __init__(self, roles: dict[str, RoleDefinition]):
        self._roles = roles                        # { name: RoleDefinition }
        self._alias_map = self._build_alias_map()  # { alias: canonical_name }

    # ── Carga desde archivos JSON ──────────────────────────────────────────

    @classmethod
    def load(
        cls,
        aliases_path: Optional[Path] = None,
        groups_path:  Optional[Path] = None,
        ref_size:     int = 32,
    ) -> "RoleRegistry":
        """
        Construye el registro cargando los JSON de assets.

        aliases_path → ruta a roles_aliases.json (usa default si None)
        groups_path  → ruta a default_groups.json (usa default si None)
        ref_size     → tamaño de referencia para calcular hotspots por defecto
        """
        aliases_path = aliases_path or _ALIASES_FILE
        groups_path  = groups_path  or _GROUPS_FILE

        aliases_data = cls._load_json(aliases_path)
        groups_data  = cls._load_json(groups_path)

        # Construir lookup de grupo por nombre de rol
        group_map: dict[str, str] = {}
        for group_name, role_list in groups_data.items():
            if group_name.startswith("_"):
                continue
            for role_name in role_list:
                group_map[role_name] = group_name

        roles: dict[str, RoleDefinition] = {}

        for role_name, alias_list in aliases_data.items():
            if role_name.startswith("_"):
                continue

            group = group_map.get(role_name, "normal")

            # Hotspot por defecto en píxeles para ref_size
            hx_pct, hy_pct = _DEFAULT_HOTSPOT_PCT.get(role_name, (0.0, 0.0))
            hx = round(hx_pct * ref_size)
            hy = round(hy_pct * ref_size)

            roles[role_name] = RoleDefinition(
                name              = role_name,
                aliases           = tuple(alias_list),
                group             = group,
                default_hotspot_x = hx,
                default_hotspot_y = hy,
                ref_size          = ref_size,
                description       = cls._describe(role_name),
            )

        return cls(roles)

    # ── Consultas ──────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[RoleDefinition]:
        """Devuelve la definición de un rol por nombre canónico."""
        return self._roles.get(name)

    def get_by_alias(self, alias: str) -> Optional[RoleDefinition]:
        """Devuelve la definición de un rol buscando por cualquier alias."""
        canonical = self._alias_map.get(alias)
        if canonical:
            return self._roles.get(canonical)
        return None

    def all_names(self) -> list[str]:
        """Lista de todos los nombres canónicos en orden de definición."""
        return list(self._roles.keys())

    def names_in_group(self, group: str) -> list[str]:
        """Lista de nombres canónicos que pertenecen a un grupo dado."""
        return [
            name for name, role in self._roles.items()
            if role.group == group
        ]

    def all_groups(self) -> list[str]:
        """Lista de grupos disponibles (sin duplicados, en orden)."""
        seen: list[str] = []
        for role in self._roles.values():
            if role.group not in seen:
                seen.append(role.group)
        return seen

    def all_aliases(self) -> dict[str, list[str]]:
        """
        Devuelve un dict { nombre_canónico: [alias, ...] }
        con todos los roles y sus alias.
        """
        return {
            name: list(role.aliases)
            for name, role in self._roles.items()
        }

    def canonical_name(self, name_or_alias: str) -> Optional[str]:
        """
        Dado un nombre o alias, devuelve el nombre canónico.
        Devuelve None si no se reconoce.
        """
        if name_or_alias in self._roles:
            return name_or_alias
        return self._alias_map.get(name_or_alias)

    def __len__(self) -> int:
        return len(self._roles)

    def __contains__(self, name: str) -> bool:
        return name in self._roles

    def __repr__(self) -> str:
        return f"RoleRegistry({len(self._roles)} roles)"

    # ── Internos ───────────────────────────────────────────────────────────

    def _build_alias_map(self) -> dict[str, str]:
        """
        Construye un dict inverso { alias → nombre_canónico }
        para búsquedas rápidas por alias.
        """
        alias_map: dict[str, str] = {}
        for name, role in self._roles.items():
            for alias in role.aliases:
                # Si hay conflicto, el primero en aparecer gana
                if alias not in alias_map:
                    alias_map[alias] = name
        return alias_map

    @staticmethod
    def _load_json(path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(
                f"Archivo de assets no encontrado: {path}\n"
                f"Asegúrate de que el repositorio está completo."
            )
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _describe(role_name: str) -> str:
        """Descripción corta legible para mostrar en la UI."""
        descriptions = {
            "default":       "Cursor estándar (flecha)",
            "pointer":       "Enlace o elemento clickeable (mano)",
            "text":          "Selección de texto (barra I)",
            "vertical-text": "Selección de texto vertical",
            "wait":          "Espera del sistema (reloj)",
            "progress":      "Cargando en segundo plano",
            "crosshair":     "Selección precisa (cruceta)",
            "move":          "Mover elemento",
            "grab":          "Agarrar elemento",
            "grabbing":      "Arrastrando elemento",
            "not-allowed":   "Acción no permitida",
            "no-drop":       "No se puede soltar aquí",
            "help":          "Ayuda contextual",
            "context-menu":  "Menú contextual disponible",
            "copy":          "Copiar al soltar",
            "alias":         "Crear acceso directo al soltar",
            "cell":          "Selección de celda",
            "zoom-in":       "Acercar zoom",
            "zoom-out":      "Alejar zoom",
            "all-scroll":    "Desplazamiento en todas direcciones",
            "col-resize":    "Redimensionar columna",
            "row-resize":    "Redimensionar fila",
            "n-resize":      "Redimensionar hacia arriba",
            "s-resize":      "Redimensionar hacia abajo",
            "e-resize":      "Redimensionar hacia la derecha",
            "w-resize":      "Redimensionar hacia la izquierda",
            "ne-resize":     "Redimensionar diagonal (↗)",
            "nw-resize":     "Redimensionar diagonal (↖)",
            "se-resize":     "Redimensionar diagonal (↘)",
            "sw-resize":     "Redimensionar diagonal (↙)",
            "ew-resize":     "Redimensionar horizontal (↔)",
            "ns-resize":     "Redimensionar vertical (↕)",
        }
        return descriptions.get(role_name, role_name)
