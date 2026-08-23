# OpenHardware - tests for the licence header checker.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Tests for tools/check_licenses.py, per rules/licence-hygiene.md.

The fixtures below deliberately contain GPL text. That is why this file was
the one thing the relicense script refused to rewrite automatically: it could
not tell a licence *claim* from a licence *fixture*, and guessing would have
corrupted the tests that prove the checker works.
"""

import pathlib
import subprocess

import pytest

from tools.check_licenses import (
    SPDX_MIT,
    LicenceError,
    is_patch,
    is_third_party,
    leading_comment_block,
    mislabelled_patches,
    missing_mit,
    stray_gpl,
)

REPO = pathlib.Path(__file__).resolve().parents[2]

MIT_HEADER = (
    "# OpenHardware - a thing.\n"
    "#\n"
    "# SPDX-License-Identifier: MIT\n"
    "# Copyright (c) 2026 the OpenHardware authors. See LICENSE.\n"
)

GPL_HEADER = (
    "# OpenHardware - a thing.\n"
    "#\n"
    "# This program is free software; you can redistribute it and/or modify it\n"
    "# under the terms of the GNU General Public License as published by the\n"
    "# Free Software Foundation; either version 2, or any later version.\n"
)


def _repo(tmp_path, files: dict[str, str]) -> pathlib.Path:
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


# --- check 1: our source says MIT -------------------------------------------


def test_a_file_without_the_spdx_line_is_caught(tmp_path):
    root = _repo(tmp_path, {"a.py": "print('hi')\n"})
    assert missing_mit(root) == [root / "a.py"]


def test_a_file_with_the_spdx_line_passes(tmp_path):
    root = _repo(tmp_path, {"a.py": MIT_HEADER + "print('hi')\n"})
    assert missing_mit(root) == []


def test_a_shebang_before_the_header_is_fine(tmp_path):
    root = _repo(tmp_path, {"a.py": "#!/usr/bin/env python3\n" + MIT_HEADER})
    assert missing_mit(root) == []


def test_front_end_suffixes_are_scanned(tmp_path):
    """JS, CSS and HTML are this project's own source and must be labelled."""
    root = _repo(
        tmp_path,
        {
            "a.js": "export const x = 1;\n",
            "a.css": ":root { color: red }\n",
            "a.html": "<!doctype html>\n<p>hi</p>\n",
            "a.sh": "#!/bin/bash\necho hi\n",
        },
    )
    assert {p.name for p in missing_mit(root)} == {"a.js", "a.css", "a.html", "a.sh"}


def test_an_empty_scan_raises_rather_than_passing(tmp_path):
    with pytest.raises(LicenceError, match="no source files"):
        missing_mit(tmp_path / "nothing-here")


# --- check 2: our source does not say GPL -----------------------------------


def test_a_stray_gpl_header_is_caught(tmp_path):
    root = _repo(tmp_path, {"a.py": GPL_HEADER + "print('hi')\n"})
    assert stray_gpl(root) == [root / "a.py"]


def test_gpl_discussed_below_the_header_is_not_a_claim(tmp_path):
    """The case that made the first version of this checker fail on itself.

    A module whose docstring explains GPL handling is not making a GPL claim.
    Only the leading comment block is a claim, so only that is scanned.
    """
    body = MIT_HEADER + '"""We must never carry a GNU General Public License header."""\n'
    root = _repo(tmp_path, {"a.py": body})
    assert stray_gpl(root) == []
    assert missing_mit(root) == []


# --- the header/prose boundary ----------------------------------------------


def test_the_block_stops_at_the_first_real_line():
    """Cases are a loop rather than a parametrise, deliberately.

    `tools/inventory.py` counts `def test_*` with ast, so a parametrised test
    counts once there and five times in pytest, and
    `test_ast_count_matches_pytest_collection` fails on the divergence. That
    guard is worth more than the syntax sugar.
    """
    cases = [
        ("# head\n" '"""doc with GNU General Public License"""\n', "# head"),
        ("// head\nexport const x = 1;\n", "// head"),
        ("/* head */\n:root { color: red }\n", "/* head */"),
        ("<!doctype html>\n<!-- head -->\n<p>body</p>\n", "<!-- head -->"),
        ("#!/bin/bash\n# head\necho hi\n", "# head"),
    ]
    for text, expected_last in cases:
        actual = leading_comment_block(text).strip().splitlines()[-1].strip()
        assert actual == expected_last, f"{text!r} -> {actual!r}"


