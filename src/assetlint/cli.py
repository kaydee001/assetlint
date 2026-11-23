"""The `assetlint` command.

Exit codes: 0 when no errors were found (warnings are allowed), 1 when at
least one rule reported an error, 2 when the config or arguments are invalid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from assetlint import __version__
from assetlint.config import ConfigError, find_config, load_config
from assetlint.engine import run
from assetlint.report import print_text

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_USAGE = 2

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
) -> None:
    """Check assets against the rules in assetlint.toml."""
    console = Console(highlight=False)
    err_console = Console(stderr=True, highlight=False)

    config_path = config or find_config(path)
    try:
        settings = load_config(config_path)
    except ConfigError as exc:
        err_console.print(f"[bold red]Config error:[/bold red] {exc}", markup=True)
        raise typer.Exit(EXIT_USAGE) from exc

    result = run(path, settings)
    print_text(result, console)
    raise typer.Exit(EXIT_PROBLEMS if result.errors else EXIT_OK)
