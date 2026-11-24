"""The assetlint.toml schema, and how a config file is found and loaded."""

from __future__ import annotations

import copy
import re
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path
from string import Formatter
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PositiveInt,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from assetlint.presets import PRESETS

CONFIG_FILENAME = "assetlint.toml"

PresetName = Literal["unreal", "unity", "godot"]

Severity = Literal["error", "warn", "off"]

# File types checked when the config doesn't say otherwise.
DEFAULT_EXTENSIONS: list[str] = [
    # meshes and scenes
    ".gltf", ".glb", ".obj", ".fbx", ".blend", ".usd", ".usda", ".usdc", ".usdz",
    # textures
    ".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".exr", ".hdr", ".psd", ".dds", ".ktx2",
]  # fmt: skip


class ConfigError(Exception):
    """The config file is missing, unreadable or invalid."""


def _normalize_extension(ext: str) -> str:
    ext = ext.strip().lower()
    if not ext:
        raise ValueError("empty extension")
    return ext if ext.startswith(".") else f".{ext}"


class _Strict(BaseModel):
    # Unknown keys are errors, so a typo like `serverity` is caught instead of ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class NamingRuleConfig(_Strict):
    severity: Severity = "error"
    # The whole file name without its extension must match. The default
    # rejects spaces and Blender's `.001` duplicate suffixes.
    pattern: str = r"[A-Za-z0-9_\-]+"
    # Required prefix by extension, e.g. {".glb" = "SM_", ".png" = "T_"}.
    prefixes: dict[str, str] = Field(default_factory=dict)

    @field_validator("pattern")
    @classmethod
    def _pattern_compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"not a valid regular expression: {exc}") from exc
        return value

    @field_validator("prefixes")
    @classmethod
    def _normalize_prefix_keys(cls, value: dict[str, str]) -> dict[str, str]:
        return {_normalize_extension(ext): prefix for ext, prefix in value.items()}


_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*([kmgt]i?b|b)?", re.IGNORECASE)
_SIZE_UNITS = {
    "b": 1,
    "kb": 10**3, "mb": 10**6, "gb": 10**9, "tb": 10**12,
    "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40,
}  # fmt: skip


def parse_size(value: object) -> int:
    """Bytes from a number or a string such as "50MB" (10^6) or "2MiB" (2^20)."""
    if isinstance(value, int) and not isinstance(value, bool):
        size = value
    elif isinstance(value, str) and (match := _SIZE.fullmatch(value.strip())):
        number, unit = match.groups()
        size = int(float(number) * _SIZE_UNITS[(unit or "b").lower()])
    else:
        raise ValueError('expected a number of bytes or a size such as "50MB" or "2MiB"')
    if size <= 0:
        raise ValueError("must be greater than zero")
    return size


# A size in bytes. KB, MB and GB are powers of 1000; KiB, MiB and GiB are powers of 1024.
ByteSize = Annotated[int, BeforeValidator(parse_size)]


