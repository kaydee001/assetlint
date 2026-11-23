from pathlib import Path

import pytest

from assetlint.config import (
    CONFIG_FILENAME,
    Config,
    ConfigError,
    find_config,
    load_config,
    parse_size,
)


def write_config(directory: Path, text: str) -> Path:
    path = directory / CONFIG_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


def test_no_config_gives_defaults() -> None:
    config = load_config(None)
    assert config == Config()
    assert config.rules.naming.severity == "error"
    assert ".glb" in config.extensions


def test_find_config_walks_up_to_parent(tmp_path: Path) -> None:
    path = write_config(tmp_path, "")
    nested = tmp_path / "props" / "crates"
    nested.mkdir(parents=True)
    assert find_config(nested) == path.resolve()


def test_find_config_from_a_file_looks_in_its_folder(tmp_path: Path) -> None:
    path = write_config(tmp_path, "")
    asset = tmp_path / "SM_Crate.glb"
    asset.touch()
    assert find_config(asset) == path.resolve()


def test_loads_rule_settings(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        extensions = ["GLB", "png"]
        [rules.naming]
        severity = "warn"
        pattern = "[A-Z].*"
        [rules.naming.prefixes]
        glb = "SM_"
        """,
    )
    config = load_config(path)
    assert config.extensions == [".glb", ".png"]
    assert config.rules.naming.severity == "warn"
    assert config.rules.naming.prefixes == {".glb": "SM_"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('[rules.naming]\nserverity = "error"', "rules.naming.serverity: unknown key"),
        ('[rules.namng]\nseverity = "error"', "rules.namng: unknown key"),
        ('[rules.naming]\nseverity = "fatal"', "rules.naming.severity"),
        ('[rules.naming]\npattern = "[unclosed"', "not a valid regular expression"),
        ("this is = = not toml", "invalid TOML"),
    ],
)
def test_bad_config_gives_a_clear_error(tmp_path: Path, text: str, expected: str) -> None:
    path = write_config(tmp_path, text)
    with pytest.raises(ConfigError, match=expected.replace(".", r"\.").replace("[", r"\[")):
        load_config(path)


@pytest.mark.parametrize(
    ("value", "size"),
    [
        (2048, 2048),
        ("512", 512),
        ("50MB", 50_000_000),
        ("1.5 kb", 1500),
        ("2MiB", 2 * 1024 * 1024),
        ("1GiB", 1024**3),
    ],
)
def test_parse_size(value: object, size: int) -> None:
    assert parse_size(value) == size


@pytest.mark.parametrize("value", ["", "big", "5 parsecs", "-1MB", 0, -5, True, 1.5])
def test_parse_size_rejects_nonsense(value: object) -> None:
    with pytest.raises(ValueError):
        parse_size(value)


def test_loads_the_core_rule_settings(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
        [rules.formats]
        allowed = ["GLB", "png"]
        [rules.size]
        max = "10MB"
        max_by_type = { png = "2MiB" }
        [rules.triangles]
        max = 5000
        [rules.textures]
        max_size = 2048
        power_of_two = false
        [rules.duplicates]
        severity = "off"
        """,
    )
    rules = load_config(path).rules
    assert rules.formats.allowed == [".glb", ".png"]
    assert (rules.size.max, rules.size.max_by_type) == (10_000_000, {".png": 2 * 1024 * 1024})
    assert rules.triangles.max == 5000
    assert (rules.textures.max_size, rules.textures.power_of_two) == (2048, False)
    assert rules.duplicates.severity == "off"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('[rules.size]\nmax = "lots"', "rules.size.max"),
        ("[rules.triangles]\nmax = 0", "rules.triangles.max"),
        ("[rules.textures]\nmax_size = -1", "rules.textures.max_size"),
    ],
)
def test_bad_limits_are_rejected(tmp_path: Path, text: str, expected: str) -> None:
    with pytest.raises(ConfigError, match=expected.replace(".", r"\.")):
        load_config(write_config(tmp_path, text))
