from pathlib import Path

import pytest

from assetlint.config import Config, NamingRuleConfig, RulesConfig
from assetlint.engine import discover, run


def touch(root: Path, *rels: str) -> None:
    for rel in rels:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def write_objs(root: Path, *rels: str) -> None:
    """Small, readable OBJ files with different content, so only naming can fail."""
    for rel in rels:
        (root / rel).write_text(f"# {rel}\nv 0 0 0\n")


def rels(root: Path, config: Config) -> list[str]:
    return [asset.rel for asset in discover(root, config)]


def test_discover_filters_by_extension_and_sorts(tmp_path: Path) -> None:
    touch(tmp_path, "props/b.glb", "props/a.PNG", "readme.md", "a.obj")
    assert rels(tmp_path, Config()) == ["a.obj", "props/a.PNG", "props/b.glb"]


def test_discover_skips_hidden_folders(tmp_path: Path) -> None:
    touch(tmp_path, ".git/objects/x.png", ".venv/lib/y.glb", "z.glb")
    assert rels(tmp_path, Config()) == ["z.glb"]


def test_discover_applies_exclude_patterns(tmp_path: Path) -> None:
    touch(tmp_path, "build/out.glb", "props/old_backup.glb", "props/crate.glb")
    config = Config(exclude=["build/*", "*_backup.*"])
    assert rels(tmp_path, config) == ["props/crate.glb"]


def test_discover_a_single_file(tmp_path: Path) -> None:
    touch(tmp_path, "Cube.001.glb")
    assert rels(tmp_path / "Cube.001.glb", Config()) == ["Cube.001.glb"]


def test_run_reports_findings_with_rule_and_severity(tmp_path: Path) -> None:
    write_objs(tmp_path, "ok.obj", "Cube.001.obj")
    config = Config(rules=RulesConfig(naming=NamingRuleConfig(severity="warn")))
    result = run(tmp_path, config, display_root=tmp_path)
    assert result.files_checked == 2
    [finding] = result.findings
    assert (finding.rule, finding.severity, finding.path) == ("naming", "warn", "Cube.001.obj")
    assert (result.errors, result.warnings) == (0, 1)


def test_rule_switched_off_reports_nothing(tmp_path: Path) -> None:
    write_objs(tmp_path, "Cube.001.obj")
    result = run(tmp_path, Config(rules=RulesConfig(naming=NamingRuleConfig(severity="off"))))
    assert result.findings == []


def test_each_file_is_parsed_once_per_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # triangles and references both read the mesh; it should be parsed once.
    from assetlint import model

    calls: list[Path] = []
    real = model.read_obj

    def counting(path: Path) -> object:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(model, "read_obj", counting)
    write_objs(tmp_path, "SM_A.obj")
    run(tmp_path, Config())
    assert len(calls) == 1
