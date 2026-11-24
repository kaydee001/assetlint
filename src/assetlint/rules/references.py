"""References: the textures, buffers and .mtl files a mesh points at exist, with portable paths."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from assetlint.config import ReferencesRuleConfig
from assetlint.model import Asset
from assetlint.readers import MeshInfo, Reference
from assetlint.rules.base import Rule

# C:\..., C:/..., \\server\share, /home/... : absolute on some OS, so broken everywhere else.
_ABSOLUTE = re.compile(r"^([A-Za-z]:[\\/]|[\\/])")


class ReferencesRule(Rule[ReferencesRuleConfig]):
    id = "references"
    label = "Linked files"
    description = "Files a mesh refers to exist, with relative paths that work on every OS."
    why = (
        "A mesh pointing at a missing file, an absolute path or the wrong case "
        "shows up untextured on other machines."
    )
    how = (
        "Use relative paths with forward slashes and matching case. Fix… repairs slashes and case."
    )

    def __init__(self) -> None:
        self._listings: dict[Path, list[str] | None] = {}

    def check(self, asset: Asset, config: ReferencesRuleConfig) -> Iterator[str]:
        mesh = asset.mesh
        if not isinstance(mesh, MeshInfo):
            return
        for ref in mesh.references:
            yield from self._check_reference(ref)

    def _check_reference(self, ref: Reference) -> Iterator[str]:
        what = f"references '{ref.raw}'" + (f" (in '{ref.via}')" if ref.via else "")
        if _ABSOLUTE.match(ref.raw):
            yield f"{what}, an absolute path; use a path relative to the file"
            return
        if "\\" in ref.raw:
            yield f"{what}, with backslashes, which only work on Windows; use '/'"

        found, on_disk = self.locate(ref.base, ref.raw.replace("\\", "/"))
        if not found:
            yield f"{what}, which doesn't exist"
        elif on_disk is not None:
            yield f"{what}, but it's '{on_disk}' on disk; the case must match on Linux"

    def locate(self, base: Path, rel: str) -> tuple[bool, str | None]:
        """Find `rel` under `base` by listing folders, not `Path.exists()`, because
        Windows and macOS ignore case and would hide a mismatch that breaks on Linux.
        Returns (found, the path as spelled on disk when its case differs)."""
        current = base
        spelled: list[str] = []
        case_differs = False
        for part in rel.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                current = current.parent
                spelled.append(part)
                continue
            names = self._listing(current)
            if names is None:
                return False, None
            if part not in names:
                matches = [n for n in names if n.lower() == part.lower()]
                if not matches:
                    return False, None
                part, case_differs = matches[0], True
            current = current / part
            spelled.append(part)
        return True, ("/".join(spelled) if case_differs else None)

    def _listing(self, folder: Path) -> list[str] | None:
        if folder not in self._listings:
            try:
                self._listings[folder] = os.listdir(folder)
            except OSError:
                self._listings[folder] = None
        return self._listings[folder]
