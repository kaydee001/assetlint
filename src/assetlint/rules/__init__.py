"""The built-in rules, and building the active set from a config."""

from __future__ import annotations

from typing import Any

from assetlint.config import Config
from assetlint.rules.base import Rule
from assetlint.rules.duplicates import DuplicatesRule
from assetlint.rules.formats import FormatsRule
from assetlint.rules.naming import NamingRule
from assetlint.rules.references import ReferencesRule
from assetlint.rules.size import SizeRule
from assetlint.rules.textures import TexturesRule
from assetlint.rules.triangles import TrianglesRule

# Each rule's id is also its table name under [rules] in assetlint.toml.
BUILTIN_RULES: list[type[Rule[Any]]] = [
    FormatsRule,
    SizeRule,
    NamingRule,
    DuplicatesRule,
    TrianglesRule,
    TexturesRule,
    ReferencesRule,
]


def build_rules(config: Config) -> list[Rule[Any]]:
    """Instantiate every rule that isn't switched off."""
    rules: list[Rule[Any]] = []
    for rule_cls in BUILTIN_RULES:
        rule_config = getattr(config.rules, rule_cls.id)
        if rule_config.severity != "off":
            rules.append(rule_cls(rule_config))
    return rules


__all__ = ["BUILTIN_RULES", "Rule", "build_rules"]
