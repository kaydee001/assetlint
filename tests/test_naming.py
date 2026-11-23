from pathlib import Path

import pytest

from assetlint.config import NamingRuleConfig
from assetlint.model import Asset
from assetlint.rules.naming import NamingRule


def messages(rule: NamingRule, filename: str) -> list[str]:
    return list(rule.check(Asset(path=Path("/assets", filename), rel=filename)))


@pytest.mark.parametrize("filename", ["SM_Crate.glb", "crate_01.png", "rock-large.obj"])
def test_default_pattern_accepts_plain_names(filename: str) -> None:
    assert messages(NamingRule(NamingRuleConfig()), filename) == []


@pytest.mark.parametrize(
    ("filename", "hint"),
    [
        ("Cube.001.glb", "Blender duplicate suffix"),
        ("crate box.obj", "contains a space"),
        ("crate#1.png", ""),
    ],
)
def test_default_pattern_rejects_bad_names(filename: str, hint: str) -> None:
    [message] = messages(NamingRule(NamingRuleConfig()), filename)
    assert "doesn't match the naming pattern" in message
    assert hint in message


def test_missing_prefix_is_reported() -> None:
    rule = NamingRule(NamingRuleConfig(prefixes={".png": "T_"}))
    assert messages(rule, "T_Crate.png") == []
    assert messages(rule, "Crate.png") == ["'Crate.png' should start with 'T_' (.png files)"]


def test_prefix_matches_extension_case_insensitively() -> None:
    rule = NamingRule(NamingRuleConfig(prefixes={"PNG": "T_"}))
    assert messages(rule, "Crate.PNG") == ["'Crate.PNG' should start with 'T_' (.png files)"]


def test_pattern_must_match_the_whole_name() -> None:
    rule = NamingRule(NamingRuleConfig(pattern="[A-Z]+"))
    assert messages(rule, "ABC.glb") == []
    assert len(messages(rule, "ABCdef.glb")) == 1
