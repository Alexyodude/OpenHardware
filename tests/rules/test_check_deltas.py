# OpenHardware — tests for the upstream delta checker.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pytest

from tools.check_deltas import logged_paths, unlogged_modifications

LEDGER = """# Upstream deltas

## `src/lib/spareparts.cc`

Reason: analog net semantics, spec section 4.1.
"""


def test_ledger_paths_are_parsed(tmp_path):
    path = tmp_path / "upstream-deltas.md"
    path.write_text(LEDGER, encoding="utf-8")
    assert logged_paths(path) == {"src/lib/spareparts.cc"}


def test_missing_ledger_yields_no_paths(tmp_path):
    assert logged_paths(tmp_path / "absent.md") == set()


def test_modified_upstream_file_without_entry_is_flagged():
    result = unlogged_modifications(
        changed={"src/lib/board.h"},
        at_fork={"src/lib/board.h"},
        logged=set(),
    )
    assert result == ["src/lib/board.h"]


def test_modified_upstream_file_with_entry_passes():
    result = unlogged_modifications(
        changed={"src/lib/board.h"},
        at_fork={"src/lib/board.h"},
        logged={"src/lib/board.h"},
    )
    assert result == []


def test_new_file_is_never_flagged():
    # Additive files are unrestricted; they did not exist at fork-point.
    result = unlogged_modifications(
        changed={"tools/check_deltas.py"},
        at_fork={"src/lib/board.h"},
        logged=set(),
    )
    assert result == []


def test_empty_fork_point_set_raises():
    # An empty fork-point listing means the tag resolved to nothing; treating
    # that as "no upstream files" would pass every modification silently.
    with pytest.raises(ValueError, match="no files at fork-point"):
        unlogged_modifications(changed={"a"}, at_fork=set(), logged=set())