class FormatsRuleConfig(_Strict):
    severity: Severity = "error"
    # File types allowed in the folder. Default: every checked type. Files are
    # also checked to be what their extension says, and not empty or corrupt.
    allowed: list[str] | None = None

    @field_validator("allowed")
    @classmethod
    def _normalize_allowed(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else sorted({_normalize_extension(e) for e in value})


class SizeRuleConfig(_Strict):
    severity: Severity = "error"
    # Largest file allowed. No limit unless set.
    max: ByteSize | None = None
    # Limit by extension, overriding `max`, e.g. {".png" = "8MB"}.
    max_by_type: dict[str, ByteSize] = Field(default_factory=dict)

    @field_validator("max_by_type")
    @classmethod
    def _normalize_keys(cls, value: dict[str, int]) -> dict[str, int]:
        return {_normalize_extension(ext): size for ext, size in value.items()}


class DuplicatesRuleConfig(_Strict):
    severity: Severity = "warn"


class TrianglesRuleConfig(_Strict):
    severity: Severity = "error"
    # Most triangles allowed in one mesh file (glTF/GLB and OBJ). No limit unless set.
    max: PositiveInt | None = None


class TexturesRuleConfig(_Strict):
    severity: Severity = "warn"
    # Width and height must each be a power of two (1, 2, 4 ... 4096).
    power_of_two: bool = True
    # Largest width or height allowed, in pixels. No limit unless set.
    max_size: PositiveInt | None = None


class ReferencesRuleConfig(_Strict):
    severity: Severity = "error"


class RulesConfig(_Strict):
    formats: FormatsRuleConfig = Field(default_factory=FormatsRuleConfig)
    size: SizeRuleConfig = Field(default_factory=SizeRuleConfig)
    naming: NamingRuleConfig = Field(default_factory=NamingRuleConfig)
    duplicates: DuplicatesRuleConfig = Field(default_factory=DuplicatesRuleConfig)
    triangles: TrianglesRuleConfig = Field(default_factory=TrianglesRuleConfig)
    textures: TexturesRuleConfig = Field(default_factory=TexturesRuleConfig)
    references: ReferencesRuleConfig = Field(default_factory=ReferencesRuleConfig)


_CUSTOM_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
_TEMPLATE_FIELDS = {"stem", "base"}
_REQUIREMENTS = (
    "forbidden", "name_pattern", "max_size", "min_triangles", "max_triangles",
    "min_texture_size", "max_texture_size", "square", "requires",
)  # fmt: skip


class CustomRuleConfig(_Strict):
    """A rule written in assetlint.toml: which files it covers, and what they must be.

    A file breaks the rule once for each requirement it misses. Requirements that
    don't fit a file (triangles on a PNG) are skipped for it.
    """

    # Shown as the rule's name in reports, e.g. "hero-textures".
    id: str
    description: str = ""
    severity: Severity = "error"
    # Which files: path patterns as in `exclude` (empty: all) and file types (empty: all).
    paths: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    # Requirements. At least one must be set.
    forbidden: bool = False  # these files mustn't be here at all
    name_pattern: str | None = None  # the name without extension must match this regex
    max_size: ByteSize | None = None
    min_triangles: PositiveInt | None = None
    max_triangles: PositiveInt | None = None
    min_texture_size: PositiveInt | None = None  # smallest width or height, in pixels
    max_texture_size: PositiveInt | None = None  # largest width or height, in pixels
    square: bool = False
    # Files that must exist next to each one, e.g. "T_{base}_D.png": {stem} is the
    # name without extension, {base} the same without its naming prefix (SM_, T_...).
    requires: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not _CUSTOM_ID.fullmatch(value):
            raise ValueError("use lowercase letters, digits, - and _, e.g. hero-textures")
        if value in RulesConfig.model_fields:
            raise ValueError(f"'{value}' is a built-in rule; choose another id")
        return value

    @field_validator("types")
    @classmethod
    def _normalize_types(cls, value: list[str]) -> list[str]:
        return sorted({_normalize_extension(e) for e in value})

    @field_validator("name_pattern")
    @classmethod
    def _pattern_compiles(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"not a valid regular expression: {exc}") from exc
        return value

    @field_validator("requires")
    @classmethod
    def _templates(cls, value: list[str]) -> list[str]:
        for template in value:
            if not template.strip():
                raise ValueError("empty file name")
            if re.match(r"^([A-Za-z]:)?[\\/]", template):
                raise ValueError(f"'{template}': use a path relative to the file")
            try:
                fields = {f for _, f, _, _ in Formatter().parse(template) if f is not None}
            except ValueError as exc:
                raise ValueError(f"'{template}': {exc}") from exc
            if unknown := fields - _TEMPLATE_FIELDS:
                name = sorted(unknown)[0]
                raise ValueError(f"'{template}': unknown {{{name}}}; use {{stem}} or {{base}}")
        return value

    @model_validator(mode="after")
    def _sensible(self) -> CustomRuleConfig:
        if not any(getattr(self, key) for key in _REQUIREMENTS):
            raise ValueError("set at least one requirement, such as max_size or name_pattern")
        for low, high in (
            ("min_triangles", "max_triangles"),
            ("min_texture_size", "max_texture_size"),
        ):
            lo, hi = getattr(self, low), getattr(self, high)
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"{low} is larger than {high}")
        return self

    def covers(self, rel: str, ext: str) -> bool:
        if self.types and ext not in self.types:
            return False
        return not self.paths or any(path_matches(rel, p) for p in self.paths)


