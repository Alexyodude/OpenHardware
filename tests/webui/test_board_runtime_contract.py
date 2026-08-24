# OpenHardware — what a board must supply before firmware can run on it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# The **runtime** contract, over `webui/boards/<chip>.py`. Not
# `tools/check_board_contract.py`, which is about PICSimLab's C++ `board.h`
# and shares nothing with this but a word. See `webui/boards/contract.py`.
#
# ## The test that does the most work here is the drift guard
#
# `VECTOR_TABLE_OFFSETS` now lives in the board modules, where the chip is
# described. `webui/api.py` still holds its own copy, because that file is
# claimed by OH-32 and is not this ticket's to edit -- so for the moment the
# same fact is written twice, which is the arrangement most likely to rot.
# `test_the_offsets_api_uses_agree_with_the_boards_that_declare_them` is what
# stops it rotting, and it is what makes the copy in `api.py` safe to delete
# whenever OH-32 lands.

import pathlib

import pytest

from webui.boards import catalogue, contract

REPO = pathlib.Path(__file__).resolve().parents[2]


class NotABoard:
    """A stand-in for a board module that supplies nothing.

    A class rather than a real module, because the interesting cases are
    modules that do *not* exist on disk, and `contract.missing` only ever asks
    `hasattr`.
    """

    __name__ = "webui.boards.notaboard"


class OnlyInstalls:
    __name__ = "webui.boards.onlyinstalls"

    @staticmethod
    def install(cpu):  # pragma: no cover - never called, only looked up
        raise AssertionError("the contract must not run install()")


# --- the boards that exist satisfy it ---------------------------------------


def test_every_board_module_satisfies_the_contract():
    """The claim the ticket asked for. If this fails, a board can be loaded by
    `api.py` and then entered at the wrong address."""
    for module in contract.board_modules():
        assert contract.missing(module) == [], (
            f"{module.__name__} is missing {contract.missing(module)}"
        )


def test_the_two_boards_disagree_about_where_the_vector_table_is():
    """The reason this is a board fact and not a constant.

    An RP2040 image is linked past 256 bytes of boot2 and a SAMD21 image is
    not. One number cannot serve both, and this is what would have to change
    before anyone could put it back in `api.py`.
    """
    from webui.boards import rp2040, samd21

    assert rp2040.VECTOR_TABLE_OFFSETS == (0, rp2040.BOOT2_BYTES)
    assert samd21.VECTOR_TABLE_OFFSETS == (0,)
    assert rp2040.VECTOR_TABLE_OFFSETS != samd21.VECTOR_TABLE_OFFSETS


def test_the_offsets_api_uses_agree_with_the_boards_that_declare_them():
    """The drift guard, and the point of the whole exercise.

    `webui/api.py` keeps its own table because it belongs to OH-32. Two copies
    of one fact is exactly the arrangement that goes wrong quietly, so this
    pins them together: change either and this fails, and deleting api.py's
    copy in favour of the board's is safe precisely because this passed.
    """
    from webui import api

    described = catalogue.described_chips()
    checked = 0
    for chip in catalogue.CHIPS:
        if chip.upper().replace("-", "") not in described:
            continue
        module = __import__(api.description_module(chip), fromlist=["*"])
        used = api.VECTOR_TABLE_OFFSETS.get(chip, api.DEFAULT_VECTOR_TABLE_OFFSETS)
        assert tuple(used) == tuple(module.VECTOR_TABLE_OFFSETS), (
            f"{chip}: api.py would enter at {used}, the board says "
            f"{module.VECTOR_TABLE_OFFSETS}"
        )
        checked += 1
    assert checked >= 2, f"only {checked} described chips compared; expected both"


# --- a board missing a part fails with the part named ------------------------


def test_a_board_supplying_nothing_is_missing_everything():
    assert contract.missing(NotABoard) == [r.name for r in contract.REQUIRED]


def test_a_board_missing_one_part_is_missing_only_that_one():
    """Reported as a list rather than the first failure, so a board written
    from scratch learns everything it owes in one run."""
    assert contract.missing(OnlyInstalls) == ["VECTOR_TABLE_OFFSETS"]


def test_the_failure_names_the_part():
    with pytest.raises(contract.RuntimeContractError) as caught:
        contract.check(OnlyInstalls)
    assert "VECTOR_TABLE_OFFSETS" in str(caught.value)


def test_the_failure_says_what_breaks_without_it():
    """A name tells a reader what to type; the reason tells them what to put
    in it. `api.py _place()` is the caller, and the message says so."""
    with pytest.raises(contract.RuntimeContractError) as caught:
        contract.check(OnlyInstalls)
    assert "_place" in str(caught.value)
    assert "reset vector" in str(caught.value)


def test_a_board_that_satisfies_the_contract_raises_nothing():
    from webui.boards import rp2040

    contract.check(rp2040)


# --- the contract cannot grow without a caller -------------------------------


def test_every_requirement_names_a_file_that_exists_and_mentions_it():
    """The admission test, enforced rather than described.

    `Requirement.why` names the caller that asks for the part. This checks the
    file it names is real and does mention the part -- so a requirement added
    because a board "ought" to have it fails here, which is the ticket's own
    warning made structural: *the contract must not become a list of registers
    a board is expected to fill in*.
    """
    for requirement in contract.REQUIRED:
        cited = [
            word.strip(":,")
            for word in requirement.why.split()
            if word.endswith(".py") or ".py" in word
        ]
        assert cited, f"{requirement.name} names no caller: {requirement.why!r}"
        path = REPO / cited[0].rstrip(":,")
        assert path.is_file(), f"{requirement.name} cites {path}, which is not there"
        assert requirement.name in path.read_text(encoding="utf-8"), (
            f"{requirement.name} cites {cited[0]}, which does not mention it"
        )


def test_the_contract_is_short_enough_to_read():
    """Not a style rule. A contract long enough to skim is one a board author
    satisfies by copying another board, which is the failure the ticket opens
    with: *a second board written by reading the first is how the shape gets
    copied wrong*."""
    assert len(contract.REQUIRED) <= 5, (
        f"{len(contract.REQUIRED)} requirements; each one taxes every future "
        f"board, so adding one should be uncomfortable"
    )


# --- the module list -------------------------------------------------------


def test_the_helpers_beside_the_boards_are_not_boards():
    names = contract.board_module_names()
    assert "webui.boards.contract" not in names
    assert "webui.boards.catalogue" not in names
    assert "webui.boards.__init__" not in names


def test_the_board_list_comes_from_the_directory(tmp_path):
    """Derived rather than listed, so adding a board stays 'add one file' --
    the same convention `catalogue.described_chips` keeps."""
    (tmp_path / "somechip.py").write_text("", encoding="utf-8")
    (tmp_path / "contract.py").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    assert contract.board_module_names(tmp_path) == ["webui.boards.somechip"]


def test_this_contract_is_named_apart_from_the_picsimlab_one():
    """Two things in this repository are called the board contract. The
    exception carries `Runtime` so a traceback says which."""
    assert "Runtime" in contract.RuntimeContractError.__name__
    assert not hasattr(contract, "ContractError")
