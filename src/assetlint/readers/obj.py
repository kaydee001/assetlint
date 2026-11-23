"""Wavefront OBJ: triangle count, material libraries (.mtl) and the textures they use."""

from __future__ import annotations

from pathlib import Path

from assetlint.readers import MeshInfo, Reference, Unreadable

# .mtl statements that name a texture file.
_TEXTURE_KEYS = {
    "map_ka", "map_kd", "map_ks", "map_ke", "map_ns", "map_d", "map_bump", "bump",
    "disp", "decal", "refl", "norm", "map_pr", "map_pm", "map_ps", "map_rma", "map_orm",
}  # fmt: skip
# Texture options and how many values each takes. -o, -s and -t take one to three numbers.
_OPTION_ARGS = {
    "-blendu": 1, "-blendv": 1, "-bm": 1, "-boost": 1, "-cc": 1, "-clamp": 1,
    "-imfchan": 1, "-mm": 2, "-texres": 1, "-type": 1, "-o": 3, "-s": 3, "-t": 3,
}  # fmt: skip
_VARIABLE_ARGS = {"-o", "-s", "-t"}
_SNIFF_BYTES = 8192


def read_obj(path: Path) -> MeshInfo | Unreadable:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return Unreadable(f"can't read file: {exc.strerror or exc}")
    if b"\x00" in data[:_SNIFF_BYTES]:
        return Unreadable("looks like a binary file, not OBJ text")

    triangles = 0
    libraries: list[str] = []
    for line in data.decode("utf-8-sig", errors="replace").splitlines():
        keyword, rest = _split(line)
        if keyword == "f":
            corners = len(rest.split())
            if corners >= 3:
                triangles += corners - 2  # a polygon with n corners is n - 2 triangles
        elif keyword == "mtllib" and rest:
            libraries.extend(_library_names(rest))

    base = path.parent
    refs: list[Reference] = []
    for library in libraries:
        refs.append(Reference(raw=library, base=base))
        refs.extend(_mtl_textures(base, library))
    return MeshInfo(triangles=triangles, references=refs)


def _split(line: str) -> tuple[str, str]:
    """A statement's keyword and the rest; OBJ and MTL allow tabs as well as spaces."""
    parts = line.split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1].strip() if len(parts) > 1 else ""


def _library_names(rest: str) -> list[str]:
    """`mtllib` may list several files, but exporters also write one name with spaces."""
    parts = rest.split()
    if len(parts) > 1 and all(p.lower().endswith(".mtl") for p in parts):
        return parts
    return [rest]


def _mtl_textures(base: Path, library: str) -> list[Reference]:
    mtl = base / library.replace("\\", "/")
    try:
        text = mtl.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []  # missing or unreadable: the references rule reports the .mtl itself
    mtl_base = mtl.parent
    refs = []
    for line in text.splitlines():
        keyword, rest = _split(line)
        if keyword.lower() in _TEXTURE_KEYS and (name := _texture_name(rest)):
            refs.append(Reference(raw=name, base=mtl_base, via=library))
    return refs


def _texture_name(rest: str) -> str:
    """The file name after any options: `-s 2 2 1 -bm 0.5 wood floor.png` -> `wood floor.png`."""
    tokens = rest.split()
    i = 0
    while i < len(tokens) and tokens[i].lower() in _OPTION_ARGS:
        option = tokens[i].lower()
        i += 1
        if option in _VARIABLE_ARGS:
            taken = 0
            while taken < 3 and i < len(tokens) and _is_number(tokens[i]):
                i += 1
                taken += 1
        else:
            i += _OPTION_ARGS[option]
    return " ".join(tokens[i:])


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True
