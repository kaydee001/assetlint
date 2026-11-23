"""The rules editor: presets, and saving assetlint.toml without losing what people wrote."""

from __future__ import annotations

from pathlib import Path

import pytest

from assetlint.app import editor
from assetlint.app.api import ApiError
from assetlint.config import CONFIG_FILENAME, Config, PresetName, load_config
from assetlint.presets import PRESETS

HAND_WRITTEN = """\
# Our studio's asset rules. Ask Sam before loosening budgets.
preset = "unreal"

[rules.triangles]
max = 5000  # mobile target

[[overrides]]
paths = ["characters/"]  # heroes get more
rules.triangles.max = 20000
"""


def project(tmp_path: Path, text: str | None = HAND_WRITTEN) -> Path:
    if text is not None:
        (tmp_path / CONFIG_FILENAME).write_text(text, encoding="utf-8")
    return tmp_path


def saved(tmp_path: Path) -> str:
    return (tmp_path / CONFIG_FILENAME).read_text(encoding="utf-8")


# --- presets ------------------------------------------------------------------


def test_preset_names_match_the_presets() -> None:
    assert set(PresetName.__args__) == set(PRESETS)  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_preset_is_a_valid_config(name: str) -> None:
    Config.model_validate({"preset": name})


def test_own_rules_win_over_the_preset() -> None:
    config = Config.model_validate(
        {"preset": "unreal", "rules": {"naming": {"prefixes": {".fbx": "SK_"}}}}
    )
    assert config.rules.naming.prefixes[".fbx"] == "SK_"  # own setting
    assert config.rules.naming.prefixes[".png"] == "T_"  # from the preset
    assert config.rules.textures.max_size == 8192


# --- loading ------------------------------------------------------------------


def test_load_shows_what_the_file_sets_and_what_applies(tmp_path: Path) -> None:
    data = editor.load_settings(str(project(tmp_path)))
    assert (data["exists"], data["preset"]) == (True, "unreal")
    rules = {r["id"]: r for r in data["rules"]}
    triangles = {f["key"]: f for f in rules["triangles"]["fields"]}
    assert triangles["max"] == {**triangles["max"], "value": 5000, "set": True}
    textures = {f["key"]: f for f in rules["textures"]["fields"]}
    assert textures["max_size"]["value"] == 8192 and not textures["max_size"]["set"]
    assert rules["textures"]["severity"] == {"value": "error", "set": False}  # from the preset
    assert data["overrides"] == [{"paths": ["characters/"], "rules": {"triangles": {"max": 20000}}}]


def test_load_without_a_config_points_at_a_new_file(tmp_path: Path) -> None:
    data = editor.load_settings(str(project(tmp_path, None)))
    assert data["exists"] is False
    assert data["path"] == str(tmp_path.resolve() / CONFIG_FILENAME)


# --- saving -------------------------------------------------------------------


def test_saving_nothing_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    editor.save_settings(str(project(tmp_path)), {})
    assert saved(tmp_path) == HAND_WRITTEN


def test_saving_unchanged_overrides_keeps_their_comments(tmp_path: Path) -> None:
    folder = str(project(tmp_path))
    overrides = editor.load_settings(folder)["overrides"]
    editor.save_settings(folder, {"overrides": overrides})
    assert saved(tmp_path) == HAND_WRITTEN


def test_changing_one_value_keeps_every_comment(tmp_path: Path) -> None:
    editor.save_settings(str(project(tmp_path)), {"rules": {"triangles": {"max": 8000}}})
    text = saved(tmp_path)
    assert "max = 8000" in text
    for comment in ("# Our studio's asset rules", "# heroes get more"):
        assert comment in text
    assert load_config(tmp_path / CONFIG_FILENAME).rules.triangles.max == 8000


def test_adding_and_removing_settings(tmp_path: Path) -> None:
    folder = str(project(tmp_path))
    editor.save_settings(
        folder,
        {
            "preset": "godot",
            "exclude": ["build/"],
            "rules": {
                "triangles": {"max": None},  # back to the default
                "size": {"max": "50MB", "max_by_type": {".png": "8MB"}},
                "duplicates": {"severity": "off"},
            },
        },
    )
    config = load_config(tmp_path / CONFIG_FILENAME)
    assert config.preset == "godot"
    assert config.exclude == ["build/"]
    assert config.rules.triangles.max is None
    assert (config.rules.size.max, config.rules.size.max_by_type) == (
        50_000_000,
        {".png": 8_000_000},
    )
    assert config.rules.duplicates.severity == "off"
    assert '"50MB"' in saved(tmp_path)  # written as the user typed it


def test_removing_the_preset(tmp_path: Path) -> None:
    editor.save_settings(str(project(tmp_path)), {"preset": None})
    assert "preset" not in saved(tmp_path)
    assert load_config(tmp_path / CONFIG_FILENAME).preset is None


def test_replacing_overrides(tmp_path: Path) -> None:
    editor.save_settings(
        str(project(tmp_path)),
        {
            "overrides": [
                {"paths": ["legacy/", " "], "rules": {"naming": {"severity": "off"}}},
                {
                    "paths": ["fx/"],
                    "rules": {"textures": {"power_of_two": False, "max_size": None}},
                },
            ]
        },
    )
    config = load_config(tmp_path / CONFIG_FILENAME)
    assert [o.paths for o in config.overrides] == [["legacy/"], ["fx/"]]
    assert config.rules_for("legacy/a.obj").naming.severity == "off"
    assert config.rules_for("fx/a.png").textures.power_of_two is False


def test_a_new_file_is_created_with_a_header(tmp_path: Path) -> None:
    result = editor.save_settings(str(project(tmp_path, None)), {"preset": "unity"})
    assert result["created"] is True
    text = saved(tmp_path)
    assert text.startswith("# Asset Lint settings")
    assert load_config(tmp_path / CONFIG_FILENAME).preset == "unity"


def test_an_invalid_change_is_refused_and_the_file_is_untouched(tmp_path: Path) -> None:
    folder = str(project(tmp_path))
    with pytest.raises(ApiError, match=r"rules.triangles.max"):
        editor.save_settings(folder, {"rules": {"triangles": {"max": -5}}})
    with pytest.raises(ApiError, match=r"rules.naming.pattern"):
        editor.save_settings(folder, {"rules": {"naming": {"pattern": "[unclosed"}}})
    with pytest.raises(ApiError, match="Unknown rule"):
        editor.save_settings(folder, {"rules": {"nope": {"max": 1}}})
    assert saved(tmp_path) == HAND_WRITTEN
    assert not list(tmp_path.glob(".assetlint-*"))  # no temp files left behind


def test_the_config_in_a_parent_folder_is_the_one_edited(tmp_path: Path) -> None:
    sub = project(tmp_path) / "props"
    sub.mkdir()
    result = editor.save_settings(str(sub), {"rules": {"triangles": {"max": 100}}})
    assert result["path"] == str(tmp_path.resolve() / CONFIG_FILENAME)
    assert not (sub / CONFIG_FILENAME).exists()
