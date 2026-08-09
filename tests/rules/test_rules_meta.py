# OpenHardware — tests for the rule frontmatter parser.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pathlib

import pytest

from tools.rules_meta import Mechanism, RuleParseError, load_rules, parse_rule

VALID = """---
rule: example
mechanisms:
  - tier: SCRIPT-ENFORCED
    checker: tools/check_example.py
    armed: true
---

# Example rule
"""


def write(tmp_path: pathlib.Path, text: str, name: str = "example.md") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_a_valid_rule(tmp_path):
    rule = parse_rule(write(tmp_path, VALID))
    assert rule.name == "example"
    assert rule.mechanisms == (
        Mechanism("SCRIPT-ENFORCED", "tools/check_example.py", True, None),
    )


def test_missing_frontmatter_raises(tmp_path):
    with pytest.raises(RuleParseError, match="no frontmatter"):
        parse_rule(write(tmp_path, "# Just a heading\n"))


def test_unclosed_frontmatter_raises(tmp_path):
    with pytest.raises(RuleParseError, match="not closed"):
        parse_rule(write(tmp_path, "---\nrule: example\n"))


def test_unknown_tier_raises(tmp_path):
    text = VALID.replace("SCRIPT-ENFORCED", "VIBES-ENFORCED")
    with pytest.raises(RuleParseError, match="VIBES-ENFORCED"):
        parse_rule(write(tmp_path, text))


def test_enforced_mechanism_without_checker_raises(tmp_path):
    text = VALID.replace("    checker: tools/check_example.py\n", "")
    with pytest.raises(RuleParseError, match="names no checker"):
        parse_rule(write(tmp_path, text))


def test_non_boolean_armed_raises(tmp_path):
    text = VALID.replace("armed: true", "armed: yes-please")
    with pytest.raises(RuleParseError, match="must be true or false"):
        parse_rule(write(tmp_path, text))


def test_empty_rules_directory_raises(tmp_path):
    # A rules dir with no rules must be an error, never an empty pass.
    with pytest.raises(RuleParseError, match="no rule files"):
        load_rules(tmp_path)


def test_missing_rules_directory_raises(tmp_path):
    with pytest.raises(RuleParseError, match="does not exist"):
        load_rules(tmp_path / "nope")
