"""File size: a maximum for every file, or per file type."""

from __future__ import annotations

from collections.abc import Iterator

from assetlint.config import SizeRuleConfig
from assetlint.model import Asset
from assetlint.rules.base import Rule


class SizeRule(Rule[SizeRuleConfig]):
    id = "size"
    description = "Files stay under the size limit for their type."

    def check(self, asset: Asset, config: SizeRuleConfig) -> Iterator[str]:
        limit = config.max_by_type.get(asset.ext, config.max)
        if limit is not None and asset.size > limit:
            size_text, limit_text = human_size(asset.size), human_size(limit)
            if size_text == limit_text:  # rounding hides the difference; show exact bytes
                size_text, limit_text = f"{asset.size:,} bytes", f"{limit:,}-byte"
            yield f"{size_text}, over the {limit_text} limit"


def human_size(size: int) -> str:
    """Sizes in powers of 1000, as file managers show them: 1,500,000 -> '1.5 MB'."""
    for unit, scale in (("GB", 10**9), ("MB", 10**6), ("KB", 10**3)):
        if size >= scale:
            return f"{size / scale:.1f} {unit}".replace(".0 ", " ")
    return f"{size} bytes"
