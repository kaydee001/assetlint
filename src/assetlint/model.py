"""The data that flows through a check: assets in, findings out."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Literal

from assetlint.readers import ImageInfo, MeshInfo, Unreadable
from assetlint.readers.gltf import read_gltf
from assetlint.readers.image import PILLOW_FORMATS, read_image
from assetlint.readers.obj import read_obj

FindingSeverity = Literal["error", "warn"]


@dataclass(frozen=True)
class Asset:
    """One file to check."""

    path: Path  # absolute path on disk
    rel: str  # relative to the root (the config's folder); patterns match this
    shown: str = ""  # as reports show it; the engine fills it in, else `rel`

    @property
    def display(self) -> str:
        return self.shown or self.rel

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def ext(self) -> str:
        return self.path.suffix.lower()

    # The cached properties below read the file once, on first use, and keep the
    # result on this Asset: one parse per file per run, however many rules ask.
    # (cached_property writes to __dict__ directly, so it works on a frozen dataclass.)

    @cached_property
    def size(self) -> int:
        return self.path.stat().st_size

    @cached_property
    def mesh(self) -> MeshInfo | Unreadable | None:
        """Triangles and file references, or None when this isn't a mesh type we read."""
        if self.ext in (".gltf", ".glb"):
            return read_gltf(self.path)
        if self.ext == ".obj":
            return read_obj(self.path)
        return None

    @cached_property
    def image(self) -> ImageInfo | Unreadable | None:
        """Size and format, or None when this isn't an image type we read."""
        return read_image(self.path) if self.ext in PILLOW_FORMATS else None


@dataclass(frozen=True)
class Finding:
    """One problem a rule found in one asset."""

    rule: str
    severity: FindingSeverity
    path: str  # Asset.rel
    message: str


@dataclass(frozen=True)
class RuleInfo:
    """A rule that ran, for reports that list rules (SARIF) and the app."""

    id: str
    description: str
    default_severity: str  # "error", "warn" or "off"
    custom: bool = False


@dataclass
class Result:
    files_checked: int = 0
    findings: list[Finding] = field(default_factory=list)
    rules: list[RuleInfo] = field(default_factory=list)  # the engine fills it

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warn")
