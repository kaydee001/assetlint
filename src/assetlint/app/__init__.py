"""The Asset Lint app: a small desktop window over the same engine and assetlint.toml as the CLI.

The screens are HTML served by a local server (see server.py) and shown in a
native window by pywebview, which uses the web view the OS already has (Edge
WebView2 on Windows, WebKit on macOS), so no browser is bundled. Without
pywebview installed, the same screens open in the default browser instead.
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from typing import Literal

from assetlint.app.server import AppServer

Mode = Literal["window", "browser", "none"]
INSTALL_HINT = 'For the app window, install the app extra: pip install "assetlint[app]"'


def serve(start_folder: Path | None = None, port: int = 0, mode: Mode = "window") -> None:
    server = AppServer(port=port, start_folder=start_folder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if mode == "window":
            if _open_window(server):
                return
            print(f"{INSTALL_HINT}\nOpening it in your browser instead.", flush=True)
            mode = "browser"
        print(f"Asset Lint is running at {server.url}", flush=True)
        print("Keep this window open while you use it. Press Ctrl+C to stop.", flush=True)
        if mode == "browser":
            webbrowser.open(server.url)
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


def _open_window(server: AppServer) -> bool:
    """Show the app in a native window until it's closed. False if pywebview isn't installed."""
    try:
        import webview
    except ImportError:
        return False
    window = webview.create_window(
        "Asset Lint",
        server.url,
        width=1280,
        height=860,
        min_size=(900, 600),
        background_color="#17181A",
        text_select=True,
    )
    server.window = window
    webview.start()  # returns when the window is closed
    return True


__all__ = ["AppServer", "Mode", "serve"]
