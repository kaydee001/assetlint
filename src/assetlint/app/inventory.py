"""What's in a checked folder, and the facts behind each problem, for the app's overview.

Everything here reads the Assets the check already built, so files the rules
parsed (meshes, image headers) aren't read again. The command line, CI and the
reports never see this: it's only for the app.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from assetlint.config import Config
from assetlint.model import Asset, Result
from assetlint.readers import ImageInfo, MeshInfo, Unreadable

TOP = 5  # entries in each "largest" list
MESH_TYPES = {".gltf", ".glb", ".obj"}


def inventory(result: Result) -> dict[str, Any]:
    """Totals by file type, the largest files, the heaviest meshes and the largest textures."""
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "size": 0})
    meshes: list[tuple[int, str]] = []
    textures: list[tuple[int, int, int, str]] = []
    unreadable = 0
    total = 0
    for asset in result.assets:
        size = _size(asset)
        total += size
        entry = by_type[asset.ext or "(none)"]
        entry["count"] += 1
        entry["size"] += size
        facts = facts_for(asset)
        if facts.get("unreadable"):
            unreadable += 1
        if "triangles" in facts:
            meshes.append((facts["triangles"], asset.display))
        if "width" in facts:
            textures.append(
                (facts["width"] * facts["height"], facts["width"], facts["height"], asset.display)
            )

    largest = sorted(result.assets, key=_size, reverse=True)[:TOP]
    return {
        "files": len(result.assets),
        "total_size": total,
        "unreadable": unreadable,
        "by_type": sorted(
            ({"type": ext, **counts} for ext, counts in by_type.items()),
            key=lambda t: (-t["count"], t["type"]),
        ),
        "largest_files": [{"path": a.display, "size": _size(a)} for a in largest if _size(a) > 0],
        "heaviest_meshes": [
            {"path": path, "triangles": n} for n, path in sorted(meshes, reverse=True)[:TOP]
        ],
        "largest_textures": [
            {"path": path, "width": w, "height": h}
            for _, w, h, path in sorted(textures, reverse=True)[:TOP]
        ],
    }


def problem_files(result: Result, config: Config) -> dict[str, dict[str, Any]]:
    """For each file with a problem: its size, triangles or dimensions, and for naming problems
    the pattern and prefix that apply to it and a name that would pass."""
    from assetlint.app.fixes import suggest_name  # fixes builds on the api module

    with_problems = {f.path for f in result.findings}
    naming = {f.path for f in result.findings if f.rule == "naming"}
    out: dict[str, dict[str, Any]] = {}
    for asset in result.assets:
        if asset.display not in with_problems:
            continue
        facts = facts_for(asset)
        if asset.display in naming:
            rules = config.rules_for(asset.rel).naming
            facts["naming"] = {
                "pattern": rules.pattern,
                "prefix": rules.prefixes.get(asset.ext, ""),
                "suggested": suggest_name(asset.name, rules),
            }
        out[asset.display] = facts
    return out


def facts_for(asset: Asset) -> dict[str, Any]:
    """Size, and triangles or dimensions when the check already knows them or they're cheap."""
    facts: dict[str, Any] = {"size": _size(asset)}
    if asset.ext in MESH_TYPES:
        mesh = asset.mesh
        if isinstance(mesh, MeshInfo):
            facts["triangles"] = mesh.triangles
        elif isinstance(mesh, Unreadable):
            facts["unreadable"] = True
    else:
        image = asset.image
        if isinstance(image, ImageInfo):
            facts["width"], facts["height"] = image.width, image.height
        elif isinstance(image, Unreadable):
            facts["unreadable"] = True
    return facts


def _size(asset: Asset) -> int:
    try:
        return asset.size
    except OSError:
        return 0  # deleted or locked since the check
