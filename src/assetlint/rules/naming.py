"""Naming conventions: a pattern for file names and a required prefix per file type."""

from __future__ import annotations

import re
from collections.abc import Iterator

from assetlint.config import NamingRuleConfig
from assetlint.model import Asset
from assetlint.rules.base import Rule

_BLENDER_DUPLICATE_SUFFIX = re.compile(r"\.\d{3}$")


class NamingRule(Rule[NamingRuleConfig]):
    id = "naming"
    description = "File names follow the naming pattern and the prefix for their type."

    def __init__(self, config: NamingRuleConfig) -> None:
        super().__init__(config)
        self._pattern = re.compile(config.pattern)

    def check(self, asset: Asset) -> Iterator[str]:
        stem = asset.stem

        prefix = self.config.prefixes.get(asset.ext)
        if prefix and not stem.startswith(prefix):
            yield f"'{asset.name}' should start with '{prefix}' ({asset.ext} files)"

        if not self._pattern.fullmatch(stem):
            yield f"'{asset.name}' doesn't match the naming pattern{_hint(stem)}"


def _hint(stem: str) -> str:
    """Name the likely cause, so the message says more than 'doesn't match'."""
    if " " in stem:
        return ": it contains a space"
    if _BLENDER_DUPLICATE_SUFFIX.search(stem):
        return f": '{stem[-4:]}' looks like a Blender duplicate suffix"
    return ""
