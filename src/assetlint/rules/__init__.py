"""The built-in rules, and building the active set from a config."""

from __future__ import annotations

from typing import Any

from assetlint.config import Config
from assetlint.rules.base import Rule
from assetlint.rules.custom import CustomRule
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


def build_rules(config: Config | None = None) -> list[Rule[Any]]:
    """A fresh instance of every rule for one run: the built-ins, then the config's custom rules.

    Rules switched off are skipped per asset.
    """
    custom = [CustomRule(entry, config) for entry in config.custom] if config else []
    return [*(rule_cls() for rule_cls in BUILTIN_RULES), *custom]


__all__ = ["BUILTIN_RULES", "CustomRule", "Rule", "build_rules"]
