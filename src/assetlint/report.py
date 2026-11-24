"""Reports: terminal text, JSON, SARIF 2.1.0, and GitHub Actions annotations.

Only the text report goes through Rich. The others are machine-read and are
built as plain strings, so nothing wraps or styles them.
"""

from __future__ import annotations

import hashlib
import json
from itertools import groupby
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import quote

from rich.console import Console
from rich.markup import escape

from assetlint import __version__
from assetlint.model import Finding, Result, RuleInfo
from assetlint.rules import BUILTIN_RULES

HOMEPAGE = "https://github.com/kaydee001/assetlint"

_SEVERITY_STYLE = {"error": "bold red", "warn": "yellow"}
_SARIF_LEVEL = {"error": "error", "warn": "warning"}


# --- text -------------------------------------------------------------------


def print_text(result: Result, console: Console) -> None:
    rule_width = max((len(f.rule) for f in result.findings), default=0)
    for path, findings in groupby(result.findings, key=lambda f: f.path):
        console.print(f"[bold]{escape(path)}[/bold]")
        for finding in findings:
            style = _SEVERITY_STYLE[finding.severity]
            console.print(
                f"  [{style}]{finding.severity:<5}[/{style}]  "
                f"[dim]{finding.rule:<{rule_width}}[/dim]  {escape(finding.message)}"
            )
        console.print()
    console.print(summary_line(result, markup=True))


def summary_line(result: Result, markup: bool = False) -> str:
    files = _plural(result.files_checked, "file")
    if not result.findings:
        text = f"No problems found in {files}."
        return f"[green]{text}[/green]" if markup else text
    problems = f"Found {_plural(len(result.findings), 'problem')}"
    counts = f"({_plural(result.errors, 'error')}, {_plural(result.warnings, 'warning')})"
    if markup:
        style = "bold red" if result.errors else "yellow"
        problems = f"[{style}]{problems}[/{style}]"
    return f"{problems} {counts} in {files}."


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


# --- JSON -------------------------------------------------------------------


def to_json(result: Result) -> str:
    report = {
        "version": __version__,
        "files_checked": result.files_checked,
        "errors": result.errors,
        "warnings": result.warnings,
        "findings": [
            {"path": f.path, "rule": f.rule, "severity": f.severity, "message": f.message}
            for f in result.findings
        ],
    }
    return json.dumps(report, indent=2) + "\n"


# --- SARIF ------------------------------------------------------------------


def to_sarif(result: Result) -> str:
    """SARIF 2.1.0, as GitHub code scanning reads it."""
    infos = result.rules or _builtin_rules()
    rule_ids = [rule.id for rule in infos]
    rules = [
        {
            "id": rule.id,
            "name": rule.id,
            "shortDescription": {"text": rule.description},
            "helpUri": f"{HOMEPAGE}#{'custom-rules' if rule.custom else 'rules'}",
            "defaultConfiguration": {"level": _SARIF_LEVEL.get(rule.default_severity, "none")},
        }
        for rule in infos
    ]
    log = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "assetlint",
                        "version": __version__,
                        "informationUri": HOMEPAGE,
                        "rules": rules,
                    }
                },
                "results": [_sarif_result(f, rule_ids.index(f.rule)) for f in result.findings],
            }
        ],
    }
    return json.dumps(log, indent=2) + "\n"


def _builtin_rules() -> list[RuleInfo]:
    """For a Result built without the engine (tests, tools): the built-in rules."""
    from assetlint.engine import rule_info

    return [rule_info(rule_cls()) for rule_cls in BUILTIN_RULES]


def _sarif_result(finding: Finding, rule_index: int) -> dict[str, Any]:
    return {
        "ruleId": finding.rule,
        "ruleIndex": rule_index,
        "level": _SARIF_LEVEL[finding.severity],
        "message": {"text": finding.message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": _artifact_location(finding.path),
                    # Assets have no lines; GitHub needs a region to place the alert.
                    "region": {"startLine": 1},
                }
            }
        ],
        # Assets are mostly binary, so GitHub can't fingerprint them from their lines.
        "partialFingerprints": {"assetlintFinding/v1": _fingerprint(finding)},
    }


def _artifact_location(path: str) -> dict[str, str]:
    if PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute():
        drive_path = path if path.startswith("/") else f"/{path}"
        return {"uri": "file://" + quote(drive_path, safe="/:")}
    return {"uri": quote(path, safe="/"), "uriBaseId": "%SRCROOT%"}


def _fingerprint(finding: Finding) -> str:
    key = f"{finding.rule}\0{finding.path}\0{finding.message}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


# --- GitHub Actions ---------------------------------------------------------


def to_github(result: Result) -> str:
    """One workflow command per finding, so GitHub annotates the file in the run and the PR."""
    lines = []
    for f in result.findings:
        command = "error" if f.severity == "error" else "warning"
        props = f"file={_escape_property(f.path)},title={_escape_property(f'assetlint ({f.rule})')}"
        lines.append(f"::{command} {props}::{_escape_data(f.message)}")
    lines.append(summary_line(result))
    return "\n".join(lines) + "\n"


def to_step_summary(result: Result) -> str:
    """Markdown for $GITHUB_STEP_SUMMARY, listing every finding.

    GitHub shows only the first 10 error and 10 warning annotations of a step,
    so the summary is where nothing gets cut.
    """
    lines = ["### assetlint", "", summary_line(result), ""]
    if result.findings:
        lines += ["| File | Rule | Severity | Problem |", "| --- | --- | --- | --- |"]
        for f in result.findings:
            cells = (f"`{f.path}`", f.rule, f.severity, f.message)
            lines.append("| " + " | ".join(_escape_cell(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
