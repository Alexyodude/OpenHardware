# OpenHardware — tests for the GPL header checker.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pytest

from tools.check_licenses import find_missing_headers, find_v2_only

V2_OR_LATER = (
    "# This program is free software; you can redistribute it and/or modify it\n"
    "# under the terms of the GNU General Public License as published by the Free\n"
    "# Software Foundation; either version 2, or (at your option) any later version.\n"
)

V2_ONLY = (
    "# This program is free software; you can redistribute it and/or modify it\n"
    "# under the terms of the GNU General Public License version 2 as published\n"
    "# by the Free Software Foundation.\n"
)

# Mentions the GPL without granting version 2 of it at all — e.g. a file that
# was relicensed away from GPL. The old two-condition check (GPL name present,
# "later version" absent) flagged this as v2-only, which is wrong: it never
# granted version 2 in the first place. The three-condition check requires an
# actual "version 2" mention before flagging.
GPL_MENTION_WITHOUT_VERSION_GRANT = (
    "# This file was relicensed from the GNU General Public License to the MIT\n"
    "# License; see LICENSE-MIT for the terms that now apply.\n"
)


def test_v2_only_header_is_detected(tmp_path):
    (tmp_path / "bad.py").write_text(V2_ONLY, encoding="utf-8")
    assert find_v2_only(tmp_path) == [tmp_path / "bad.py"]


def test_v2_or_later_header_is_accepted(tmp_path):
    (tmp_path / "good.py").write_text(V2_OR_LATER, encoding="utf-8")
    assert find_v2_only(tmp_path) == []


def test_non_source_files_are_ignored(tmp_path):
    # COPYING is the stock GPL-2 text and must never trip the v2-only check.
    # A real source file sits alongside it because a directory holding only
    # COPYING has no source files at all, which is the error case below.
    (tmp_path / "COPYING").write_text(V2_ONLY, encoding="utf-8")
    (tmp_path / "real.py").write_text(V2_OR_LATER, encoding="utf-8")
    assert find_v2_only(tmp_path) == []


def test_missing_header_is_detected(tmp_path):
    path = tmp_path / "new.py"
    path.write_text("print('hello')\n", encoding="utf-8")
    assert find_missing_headers([path]) == [path]


def test_present_header_satisfies_the_check(tmp_path):
    path = tmp_path / "new.py"
    path.write_text(V2_OR_LATER + "print('hello')\n", encoding="utf-8")
    assert find_missing_headers([path]) == []


def test_empty_scan_raises(tmp_path):
    with pytest.raises(ValueError, match="no source files"):
        find_v2_only(tmp_path / "missing")


def test_gpl_mention_without_version_grant_is_not_flagged(tmp_path):
    (tmp_path / "relicensed.py").write_text(
        GPL_MENTION_WITHOUT_VERSION_GRANT, encoding="utf-8"
    )
    assert find_v2_only(tmp_path) == []
