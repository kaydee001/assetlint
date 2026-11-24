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
    label = "Naming"
    description = "File names follow the naming pattern and the prefix for their type."
    why = "Engine import rules, scripts and search all rely on names that follow one convention."
    how = (
        "Rename it to match the pattern and prefix. "
        "Fix… renames it and updates the files that use it."
    )

    def check(self, asset: Asset, config: NamingRuleConfig) -> Iterator[str]:
        stem = asset.stem

        prefix = config.prefixes.get(asset.ext)
        if prefix and not stem.startswith(prefix):
            yield f"'{asset.name}' should start with '{prefix}' ({asset.ext} files)"

        if not re.fullmatch(config.pattern, stem):  # re caches compiled patterns
            yield f"'{asset.name}' doesn't match the naming pattern{_hint(stem)}"


def _hint(stem: str) -> str:
    """Name the likely cause, so the message says more than 'doesn't match'."""
    if " " in stem:
        return ": it contains a space"
    if _BLENDER_DUPLICATE_SUFFIX.search(stem):
        return f": '{stem[-4:]}' looks like a Blender duplicate suffix"
    return ""
