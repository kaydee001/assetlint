"""Ready-made rule sets for common engines, chosen with `preset = "..."` in assetlint.toml.

A preset is a starting point: its settings sit under [rules], so anything set
in [rules] or [[overrides]] wins over it.
"""

from __future__ import annotations

from typing import Any

_MESHES = [".fbx", ".obj", ".glb", ".gltf", ".blend"]
_TEXTURES = [".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".psd", ".exr", ".dds"]

PRESETS: dict[str, dict[str, Any]] = {
    "unreal": {
        "label": "Unreal Engine",
        "description": (
            "Prefixes from the widely used Unreal style guide (Allar's ue5-style-guide): "
            "SM_ for meshes, T_ for textures, PascalCase names. Textures must be powers "
            "of two, up to 8192, for mipmaps and streaming."
        ),
        "rules": {
            "naming": {
                "pattern": "[A-Z]{1,3}_[A-Z][A-Za-z0-9]*(_[A-Za-z0-9]+)*",
                "prefixes": {
                    **{ext: "SM_" for ext in _MESHES},
                    **{ext: "T_" for ext in _TEXTURES},
                },
            },
            "textures": {"severity": "error", "power_of_two": True, "max_size": 8192},
        },
    },
    "unity": {
        "label": "Unity",
        "description": (
            "Unity has no official naming convention; this follows common practice: "
            "PascalCase names without spaces or prefixes. Non-power-of-two textures warn."
        ),
        "rules": {
            "naming": {"pattern": "[A-Z][A-Za-z0-9]*(_[A-Za-z0-9]+)*"},
            "textures": {"severity": "warn", "power_of_two": True, "max_size": 8192},
        },
    },
    "godot": {
        "label": "Godot",
        "description": (
            "Godot's style guide asks for snake_case file and folder names, "
            "e.g. crate_wood.glb. Non-power-of-two textures warn."
        ),
        "rules": {
            "naming": {"pattern": "[a-z0-9]+(_[a-z0-9]+)*"},
            "textures": {"severity": "warn", "power_of_two": True, "max_size": 8192},
        },
    },
}
