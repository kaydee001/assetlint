"""The interface every rule implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Protocol

from assetlint.config import RulesConfig, Severity
from assetlint.model import Asset


class RuleConfig(Protocol):
    @property
    def severity(self) -> Severity: ...


class Rule[C: RuleConfig](ABC):
    """A check run against each asset.

    One instance checks every asset in a run. Settings come with each asset,
    because per-folder overrides can give assets different settings. A rule
    yields plain messages; the engine attaches the rule id, severity and path.
    Rules that compare files with each other (such as duplicates) collect what
    they need in `check` and report it from `finish`.
    """

    id: str
    description: str
    label: str = ""  # a plain name for people, e.g. "Linked files"; the id stays in the config
    why: str = ""  # the app explains each rule: why it matters ...
    how: str = ""  # ... and how to fix what it finds

    def settings(self, rules: RulesConfig, asset: Asset) -> C | None:
        """This rule's settings for `asset`, or None when the rule doesn't cover it."""
        config: C = getattr(rules, self.id)
        return config

    @abstractmethod
    def check(self, asset: Asset, config: C) -> Iterable[str]:
        """Yield one message per problem found in `asset`."""

    def finish(self) -> Iterable[tuple[Asset, str]]:
        """Yield problems that need every asset seen first. Called once, after all checks."""
        return ()
