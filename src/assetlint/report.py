"""Terminal output. JSON and SARIF reporters arrive in v1."""

from __future__ import annotations

from itertools import groupby

from rich.console import Console
from rich.markup import escape

from assetlint.model import Result

_SEVERITY_STYLE = {"error": "bold red", "warn": "yellow"}


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

    files = _plural(result.files_checked, "file")
    if not result.findings:
        console.print(f"[green]No problems found[/green] in {files}.")
        return
    problems = _plural(len(result.findings), "problem")
    counts = f"{_plural(result.errors, 'error')}, {_plural(result.warnings, 'warning')}"
    style = "bold red" if result.errors else "yellow"
    console.print(f"[{style}]Found {problems}[/{style}] ({counts}) in {files}.")


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"
