"""The core: find the assets, run the rules, collect the findings."""

from __future__ import annotations

import os
from collections.abc import Iterator
from fnmatch import fnmatchcase
from pathlib import Path

from assetlint.config import Config
from assetlint.model import Asset, Finding, Result
from assetlint.rules import build_rules


def discover(target: Path, config: Config) -> list[Asset]:
    """List the assets under `target` (a folder or a single file), sorted by path."""
    target = target.resolve()
    if target.is_file():
        return [Asset(path=target, rel=target.name)]
    extensions = set(config.extensions)
    assets = [
        asset
        for asset in _walk(target)
        if asset.ext in extensions and not _excluded(asset.rel, config.exclude)
    ]
    return sorted(assets, key=lambda a: a.rel)


def _walk(root: Path) -> Iterator[Asset]:
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden folders such as .git and .venv.
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            path = Path(dirpath, filename)
            yield Asset(path=path, rel=path.relative_to(root).as_posix())


def _excluded(rel: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(rel, pattern) for pattern in patterns)


def run(target: Path, config: Config) -> Result:
    """Check every asset under `target` against the active rules."""
    rules = build_rules(config)
    assets = discover(target, config)
    result = Result(files_checked=len(assets))

    for rule in rules:
        severity = rule.config.severity
        for asset in assets:
            for message in rule.check(asset):
                result.findings.append(Finding(rule.id, severity, asset.rel, message))
        for asset, message in rule.finish():
            result.findings.append(Finding(rule.id, severity, asset.rel, message))

    result.findings.sort(key=lambda f: (f.path, f.rule, f.message))
    return result