class Override(_Strict):
    """Rule settings for some folders or files, e.g. a bigger triangle budget for characters/."""

    # Path patterns, like `exclude`.
    paths: list[str] = Field(min_length=1)
    # Rule tables as in [rules]; only the keys given here change.
    rules: RulesConfig = Field(default_factory=RulesConfig)


class Config(_Strict):
    # A ready-made rule set ("unreal", "unity", "godot") that [rules] builds on.
    preset: PresetName | None = None
    # Only files with these extensions are checked.
    extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    # Path patterns to skip. Paths are relative to the config file's folder (or
    # the checked folder when there is no config), with forward slashes.
    # `*` matches across folders, and a pattern ending in `/` matches everything
    # under that folder: "build/", "*_backup.*", "props/old/*.png".
    exclude: list[str] = Field(default_factory=list)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    # Applied in order on top of [rules] for matching paths; the last match wins.
    overrides: list[Override] = Field(default_factory=list)
    # Rules written here, beside the built-in ones.
    custom: list[CustomRuleConfig] = Field(default_factory=list)
    # Resolved rule settings, by the indexes of the overrides that matched.
    _resolved: dict[tuple[int, ...], RulesConfig] = PrivateAttr(default_factory=dict)

    def rules_for(self, rel: str) -> RulesConfig:
        """The rule settings for one path, with every matching override applied."""
        matching = tuple(
            i for i, o in enumerate(self.overrides) if any(path_matches(rel, p) for p in o.paths)
        )
        if not matching:
            return self.rules
        cached = self._resolved.get(matching)
        if cached is None:
            merged = self.rules.model_dump(exclude_unset=True)
            for index in matching:
                _deep_merge(merged, self.overrides[index].rules.model_dump(exclude_unset=True))
            cached = self._resolved[matching] = RulesConfig.model_validate(merged)
        return cached

    @field_validator("custom")
    @classmethod
    def _unique_ids(cls, value: list[CustomRuleConfig]) -> list[CustomRuleConfig]:
        seen: set[str] = set()
        for rule in value:
            if rule.id in seen:
                raise ValueError(f"two custom rules have the id '{rule.id}'")
            seen.add(rule.id)
        return value

    @field_validator("extensions")
    @classmethod
    def _normalize_extensions(cls, value: list[str]) -> list[str]:
        return sorted({_normalize_extension(ext) for ext in value})

    @model_validator(mode="before")
    @classmethod
    def _apply_preset(cls, data: Any) -> Any:
        """Put the preset's settings under [rules], so anything in [rules] wins."""
        if not isinstance(data, dict) or data.get("preset") not in PRESETS:
            return data  # an unknown preset name is reported by the `preset` field
        rules = copy.deepcopy(PRESETS[data["preset"]]["rules"])
        own = data.get("rules", {})
        if isinstance(own, RulesConfig):
            own = own.model_dump(exclude_unset=True)
        if isinstance(own, dict):
            _deep_merge(rules, copy.deepcopy(own))
        return {**data, "rules": rules}


def path_matches(rel: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return rel.startswith(pattern)
    return fnmatchcase(rel, pattern)


def _deep_merge(into: dict[str, Any], new: dict[str, Any]) -> None:
    """Tables merge key by key (so `prefixes` gains entries); other values replace."""
    for key, value in new.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            _deep_merge(into[key], value)
        else:
            into[key] = value


def find_config(start: Path) -> Path | None:
    """Return the nearest assetlint.toml in `start` or one of its parents."""
    start = start.resolve()
    directory = start if start.is_dir() else start.parent
    for candidate_dir in (directory, *directory.parents):
        candidate = candidate_dir / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None) -> Config:
    """Load and validate a config file. With no path, return the defaults."""
    if path is None:
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{path}: can't read file: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(format_validation_error(path, exc)) from exc


def format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = [f"{path}: invalid config"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(top level)"
        message = error["msg"]
        if error["type"] == "extra_forbidden":
            message = "unknown key"
        lines.append(f"  {location}: {message}")
    return "\n".join(lines)
