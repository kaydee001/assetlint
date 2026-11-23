"""The JSON, SARIF and GitHub reports, and the CLI options that pick them."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from assetlint.cli import EXIT_PROBLEMS, app
from assetlint.model import Finding, Result
from assetlint.report import to_github, to_json, to_sarif, to_step_summary
from assetlint.rules import BUILTIN_RULES

runner = CliRunner()

RESULT = Result(
    files_checked=3,
    findings=[
        Finding("naming", "error", "props/SM_Crate Box.obj", "it contains a space"),
        Finding("textures", "warn", "textures/T_Été,1:2.png", "100x64 isn't a power of two"),
    ],
)


def test_json() -> None:
    report = json.loads(to_json(RESULT))
    assert (report["files_checked"], report["errors"], report["warnings"]) == (3, 1, 1)
    assert report["findings"][0] == {
        "path": "props/SM_Crate Box.obj",
        "rule": "naming",
        "severity": "error",
        "message": "it contains a space",
    }


def test_sarif() -> None:
    log = json.loads(to_sarif(RESULT))
    assert log["version"] == "2.1.0"
    [run] = log["runs"]
    driver = run["tool"]["driver"]
    assert [r["id"] for r in driver["rules"]] == [r.id for r in BUILTIN_RULES]

    first, second = run["results"]
    assert first["ruleId"] == "naming"
    assert driver["rules"][first["ruleIndex"]]["id"] == "naming"
    assert (first["level"], second["level"]) == ("error", "warning")
    location = first["locations"][0]["physicalLocation"]
    assert location["artifactLocation"] == {
        "uri": "props/SM_Crate%20Box.obj",
        "uriBaseId": "%SRCROOT%",
    }
    assert first["partialFingerprints"] != second["partialFingerprints"]


@pytest.mark.parametrize(
    ("path", "uri"),
    [("/home/ci/a b.png", "file:///home/ci/a%20b.png"), ("C:/art/a.png", "file:///C:/art/a.png")],
)
def test_sarif_absolute_paths_become_file_uris(path: str, uri: str) -> None:
    result = Result(1, [Finding("naming", "error", path, "x")])
    [sarif_result] = json.loads(to_sarif(result))["runs"][0]["results"]
    assert sarif_result["locations"][0]["physicalLocation"]["artifactLocation"] == {"uri": uri}


def test_github_annotations_are_escaped() -> None:
    lines = to_github(RESULT).splitlines()
    assert (
        lines[0]
        == "::error file=props/SM_Crate Box.obj,title=assetlint (naming)::it contains a space"
    )
    # `,` and `:` would end the file property early, so they're escaped there.
    assert lines[1].startswith(
        "::warning file=textures/T_Été%2C1%3A2.png,title=assetlint (textures)::"
    )
    assert lines[-1] == "Found 2 problems (1 error, 1 warning) in 3 files."


def test_github_message_newlines_are_escaped() -> None:
    result = Result(1, [Finding("formats", "error", "a.glb", "50% broken\nsecond line")])
    assert to_github(result).splitlines()[0].endswith("::50%25 broken%0Asecond line")


def test_step_summary_lists_every_finding() -> None:
    summary = to_step_summary(RESULT)
    assert "| `props/SM_Crate Box.obj` | naming | error | it contains a space |" in summary
    assert summary.count("\n| `") == 2


# --- CLI --------------------------------------------------------------------


def bad_folder(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    tmp_path = folder
    (tmp_path / "Cube.001.obj").write_text("v 0 0 0\n")
    (tmp_path / "Été.obj").write_text("v 1 0 0\n")
    return tmp_path


@pytest.mark.parametrize("fmt", ["json", "sarif"])
def test_cli_machine_formats_print_valid_json(tmp_path: Path, fmt: str) -> None:
    result = runner.invoke(app, ["check", str(bad_folder(tmp_path)), "--format", fmt])
    assert result.exit_code == EXIT_PROBLEMS
    json.loads(result.stdout)


def test_cli_output_file_is_utf8(tmp_path: Path) -> None:
    out = tmp_path / "out" / "report.json"
    out.parent.mkdir()
    folder = bad_folder(tmp_path / "assets")
    result = runner.invoke(app, ["check", str(folder), "-f", "json", "-o", str(out)])
    assert result.exit_code == EXIT_PROBLEMS
    assert result.stdout == ""
    paths = [f["path"] for f in json.loads(out.read_text(encoding="utf-8"))["findings"]]
    assert any(p.endswith("Cube.001.obj") for p in paths)


def test_cli_text_lines_are_not_wrapped(tmp_path: Path) -> None:
    name = "Cube 1 with a rather long name that would wrap at eighty columns.obj"
    (tmp_path / name).write_text("v 0 0 0\n")
    lines = runner.invoke(app, ["check", str(tmp_path)]).stdout.splitlines()
    expected = f"'{name}' doesn't match the naming pattern: it contains a space"
    assert any(expected in line for line in lines)


def test_cli_github_format_writes_the_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    result = runner.invoke(app, ["check", str(bad_folder(tmp_path / "x")), "-f", "github"])
    assert result.exit_code == EXIT_PROBLEMS
    assert "::error file=x/Cube.001.obj," in result.stdout
    assert "`x/Cube.001.obj`" in summary.read_text(encoding="utf-8")
