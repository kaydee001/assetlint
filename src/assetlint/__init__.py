"""Asset Lint: a headless linter for 3D asset folders."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("assetlint")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
