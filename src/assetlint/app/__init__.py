"""The Asset Lint app: a local web page over the same engine and assetlint.toml as the CLI."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from assetlint.app.server import AppServer


def serve(start_folder: Path | None = None, port: int = 0, open_browser: bool = True) -> None:
    server = AppServer(port=port, start_folder=start_folder)
    print(f"Asset Lint is running at {server.url}", flush=True)
    print("Keep this window open while you use it. Press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = ["AppServer", "serve"]
