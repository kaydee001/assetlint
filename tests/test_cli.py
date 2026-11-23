from pathlib import Path

from typer.testing import CliRunner

from assetlint import __version__
from assetlint.cli import EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE, app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == EXIT_OK
    assert __version__ in result.output


def test_good_samples_pass(samples: Path) -> None:
    result = runner.invoke(app, ["check", str(samples / "good")])
    assert result.exit_code == EXIT_OK, result.output
    assert "No problems found in 5 files." in result.output


def test_bad_samples_fail(samples: Path) -> None:
    result = runner.invoke(app, ["check", str(samples / "bad")])
    assert result.exit_code == EXIT_PROBLEMS, result.output
    output = result.output
    assert "Cube.001.obj" in output
    assert "SM_Barrel.obj" not in output
    assert "Found 17 problems (17 errors, 0 warnings) in 17 files." in output


def test_warnings_do_not_fail(tmp_path: Path) -> None:
    (tmp_path / "Cube.001.obj").write_text("v 0 0 0\n")
    (tmp_path / "assetlint.toml").write_text('[rules.naming]\nseverity = "warn"\n')
    result = runner.invoke(app, ["check", str(tmp_path)])
    assert result.exit_code == EXIT_OK, result.output
    assert "1 warning" in result.output


def test_invalid_config_exits_2(tmp_path: Path) -> None:
    (tmp_path / "assetlint.toml").write_text("[rules.naming]\nserverity = 'error'\n")
    result = runner.invoke(app, ["check", str(tmp_path)])
    assert result.exit_code == EXIT_USAGE
    assert "unknown key" in result.output


def test_explicit_config_option(tmp_path: Path) -> None:
    (tmp_path / "Cube.001.obj").write_text("v 0 0 0\n")
    config = tmp_path / "strict.toml"
    config.write_text('[rules.naming]\nseverity = "off"\n')
    result = runner.invoke(app, ["check", str(tmp_path), "--config", str(config)])
    assert result.exit_code == EXIT_OK, result.output
