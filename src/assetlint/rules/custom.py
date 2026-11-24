"""Custom rules: the ones a team writes as [[custom]] entries in assetlint.toml."""

from __future__ import annotations

import re
from collections.abc import Iterator

from assetlint.config import Config, CustomRuleConfig, RulesConfig
from assetlint.model import Asset
from assetlint.readers import ImageInfo, MeshInfo
from assetlint.rules.base import Rule
from assetlint.rules.references import ReferencesRule
from assetlint.rules.size import human_size


class CustomRule(Rule[CustomRuleConfig]):
    def __init__(self, entry: CustomRuleConfig, config: Config | None = None) -> None:
        self.entry = entry
        self.id = entry.id
        self.label = entry.id
        self.description = entry.description or f"Custom rule '{entry.id}'."
        self._config = config or Config()
        self._locator = ReferencesRule()  # finds files by listing folders, so case counts

    def settings(self, rules: RulesConfig, asset: Asset) -> CustomRuleConfig | None:
        return self.entry if self.entry.covers(asset.rel, asset.ext) else None

    def check(self, asset: Asset, config: CustomRuleConfig) -> Iterator[str]:
        if config.forbidden:
            yield f"'{asset.name}' isn't allowed here"
            return
        if config.name_pattern and not re.fullmatch(config.name_pattern, asset.stem):
            yield f"'{asset.name}' doesn't match the pattern {config.name_pattern}"
        if config.max_size is not None and asset.size > config.max_size:
            yield f"{human_size(asset.size)}, over the {human_size(config.max_size)} limit"
        yield from _triangles(asset, config)
        yield from _texture(asset, config)
        for template in config.requires:
            yield from self._required(asset, template)

    def _required(self, asset: Asset, template: str) -> Iterator[str]:
        wanted = template.format(stem=asset.stem, base=self._base(asset))
        found, on_disk = self._locator.locate(asset.path.parent, wanted.replace("\\", "/"))
        if not found:
            yield f"needs '{wanted}' next to it, which doesn't exist"
        elif on_disk is not None:
            yield f"needs '{wanted}', but it's '{on_disk}' on disk; the case must match on Linux"

    def _base(self, asset: Asset) -> str:
        """The name without extension and without its naming prefix: SM_Crate -> Crate."""
        prefix = self._config.rules_for(asset.rel).naming.prefixes.get(asset.ext, "")
        if prefix and asset.stem.startswith(prefix) and len(asset.stem) > len(prefix):
            return asset.stem[len(prefix) :]
        return asset.stem


def _triangles(asset: Asset, config: CustomRuleConfig) -> Iterator[str]:
    if config.min_triangles is None and config.max_triangles is None:
        return
    mesh = asset.mesh
    if not isinstance(mesh, MeshInfo):
        return  # not a mesh we read, or unreadable: the formats rule reports that
    n = mesh.triangles
    if config.max_triangles is not None and n > config.max_triangles:
        yield f"{n:,} triangles, over the maximum of {config.max_triangles:,}"
    if config.min_triangles is not None and n < config.min_triangles:
        yield f"{n:,} triangles, under the minimum of {config.min_triangles:,}"


def _texture(asset: Asset, config: CustomRuleConfig) -> Iterator[str]:
    if config.min_texture_size is None and config.max_texture_size is None and not config.square:
        return
    image = asset.image
    if not isinstance(image, ImageInfo):
        return
    w, h = image.width, image.height
    if config.max_texture_size is not None and max(w, h) > config.max_texture_size:
        yield f"{w}x{h}, over the maximum of {config.max_texture_size}"
    if config.min_texture_size is not None and min(w, h) < config.min_texture_size:
        yield f"{w}x{h}, under the minimum of {config.min_texture_size}"
    if config.square and w != h:
        yield f"{w}x{h} isn't square"
