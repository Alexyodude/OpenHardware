# OpenHardware — meta-guard: every armed SCRIPT-ENFORCED checker runs in CI.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Closes the gap `test_rules_are_armed.py` leaves open.

That file proves an armed mechanism's `checker` path exists on disk. It does
not prove the checker ever runs: a `checker: COPYING` would satisfy it just as
well as a real script. The four SCRIPT-ENFORCED checkers are only actually
enforced because `.github/workflows/rules.yml` hard-codes a `run:` step for
each — nothing links that YAML back to the rule frontmatter. Delete a step, or
add a new rule with `armed: true` and a checker CI never invokes, and this
would report green forever.

Scoped to SCRIPT-ENFORCED deliberately: `tools/ledger.py` is armed at tier
PARSER-ENFORCED. It is a library invoked by the test suite
(`tests/rules/test_ledger.py`, `test_feature_ledgers_parse.py`), not a CI
checker step with a `run:` line of its own, so it is out of scope here.
"""

from __future__ import annotations

import pathlib

from tools.rules_meta import load_rules

REPO = pathlib.Path(__file__).resolve().parents[2]
RULES_DIR = REPO / "rules"
WORKFLOW = REPO / ".github" / "workflows" / "rules.yml"


def test_every_armed_script_enforced_checker_runs_in_ci():
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    unwired = []
    for rule in load_rules(RULES_DIR):
        for mechanism in rule.mechanisms:
            if not mechanism.armed or mechanism.tier != "SCRIPT-ENFORCED":
                continue
            checker = mechanism.checker
            found = any(
                checker in line
                for line in workflow_text.splitlines()
                if line.strip().startswith("run:")
            )
            if not found:
                unwired.append(f"{rule.name}: {checker} has no 'run:' line in {WORKFLOW}")

    assert not unwired, (
        "armed SCRIPT-ENFORCED checkers not wired into CI: " + "; ".join(unwired)
    )
