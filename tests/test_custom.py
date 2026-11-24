"""Custom rules: [[custom]] entries in assetlint.toml, run by the CLI, CI and the app alike."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from make_samples import image_bytes, obj_text
from typer.testing import CliRunner

from assetlint.app import api, editor
from assetlint.cli import EXIT_OK, EXIT_PROBLEMS, EXIT_USAGE, app
from assetlint.config import Config, ConfigError, RulesConfig, load_config
from assetlint.engine import run

runner = CliRunner()


@pytest.fixture(autouse=True)
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "STATE_FILE", tmp_path / "state" / "app.json")


def write(root: Path, rel: str, content: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    return path


def findings(root: Path, toml: str) -> list[tuple[str, str, str, str]]:
    config_path = write(root, "assetlint.toml", toml)
    result = run(root, load_config(config_path), root=root, display_root=root)
    builtin = set(RulesConfig.model_fields)  # only the custom rules' findings
    return [
        (f.path, f.rule, f.severity, f.message) for f in result.findings if f.rule not in builtin
    ]


def custom(**entry: Any) -> Config:
    return Config.model_validate({"custom": [{"id": "my-rule", **entry}]})


# --- the config ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"id": "Hero Textures", "square": True}, "lowercase letters"),
        ({"id": "naming", "square": True}, "is a built-in rule"),
        ({"id": "x"}, "at least one requirement"),
        ({"id": "x", "min_triangles": 10, "max_triangles": 5}, "larger than"),
        ({"id": "x", "name_pattern": "("}, "not a valid regular expression"),
        ({"id": "x", "requires": ["T_{name}.png"]}, "unknown {name}"),
        ({"id": "x", "requires": ["/textures/a.png"]}, "relative"),
        ({"id": "x", "requires": ["C:\\textures\\a.png"]}, "relative"),
        ({"id": "x", "max_size": "lots"}, "size"),
        ({"id": "x", "square": True, "colour": "red"}, "Extra inputs"),
    ],
)
def test_invalid_custom_rules_are_explained(entry: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Config.model_validate({"custom": [entry]})


def test_custom_rule_ids_are_unique() -> None:
    with pytest.raises(ValueError, match="two custom rules have the id 'a'"):
        Config.model_validate(
            {"custom": [{"id": "a", "square": True}, {"id": "a", "square": True}]}
        )


def test_types_are_normalized() -> None:
    assert custom(types=["PNG", ".Tga"], square=True).custom[0].types == [".png", ".tga"]


# --- what the rules check ------------------------------------------------------------------


def test_forbidden_files(tmp_path: Path) -> None:
    write(tmp_path, "export/T_Rock.psd", b"8BPS")
    write(tmp_path, "source/T_Rock.psd", b"8BPS")
    toml = (
        '[[custom]]\nid = "no-psd-in-export"\npaths = ["export/"]\n'
        'types = [".psd"]\nforbidden = true\n'
    )
    assert findings(tmp_path, toml) == [
        ("export/T_Rock.psd", "no-psd-in-export", "error", "'T_Rock.psd' isn't allowed here")
    ]


def test_name_pattern_size_and_severity(tmp_path: Path) -> None:
    write(tmp_path, "chars/hero_arm.obj", obj_text(2))
    write(tmp_path, "props/hero_arm.obj", obj_text(2))
    toml = (
        '[[custom]]\nid = "char-names"\nseverity = "warn"\npaths = ["chars/"]\n'
        'name_pattern = "CH_[A-Z][A-Za-z]+"\nmax_size = 10\n'
    )
    assert findings(tmp_path, toml) == [
        (
            "chars/hero_arm.obj",
            "char-names",
            "warn",
            "'hero_arm.obj' doesn't match the pattern CH_[A-Z][A-Za-z]+",
        ),
        ("chars/hero_arm.obj", "char-names", "warn", "64 bytes, over the 10 bytes limit"),
    ]


def test_triangle_range(tmp_path: Path) -> None:
    write(tmp_path, "SM_Low.obj", obj_text(2))
    write(tmp_path, "SM_High.obj", obj_text(50))
    write(tmp_path, "T_Wood.png", image_bytes(4, 4))  # not a mesh: skipped
    toml = '[[custom]]\nid = "lod0"\nmin_triangles = 10\nmax_triangles = 40\n'
    assert [m for *_, m in findings(tmp_path, toml)] == [
        "50 triangles, over the maximum of 40",
        "2 triangles, under the minimum of 10",
    ]


def test_texture_size_and_square(tmp_path: Path) -> None:
    write(tmp_path, "T_Wide.png", image_bytes(64, 32))
    write(tmp_path, "T_Tiny.png", image_bytes(8, 8))
    write(tmp_path, "T_Ok.png", image_bytes(32, 32))
    toml = '[[custom]]\nid = "ui"\nmin_texture_size = 16\nmax_texture_size = 32\nsquare = true\n'
    assert [(p, m) for p, _, _, m in findings(tmp_path, toml)] == [
        ("T_Tiny.png", "8x8, under the minimum of 16"),
        ("T_Wide.png", "64x32 isn't square"),
        ("T_Wide.png", "64x32, over the maximum of 32"),
    ]


def test_required_companion_files(tmp_path: Path) -> None:
    write(tmp_path, "SM_Crate.obj", obj_text())
    write(tmp_path, "T_Crate_D.png", image_bytes(4, 4))
    write(tmp_path, "SM_Barrel.obj", obj_text(2))
    write(tmp_path, "SM_Chair.obj", obj_text(3))
    write(tmp_path, "t_chair_d.png", image_bytes(4, 4, color=(1, 2, 3)))
    toml = (
        '[rules.naming]\nseverity = "off"\nprefixes = { ".obj" = "SM_" }\n\n'
        '[[custom]]\nid = "mesh-has-texture"\ntypes = [".obj"]\nrequires = ["T_{base}_D.png"]\n'
    )
    assert [(p, m) for p, _, _, m in findings(tmp_path, toml)] == [
        ("SM_Barrel.obj", "needs 'T_Barrel_D.png' next to it, which doesn't exist"),
        (
            "SM_Chair.obj",
            "needs 'T_Chair_D.png', but it's 't_chair_d.png' on disk; the case must match on Linux",
        ),
    ]


def test_base_without_a_prefix_is_the_stem(tmp_path: Path) -> None:
    write(tmp_path, "rock.obj", obj_text())
    write(tmp_path, "rock.obj.meta", "guid: 1\n")
    toml = '[[custom]]\nid = "unity-meta"\nrequires = ["{stem}.obj.meta", "{base}.mtl"]\n'
    assert [m for *_, m in findings(tmp_path, toml)] == [
        "needs 'rock.mtl' next to it, which doesn't exist"
    ]


def test_off_and_exclude_still_apply(tmp_path: Path) -> None:
    write(tmp_path, "build/SM_A.obj", obj_text())
    write(tmp_path, "SM_B.obj", obj_text())
    toml = (
        'exclude = ["build/"]\n\n[[custom]]\nid = "a"\nforbidden = true\n\n'
        '[[custom]]\nid = "b"\nseverity = "off"\nforbidden = true\n'
    )
    assert findings(tmp_path, toml) == [("SM_B.obj", "a", "error", "'SM_B.obj' isn't allowed here")]


# --- reports and the CLI -------------------------------------------------------------------


def test_cli_reports_custom_rules_in_every_format(tmp_path: Path) -> None:
    write(tmp_path, "SM_A.obj", obj_text())
    write(
        tmp_path,
        "assetlint.toml",
        '[[custom]]\nid = "no-obj"\ndescription = "Export glTF, not OBJ"\nforbidden = true\n',
    )
    text = runner.invoke(app, ["check", str(tmp_path)])
    assert text.exit_code == EXIT_PROBLEMS, text.output
    assert "no-obj" in text.output

    sarif = runner.invoke(app, ["check", str(tmp_path), "--format", "sarif"])
    assert sarif.exit_code == EXIT_PROBLEMS, sarif.output
    run_ = json.loads(sarif.output)["runs"][0]
    rules = run_["tool"]["driver"]["rules"]
    index = run_["results"][0]["ruleIndex"]
    assert rules[index]["id"] == "no-obj"
    assert rules[index]["shortDescription"]["text"] == "Export glTF, not OBJ"
    assert [r["id"] for r in rules][:7] == [
        "formats", "size", "naming", "duplicates", "triangles", "textures", "references",
    ]  # fmt: skip

    github = runner.invoke(app, ["check", str(tmp_path), "--format", "github"])
    assert "title=assetlint (no-obj)" in github.output

    as_json = runner.invoke(app, ["check", str(tmp_path), "--format", "json"])
    assert json.loads(as_json.output)["findings"][0]["rule"] == "no-obj"


def test_cli_explains_a_bad_custom_rule(tmp_path: Path) -> None:
    write(tmp_path, "assetlint.toml", '[[custom]]\nid = "x"\n')
    result = runner.invoke(app, ["check", str(tmp_path)])
    assert result.exit_code == EXIT_USAGE
    assert "at least one requirement" in result.output


def test_a_folder_without_custom_rules_is_unchanged(tmp_path: Path) -> None:
    write(tmp_path, "SM_A.obj", obj_text())
    assert runner.invoke(app, ["check", str(tmp_path)]).exit_code == EXIT_OK


# --- the app -------------------------------------------------------------------------------


def test_check_lists_custom_rules(tmp_path: Path) -> None:
    write(tmp_path, "SM_A.obj", obj_text())
    write(
        tmp_path,
        "assetlint.toml",
        '[[custom]]\nid = "no-obj"\nseverity = "warn"\nforbidden = true\n',
    )
    data = api.check(str(tmp_path))
    rule = data["rules"][-1]
    assert (rule["id"], rule["severity"], rule["custom"]) == ("no-obj", "warn", True)
    assert data["warnings"] == 1


def test_editor_round_trip_keeps_comments(tmp_path: Path) -> None:
    toml = (
        '# team rules\n[[custom]]\n# hero textures are 4K\nid = "hero"\n'
        'paths = ["characters/hero/"]\nmax_size = "8MB"\n'
    )
    write(tmp_path, "assetlint.toml", toml)
    loaded = editor.load_settings(str(tmp_path))
    assert loaded["custom"] == [{"id": "hero", "paths": ["characters/hero/"], "max_size": "8MB"}]
    assert [f["key"] for f in loaded["custom_fields"]][:2] == ["paths", "types"]

    editor.save_settings(str(tmp_path), {"custom": loaded["custom"]})
    assert (tmp_path / "assetlint.toml").read_text() == toml  # unchanged: comments stay


def test_editor_adds_edits_and_removes_custom_rules(tmp_path: Path) -> None:
    write(tmp_path, "assetlint.toml", "# keep me\n[rules.triangles]\nmax = 500\n")
    rule = {
        "id": "ui",
        "severity": "warn",
        "paths": ["ui/", ""],
        "types": [],
        "square": True,
        "forbidden": False,
        "name_pattern": None,
    }
    editor.save_settings(str(tmp_path), {"custom": [rule]})
    text = (tmp_path / "assetlint.toml").read_text()
    assert text.startswith("# keep me\n")
    assert tomllib.loads(text)["custom"] == [
        {"id": "ui", "severity": "warn", "paths": ["ui/"], "square": True}
    ]

    editor.save_settings(str(tmp_path), {"custom": []})
    assert "custom" not in tomllib.loads((tmp_path / "assetlint.toml").read_text())


def test_editor_refuses_an_invalid_custom_rule(tmp_path: Path) -> None:
    write(tmp_path, "assetlint.toml", "")
    with pytest.raises(api.ApiError, match="at least one requirement"):
        editor.save_settings(str(tmp_path), {"custom": [{"id": "x"}]})
    with pytest.raises(api.ApiError, match="needs an id"):
        editor.save_settings(str(tmp_path), {"custom": [{"square": True}]})
    assert (tmp_path / "assetlint.toml").read_text() == ""


def test_load_config_reports_custom_errors_with_their_place(tmp_path: Path) -> None:
    path = write(tmp_path, "assetlint.toml", '[[custom]]\nid = "x"\nsquare = true\nshape = 1\n')
    with pytest.raises(ConfigError, match=r"custom\.0\.shape: unknown key"):
        load_config(path)


def test_custom_rules_can_target_types_the_built_in_rules_skip(tmp_path: Path) -> None:
    """.blend1 isn't a checked type, so only the custom rule sees it: no naming
    problem for the space in the name, no format check."""
    write(tmp_path, "My Scene.blend1", b"BLENDER")
    write(tmp_path, "SM_Ok.obj", obj_text())
    config_path = write(
        tmp_path,
        "assetlint.toml",
        '[[custom]]\nid = "no-backups"\ntypes = [".blend1"]\nforbidden = true\n',
    )
    result = run(tmp_path, load_config(config_path), root=tmp_path, display_root=tmp_path)
    assert [(f.path, f.rule) for f in result.findings] == [("My Scene.blend1", "no-backups")]
