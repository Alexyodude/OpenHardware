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


def test_ci_runs_every_suite_in_testpaths():
    """The other half, and the half that was false.

    `test_every_armed_script_enforced_checker_runs_in_ci` above proves the
    checkers run. Nothing proved the *tests* did. Measured 2026-08-26: the
    workflow ran `pytest tests/i8086/`, `tests/rules/` and `tests/webui/` by
    name, so tests/avr, tests/cortexm0, tests/riscv32 and tests/rv32 — four of
    the five cores — were in neither CI nor its reach.

    `tests/rules/test_testpaths.py` guards the configuration; this guards the
    workflow's use of it. Between them a suite cannot fall out of the gate at
    either end.

    A bare `pytest` satisfies this by reading `testpaths` itself, which is why
    it is the shape CI now uses: a suite added to `pyproject.toml` is run here
    without anybody editing the workflow.
    """
    import tomllib

    workflow = WORKFLOW.read_text(encoding="utf-8")
    runs = [line.split("run:", 1)[1].strip()
            for line in workflow.splitlines() if line.strip().startswith("run:")]
    pytest_runs = [r for r in runs if r.split()[:1] == ["pytest"]]
    assert pytest_runs, f"nothing in {WORKFLOW} runs pytest at all"

    # A bare `pytest` -- no path argument -- reads testpaths and therefore
    # covers every suite by construction.
    if any(not [word for word in r.split()[1:] if not word.startswith("-")]
           for r in pytest_runs):
        return

    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    wanted = set(config["tool"]["pytest"]["ini_options"]["testpaths"])
    named = {word.rstrip("/") for r in pytest_runs for word in r.split()[1:]
             if not word.startswith("-")}
    missing = sorted(wanted - {n.rstrip("/") for n in named})
    assert not missing, (
        f"CI names its suites and misses {missing}. Either add them or run "
        f"bare `pytest`, which reads testpaths and cannot miss one."
    )
