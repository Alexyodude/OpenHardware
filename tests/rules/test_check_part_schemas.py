# OpenHardware — tests for the part schema checker.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

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


def _cite(tmp_path, filename, cited_as):
    """Lay out a repo holding `src/<filename>`, and a schema citing `cited_as`."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / filename).write_text("x\n" * 300, encoding="utf-8")
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    (schemas / "example.json").write_text(
        json.dumps({**GOOD, "source": f"src/{cited_as}:220"}), encoding="utf-8"
    )
    return schemas


def test_a_citation_matching_the_on_disk_spelling_passes(tmp_path):
    schemas = _cite(tmp_path, "output_LEDs.cc", "output_LEDs.cc")
    assert find_problems(schemas, repo_root=tmp_path) == []


def test_a_citation_with_the_wrong_case_is_a_problem(tmp_path):
    """The shipped LEDs schema cited `output_leds.cc`; the file is `output_LEDs.cc`.

    Windows resolved it happily and the checker printed OK for six days. Linux
    CI rejected it on the first run this repository ever performed.

    On a case-sensitive filesystem this test passes because the cited file
    genuinely is not there; on Windows and macOS it passes only because the
    checker now compares spelling rather than asking the filesystem. Same
    verdict, two routes -- which is the point, since the old checker's verdict
    depended on which machine ran it.
    """
    schemas = _cite(tmp_path, "output_LEDs.cc", "output_leds.cc")
    problems = find_problems(schemas, repo_root=tmp_path)
    assert any("output_leds.cc" in p for p in problems)


def test_an_empty_directory_raises(tmp_path):
    with pytest.raises(Exception, match="no schemas"):
        find_problems(tmp_path)


def test_the_shipped_schemas_pass(upstream):
    # The schemas live here; the paths they cite live in PICSimLab. Since the
    # split those are two different roots, and conflating them was what made
    # this test pass against a tree that no longer exists.
    assert (
        find_problems(REPO / "webui" / "parts" / "schemas", repo_root=upstream) == []
    )
