"""Build the Asset Lint desktop app as a single double-click file.

    uv run --extra app --with pyinstaller python packaging/build_app.py

Writes dist/AssetLint.exe on Windows (dist/AssetLint on Linux, dist/AssetLint.app
on macOS). Build on the OS you're building for: PyInstaller doesn't cross-compile.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ICON = HERE / "build" / "assetlint.ico"


def make_icon() -> Path:
    """The app icon: the amber cube from the app's header, drawn at 256 px."""
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=48, fill=(23, 24, 26, 255))
    c, r = size / 2, 84
    top, bottom = (c, c - r), (c, c + r)
    upper_left, upper_right = (c - r * 0.87, c - r / 2), (c + r * 0.87, c - r / 2)
    lower_left, lower_right = (c - r * 0.87, c + r / 2), (c + r * 0.87, c + r / 2)
    amber, dim = (232, 163, 61, 255), (232, 163, 61, 140)
    width = 14
    outline = [top, upper_right, lower_right, bottom, lower_left, upper_left, top]
    draw.line(outline, fill=amber, width=width, joint="curve")
    draw.line([upper_left, (c, c), upper_right], fill=dim, width=width, joint="curve")
    draw.line([(c, c), bottom], fill=dim, width=width)
    ICON.parent.mkdir(parents=True, exist_ok=True)
    image.save(ICON, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return ICON


def main() -> None:
    import PyInstaller.__main__

    icon = make_icon()
    PyInstaller.__main__.run(
        [
            str(HERE / "launch.py"),
            "--name=AssetLint",
            "--onefile",
            "--windowed",  # no console window behind the app
            f"--icon={icon}",
            "--collect-data=assetlint",  # the app's HTML, CSS and JS
            "--collect-submodules=send2trash",  # it picks its trash backend per OS at run time
            f"--distpath={ROOT / 'dist'}",
            f"--workpath={HERE / 'build'}",
            f"--specpath={HERE / 'build'}",
            "--noconfirm",
            "--clean",
        ]
    )
    suffix = ".exe" if sys.platform == "win32" else ".app" if sys.platform == "darwin" else ""
    print(f"\nBuilt {ROOT / 'dist' / ('AssetLint' + suffix)}")


if __name__ == "__main__":
    main()
