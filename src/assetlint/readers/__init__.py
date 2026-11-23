"""Readers turn a file into the few facts the rules need.

They read only what they must (a glTF's JSON, an image's header) and never
decode pixels or vertex data, so a check stays fast on large folders. A file
that can't be read comes back as `Unreadable`; only the formats rule reports
it, so one broken file doesn't produce a finding from every rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Unreadable:
    reason: str


@dataclass(frozen=True)
class Reference:
    """A path one file uses to point at another, such as a texture."""

    raw: str  # as written in the file, after percent-decoding for glTF
    base: Path  # the folder the path is relative to
    via: str | None = None  # the in-between file holding it, e.g. an OBJ's .mtl


@dataclass(frozen=True)
class MeshInfo:
    triangles: int
    references: list[Reference] = field(default_factory=list)


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    format: str  # Pillow's format name, e.g. "PNG", "JPEG"


__all__ = ["ImageInfo", "MeshInfo", "Reference", "Unreadable"]
