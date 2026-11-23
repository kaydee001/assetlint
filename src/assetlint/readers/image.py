"""Image size and format from the file header, through Pillow. Pixels are never decoded."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError

from assetlint.readers import ImageInfo, Unreadable

# Pillow's name for each format it reads that we check. Other texture types
# (.exr, .hdr, .ktx2, .dds) are left out: Pillow can't read them, or not all of them.
PILLOW_FORMATS: dict[str, set[str]] = {
    ".png": {"PNG"},
    ".jpg": {"JPEG", "MPO"},  # MPO: a JPEG with extra frames, as phone cameras save
    ".jpeg": {"JPEG", "MPO"},
    ".tga": {"TGA"},
    ".tif": {"TIFF"},
    ".tiff": {"TIFF"},
    ".psd": {"PSD"},
}


def read_image(path: Path) -> ImageInfo | Unreadable:
    # Only the header is read, so the decompression-bomb limit doesn't apply.
    # Passing it would stop a 20k texture being reported as too large.
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(path) as image:
            return ImageInfo(width=image.width, height=image.height, format=image.format or "")
    except UnidentifiedImageError:
        return Unreadable("not a readable image")
    except (OSError, SyntaxError, ValueError) as exc:
        return Unreadable(f"broken image: {exc}")
    finally:
        Image.MAX_IMAGE_PIXELS = previous
