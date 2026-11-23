"""Formats: only allowed file types, and each file really is what its extension says."""

from __future__ import annotations

from collections.abc import Iterator

from assetlint.config import FormatsRuleConfig
from assetlint.model import Asset
from assetlint.readers import ImageInfo, Unreadable
from assetlint.readers.image import PILLOW_FORMATS
from assetlint.rules.base import Rule

# The first bytes of formats no reader opens. Types not listed here (.fbx, .usd)
# have no single dependable signature and are only checked for being empty.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".blend": (b"BLENDER", b"\x28\xb5\x2f\xfd", b"\x1f\x8b"),  # plain, zstd, gzip
    ".exr": (b"\x76\x2f\x31\x01",),
    ".hdr": (b"#?RADIANCE", b"#?RGBE"),
    ".dds": (b"DDS ",),
    ".ktx2": (b"\xabKTX 20\xbb\r\n\x1a\n",),
    ".usda": (b"#usda",),
    ".usdc": (b"PXR-USDC",),
    ".usdz": (b"PK\x03\x04",),
}
_LFS_POINTER = b"version https://git-lfs.github.com/spec/"
_SIGNATURE_BYTES = max(len(sig) for sigs in _SIGNATURES.values() for sig in sigs)


class FormatsRule(Rule[FormatsRuleConfig]):
    id = "formats"
    description = "Only allowed file types, and no empty, corrupt or misnamed files."

    def check(self, asset: Asset) -> Iterator[str]:
        allowed = self.config.allowed
        if allowed is not None and asset.ext not in allowed:
            yield f"{asset.ext} files aren't allowed (allowed: {', '.join(allowed)})"
            return
        if asset.size == 0:
            yield "the file is empty"
            return
        with asset.path.open("rb") as f:
            head = f.read(max(_SIGNATURE_BYTES, len(_LFS_POINTER)))
        if head.startswith(_LFS_POINTER):
            # Common in CI: actions/checkout leaves LFS files as pointers unless `lfs: true`.
            yield "this is a Git LFS pointer, not the file; fetch LFS files first (git lfs pull)"
            return

        for parsed in (asset.mesh, asset.image):
            if isinstance(parsed, Unreadable):
                yield parsed.reason
                return

        image = asset.image
        if isinstance(image, ImageInfo) and image.format not in PILLOW_FORMATS[asset.ext]:
            yield f"it's a {image.format} image with a {asset.ext} extension"

        signatures = _SIGNATURES.get(asset.ext)
        if signatures and not head.startswith(signatures):
            yield f"doesn't look like a {asset.ext} file (its first bytes are wrong)"
