"""What the app's page asks for, as plain functions returning JSON-ready dicts.

The HTTP server only routes requests here, so everything the app does can be
tested without a browser.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from assetlint import __version__
from assetlint.config import ConfigError, find_config, load_config
from assetlint.engine import run
from assetlint.rules import BUILTIN_RULES

STATE_FILE = Path.home() / ".assetlint" / "app.json"
MAX_RECENT = 8


class ApiError(Exception):
    """A problem to show the user, such as a folder that doesn't exist."""


def check(folder: str) -> dict[str, Any]:
    """Check a folder with its assetlint.toml (or the defaults) and return the results."""
    target = existing_folder(folder)
    config_path = find_config(target)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise ApiError(str(exc)) from exc

    result = run(
        target, config, root=config_path.parent if config_path else None, display_root=target
    )
    remember(target)
    findings = [
        {"path": f.path, "rule": f.rule, "severity": f.severity, "message": f.message}
        for f in result.findings
    ]
    from assetlint.app.fixes import Project, fixable  # fixes builds on this module

    project = Project(target, config_path.parent if config_path else target, config)
    return {
        "folder": str(target),
        "config": str(config_path) if config_path else None,
        "files_checked": result.files_checked,
        "errors": result.errors,
        "warnings": result.warnings,
        "findings": findings,
        "fixable": sorted(fixable(project, findings)),
        "rules": [
            {
                "id": rule.id,
                "description": rule.description,
                "severity": getattr(config.rules, rule.id).severity,
            }
            for rule in BUILTIN_RULES
        ],
    }


def info(start_folder: Path | None, can_browse: bool) -> dict[str, Any]:
    return {
        "version": __version__,
        "start_folder": str(start_folder) if start_folder else None,
        "recent": recent(),
        "can_browse": can_browse,
    }


def browse() -> dict[str, Any]:
    """Open the system's folder picker and return the chosen folder, or None if cancelled.

    It runs in its own process: Tk must own the main thread (macOS insists),
    and the server's request threads aren't it.
    """
    script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
        "print(filedialog.askdirectory(title='Choose an asset folder') or '')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    chosen = done.stdout.strip()
    return {"folder": str(Path(chosen)) if chosen else None}


# --- recent folders -----------------------------------------------------------


def recent() -> list[str]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        folders = data.get("recent", [])
    except (OSError, ValueError, AttributeError):
        return []
    return [f for f in folders if isinstance(f, str)][:MAX_RECENT]


def remember(folder: Path) -> None:
    folders = [str(folder), *[f for f in recent() if f != str(folder)]][:MAX_RECENT]
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"recent": folders}, indent=2), encoding="utf-8")
    except OSError:
        pass  # recent folders are a convenience; never fail a check over them


# --- helpers --------------------------------------------------------------------


def existing_folder(folder: str) -> Path:
    if not folder.strip():
        raise ApiError("Choose a folder to check.")
    path = Path(folder.strip().strip('"')).expanduser()
    if not path.exists():
        raise ApiError(f"{path} doesn't exist.")
    if not path.is_dir():
        raise ApiError(f"{path} is a file. Choose the folder it's in.")
    return path.resolve()


def tk_available() -> bool:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    return True
