# OpenHardware — tests for the backend layering checker.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pathlib

import pytest

from tools.check_layering import find_violations

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_forbidden_parts_include_is_found(tmp_path):
    (tmp_path / "bsim_bad.cc").write_text(
        '#include "../parts/input_POT.h"\n', encoding="utf-8"
    )
    violations = find_violations(tmp_path)
    assert len(violations) == 1
    assert violations[0][1] == 1
    assert violations[0][2] == "../parts/input_POT.h"


def test_forbidden_ui_include_is_found(tmp_path):
    (tmp_path / "bsim_bad.h").write_text('#include "picsimlab1.h"\n', encoding="utf-8")
    assert len(find_violations(tmp_path)) == 1


def test_lxrad_include_is_found(tmp_path):
    (tmp_path / "bsim_bad.h").write_text("#include <lxrad.h>\n", encoding="utf-8")
    assert len(find_violations(tmp_path)) == 1


def test_permitted_includes_are_not_flagged(tmp_path):
    (tmp_path / "bsim_ok.h").write_text(
        '#include "../lib/board.h"\n'
        '#include "../devices/bitbang_uart.h"\n'
        "#include <simavr/avr_adc.h>\n",
        encoding="utf-8",
    )
    assert find_violations(tmp_path) == []


def test_empty_directory_raises(tmp_path):
    # Nothing to scan must be an error, not a pass.
    with pytest.raises(ValueError, match="no source files"):
        find_violations(tmp_path / "missing")


def test_real_sim_backend_is_clean():
    # Verified clean at fork-point on 2026-08-09; this pins it.
    assert find_violations(REPO / "src" / "sim_backend") == []
