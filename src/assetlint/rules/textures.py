"""Texture dimensions: powers of two, and a maximum width and height."""

from __future__ import annotations

from collections.abc import Iterator

from assetlint.config import TexturesRuleConfig
from assetlint.model import Asset
from assetlint.readers import ImageInfo
from assetlint.rules.base import Rule


class TexturesRule(Rule[TexturesRuleConfig]):
    id = "textures"
    description = "Textures have power-of-two sizes within the maximum."

    def check(self, asset: Asset, config: TexturesRuleConfig) -> Iterator[str]:
        image = asset.image
        if not isinstance(image, ImageInfo):
            return
        dims = f"{image.width}x{image.height}"

        if config.power_of_two and not (_pow2(image.width) and _pow2(image.height)):
            yield f"{dims} isn't a power of two on each side (e.g. 512, 1024, 2048)"

        largest = config.max_size
        if largest is not None and max(image.width, image.height) > largest:
            yield f"{dims}, over the maximum of {largest}"


def _pow2(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0
