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
from assetlint.model import Asset, Finding, Result, RuleInfo
from assetlint.rules import CustomRule, build_rules
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
    # Custom rules may name types the built-in rules don't check (".blend1" backups, say):
    # find those files too, but only for the custom rules.
    builtin_types = set(config.extensions)
    custom_types = {ext for entry in config.custom for ext in entry.types} - builtin_types
    search = config.model_copy(update={"extensions": sorted(builtin_types | custom_types)})
    assets = [
        replace(asset, shown=display_path(asset.path, display_root))
        for asset in discover(target, search, root)
    ]
    settings = {asset: config.rules_for(asset.rel) for asset in assets}
    rules = build_rules(config)
    result = Result(files_checked=len(assets), rules=[rule_info(rule) for rule in rules])

    def add(rule: Rule[Any], asset: Asset, message: str) -> None:
        rule_config = rule.settings(settings[asset], asset)
        if rule_config is not None:
            result.findings.append(Finding(rule.id, rule_config.severity, asset.display, message))

    for rule in rules:
        for asset in assets:
            if asset.ext not in builtin_types and not isinstance(rule, CustomRule):
                continue
            rule_config = rule.settings(settings[asset], asset)
            if rule_config is None or rule_config.severity == "off":
                continue
            for message in rule.check(asset, rule_config):
                add(rule, asset, message)
        for asset, message in rule.finish():
            add(rule, asset, message)

    result.findings.sort(key=lambda f: (f.path, f.rule, f.message))
    return result


def rule_info(rule: Rule[Any]) -> RuleInfo:
    """A rule's id, description and severity before any config: the built-in default, or the
    severity a custom rule is written with."""
    if isinstance(rule, CustomRule):
        info = RuleInfo(rule.id, rule.description, rule.entry.severity, custom=True)
        return replace(info, label=rule.label)
    severity = getattr(RulesConfig(), rule.id).severity
    return RuleInfo(rule.id, rule.description, severity, label=rule.label or rule.id)
