"""Read and write assetlint.toml for the app's rules editor.

Saving edits the file in place with tomlkit: only the keys the user changed
are touched, so comments and layout people wrote by hand survive. The result
is validated with the same Config model the CLI uses before it's written, and
it's written atomically, so a failed save never leaves a broken file.
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomlkit
from pydantic import ValidationError
from tomlkit.items import AoT, Table

from assetlint.app.api import ApiError, existing_folder
from assetlint.config import (
    CONFIG_FILENAME,
    Config,
    ConfigError,
    find_config,
    format_validation_error,
    load_config,
)
from assetlint.presets import PRESETS
from assetlint.rules import BUILTIN_RULES

# The settings the editor shows for each rule, besides severity.
# kind: int | size | bool | text | extensions | map (extension -> text or size)
FIELDS: dict[str, list[dict[str, str]]] = {
    "formats": [
        {
            "key": "allowed",
            "kind": "extensions",
            "label": "Allowed file types",
            "help": "Empty: every checked type is allowed.",
        },
    ],
    "size": [
        {
            "key": "max",
            "kind": "size",
            "label": "Largest file",
            "help": "e.g. 50MB. Empty: no limit.",
        },
        {
            "key": "max_by_type",
            "kind": "map",
            "value_kind": "size",
            "label": "Limit by file type",
            "help": "Overrides the limit above for these types.",
        },
    ],
    "naming": [
        {
            "key": "pattern",
            "kind": "text",
            "label": "Name pattern",
            "help": "A regular expression the whole name (without extension) must match.",
        },
        {
            "key": "prefixes",
            "kind": "map",
            "value_kind": "text",
            "label": "Prefix by file type",
            "help": "e.g. .fbx -> SM_, .png -> T_",
        },
    ],
    "duplicates": [],
    "triangles": [
        {
            "key": "max",
            "kind": "int",
            "label": "Triangle budget",
            "help": "Most triangles in one mesh file. Empty: no budget.",
        },
    ],
    "textures": [
        {"key": "power_of_two", "kind": "bool", "label": "Sizes must be powers of two"},
        {
            "key": "max_size",
            "kind": "int",
            "label": "Largest width or height",
            "help": "In pixels. Empty: no limit.",
        },
    ],
    "references": [],
}

# A custom rule's settings, in the order they're written to the file.
CUSTOM_FIELDS: list[dict[str, str]] = [
    {"key": "paths", "kind": "lines", "label": "Folders or files",
     "help": "One pattern per line, e.g. characters/ or props/*_LOD0.*  Empty: everywhere."},
    {"key": "types", "kind": "extensions", "label": "File types", "help": "Empty: every type."},
    {"key": "forbidden", "kind": "bool", "label": "Not allowed here at all"},
    {"key": "name_pattern", "kind": "text", "label": "Name pattern",
     "help": "A regular expression the whole name (without extension) must match."},
    {"key": "max_size", "kind": "size", "label": "Largest file", "help": "e.g. 8MB"},
    {"key": "min_triangles", "kind": "int", "label": "Fewest triangles"},
    {"key": "max_triangles", "kind": "int", "label": "Most triangles"},
    {"key": "min_texture_size", "kind": "int", "label": "Smallest texture side",
     "help": "In pixels."},
    {"key": "max_texture_size", "kind": "int", "label": "Largest texture side",
     "help": "In pixels."},
    {"key": "square", "kind": "bool", "label": "Textures must be square"},
    {"key": "requires", "kind": "lines", "label": "Files that must sit next to it",
     "help": "One per line. {stem} is the name, {base} the name without its prefix: "
             "T_{base}_D.png"},
]  # fmt: skip
_CUSTOM_ORDER = ["id", "description", "severity", *(f["key"] for f in CUSTOM_FIELDS)]

NEW_FILE_HEADER = (
    "# Asset Lint settings. Edited with the Asset Lint app; safe to edit by hand too.\n"
    "# The command line, CI and the app all read this file.\n"
)


def config_target(folder: Path) -> tuple[Path, bool]:
    """The config file the editor works on: the one in use, or a new one in `folder`."""
    found = find_config(folder)
    return (found, True) if found else (folder / CONFIG_FILENAME, False)


def load_settings(folder_text: str) -> dict[str, Any]:
    folder = existing_folder(folder_text)
    path, exists = config_target(folder)
    raw = _read_raw(path) if exists else {}
    try:
        config = load_config(path if exists else None)
    except ConfigError as exc:
        raise ApiError(str(exc)) from exc

    raw_rules = raw.get("rules", {}) if isinstance(raw.get("rules"), dict) else {}
    rules = []
    for rule in BUILTIN_RULES:
        own = raw_rules.get(rule.id, {}) if isinstance(raw_rules.get(rule.id), dict) else {}
        effective = getattr(config.rules, rule.id)
        rules.append(
            {
                "id": rule.id,
                "label": rule.label or rule.id,
                "description": rule.description,
                "why": rule.why,
                "severity": {"value": effective.severity, "set": "severity" in own},
                "fields": [
                    {
                        **field,
                        # what's in the file as written (e.g. "50MB"), else what applies
                        "value": own[field["key"]]
                        if field["key"] in own
                        else _jsonable(getattr(effective, field["key"])),
                        "set": field["key"] in own,
                    }
                    for field in FIELDS[rule.id]
                ],
            }
        )

    return {
        "path": str(path),
        "exists": exists,
        "preset": raw.get("preset"),
        "presets": [
            {"id": key, "label": p["label"], "description": p["description"]}
            for key, p in PRESETS.items()
        ],
        "rules": rules,
        "exclude": raw.get("exclude", []),
        "overrides": [_override_for_editor(o) for o in raw.get("overrides", [])],
        "custom": [c for c in raw.get("custom", []) if isinstance(c, dict)],
        "custom_fields": CUSTOM_FIELDS,
    }


def save_settings(folder_text: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Apply the editor's changes to assetlint.toml and return where it was saved.

    changes = {
        "preset": "unreal" | None,                       # optional
        "rules": {"triangles": {"max": 5000, "severity": None}},  # None: remove the key
        "exclude": ["build/"],                           # optional
        "overrides": [{"paths": [...], "rules": {...}}], # optional, replaces them all
    }
    """
    folder = existing_folder(folder_text)
    path, exists = config_target(folder)
    doc = (
        tomlkit.parse(path.read_text(encoding="utf-8"))
        if exists
        else tomlkit.parse(NEW_FILE_HEADER)
    )

    if "preset" in changes:
        _set_or_remove(doc, "preset", changes["preset"])
    if "exclude" in changes:
        _set_or_remove(doc, "exclude", changes["exclude"] or None)

    for rule_id, keys in (changes.get("rules") or {}).items():
        if rule_id not in FIELDS or not isinstance(keys, dict):
            raise ApiError(f"Unknown rule: {rule_id}")
        rules_table = doc.setdefault("rules", tomlkit.table(is_super_table=True))
        table = rules_table.setdefault(rule_id, tomlkit.table())
        for key, value in keys.items():
            _set_or_remove(table, key, value)
        if not table:
            del rules_table[rule_id]
        if not rules_table:
            del doc["rules"]

    if "overrides" in changes:
        overrides = [_override_for_toml(o) for o in changes["overrides"] or []]
        current = doc["overrides"].unwrap() if "overrides" in doc else []
        if overrides != current:  # rewriting unchanged overrides would drop their comments
            if "overrides" in doc:
                del doc["overrides"]
            if overrides:
                doc["overrides"] = _array_of_tables(overrides)

    if "custom" in changes:
        custom = [_custom_for_toml(c) for c in changes["custom"] or []]
        current = doc["custom"].unwrap() if "custom" in doc else []
        if custom != current:  # rewriting unchanged rules would drop their comments
            if "custom" in doc:
                del doc["custom"]
            if custom:
                aot = tomlkit.aot()
                for entry in custom:
                    table = tomlkit.table()
                    table.update(entry)
                    aot.append(table)
                doc["custom"] = aot

    text = tomlkit.dumps(doc)
    _validate(path, text)
    _write_atomically(path, text)
    return {"path": str(path), "created": not exists}


