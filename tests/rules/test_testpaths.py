# OpenHardware — every suite is in the gate.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## Why this file exists
#
# **`tests/avr` was absent from `pyproject.toml`'s `testpaths` and nothing
# noticed.** Measured 2026-08-26 while closing OH-58: bare `pytest` collected
# 1,318 tests, the AVR suite's 35 were not among them, and the core that
# `webui/boards/catalogue.py` claims runs firmware on an Arduino Uno had never
# been exercised by the gate `CLAUDE.md` tells everyone to run. It passed
# because somebody ran `pytest tests/avr/` by hand.
#
# That is the quietest failure a test suite has. Every other kind announces
# itself; a suite nobody runs looks exactly like a suite that passes.
#
# `test_ast_count_matches_pytest_collection` does not cover it and is not
# meant to — it compares the ast model against pytest for `tests/rules/`
# alone, so a whole directory can vanish from the configuration without moving
# either number.

from __future__ import annotations

import pathlib
import tomllib

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Directories under `tests/` that hold data rather than tests, and are named
#: in `norecursedirs` for the same reason.
NOT_SUITES = {"fixtures", "__pycache__"}


def suites() -> set[str]:
    """Every directory under `tests/` holding at least one `test_*.py`."""
    return {
        path.parent.relative_to(REPO).as_posix()
        for path in (REPO / "tests").rglob("test_*.py")
        if path.parent.name not in NOT_SUITES
    }


def configured() -> list[str]:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return config["tool"]["pytest"]["ini_options"]["testpaths"]


def test_every_directory_of_tests_is_named_in_testpaths():
    """The one that would have caught it.

    Found by discovery rather than by a list here, so adding a suite and
    forgetting the configuration fails immediately — a second list to maintain
    would go stale in exactly the same way the first one did.
    """
    listed = set(configured())
    missing = sorted(suites() - listed)
    assert not missing, (
        f"these hold tests and bare `pytest` will not run them: {missing}. "
        f"Add them to testpaths in pyproject.toml."
    )


def test_testpaths_names_nothing_that_does_not_exist():
    """The other direction. A path that has been renamed away is silent —
    pytest does not complain about a `testpaths` entry it cannot find, it
    simply collects less."""
    gone = sorted(entry for entry in configured() if not (REPO / entry).is_dir())
    assert not gone, f"testpaths names directories that do not exist: {gone}"
