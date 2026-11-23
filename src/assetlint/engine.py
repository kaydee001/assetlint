"""The core: find the assets, run the rules, collect the findings.

Two kinds of path are in play:
- `Asset.rel` is relative to the root (the config file's folder, or the checked
  folder when there is no config). `exclude` and `overrides` patterns match it,
  so they mean the same thing wherever the check is started from.
- `Finding.path` is what reports show: relative to the display folder (the
  GitHub workspace in Actions, else the current folder), so editors and GitHub
  can open the file.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

from assetlint.config import Config, RulesConfig, path_matches
from assetlint.model import Asset, Finding, Result
from assetlint.rules import build_rules
from assetlint.rules.base import Rule


def discover(target: Path, config: Config, root: Path | None = None) -> list[Asset]:
    """List the assets under `target` (a folder or a single file), sorted by path."""
    target = target.resolve()
    folder = target if target.is_dir() else target.parent
    root = root.resolve() if root else folder
    if not folder.is_relative_to(root):
        root = folder  # an explicit --config from elsewhere: patterns are relative to the target
    if target.is_file():
        return [Asset(path=target, rel=target.relative_to(root).as_posix())]
    extensions = set(config.extensions)
    assets = [
        asset
        for asset in _walk(target, root)
        if asset.ext in extensions and not any(path_matches(asset.rel, p) for p in config.exclude)
    ]
    return sorted(assets, key=lambda a: a.rel)


def _walk(target: Path, root: Path) -> Iterator[Asset]:
    for dirpath, dirnames, filenames in os.walk(target):
        # Skip hidden folders such as .git and .venv.
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            path = Path(dirpath, filename)
            yield Asset(path=path, rel=path.relative_to(root).as_posix())


def display_path(path: Path, display_root: Path) -> str:
    """`path` relative to `display_root` with forward slashes, or absolute when outside it."""
    try:
        return path.relative_to(display_root).as_posix()
    except ValueError:
        return path.as_posix()


def default_display_root() -> Path:
    workspace = os.environ.get("GITHUB_WORKSPACE")
    return Path(workspace).resolve() if workspace else Path.cwd().resolve()


def run(
    target: Path,
    config: Config,
    root: Path | None = None,
    display_root: Path | None = None,
) -> Result:
    """Check every asset under `target` against the active rules."""
    display_root = display_root.resolve() if display_root else default_display_root()
    assets = [
        replace(asset, shown=display_path(asset.path, display_root))
        for asset in discover(target, config, root)
    ]
    settings = {asset: config.rules_for(asset.rel) for asset in assets}
    result = Result(files_checked=len(assets))

    def add(rule: Rule[Any], asset: Asset, message: str) -> None:
        severity = _rule_config(settings[asset], rule).severity
        result.findings.append(Finding(rule.id, severity, asset.display, message))

    for rule in build_rules():
        for asset in assets:
            rule_config = _rule_config(settings[asset], rule)
            if rule_config.severity == "off":
                continue
            for message in rule.check(asset, rule_config):
                add(rule, asset, message)
        for asset, message in rule.finish():
            add(rule, asset, message)

    result.findings.sort(key=lambda f: (f.path, f.rule, f.message))
    return result


def _rule_config(rules: RulesConfig, rule: Rule[Any]) -> Any:
    return getattr(rules, rule.id)
