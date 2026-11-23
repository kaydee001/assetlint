"""Per-folder overrides, and which folder path patterns are relative to."""

from pathlib import Path

import pytest
from make_samples import obj_text

from assetlint.config import CONFIG_FILENAME, Config, ConfigError, load_config
from assetlint.engine import run


def config_from(text: str, tmp_path: Path) -> Config:
    path = tmp_path / CONFIG_FILENAME
    path.write_text(text, encoding="utf-8")
    return load_config(path)


BUDGETS = """
[rules.triangles]
max = 10

[[overrides]]
paths = ["characters/"]
rules.triangles.max = 100

[[overrides]]
paths = ["characters/bosses/*"]
rules.triangles.max = 1000
"""


def test_overrides_apply_to_matching_paths_and_the_last_match_wins(tmp_path: Path) -> None:
    config = config_from(BUDGETS, tmp_path)
    assert config.rules_for("props/SM_Crate.obj").triangles.max == 10
    assert config.rules_for("characters/SM_Hero.obj").triangles.max == 100
    assert config.rules_for("characters/bosses/SM_Dragon.obj").triangles.max == 1000


def test_an_override_changes_only_the_keys_it_sets(tmp_path: Path) -> None:
    config = config_from(
        """
        [rules.triangles]
        severity = "warn"
        max = 10
        [rules.naming.prefixes]
        ".obj" = "SM_"
        [[overrides]]
        paths = ["fx/*"]
        rules.triangles.max = 50
        rules.naming.prefixes = { ".png" = "FX_" }
        """,
        tmp_path,
    )
    rules = config.rules_for("fx/smoke.obj")
    assert (rules.triangles.severity, rules.triangles.max) == ("warn", 50)
    # Tables merge: the override adds a prefix and keeps the one from [rules].
    assert rules.naming.prefixes == {".obj": "SM_", ".png": "FX_"}


def test_an_override_can_switch_a_rule_off(tmp_path: Path) -> None:
    config = config_from(
        '[[overrides]]\npaths = ["legacy/"]\nrules.naming.severity = "off"\n', tmp_path
    )
    (tmp_path / "legacy").mkdir()
    (tmp_path / "legacy" / "Cube.001.obj").write_text(obj_text(comment="legacy"))
    (tmp_path / "Cube.001.obj").write_text(obj_text(comment="new"))
    result = run(tmp_path, config, root=tmp_path, display_root=tmp_path)
    assert [f.path for f in result.findings] == ["Cube.001.obj"]


def test_budget_override_in_a_run(tmp_path: Path) -> None:
    config = config_from(BUDGETS, tmp_path)
    for rel, triangles in [("props/SM_A.obj", 50), ("characters/SM_B.obj", 50)]:
        (tmp_path / rel).parent.mkdir(exist_ok=True)
        (tmp_path / rel).write_text(obj_text(triangles, comment=rel))
    result = run(tmp_path, config, root=tmp_path, display_root=tmp_path)
    assert [(f.path, f.rule) for f in result.findings] == [("props/SM_A.obj", "triangles")]


def test_duplicates_are_found_across_folders_with_different_settings(tmp_path: Path) -> None:
    config = config_from(BUDGETS, tmp_path)
    for rel in ("props/SM_A.obj", "characters/SM_A.obj"):
        (tmp_path / rel).parent.mkdir(exist_ok=True)
        (tmp_path / rel).write_text(obj_text(comment="same"))
    result = run(tmp_path, config, root=tmp_path, display_root=tmp_path)
    assert {f.path for f in result.findings if f.rule == "duplicates"} == {
        "props/SM_A.obj",
        "characters/SM_A.obj",
    }


@pytest.mark.parametrize(
    ("text", "location"),
    [
        ("[[overrides]]\npaths = []\n", "overrides.0.paths"),
        (
            '[[overrides]]\npaths = ["a/"]\nrules.triangles.max = 0\n',
            "overrides.0.rules.triangles.max",
        ),
        ('[[overrides]]\npaths = ["a/"]\nrules.triangle.max = 5\n', "overrides.0.rules.triangle"),
        ('[[overrides]]\npaths = ["a/"]\nrule.naming.severity = "off"\n', "overrides.0.rule"),
    ],
)
def test_bad_overrides_name_their_location(tmp_path: Path, text: str, location: str) -> None:
    with pytest.raises(ConfigError, match=location.replace(".", r"\.")):
        config_from(text, tmp_path)


def test_patterns_are_relative_to_the_config_folder(tmp_path: Path) -> None:
    """Checking a subfolder must not change what `exclude` and `overrides` mean."""
    config = config_from('exclude = ["props/old/"]\n', tmp_path)
    old = tmp_path / "props" / "old"
    old.mkdir(parents=True)
    (old / "Cube.001.obj").write_text(obj_text(comment="old"))
    (tmp_path / "props" / "Cube.002.obj").write_text(obj_text(comment="new"))
    result = run(tmp_path / "props", config, root=tmp_path, display_root=tmp_path)
    assert [f.path for f in result.findings] == ["props/Cube.002.obj"]
