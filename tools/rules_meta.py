# OpenHardware — parse .claude/rules frontmatter into structured metadata.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Parse ``.claude/rules/*.md`` frontmatter.

A malformed rule file raises. It is never skipped: a rule that silently fails
to parse is indistinguishable from a rule nobody wrote, which is the exact
failure the rule system exists to prevent.
"""

from __future__ import annotations

import dataclasses
import pathlib

import yaml

RULES_DIR = pathlib.Path(".claude/rules")

VALID_TIERS = frozenset(
    {
        "CONVENTION",
        "HOOK-ENFORCED",
        "SCRIPT-ENFORCED",
        "TEST-ENFORCED",
        "PARSER-ENFORCED",
    }
)


class RuleParseError(Exception):
    """A rule file's frontmatter is missing, malformed, or incomplete."""


@dataclasses.dataclass(frozen=True)
class Mechanism:
    tier: str
    checker: str | None
    armed: bool
    blocked_by: str | None = None


@dataclasses.dataclass(frozen=True)
class Rule:
    name: str
    path: pathlib.Path
    mechanisms: tuple[Mechanism, ...]


def _frontmatter(text: str, path: pathlib.Path) -> dict:
    if not text.startswith("---\n"):
        raise RuleParseError(f"{path}: no frontmatter block (file must start with '---')")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise RuleParseError(f"{path}: frontmatter block is not closed")
    try:
        data = yaml.safe_load(text[4 : end + 1])
    except yaml.YAMLError as exc:
        raise RuleParseError(f"{path}: invalid YAML in frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise RuleParseError(f"{path}: frontmatter must be a mapping")
    return data


def parse_rule(path: pathlib.Path) -> Rule:
    data = _frontmatter(path.read_text(encoding="utf-8"), path)

    name = data.get("rule")
    if not name:
        raise RuleParseError(f"{path}: missing required key 'rule'")

    raw = data.get("mechanisms")
    if not isinstance(raw, list) or not raw:
        raise RuleParseError(f"{path}: 'mechanisms' must be a non-empty list")

    mechanisms = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise RuleParseError(f"{path}: mechanism {index} is not a mapping")
        tier = item.get("tier")
        if tier not in VALID_TIERS:
            raise RuleParseError(
                f"{path}: mechanism {index} has tier {tier!r}; "
                f"valid tiers are {sorted(VALID_TIERS)}"
            )
        armed = item.get("armed")
        if not isinstance(armed, bool):
            raise RuleParseError(
                f"{path}: mechanism {index} 'armed' must be true or false"
            )
        checker = item.get("checker")
        if tier != "CONVENTION" and not checker:
            raise RuleParseError(
                f"{path}: mechanism {index} is {tier} but names no checker"
            )
        mechanisms.append(Mechanism(tier, checker, armed, item.get("blocked_by")))

    return Rule(name=name, path=path, mechanisms=tuple(mechanisms))


def load_rules(rules_dir: pathlib.Path = RULES_DIR) -> list[Rule]:
    if not rules_dir.is_dir():
        raise RuleParseError(f"{rules_dir}: rules directory does not exist")
    paths = sorted(rules_dir.glob("*.md"))
    if not paths:
        raise RuleParseError(f"{rules_dir}: contains no rule files")
    return [parse_rule(path) for path in paths]
