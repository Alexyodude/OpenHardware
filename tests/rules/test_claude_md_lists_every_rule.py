# OpenHardware — every rule must be named in CLAUDE.md.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import pathlib

from tools.rules_meta import load_rules

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_claude_md_references_every_rule():
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    missing = [
        rule.name
        for rule in load_rules(REPO / "rules")
        if rule.name not in text
    ]
    assert not missing, f"CLAUDE.md does not mention: {missing}"
