"""glTF 2.0 (.gltf JSON and .glb binary): triangle count and external file references.

Only the JSON part is read. Each mesh is counted once, however many nodes use it.
"""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from assetlint.readers import MeshInfo, Reference, Unreadable

_GLB_MAGIC = b"glTF"
_CHUNK_JSON = b"JSON"
_URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+:")  # http:, data: ... but not C:

# Primitive modes: 4 triangles, 5 triangle strip, 6 triangle fan. Points and lines count 0.
_TRIANGLES, _STRIP, _FAN = 4, 5, 6


def read_gltf(path: Path) -> MeshInfo | Unreadable:
    try:
        doc = _read_glb_json(path) if path.suffix.lower() == ".glb" else _read_json(path)
    except OSError as exc:
        return Unreadable(f"can't read file: {exc.strerror or exc}")
    if isinstance(doc, Unreadable):
        return doc
    if not isinstance(doc, dict):
        return Unreadable("not a glTF file: the JSON isn't an object")

    asset = doc.get("asset")
    version = asset.get("version") if isinstance(asset, dict) else None
    if not isinstance(version, str):
        return Unreadable("not a glTF file: no asset.version")
    if not version.startswith("2."):
        return Unreadable(f"glTF {version} isn't supported, only 2.x")

    try:
        triangles = _count_triangles(doc)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return Unreadable(f"broken glTF: a mesh points at a missing or invalid accessor ({exc!r})")
    return MeshInfo(triangles=triangles, references=_references(doc, path.parent))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Unreadable(f"not valid glTF JSON: {exc}")


def _read_glb_json(path: Path) -> Any:
    with path.open("rb") as f:
        header = f.read(20)
        if len(header) < 20 or header[:4] != _GLB_MAGIC:
            return Unreadable("not a GLB file: missing the 'glTF' header")
        _, version, length, chunk_length, chunk_type = struct.unpack("<4sIII4s", header)
        if version != 2:
            return Unreadable(f"GLB version {version} isn't supported, only 2")
        actual = path.stat().st_size
        if actual < length:
            return Unreadable(f"truncated: header says {length:,} bytes, the file is {actual:,}")
        if chunk_type != _CHUNK_JSON:
            return Unreadable("broken GLB: the first chunk isn't JSON")
        chunk = f.read(chunk_length)
    if len(chunk) < chunk_length:
        return Unreadable("truncated: the JSON chunk is cut short")
    try:
        return json.loads(chunk)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Unreadable(f"broken GLB: the JSON chunk isn't valid JSON: {exc}")


def _count_triangles(doc: dict[str, Any]) -> int:
    accessors = doc.get("accessors", [])
    total = 0
    for mesh in doc.get("meshes", []):
        for primitive in mesh["primitives"]:
            index = primitive.get("indices")
            if index is None:
                index = primitive["attributes"].get("POSITION")
            if index is None:
                continue
            if not isinstance(index, int) or index < 0:
                raise ValueError(index)
            count = int(accessors[index]["count"])
            mode = primitive.get("mode", _TRIANGLES)
            if mode == _TRIANGLES:
                total += count // 3
            elif mode in (_STRIP, _FAN):
                total += max(count - 2, 0)
    return total


def _references(doc: dict[str, Any], base: Path) -> list[Reference]:
    refs = []
    for key in ("buffers", "images"):
        items = doc.get(key, [])
        if not isinstance(items, list):
            continue
        for item in items:
            uri = item.get("uri") if isinstance(item, dict) else None
            # A GLB's own buffer has no uri; data:, http: and other URIs aren't relative files.
            if not isinstance(uri, str) or _URI_SCHEME.match(uri):
                continue
            refs.append(Reference(raw=unquote(uri), base=base))
    return refs
