"""Entry point of the packaged Asset Lint app (the double-click .exe)."""

from assetlint.app import serve

if __name__ == "__main__":
    serve(mode="window")
