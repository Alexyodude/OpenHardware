# OpenHardware — tests for the board contract coverage checker.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pathlib

import pytest

from tools.check_board_contract import (
    ContractError,
    contract_methods,
    missing_methods,
    overridden_methods,
)

REPO = pathlib.Path(__file__).resolve().parents[2]

CONTRACT = """
class board {
public:
    virtual void MStep(void) = 0;
    virtual int MReset(int flags) = 0;
    virtual std::string GetName(void) = 0;
};
"""

COVERS_ALL = """
class bsim_x : virtual public board {
public:
    void MStep(void) override;
    int MReset(int flags) override;
    std::string GetName(void) override { return "x"; };
};
"""

MISSES_ONE = """
class bsim_x : virtual public board {
public:
    void MStep(void) override;
    int MReset(int flags) override;
};
"""


def write(tmp_path: pathlib.Path, text: str, name: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_pure_virtuals_are_extracted(tmp_path):
    header = write(tmp_path, CONTRACT, "board.h")
    assert contract_methods(header) == {"MStep", "MReset", "GetName"}


def test_overrides_are_extracted_including_inline_bodies(tmp_path):
    header = write(tmp_path, COVERS_ALL, "bsim_x.h")
    # GetName is declared with an inline body; it must still register.
    assert overridden_methods([header]) == {"MStep", "MReset", "GetName"}


def test_a_missing_override_is_reported(tmp_path):
    board_h = write(tmp_path, CONTRACT, "board.h")
    pair = write(tmp_path, MISSES_ONE, "bsim_x.h")
    assert missing_methods([pair], board_h) == {"GetName"}


def test_full_coverage_reports_nothing_missing(tmp_path):
    board_h = write(tmp_path, CONTRACT, "board.h")
    pair = write(tmp_path, COVERS_ALL, "bsim_x.h")
    assert missing_methods([pair], board_h) == set()


def test_coverage_may_be_split_across_the_pair(tmp_path):
    # A real board is assembled from a bsim_* half and a board_* half; neither
    # covers the contract alone.
    board_h = write(tmp_path, CONTRACT, "board.h")
    backend = write(tmp_path, "void MStep(void) override;\nint MReset(int f) override;", "a.h")
    ui = write(tmp_path, "std::string GetName(void) override;", "b.h")
    assert missing_methods([backend, ui], board_h) == set()


def test_a_contract_with_no_pure_virtuals_raises(tmp_path):
    # An empty contract would make every pair pass — the vacuous green this
    # project exists to prevent.
    header = write(tmp_path, "class board { public: void thing(void); };", "board.h")
    with pytest.raises(ContractError, match="no pure virtuals"):
        contract_methods(header)


def test_headers_declaring_no_overrides_raise(tmp_path):
    header = write(tmp_path, "class bsim_x { public: void thing(void); };", "bsim_x.h")
    with pytest.raises(ContractError, match="no overrides"):
        overridden_methods([header])


def test_no_headers_raises():
    with pytest.raises(ContractError, match="no headers given"):
        overridden_methods([])


def test_missing_file_raises(tmp_path):
    with pytest.raises(ContractError, match="not found"):
        overridden_methods([tmp_path / "absent.h"])


def test_upstream_reference_pair_covers_the_whole_contract(upstream):
    # bsim_ucsim + board_uCboard demonstrably compile upstream, so a failure
    # here means this checker's parsing is wrong, not that the code is.
    pair = [
        upstream / "src" / "sim_backend" / "bsim_ucsim.h",
        upstream / "src" / "boards" / "board_uCboard.h",
    ]
    assert missing_methods(pair, upstream / "src" / "lib" / "board.h") == set()


def test_the_real_contract_is_the_expected_size(upstream):
    # Pins the count the strategy document cites. If board.h gains or loses a
    # pure virtual, this fails and the doc needs updating with it.
    assert len(contract_methods(upstream / "src" / "lib" / "board.h")) == 42
