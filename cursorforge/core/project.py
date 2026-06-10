"""
cursorforge/core/project.py

Modelo de datos central del proyecto CursorForge.
Define las clases que representan un archivo .cursorproject y
provee métodos para crearlo, cargarlo, modificarlo y guardarlo.

No importa nada de GTK ni de UI — solo stdlib y tipos de datos.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Versión del formato de archivo ────────────────────────────────────────────
FORMAT_VERSION = "1.0"

# ── Resoluciones estándar disponibles ─────────────────────────────────────────
SUPPORTED_RESOLUTIONS = [24, 32, 48, 64]
DEFAULT_RESOLUTIONS   = [24, 32, 48]


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses del modelo
# Cada clase mapea directamente a un bloque del JSON del proyecto.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Hotspot:
    """
    Coordenadas del punto de clic dentro de la imagen fuente original.
    Se escalan proporcionalmente al exportar en cada resolución.
    """
    x: int = 0
    y: int = 0

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: dict) -> "Hotspot":
        return cls(x=int(data.get("x", 0)), y=int(data.get("y", 0)))

    def scaled(self, source_size: int, target_size: int) -> "Hotspot":
        """Devuelve un Hotspot escalado proporcionalmente al tamaño destino."""
        if source_size == 0:
            return Hotspot(0, 0)
        factor = target_size / source_size
        return Hotspot(
            x=round(self.x * factor),
            y=round(self.y * factor),
        )


@dataclass
class AnimationFrame:
    """Un frame de un cursor animado: referencia a imagen + duración."""
    image_id: str
    delay_ms: int = 50          # duración del frame en milisegundos

    def to_dict(self) -> dict:
        return {"image_id": self.image_id, "delay_ms": self.delay_ms}

    @classmethod
    def from_dict(cls, data: dict) -> "AnimationFrame":
        return cls(
            image_id=str(data["image_id"]),
            delay_ms=int(data.get("delay_ms", 50)),
        )


@dataclass
class RoleConfig:
    """
    Configuración de un rol de cursor (ej: 'default', 'pointer', 'wait').

    image_id   → ID de la imagen asignada (None = usar fallback del sistema)
    hotspot    → punto de clic dentro de la imagen original
    override   → True si fue asignado manualmente; en modo básico la app
                 no lo sobreescribirá al cambiar la imagen global
    frames     → lista de frames si es animado; None si es estático
    aliases    → nombres alternativos del sistema (se poblán desde roles_aliases.json)
    """
    image_id:  Optional[str]              = None
    hotspot:   Hotspot                    = field(default_factory=Hotspot)
    override:  bool                       = False
    frames:    Optional[list[AnimationFrame]] = None
    aliases:   list[str]                  = field(default_factory=list)

    @property
    def is_animated(self) -> bool:
        return self.frames is not None and len(self.frames) > 0

    @property
    def is_assigned(self) -> bool:
        """True si tiene imagen o frames asignados."""
        return self.image_id is not None or self.is_animated

    def to_dict(self) -> dict:
        return {
            "image_id": self.image_id,
            "hotspot":  self.hotspot.to_dict(),
            "override": self.override,
            "frames":   [f.to_dict() for f in self.frames] if self.frames else None,
            "aliases":  self.aliases,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoleConfig":
        frames_data = data.get("frames")
        frames = (
            [AnimationFrame.from_dict(f) for f in frames_data]
            if frames_data else None
        )
        return cls(
            image_id = data.get("image_id"),
            hotspot  = Hotspot.from_dict(data.get("hotspot", {})),
            override = bool(data.get("override", False)),
            frames   = frames,
            aliases  = list(data.get("aliases", [])),
        )


@dataclass
class ImageEntry:
    """
    Registro de una imagen fuente importada por el usuario.
    La ruta se guarda absoluta; thumbnail_b64 es un PNG 64×64 en base64
    generado al importar para mostrar previews rápidos sin releer disco.
    """
    image_id:     str
    path:         str               # ruta absoluta al archivo original
    filename:     str               # solo el nombre, para mostrar en UI
    width:        int
    height:       int
    has_alpha:    bool
    thumbnail_b64: Optional[str]    = None   # PNG 64×64 en base64

    @property
    def path_obj(self) -> Path:
        return Path(self.path)

    @property
    def exists(self) -> bool:
        return self.path_obj.exists()

    def to_dict(self) -> dict:
        return {
            "image_id":      self.image_id,
            "path":          self.path,
            "filename":      self.filename,
            "width":         self.width,
            "height":        self.height,
            "has_alpha":     self.has_alpha,
            "thumbnail_b64": self.thumbnail_b64,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ImageEntry":
        return cls(
            image_id      = str(data["image_id"]),
            path          = str(data["path"]),
            filename      = str(data["filename"]),
            width         = int(data["width"]),
            height        = int(data["height"]),
            has_alpha     = bool(data["has_alpha"]),
            thumbnail_b64 = data.get("thumbnail_b64"),
        )


@dataclass
class BasicMapping:
    """
    Asignación en modo básico: cuál imagen va al grupo 'normal'
    y cuál al grupo 'active'.
    """
    normal_image_id: Optional[str] = None
    active_image_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "normal_image_id": self.normal_image_id,
            "active_image_id": self.active_image_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BasicMapping":
        return cls(
            normal_image_id = data.get("normal_image_id"),
            active_image_id = data.get("active_image_id"),
        )


@dataclass
class ExportConfig:
    """Configuración de exportación del tema."""
    resolutions: list[int]  = field(default_factory=lambda: list(DEFAULT_RESOLUTIONS))
    inherit:     str        = "Adwaita"     # tema de fallback
    output_path: str        = ""            # ruta destino; se rellena al exportar

    def to_dict(self) -> dict:
        return {
            "resolutions": self.resolutions,
            "inherit":     self.inherit,
            "output_path": self.output_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExportConfig":
        return cls(
            resolutions = list(data.get("resolutions", DEFAULT_RESOLUTIONS)),
            inherit     = str(data.get("inherit", "Adwaita")),
            output_path = str(data.get("output_path", "")),
        )


@dataclass
class ProjectMeta:
    """Metadatos del tema (nombre, autor, etc.)."""
    name:        str = "MiTema"
    author:      str = ""
    description: str = ""
    created_at:  str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    modified_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def touch(self) -> None:
        """Actualiza modified_at al momento actual."""
        self.modified_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "author":      self.author,
            "description": self.description,
            "created_at":  self.created_at,
            "modified_at": self.modified_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMeta":
        return cls(
            name        = str(data.get("name", "MiTema")),
            author      = str(data.get("author", "")),
            description = str(data.get("description", "")),
            created_at  = str(data.get("created_at", "")),
            modified_at = str(data.get("modified_at", "")),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Clase principal: CursorProject
# ─────────────────────────────────────────────────────────────────────────────

class CursorProject:
    """
    Representa un proyecto completo de tema de cursores.

    Es la única clase que sabe cómo serializar y deserializar
    el archivo .cursorproject. Todo el resto del código trabaja
    con instancias de esta clase.

    Uso básico:
        # Proyecto nuevo
        project = CursorProject.new("MiTema", "Jose")

        # Cargar desde archivo
        project = CursorProject.load("/ruta/mi_tema.cursorproject")

        # Guardar
        project.save("/ruta/mi_tema.cursorproject")
    """

    def __init__(
        self,
        meta:          ProjectMeta,
        images:        dict[str, ImageEntry],
        roles:         dict[str, RoleConfig],
        mode:          str          = "basic",
        basic_mapping: BasicMapping = None,
        export:        ExportConfig = None,
    ):
        self.meta          = meta
        self.images        = images          # { image_id: ImageEntry }
        self.roles         = roles           # { role_name: RoleConfig }
        self.mode          = mode            # "basic" | "advanced"
        self.basic_mapping = basic_mapping or BasicMapping()
        self.export        = export or ExportConfig()

        # Ruta del archivo en disco (None si aún no se ha guardado)
        self._filepath: Optional[Path] = None

    # ── Propiedades de consulta rápida ────────────────────────────────────────

    @property
    def filepath(self) -> Optional[Path]:
        return self._filepath

    @property
    def is_saved(self) -> bool:
        return self._filepath is not None

    @property
    def assigned_roles(self) -> list[str]:
        """Lista de nombres de roles que tienen imagen asignada."""
        return [name for name, cfg in self.roles.items() if cfg.is_assigned]

    @property
    def unassigned_roles(self) -> list[str]:
        """Lista de roles sin imagen (usarán fallback del sistema)."""
        return [name for name, cfg in self.roles.items() if not cfg.is_assigned]

    @property
    def missing_images(self) -> list[str]:
        """IDs de imágenes registradas cuyo archivo ya no existe en disco."""
        return [
            img_id for img_id, entry in self.images.items()
            if not entry.exists
        ]

    # ── Gestión de imágenes ───────────────────────────────────────────────────

    def add_image(self, entry: ImageEntry) -> str:
        """
        Registra una imagen en el proyecto.
        Devuelve el image_id asignado.
        """
        self.images[entry.image_id] = entry
        self.meta.touch()
        return entry.image_id

    def remove_image(self, image_id: str) -> None:
        """
        Elimina una imagen del registro y desasigna todos los roles
        que la usaban.
        """
        if image_id not in self.images:
            return

        # Desasignar de todos los roles que la usen
        for cfg in self.roles.values():
            if cfg.image_id == image_id:
                cfg.image_id = None
                cfg.override = False
            if cfg.frames:
                cfg.frames = [f for f in cfg.frames if f.image_id != image_id]
                if not cfg.frames:
                    cfg.frames = None

        # Desasignar del mapping básico
        if self.basic_mapping.normal_image_id == image_id:
            self.basic_mapping.normal_image_id = None
        if self.basic_mapping.active_image_id == image_id:
            self.basic_mapping.active_image_id = None

        del self.images[image_id]
        self.meta.touch()

    # ── Gestión de roles ──────────────────────────────────────────────────────

    def assign_role(self, role_name: str, image_id: Optional[str],
                    hotspot: Optional[Hotspot] = None) -> None:
        """
        Asigna una imagen a un rol específico y lo marca como override manual.
        Si image_id es None, desasigna el rol.
        """
        if role_name not in self.roles:
            raise KeyError(f"Rol desconocido: '{role_name}'")

        cfg = self.roles[role_name]
        cfg.image_id = image_id
        cfg.override = True
        if hotspot is not None:
            cfg.hotspot = hotspot
        self.meta.touch()

    def set_hotspot(self, role_name: str, x: int, y: int) -> None:
        """Actualiza el hotspot de un rol."""
        if role_name not in self.roles:
            raise KeyError(f"Rol desconocido: '{role_name}'")
        self.roles[role_name].hotspot = Hotspot(x, y)
        self.meta.touch()

    def apply_basic_mapping(
        self,
        normal_image_id: Optional[str],
        active_image_id: Optional[str],
        normal_roles:    list[str],
        active_roles:    list[str],
    ) -> None:
        """
        Aplica el modo básico: asigna imagen A a los roles normales
        y imagen B a los roles activos, respetando overrides manuales.
        """
        self.basic_mapping.normal_image_id = normal_image_id
        self.basic_mapping.active_image_id = active_image_id

        for role_name in normal_roles:
            if role_name in self.roles and not self.roles[role_name].override:
                self.roles[role_name].image_id = normal_image_id

        for role_name in active_roles:
            if role_name in self.roles and not self.roles[role_name].override:
                self.roles[role_name].image_id = active_image_id

        self.meta.touch()

    def clear_overrides(self) -> None:
        """Elimina todos los overrides manuales (resetea al modo básico puro)."""
        for cfg in self.roles.values():
            cfg.override = False
        self.meta.touch()

    # ── Serialización ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Convierte el proyecto completo a un diccionario serializable."""
        return {
            "version":       FORMAT_VERSION,
            "meta":          self.meta.to_dict(),
            "mode":          self.mode,
            "images":        {k: v.to_dict() for k, v in self.images.items()},
            "basic_mapping": self.basic_mapping.to_dict(),
            "roles":         {k: v.to_dict() for k, v in self.roles.items()},
            "export":        self.export.to_dict(),
        }

    def save(self, filepath: Optional[str | Path] = None) -> Path:
        """
        Guarda el proyecto en disco como JSON.

        Si se omite filepath usa la ruta guardada en self._filepath.
        Devuelve la ruta donde se guardó.
        """
        target = Path(filepath) if filepath else self._filepath
        if target is None:
            raise ValueError(
                "No se especificó ruta para guardar. "
                "Usa save('/ruta/mi_tema.cursorproject')."
            )

        target = target.with_suffix(".cursorproject")
        target.parent.mkdir(parents=True, exist_ok=True)

        self.meta.touch()
        data = self.to_dict()

        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self._filepath = target
        return target

    # ── Deserialización ───────────────────────────────────────────────────────

    @classmethod
    def load(cls, filepath: str | Path) -> "CursorProject":
        """
        Carga un proyecto desde un archivo .cursorproject.
        Lanza FileNotFoundError si no existe y ValueError si el formato
        no es reconocido.
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Verificar versión del formato
        version = data.get("version", "desconocida")
        if version != FORMAT_VERSION:
            # En el futuro aquí iría la lógica de migración
            raise ValueError(
                f"Versión de formato no compatible: '{version}'. "
                f"Esta versión de CursorForge soporta '{FORMAT_VERSION}'."
            )

        images = {
            k: ImageEntry.from_dict(v)
            for k, v in data.get("images", {}).items()
        }
        roles = {
            k: RoleConfig.from_dict(v)
            for k, v in data.get("roles", {}).items()
        }

        project = cls(
            meta          = ProjectMeta.from_dict(data.get("meta", {})),
            images        = images,
            roles         = roles,
            mode          = data.get("mode", "basic"),
            basic_mapping = BasicMapping.from_dict(data.get("basic_mapping", {})),
            export        = ExportConfig.from_dict(data.get("export", {})),
        )
        project._filepath = path
        return project

    # ── Constructor de proyecto nuevo ─────────────────────────────────────────

    @classmethod
    def new(
        cls,
        name:         str = "MiTema",
        author:       str = "",
        description:  str = "",
        role_names:   Optional[list[str]] = None,
        role_aliases: Optional[dict[str, list[str]]] = None,
    ) -> "CursorProject":
        """
        Crea un proyecto vacío listo para usar.

        role_names   → lista de roles a inicializar (los ~30 del sistema)
        role_aliases → dict { role_name: [alias, ...] } cargado desde
                       assets/roles_aliases.json
        """
        meta = ProjectMeta(name=name, author=author, description=description)

        roles: dict[str, RoleConfig] = {}
        if role_names:
            for rname in role_names:
                aliases = (role_aliases or {}).get(rname, [])
                roles[rname] = RoleConfig(aliases=aliases)

        return cls(
            meta   = meta,
            images = {},
            roles  = roles,
        )

    # ── Utilidades ────────────────────────────────────────────────────────────

    @staticmethod
    def generate_image_id() -> str:
        """Genera un ID único para una imagen (ej: 'img_a3f2')."""
        return "img_" + uuid.uuid4().hex[:4]

    def __repr__(self) -> str:
        return (
            f"CursorProject("
            f"name={self.meta.name!r}, "
            f"mode={self.mode!r}, "
            f"images={len(self.images)}, "
            f"roles={len(self.roles)}"
            f")"
        )
