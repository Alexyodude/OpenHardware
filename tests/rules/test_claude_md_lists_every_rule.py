# OpenHardware — every rule must be named in CLAUDE.md.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pathlib

from tools.rules_meta import load_rules

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_claude_md_references_every_rule():
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    missing = [
        rule.name
        for rule in load_rules(REPO / ".claude" / "rules")
        if rule.name not in text
    ]
    assert not missing, f"CLAUDE.md does not mention: {missing}"