def test_a_multiline_block_comment_is_kept_whole():
    text = "/*\n * SPDX-License-Identifier: MIT\n */\n:root { color: red }\n"
    assert SPDX_MIT in leading_comment_block(text)
    assert "color: red" not in leading_comment_block(text)


def test_a_multiline_html_comment_is_kept_whole():
    text = "<!doctype html>\n<!--\n  SPDX-License-Identifier: MIT\n-->\n<p>hi</p>\n"
    assert SPDX_MIT in leading_comment_block(text)
    assert "<p>hi</p>" not in leading_comment_block(text)


# --- exemptions --------------------------------------------------------------


def test_vendored_source_is_never_asked_for_our_header(tmp_path):
    """three.js is MIT already. Rewriting its header would misstate its origin."""
    root = _repo(
        tmp_path,
        {
            "webui/static/vendor/three.module.js": "// (c) three.js authors\n",
            "ours.py": MIT_HEADER,
        },
    )
    assert missing_mit(root) == []


def test_third_party_fixtures_are_exempt(tmp_path):
    root = _repo(
        tmp_path,
        {"tests/fixtures/sst8088/90.json": "{}\n", "ours.py": MIT_HEADER},
    )
    assert missing_mit(root) == []


def test_the_real_exempt_directories_are_recognised():
    assert is_third_party("webui/static/vendor/three.module.js")
    assert is_third_party("tests/fixtures/sst8088/README.md")
    assert not is_third_party("webui/static/app.js")
    assert is_patch("patches/0001-board-arch-x86.patch")
    assert not is_patch("tools/apply_patches.sh")


# --- check 3: patches say GPL, never MIT -------------------------------------


def test_a_patch_claiming_mit_is_caught(tmp_path):
    root = _repo(
        tmp_path,
        {
            "patches/README.md": "GNU General Public License applies here.\n",
            "patches/0001-x.patch": f"# {SPDX_MIT}\n--- a/x\n+++ b/x\n",
        },
    )
    assert root / "patches" / "0001-x.patch" in mislabelled_patches(root)


def test_a_patches_readme_that_omits_the_licence_is_caught(tmp_path):
    root = _repo(tmp_path, {"patches/README.md": "Some patches live here.\n"})
    assert mislabelled_patches(root) == [root / "patches" / "README.md"]


def test_a_correctly_labelled_patches_directory_passes(tmp_path):
    root = _repo(
        tmp_path,
        {
            "patches/README.md": (
                "These patches are under the GNU General Public License, "
                "version 2 or later.\n"
            ),
            "patches/0001-x.patch": "--- a/x\n+++ b/x\n",
        },
    )
    assert mislabelled_patches(root) == []


def test_no_patches_directory_is_not_a_failure(tmp_path):
    assert mislabelled_patches(tmp_path) == []


def test_patches_are_excluded_from_the_mit_requirement(tmp_path):
    """A patch must not be given an MIT header, so it is not asked for one."""
    root = _repo(
        tmp_path,
        {"patches/0001-x.patch": "--- a/x\n+++ b/x\n", "ours.py": MIT_HEADER},
    )
    assert missing_mit(root) == []


# --- the repository itself ---------------------------------------------------


def test_this_repository_passes_every_check():
    assert missing_mit(REPO) == []
    assert stray_gpl(REPO) == []
    assert mislabelled_patches(REPO) == []


def test_untracked_and_ignored_files_are_out_of_scope(tmp_path):
    """A licence header is a claim about code this repository distributes.

    It distributes what it tracks. An earlier version walked the filesystem
    with rglob and reported 26 problems the moment `.claude/` was installed
    from claude-template -- 151 gitignored files, none of them ours to label.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    (tmp_path / "ours.py").write_text(MIT_HEADER, encoding="utf-8")
    vendored = tmp_path / ".claude" / "agents"
    vendored.mkdir(parents=True)
    (vendored / "someone-elses.py").write_text("# no header at all\n", encoding="utf-8")

    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    assert missing_mit(tmp_path) == []
    assert stray_gpl(tmp_path) == []


def test_a_tracked_file_is_still_caught_in_a_real_repo(tmp_path):
    """The counterpart: git deciding the set must not weaken the check."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "ours.py").write_text("print('no header')\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    assert missing_mit(tmp_path) == [tmp_path / "ours.py"]
