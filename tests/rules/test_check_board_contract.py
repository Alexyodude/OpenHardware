# OpenHardware — tests for the board contract coverage checker.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

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


#: Pure virtuals in upstream's `src/lib/board.h`.
#:
#: 42 measured 2026-08-09 against the fork point (`cd92747b`).
#: 44 measured 2026-08-23 against upstream `62e8b5ba`, which added
#: `GetSimBackends()` and `GetDebuggers()`.
#:
#: Upstream is deliberately unpinned (rules/upstream-sync.md section 4), so
#: this number tracks whatever revision the reference checkout holds and
#: **will fire again** when upstream touches the contract. That is the point:
#: it is the only thing that notices a board this project has to implement
#: gained a method.
CONTRACT_SIZE = 44


def test_the_real_contract_is_the_expected_size(upstream):
    """A tripwire on upstream's board contract, not a build gate.

    When this fails, upstream changed `board.h`. Reconcile the ledgers under
    `docs/features/` and `rules/core-interface.md`, then update
    `CONTRACT_SIZE` with the date and revision you measured against.
    """
    found = contract_methods(upstream / "src" / "lib" / "board.h")
    assert len(found) == CONTRACT_SIZE, (
        f"board.h declares {len(found)} pure virtuals, expected "
        f"{CONTRACT_SIZE}. Upstream has changed the board contract. "
        f"Declared now: {sorted(found)}"
    )
