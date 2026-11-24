"""Duplicates: files with the same content, wherever they are and whatever their names."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterator

from assetlint.config import DuplicatesRuleConfig
from assetlint.model import Asset
from assetlint.rules.base import Rule

_CHUNK = 1 << 20


class DuplicatesRule(Rule[DuplicatesRuleConfig]):
    id = "duplicates"
    label = "Duplicates"
    description = "No two files have the same content."

    def __init__(self) -> None:
        self._by_size: dict[int, list[Asset]] = defaultdict(list)

    def check(self, asset: Asset, config: DuplicatesRuleConfig) -> Iterator[str]:
        if asset.size > 0:  # empty files are the formats rule's business
            self._by_size[asset.size].append(asset)
        return iter(())

    def finish(self) -> Iterator[tuple[Asset, str]]:
        # Only files that share a size can share content, so most files are never hashed.
        for same_size in self._by_size.values():
            if len(same_size) < 2:
                continue
            by_hash: dict[bytes, list[Asset]] = defaultdict(list)
            for asset in same_size:
                by_hash[_digest(asset)].append(asset)
            for copies in by_hash.values():
                if len(copies) < 2:
                    continue
                for asset in copies:
                    others = ", ".join(f"'{a.display}'" for a in copies if a is not asset)
                    yield asset, f"same content as {others}"


def _digest(asset: Asset) -> bytes:
    hasher = hashlib.blake2b()
    with asset.path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            hasher.update(chunk)
    return hasher.digest()
