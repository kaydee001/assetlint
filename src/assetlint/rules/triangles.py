"""Triangle budget for mesh files (glTF/GLB and OBJ)."""

from __future__ import annotations

from collections.abc import Iterator

from assetlint.config import TrianglesRuleConfig
from assetlint.model import Asset
from assetlint.readers import MeshInfo
from assetlint.rules.base import Rule


class TrianglesRule(Rule[TrianglesRuleConfig]):
    id = "triangles"
    label = "Triangle budget"
    description = "Meshes stay within the triangle budget."

    def check(self, asset: Asset, config: TrianglesRuleConfig) -> Iterator[str]:
        budget = config.max
        mesh = asset.mesh
        if budget is not None and isinstance(mesh, MeshInfo) and mesh.triangles > budget:
            yield f"{mesh.triangles:,} triangles, over the budget of {budget:,}"
