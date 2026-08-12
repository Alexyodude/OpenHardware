# OpenHardware — tests for the part schema checker.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import json
import pathlib

import pytest

from tools.check_part_schemas import find_problems

REPO = pathlib.Path(__file__).resolve().parents[2]

GOOD = {
    "part": "Example",
    "source": "src/parts/example.cc:100",
    "fields": [{"role": "pin", "dir": "out", "label": "A"}],
}


def write(tmp_path, data, name="example.json"):
    (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def test_a_good_schema_has_no_problems(tmp_path):
    assert find_problems(write(tmp_path, GOOD)) == []


def test_a_source_without_a_line_number_is_a_problem(tmp_path):
    # "src/parts/example.cc" does not say where; a citation must be checkable.
    bad = {**GOOD, "source": "src/parts/example.cc"}
    problems = find_problems(write(tmp_path, bad))
    assert any("line number" in p for p in problems)


def test_a_source_pointing_at_a_missing_file_is_a_problem(tmp_path):
    bad = {**GOOD, "source": "src/parts/does_not_exist.cc:1"}
    problems = find_problems(write(tmp_path, bad), repo_root=REPO)
    assert any("does not exist" in p for p in problems)


def test_an_empty_directory_raises(tmp_path):
    with pytest.raises(Exception, match="no schemas"):
        find_problems(tmp_path)


def test_the_shipped_schemas_pass():
    assert find_problems(REPO / "webui" / "parts" / "schemas", repo_root=REPO) == []
