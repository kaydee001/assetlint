"""The built-in rules, and building the active set from a config."""

from __future__ import annotations

from typing import Any

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


def build_rules() -> list[Rule[Any]]:
    """A fresh instance of every rule, for one run. Rules switched off are skipped per asset."""
    return [rule_cls() for rule_cls in BUILTIN_RULES]


__all__ = ["BUILTIN_RULES", "Rule", "build_rules"]