# --- helpers --------------------------------------------------------------------


def _read_raw(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ApiError(f"{path}: can't read it: {exc}") from exc


def _jsonable(value: Any) -> Any:
    return (
        value if value is None or isinstance(value, bool | int | str | list | dict) else str(value)
    )


def _set_or_remove(table: Any, key: str, value: Any) -> None:
    if value is None or value == "":
        if key in table:
            del table[key]
        return
    if isinstance(value, dict):
        inline = tomlkit.inline_table()
        inline.update(value)
        table[key] = inline
    else:
        table[key] = value


def _override_for_editor(override: Any) -> dict[str, Any]:
    if not isinstance(override, dict):
        return {"paths": [], "rules": {}}
    return {"paths": override.get("paths", []), "rules": override.get("rules", {})}


def _override_for_toml(override: Any) -> dict[str, Any]:
    if not isinstance(override, dict):
        raise ApiError("Each folder override needs folders and settings.")
    paths = [p.strip() for p in override.get("paths", []) if isinstance(p, str) and p.strip()]
    rules = {
        rule: {k: v for k, v in keys.items() if v is not None and v != ""}
        for rule, keys in (override.get("rules") or {}).items()
        if isinstance(keys, dict)
    }
    return {"paths": paths, "rules": {r: keys for r, keys in rules.items() if keys}}


def _custom_for_toml(entry: Any) -> dict[str, Any]:
    """A custom rule as the editor sent it, without empty settings, in a stable key order."""
    if not isinstance(entry, dict) or not str(entry.get("id", "")).strip():
        raise ApiError("Each custom rule needs an id, such as hero-textures.")
    kept = {}
    for key in _CUSTOM_ORDER:
        value = entry.get(key)
        if isinstance(value, str):
            value = value.strip()
        if isinstance(value, list):
            value = [v.strip() if isinstance(v, str) else v for v in value]
            value = [v for v in value if v != ""]
        if value is None or value == "" or value == [] or value is False:
            continue
        kept[key] = value
    unknown = set(entry) - set(_CUSTOM_ORDER)
    if unknown:
        raise ApiError(f"Unknown custom rule setting: {sorted(unknown)[0]}")
    return kept


def _array_of_tables(items: list[dict[str, Any]]) -> AoT:
    aot = tomlkit.aot()
    for item in items:
        table = tomlkit.table()
        table["paths"] = item["paths"]
        rules = tomlkit.table(is_super_table=True)
        for rule_id, keys in item["rules"].items():
            rule_table: Table = tomlkit.table()
            for key, value in keys.items():
                _set_or_remove(rule_table, key, value)
            rules[rule_id] = rule_table
        if item["rules"]:
            table["rules"] = rules
        aot.append(table)
    return aot


def _validate(path: Path, text: str) -> None:
    try:
        Config.model_validate(tomllib.loads(text))
    except ValidationError as exc:
        raise ApiError(format_validation_error(path, exc)) from exc


def _write_atomically(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".assetlint-", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
