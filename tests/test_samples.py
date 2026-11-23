"""Every rule has a sample that passes (samples/good) and one that fails (samples/bad)."""

from collections import defaultdict
from pathlib import Path

import pytest

from assetlint.config import load_config
from assetlint.engine import run
from assetlint.rules import BUILTIN_RULES

# Each file in samples/bad, and the rules it breaks. Files not listed must pass.
BAD = {
    "Cube.001.obj": {"naming"},
    "SM_Crate Box.obj": {"naming"},
    "Crate_D.png": {"naming"},
    "SM_Rock.fbx": {"formats"},
    "T_Fake_D.png": {"formats"},
    "SM_Broken.glb": {"formats"},
    "T_Noise_D.png": {"size"},
    "SM_Pot.obj": {"duplicates"},
    "copies/SM_Pot.obj": {"duplicates"},
    "SM_Dense.obj": {"triangles"},
    "T_Odd_D.png": {"textures"},
    "T_Big_D.png": {"textures"},
    "SM_Chair.obj": {"references"},
    "SM_Table.gltf": {"references"},
    "SM_Stool.obj": {"references"},
}


def rules_by_file(folder: Path, samples: Path) -> dict[str, set[str]]:
    result = run(folder, load_config(samples / "assetlint.toml"))
    found: dict[str, set[str]] = defaultdict(set)
    for finding in result.findings:
        found[finding.path].add(finding.rule)
    return dict(found)


def test_good_samples_pass_every_rule(samples: Path) -> None:
    assert rules_by_file(samples / "good", samples) == {}


def test_bad_samples_break_exactly_the_expected_rules(samples: Path) -> None:
    assert rules_by_file(samples / "bad", samples) == BAD


@pytest.mark.parametrize("rule", [r.id for r in BUILTIN_RULES])
def test_every_rule_has_a_failing_sample(rule: str) -> None:
    assert any(rule in rules for rules in BAD.values())
