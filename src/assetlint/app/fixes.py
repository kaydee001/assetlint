"""Fixes the app can make for a file: rename it, repair the paths it uses, trash a duplicate.

A fix is planned first and shown as a preview: every rename, edit and file
moved to the trash. Applying it plans it again from the files on disk and
refuses if the plan differs from the preview (something changed in between),
so the page never sends the changes themselves, only which fix to apply.

Renaming or trashing a file also rewrites the meshes that point at it: .gltf
and .glb image and buffer URIs, OBJ `mtllib` lines and .mtl texture lines.
Every edit keeps the rest of the file byte for byte. A Unity `.meta` file next
to the asset moves (or goes to the trash) with it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, unquote

from assetlint.app.api import ApiError, existing_folder
from assetlint.config import Config, ConfigError, NamingRuleConfig, find_config, load_config
from assetlint.engine import discover
from assetlint.model import Asset
from assetlint.readers import MeshInfo, Reference
from assetlint.readers.obj import _TEXTURE_KEYS, _library_names, _split, _texture_name
from assetlint.rules.duplicates import _digest
from assetlint.rules.references import _ABSOLUTE, ReferencesRule

MESH_TYPES = (".gltf", ".glb", ".obj")
SIDECAR = ".meta"  # Unity keeps an asset's GUID and import settings in <file>.meta
ENGINE_NOTE = (
    "Engine files that point at it by path (scenes, Godot .import, Unreal .uasset) aren't updated."
)
_GLB_HEADER = struct.Struct("<4sII")
_CHUNK_HEADER = struct.Struct("<I4s")
_GLTF_URI = re.compile(r'("uri"\s*:\s*)"((?:[^"\\]|\\.)*)"')
_BLENDER_SUFFIX = re.compile(r"\.\d{3}$")
_RESERVED = {"con", "prn", "aux", "nul"} | {f"{d}{i}" for d in ("com", "lpt") for i in range(1, 10)}
_URI_SAFE = "/!$&'()*+,;=@~"


# --- the plan ----------------------------------------------------------------------


@dataclass
class Change:
    kind: Literal["rename", "edit", "trash"]
    path: Path
    to: Path | None = None  # rename: the new path
    content: bytes | None = None  # edit: the whole new file
    detail: str = ""  # edit: what changes, for the preview


@dataclass
class Fix:
    id: str
    title: str
    changes: list[Change] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    blocked: str | None = None  # why it can't be applied as it stands
    name: str | None = None  # rename: the new file name

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for c in self.changes:
            h.update(f"{c.kind}\0{c.path}\0{c.to}\0".encode())
            h.update(hashlib.sha256(c.content or b"").digest())
        return h.hexdigest()[:16]


@dataclass
class Project:
    folder: Path  # the checked folder; finding paths are relative to it
    root: Path  # the config's folder (or the checked folder): nothing outside it is touched
    config: Config

    def shown(self, path: Path) -> str:
        return Path(os.path.relpath(path, self.folder)).as_posix()

    def asset(self, path: Path) -> Asset:
        return Asset(path=path, rel=path.relative_to(self.root).as_posix())


def load_project(folder_text: str) -> Project:
    folder = existing_folder(folder_text)
    config_path = find_config(folder)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise ApiError(str(exc)) from exc
    return Project(folder, config_path.parent if config_path else folder, config)


def file_in(project: Project, rel: str) -> Path:
    path = (project.folder / rel).resolve()
    if not path.is_relative_to(project.folder) or not path.is_file():
        raise ApiError(f"'{rel}' isn't a file in this folder. Check the folder again.")
    return path


# --- the API -------------------------------------------------------------------------


def fixable(project: Project, findings: list[dict[str, Any]]) -> set[str]:
    """Paths (as findings show them) of the files that have a fix to offer."""
    paths = set()
    for f in findings:
        if f["rule"] in ("naming", "duplicates"):
            paths.add(f["path"])
        elif f["rule"] == "references" and f["path"] not in paths:
            path = (project.folder / f["path"]).resolve()
            if _path_repairs(path):
                paths.add(f["path"])
    return paths


def list_fixes(folder: str, rel: str, name: str | None = None) -> dict[str, Any]:
    project = load_project(folder)
    path = file_in(project, rel)
    return {"path": rel, "fixes": [_to_json(project, fix) for fix in plan(project, path, name)]}


def apply_fix(
    folder: str, rel: str, fix_id: str, fingerprint: str, name: str | None
) -> dict[str, Any]:
    project = load_project(folder)
    path = file_in(project, rel)
    fix = next((f for f in plan(project, path, name) if f.id == fix_id), None)
    if fix is None or fix.fingerprint() != fingerprint:
        raise ApiError("The files changed since the preview. Look at the fix again.")
    if fix.blocked:
        raise ApiError(fix.blocked)
    _apply(project, fix.changes)
    return {"done": fix.title}


def plan(project: Project, path: Path, name: str | None = None) -> list[Fix]:
    rel = project.asset(path).rel
    rules = project.config.rules_for(rel)
    fixes = []
    if rules.naming.severity != "off" and (
        name is not None or _naming_problems(path.name, rules.naming)
    ):
        fixes.append(
            _rename(project, path, suggest_name(path.name, rules.naming) if name is None else name)
        )
    if rules.references.severity != "off" and (repairs := _path_repairs(path)):
        fixes.append(_repair_paths(project, repairs))
    if rules.duplicates.severity != "off":
        fixes.extend(_trash_duplicate(project, path))
    return fixes


def _to_json(project: Project, fix: Fix) -> dict[str, Any]:
    def change(c: Change) -> dict[str, Any]:
        out = {"kind": c.kind, "path": project.shown(c.path), "detail": c.detail}
        if c.to is not None:
            out["to"] = project.shown(c.to)
        return out

    return {
        "id": fix.id,
        "title": fix.title,
        "name": fix.name,
        "changes": [change(c) for c in fix.changes],
        "notes": fix.notes,
        "blocked": fix.blocked,
        "fingerprint": fix.fingerprint(),
    }


# --- rename -------------------------------------------------------------------------


def suggest_name(filename: str, naming: NamingRuleConfig) -> str:
    """A name the naming rule should accept: no Blender suffix, `_` for spaces, the prefix."""
    stem, ext = os.path.splitext(filename)
    stem = _BLENDER_SUFFIX.sub("", stem)
    stem = re.sub(r"[^\w\-]+", "_", stem).strip("_") or "asset"
    prefix = naming.prefixes.get(ext.lower(), "")
    if prefix and not stem.startswith(prefix):
        if stem.lower().startswith(prefix.lower()):
            stem = stem[len(prefix) :]
        stem = prefix + stem.lstrip("_")
    return stem + ext


def _naming_problems(filename: str, naming: NamingRuleConfig) -> list[str]:
    stem, ext = os.path.splitext(filename)
    problems = []
    prefix = naming.prefixes.get(ext.lower())
    if prefix and not stem.startswith(prefix):
        problems.append(f"doesn't start with '{prefix}'")
    if not re.fullmatch(naming.pattern, stem):
        problems.append("doesn't match the naming pattern")
    return problems


def _rename(project: Project, path: Path, name: str) -> Fix:
    name = name.strip()
    fix = Fix(id="rename", title="Rename", name=name)
    problem = _bad_name(path, name)
    if problem:
        fix.blocked = problem
        return fix

    target = path.with_name(name)
    if target.exists() and not os.path.samefile(target, path):
        fix.blocked = f"'{project.shown(target)}' already exists. Choose another name."
        return fix
    fix.title = f"Rename to {name}"
    fix.changes.append(Change("rename", path, to=target))
    sidecar = path.with_name(path.name + SIDECAR)
    if sidecar.is_file():
        fix.changes.append(Change("rename", sidecar, to=target.with_name(name + SIDECAR)))

    referrers = _referrers(project.root, path)
    for holder, refs in referrers.items():
        edits = {ref.raw: _with_last_part(ref.raw, name) for ref in refs}
        fix.changes.append(_edit(holder, edits))
    still = _naming_problems(name, project.config.rules_for(project.asset(target).rel).naming)
    if still:
        fix.notes.append(f"The new name still {' and '.join(still)}.")
    fix.notes.append(ENGINE_NOTE)
    return fix


def _bad_name(path: Path, name: str) -> str | None:
    if not name or name in (".", ".."):
        return "Type a new name."
    if any(c in name for c in '/\\:*?"<>|') or any(ord(c) < 32 for c in name):
        return "A file name can't contain / \\ : * ? \" < > |"
    if name.endswith((".", " ")):
        return "A file name can't end with a dot or a space (Windows drops them)."
    if name.split(".")[0].lower() in _RESERVED:
        return f"'{name.split('.')[0]}' is a reserved name on Windows."
    if os.path.splitext(name)[1].lower() != path.suffix.lower():
        return f"Keep the {path.suffix} extension."
    if name == path.name:
        return "That's the current name."
    return None


def _with_last_part(raw: str, name: str) -> str:
    cut = max(raw.rfind("/"), raw.rfind("\\"))
    return raw[: cut + 1] + name


# --- repair paths ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Repair:
    holder: Path  # the file the path is written in: the mesh, or its .mtl
    raw: str
    new: str


def _path_repairs(path: Path) -> list[_Repair]:
    """Backslashes and wrong-case paths in a mesh, which can be fixed without guessing."""
    if path.suffix.lower() not in MESH_TYPES:
        return []
    mesh = Asset(path=path, rel=path.name).mesh
    if not isinstance(mesh, MeshInfo):
        return []
    locator = ReferencesRule()
    repairs = []
    for ref in mesh.references:
        if _ABSOLUTE.match(ref.raw):
            continue  # where it should point is a guess
        new = ref.raw.replace("\\", "/")
        found, on_disk = locator.locate(ref.base, new)
        if not found:
            continue
        new = on_disk or new
        if new != ref.raw:
            repairs.append(_Repair(_holder(path, ref), ref.raw, new))
    return list(dict.fromkeys(repairs))


def _repair_paths(project: Project, repairs: list[_Repair]) -> Fix:
    by_holder: dict[Path, dict[str, str]] = defaultdict(dict)
    for r in repairs:
        by_holder[r.holder][r.raw] = r.new
    n = len(repairs)
    fix = Fix(id="paths", title=f"Fix {n} path{'s' if n > 1 else ''}")
    fix.changes = [_edit(holder, edits) for holder, edits in by_holder.items()]
    return fix


# --- duplicates -------------------------------------------------------------------------


def _trash_duplicate(project: Project, path: Path) -> Iterator[Fix]:
    size = path.stat().st_size
    if size == 0:
        return
    same_size = [
        a.path
        for a in discover(project.folder, project.config, project.root)
        if a.path != path and a.size == size
    ]
    if not same_size:
        return
    digest = _digest(Asset(path=path, rel=""))
    copies = [p for p in same_size if _digest(Asset(path=p, rel="")) == digest]
    referrers = _referrers(project.root, path) if copies else {}
    for kept in copies:
        fix = Fix(
            id=f"trash:{project.shown(kept)}",
            title=f"Move to the trash, keep {project.shown(kept)}",
        )
        fix.changes.append(Change("trash", path))
        sidecar = path.with_name(path.name + SIDECAR)
        if sidecar.is_file():
            fix.changes.append(Change("trash", sidecar))
        for holder, refs in referrers.items():
            base = refs[0].base
            to_kept = Path(os.path.relpath(kept, base)).as_posix()
            fix.changes.append(_edit(holder, {ref.raw: to_kept for ref in refs}))
        if referrers:
            fix.notes.append(ENGINE_NOTE)
        if sidecar.is_file():
            fix.notes.append("Unity links assets by the GUID in .meta files, not by path.")
        yield fix


# --- who points at a file ------------------------------------------------------------------


def _referrers(root: Path, target: Path) -> dict[Path, list[Reference]]:
    """Every file under `root` holding a path to `target`, with those references.

    All meshes count, including excluded ones: an excluded mesh still breaks
    when its texture is renamed.
    """
    found: dict[Path, dict[str, Reference]] = defaultdict(dict)
    for mesh_path in _meshes(root):
        mesh = Asset(path=mesh_path, rel=mesh_path.name).mesh
        if not isinstance(mesh, MeshInfo):
            continue
        for ref in mesh.references:
            if _ABSOLUTE.match(ref.raw):
                continue
            pointed = ref.base / ref.raw.replace("\\", "/")
            if pointed.is_file() and os.path.samefile(pointed, target):
                found[_holder(mesh_path, ref)][ref.raw] = ref
    return {holder: list(refs.values()) for holder, refs in found.items()}


def _meshes(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() in MESH_TYPES:
                yield Path(dirpath, filename)


def _holder(mesh: Path, ref: Reference) -> Path:
    if ref.via is None:
        return mesh
    return (mesh.parent / ref.via.replace("\\", "/")).resolve()


# --- editing the files that hold paths --------------------------------------------------------


def _edit(holder: Path, edits: dict[str, str]) -> Change:
    data = holder.read_bytes()
    ext = holder.suffix.lower()
    if ext == ".gltf":
        content = _rewrite_gltf_json(data.decode("utf-8"), edits).encode("utf-8")
    elif ext == ".glb":
        content = _rewrite_glb(data, edits)
    else:
        content = _rewrite_lines(data, edits, mtl=ext != ".obj")
    detail = ", ".join(f"'{old}' → '{new}'" for old, new in edits.items())
    return Change("edit", holder, content=content, detail=detail)


def _rewrite_gltf_json(text: str, edits: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        uri = json.loads(f'"{match.group(2)}"')
        new = edits.get(unquote(uri))
        if new is None:
            return match.group(0)
        return match.group(1) + json.dumps(quote(new, safe=_URI_SAFE), ensure_ascii=False)

    return _GLTF_URI.sub(replace, text)


def _rewrite_glb(data: bytes, edits: dict[str, str]) -> bytes:
    magic, version, _ = _GLB_HEADER.unpack_from(data)
    length, kind = _CHUNK_HEADER.unpack_from(data, 12)
    start = 12 + _CHUNK_HEADER.size
    text = _rewrite_gltf_json(data[start : start + length].decode("utf-8"), edits)
    chunk = text.encode("utf-8")
    chunk += b" " * (-len(chunk) % 4)  # chunks are 4-byte aligned; JSON pads with spaces
    rest = data[start + length :]
    total = 12 + _CHUNK_HEADER.size + len(chunk) + len(rest)
    header = _GLB_HEADER.pack(magic, version, total) + _CHUNK_HEADER.pack(len(chunk), kind)
    return header + chunk + rest


def _rewrite_lines(data: bytes, edits: dict[str, str], mtl: bool) -> bytes:
    """Change file names in `mtllib` (OBJ) or texture (MTL) lines; every other byte stays."""
    lines = data.decode("utf-8", errors="surrogateescape").splitlines(keepends=True)
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        keyword, rest = _split(body.lstrip("﻿"))
        if mtl and keyword.lower() in _TEXTURE_KEYS:
            names = [_texture_name(rest)]
        elif not mtl and keyword == "mtllib" and rest:
            names = _library_names(rest)
        else:
            continue
        for old in names:
            if old in edits and (at := body.rfind(old)) >= 0:
                body = body[:at] + edits[old] + body[at + len(old) :]
        lines[i] = body + line[len(line.rstrip("\r\n")) :]
    return "".join(lines).encode("utf-8", errors="surrogateescape")


# --- applying -----------------------------------------------------------------------------


def _apply(project: Project, changes: list[Change]) -> None:
    """Edits first, then renames, then the trash; on a failure, undo what was done."""
    for c in changes:
        for p in (c.path, c.to):
            if p is not None and not p.resolve().is_relative_to(project.root):
                raise ApiError(f"'{p}' is outside the project folder.")

    undo: list[tuple[str, Path, Any]] = []
    trashed: list[Path] = []
    order = {"edit": 0, "rename": 1, "trash": 2}
    try:
        for c in sorted(changes, key=lambda c: order[c.kind]):
            if c.kind == "edit":
                assert c.content is not None
                original = c.path.read_bytes()
                _write_atomically(c.path, c.content)
                undo.append(("edit", c.path, original))
            elif c.kind == "rename":
                assert c.to is not None
                os.rename(c.path, c.to)
                undo.append(("rename", c.to, c.path))
            else:
                from send2trash import send2trash  # type: ignore[import-untyped]

                send2trash(c.path)
                trashed.append(c.path)
    except Exception as exc:
        for kind, path, back in reversed(undo):
            try:
                if kind == "edit":
                    _write_atomically(path, back)
                else:
                    os.rename(path, back)
            except OSError:
                pass
        if trashed:
            names = ", ".join(project.shown(p) for p in trashed)
            message = f"Couldn't finish the fix: {_why(exc)} ({names} went to the trash.)"
            raise ApiError(message) from exc
        raise ApiError(f"Couldn't finish the fix, so nothing was changed: {_why(exc)}") from exc


def _why(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return f"{exc.filename} is in use or read-only. Close it in other apps and try again."
    if isinstance(exc, OSError):
        return f"{exc.filename}: {exc.strerror or exc}"
    return str(exc)


def _write_atomically(path: Path, content: bytes) -> None:
    tmp = path.with_name(f".assetlint-{os.getpid()}-{path.name}")
    try:
        tmp.write_bytes(content)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
