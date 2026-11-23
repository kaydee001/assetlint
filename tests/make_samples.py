"""Builders for small test assets, and the script that writes samples/.

Regenerate the sample folders with:

    uv run python tests/make_samples.py

Each file in samples/bad breaks exactly the rules listed for it in
tests/test_samples.py, and every file in samples/good passes.
"""

from __future__ import annotations

import base64
import io
import json
import random
import shutil
import struct
from pathlib import Path
from typing import Any

from PIL import Image

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


# --- builders ---------------------------------------------------------------


def obj_text(triangles: int = 1, mtllib: str | None = None, comment: str = "") -> str:
    """An OBJ with `triangles` separate triangles (a quad face counts as 2)."""
    lines = [f"# {comment}"] if comment else []
    if mtllib:
        lines.append(f"mtllib {mtllib}")
    for i in range(triangles):
        lines += [f"v {i} 0 0", f"v {i} 1 0", f"v {i} 0 1"]
    lines += [f"f {3 * i + 1} {3 * i + 2} {3 * i + 3}" for i in range(triangles)]
    return "\n".join(lines) + "\n"


def gltf_doc(
    triangles: int = 1, images: list[str] | None = None, buffer_uri: str | None = None
) -> tuple[dict[str, Any], bytes]:
    """A glTF 2.0 document with one non-indexed triangle mesh, and its binary buffer."""
    corners = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
    vertices = [(float(i), y, z) for i in range(triangles) for y, z in corners]
    data = b"".join(struct.pack("<3f", *v) for v in vertices)
    buffer: dict[str, Any] = {"byteLength": len(data)}
    if buffer_uri:
        buffer["uri"] = buffer_uri
    doc: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "assetlint samples"},
        "buffers": [buffer],
        "bufferViews": [{"buffer": 0, "byteLength": len(data)}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [float(max(triangles - 1, 0)), 1.0, 1.0],
            }
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if images:
        doc["images"] = [{"uri": uri} for uri in images]
    return doc, data


def glb_bytes(doc: dict[str, Any], binary: bytes = b"") -> bytes:
    """Pack a glTF document and its buffer into a GLB file."""
    json_chunk = json.dumps(doc).encode()
    json_chunk += b" " * (-len(json_chunk) % 4)
    chunks = struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
    if binary:
        binary += b"\x00" * (-len(binary) % 4)
        chunks += struct.pack("<I4s", len(binary), b"BIN\x00") + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def image_bytes(
    width: int, height: int, fmt: str = "PNG", color: tuple[int, int, int] = (128, 96, 64)
) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, fmt)
    return out.getvalue()


def noise_png(width: int, height: int, seed: int) -> bytes:
    """A PNG that doesn't compress, for size tests."""
    rng = random.Random(seed)
    image = Image.frombytes("RGB", (width, height), rng.randbytes(width * height * 3))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


# --- the sample folders -----------------------------------------------------


def _write(root: Path, rel: str, content: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_bytes(content.encode())  # bytes, so line endings are \n on every OS
    else:
        path.write_bytes(content)


def make_good(root: Path) -> None:
    _write(root, "notes.txt", "Not an asset type, so assetlint skips this file.\n")
    _write(root, "SM_Crate.obj", obj_text(12, mtllib="SM_Crate.mtl", comment="good crate"))
    _write(root, "SM_Crate.mtl", "newmtl crate\nmap_Kd -s 1 1 1 textures/T_Crate_D.png\n")
    _write(root, "textures/T_Crate_D.png", image_bytes(64, 64, color=(150, 110, 60)))
    doc, data = gltf_doc(20)
    _write(root, "SM_Rock.glb", glb_bytes(doc, data))
    doc, data = gltf_doc(8, images=["T_Lamp_E.jpg"], buffer_uri="SM_Lamp.bin")
    _write(root, "SM_Lamp.gltf", json.dumps(doc, indent=2) + "\n")
    _write(root, "SM_Lamp.bin", data)
    _write(root, "T_Lamp_E.jpg", image_bytes(128, 64, "JPEG", color=(250, 230, 160)))


def make_bad(root: Path) -> None:
    # naming
    _write(root, "Cube.001.obj", obj_text(comment="Blender duplicate suffix"))
    _write(root, "SM_Crate Box.obj", obj_text(comment="space in the name"))
    _write(root, "Crate_D.png", image_bytes(32, 32, color=(10, 20, 30)))  # no T_ prefix
    _write(root, "SM_Barrel.obj", obj_text(comment="this one is fine"))
    # formats
    _write(root, "SM_Rock.fbx", b"Kaydara FBX Binary  \x00\x1a\x00")  # .fbx isn't allowed
    _write(root, "T_Fake_D.png", image_bytes(32, 32, "JPEG", color=(40, 50, 60)))
    doc, data = gltf_doc(4)
    _write(root, "SM_Broken.glb", glb_bytes(doc, data)[:-40])  # cut short
    # size
    _write(root, "T_Noise_D.png", noise_png(256, 256, seed=7))
    # duplicates
    _write(root, "SM_Pot.obj", obj_text(2, comment="a pot"))
    _write(root, "copies/SM_Pot.obj", obj_text(2, comment="a pot"))
    # triangles
    _write(root, "SM_Dense.obj", obj_text(600, comment="over the budget"))
    # textures
    _write(root, "T_Odd_D.png", image_bytes(100, 64, color=(70, 80, 90)))
    _write(root, "T_Big_D.png", image_bytes(2048, 2048, color=(90, 100, 110)))
    # references
    _write(root, "SM_Chair.obj", obj_text(comment="texture case mismatch", mtllib="SM_Chair.mtl"))
    _write(root, "SM_Chair.mtl", "newmtl chair\nmap_Kd textures/t_chair_d.png\n")
    _write(root, "textures/T_Chair_D.png", image_bytes(64, 64, color=(120, 130, 140)))
    doc, data = gltf_doc(2, images=["T_Table_D.png"])  # the texture was never added
    embedded = base64.b64encode(data).decode()
    doc["buffers"][0]["uri"] = f"data:application/octet-stream;base64,{embedded}"
    _write(root, "SM_Table.gltf", json.dumps(doc, indent=2) + "\n")
    stool = obj_text(comment="absolute path", mtllib=r"C:\Users\artist\Desktop\stool.mtl")
    _write(root, "SM_Stool.obj", stool)


def main() -> None:
    for name, make in (("good", make_good), ("bad", make_bad)):
        folder = SAMPLES / name
        shutil.rmtree(folder, ignore_errors=True)
        make(folder)
        print(f"wrote {folder}")


if __name__ == "__main__":
    main()
