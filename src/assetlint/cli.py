"""The `assetlint` command.

Exit codes: 0 when no errors were found (warnings are allowed), 1 when at
least one rule reported an error, 2 when the config or arguments are invalid.
"""

from __future__ import annotations

import io
import os
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from assetlint import __version__
from assetlint.config import ConfigError, find_config, load_config
from assetlint.engine import run
from assetlint.model import Result
from assetlint.report import print_text, to_github, to_json, to_sarif, to_step_summary

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_USAGE = 2


class OutputFormat(StrEnum):
    text = "text"
    json = "json"
    sarif = "sarif"
    github = "github"  # GitHub Actions annotations, plus the step summary


app = typer.Typer(
    help="Lint 3D asset folders: naming, budgets and formats.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"assetlint {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_print_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """Lint 3D asset folders: naming, budgets and formats."""


@app.command()
def check(
    path: Annotated[
        Path,
        typer.Argument(exists=True, help="Folder or file to check.", show_default=True),
    ] = Path("."),
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            exists=True,
            dir_okay=False,
            help="Config file. Default: the nearest assetlint.toml in PATH or its parents.",
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Report format.", case_sensitive=False),
    ] = OutputFormat.text,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", dir_okay=False, help="Write the report to this file (UTF-8)."
        ),
    ] = None,
) -> None:
    """Check assets against the rules in assetlint.toml."""
    err_console = Console(stderr=True, highlight=False)

    config_path = config or find_config(path)
    try:
        settings = load_config(config_path)
    except ConfigError as exc:
        err_console.print(f"[bold red]Config error:[/bold red] {exc}", markup=True)
        raise typer.Exit(EXIT_USAGE) from exc

    root = config_path.resolve().parent if config_path else None
    result = run(path, settings, root=root)
    _report(result, output_format, output)
    raise typer.Exit(EXIT_PROBLEMS if result.errors else EXIT_OK)


def _report(result: Result, output_format: OutputFormat, output: Path | None) -> None:
    if output_format is OutputFormat.text:
        if output is None:
            # soft_wrap: long lines stay whole in CI logs instead of wrapping at 80 columns.
            print_text(result, Console(highlight=False, soft_wrap=True))
            return
        with output.open("w", encoding="utf-8") as f:
            print_text(result, Console(file=f, highlight=False, soft_wrap=True, no_color=True))
        return

    text = {
        OutputFormat.json: to_json,
        OutputFormat.sarif: to_sarif,
        OutputFormat.github: to_github,
    }[output_format](result)
    if output is None:
        _write_stdout(text)
    else:
        output.write_text(text, encoding="utf-8")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if output_format is OutputFormat.github and summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(to_step_summary(result))


def _write_stdout(text: str) -> None:
    # A piped Windows stdout may be cp1252: escape what it can't encode rather than crash.
    stream = sys.stdout
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(errors="backslashreplace")
    stream.write(text)
    stream.flush()
