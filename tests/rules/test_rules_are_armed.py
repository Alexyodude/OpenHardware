# OpenHardware — meta-guard: every armed mechanism names a real checker.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import pathlib

from tools.rules_meta import load_rules

REPO = pathlib.Path(__file__).resolve().parents[2]
RULES_DIR = REPO / "rules"


def test_rules_parse():
    # load_rules raises on an empty or missing directory, so this also proves
    # at least one rule exists.
    assert load_rules(RULES_DIR)


def test_every_armed_mechanism_has_an_existing_checker():
    missing = []
    for rule in load_rules(RULES_DIR):
        for mechanism in rule.mechanisms:
            if not mechanism.armed or mechanism.tier == "CONVENTION":
                continue
            if not (REPO / mechanism.checker).exists():
                missing.append(f"{rule.name}: {mechanism.checker}")
    assert not missing, f"armed mechanisms naming absent checkers: {missing}"


def test_every_unarmed_mechanism_explains_why():
    unexplained = []
    for rule in load_rules(RULES_DIR):
        for mechanism in rule.mechanisms:
            if mechanism.armed or mechanism.tier == "CONVENTION":
                continue
            if not mechanism.blocked_by:
                unexplained.append(f"{rule.name}: {mechanism.tier}")
    assert not unexplained, f"unarmed mechanisms with no blocked_by: {unexplained}"
