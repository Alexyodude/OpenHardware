# OpenHardware — what a board must supply before firmware can run on it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# The **runtime** contract, over `webui/boards/<chip>.py`. Not
# `tools/check_board_contract.py`, which is about PICSimLab's C++ `board.h`
# and shares nothing with this but a word. See `webui/boards/contract.py`.
#
# ## The drift guard did its job and is gone
#
# `VECTOR_TABLE_OFFSETS` moved to the board modules under OH-31 while
# `webui/api.py` kept a copy it was not that ticket's to delete, so the same
# fact was written twice -- the arrangement most likely to rot. A test pinned
# the two together, and its stated purpose was to make deleting api.py's copy
# safe. OH-52 deleted it. What replaced the guard is
# `test_the_offsets_have_exactly_one_home_and_it_is_the_board`, which asserts
# the copy did not come back: a guard whose job is finished should end, and the
# thing worth watching afterwards is the regression, not the invariant.
#
# ## What this file now covers that it did not
#
# Half the runtime contract moved into `core/<core>/machine.py` -- the entry
# model, the register file, which address space a hexdump reads. A board is
# checked against **its own machine**, so `contract.missing(module)` with no
# core is the weak question and asking it here would make these tests vacuous.

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
    `api.py` and then entered at the wrong address.

    **Checked against each board's own core**, which is the whole of OH-52.
    `contract.missing(module)` with no core asks only what is universal and
    would pass a board that owes its machine something -- an Armv6-M board with
    no `VECTOR_TABLE_OFFSETS`, say. The weak question exists; asking it here
    would make this test vacuous.
    """
    for module in contract.board_modules():
        core = contract.core_for(module)
        absent = contract.missing(module, core)
        assert absent == [], f"{module.__name__} ({core}) is missing {absent}"


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


def test_the_offsets_have_exactly_one_home_and_it_is_the_board():
    """What the drift guard turned into once the drift became impossible.

    This test used to compare `api.VECTOR_TABLE_OFFSETS` against each board's
    own copy, because api.py held a second one and belonged to another ticket.
    That copy is gone: the guard's whole purpose was to make deleting it safe,
    and deleting it is the better end than pinning it forever. What is left to
    assert is that it did not come back, and that the surviving copy is the one
    a load actually reads.
    """
    from webui import api

    assert not hasattr(api, "VECTOR_TABLE_OFFSETS"), (
        "api.py is keeping a second copy of where a chip's vector table is. "
        "That is a fact about silicon in the module that speaks HTTP, and two "
        "copies of it is the arrangement that rots quietly"
    )
    assert not hasattr(api, "RP2040_BOOT2_BYTES"), "same, for boot2's length"

    described = catalogue.described_chips()
    checked = 0
    for chip in catalogue.CHIPS:
        if chip.upper().replace("-", "") not in described:
            continue
        module = __import__(api.description_module(chip), fromlist=["*"])
        core = catalogue.CHIPS[chip][1]
        if "VECTOR_TABLE_OFFSETS" not in [
            r.name for r in contract.core_requirements(core)
        ]:
            continue
        assert isinstance(module.VECTOR_TABLE_OFFSETS, tuple)
        checked += 1
    assert checked >= 2, f"only {checked} described chips compared; expected both"


# --- a board missing a part fails with the part named ------------------------


def test_a_board_supplying_nothing_is_missing_everything():
    expected = [r.name for r in contract.requirements("cortexm0")]
    assert contract.missing(NotABoard, "cortexm0") == expected


def test_a_board_missing_one_part_is_missing_only_that_one():
    """Reported as a list rather than the first failure, so a board written
    from scratch learns everything it owes in one run."""
    assert contract.missing(OnlyInstalls, "cortexm0") == ["VECTOR_TABLE_OFFSETS"]


def test_the_same_board_owes_nothing_further_on_a_machine_without_a_table():
    """The point of OH-52, stated as the smallest possible fact.

    `OnlyInstalls` is one module. Checked as an Armv6-M board it is missing
    `VECTOR_TABLE_OFFSETS`; checked as an AVR board it is complete. Nothing
    about the module changed -- what changed is which machine is asking, which
    is the thing the contract could not previously express.
    """
    assert contract.missing(OnlyInstalls, "cortexm0") == ["VECTOR_TABLE_OFFSETS"]
    assert contract.missing(OnlyInstalls, "avr") == []


def test_the_failure_names_the_part():
    with pytest.raises(contract.RuntimeContractError) as caught:
        contract.check(OnlyInstalls, "cortexm0")
    assert "VECTOR_TABLE_OFFSETS" in str(caught.value)


def test_the_failure_says_what_breaks_without_it():
    """A name tells a reader what to type; the reason tells them what to put
    in it. `core/cortexm0/machine.py enter()` is the caller, and the message
    says so -- along with which machine was asking, since the same module can
    be complete on one and not on another."""
    with pytest.raises(contract.RuntimeContractError) as caught:
        contract.check(OnlyInstalls, "cortexm0")
    assert "core/cortexm0/machine.py enter()" in str(caught.value)
    assert "reset vector" in str(caught.value)
    assert "as a cortexm0 board" in str(caught.value)


def test_a_core_with_no_machine_module_cannot_host_a_board():
    """Not "this board owes nothing". `core/riscv32` is built today and has no
    `machine.py`, so nothing knows how a RISC-V board powers on -- and an empty
    requirement list would make that indistinguishable from a board that
    satisfies everything, which is the vacuous-pass failure this repository
    refuses everywhere else."""
    with pytest.raises(contract.RuntimeContractError) as caught:
        contract.core_requirements("riscv32")
    assert "core.riscv32.machine" in str(caught.value)
    assert "cannot host a board" in str(caught.value)


def test_a_board_that_satisfies_the_contract_raises_nothing():
    from webui.boards import rp2040

    contract.check(rp2040, contract.core_for(rp2040))


# --- the contract cannot grow without a caller -------------------------------


def test_every_requirement_names_a_file_that_exists_and_mentions_it():
    """The admission test, enforced rather than described.

    `Requirement.why` names the caller that asks for the part. This checks the
    file it names is real and does mention the part -- so a requirement added
    because a board "ought" to have it fails here, which is the ticket's own
    warning made structural: *the contract must not become a list of registers
    a board is expected to fill in*.
    """
    cores = sorted({contract.core_for(m) for m in contract.board_modules()})
    assert cores, "no board modules to derive cores from"
    every = list(contract.REQUIRED)
    for core in cores:
        every.extend(contract.core_requirements(core))

    for requirement in every:
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
    copied wrong*.

    Counted per machine rather than over `REQUIRED` alone, because moving a
    requirement into `core/<core>/machine.py` must not be a way of getting it
    past this. What a board author reads is the total for their board.
    """
    for core in sorted({contract.core_for(m) for m in contract.board_modules()}):
        wanted = contract.requirements(core)
        assert len(wanted) <= 5, (
            f"a {core} board owes {len(wanted)} things; each one taxes every "
            f"future board on that machine, so adding one should be "
            f"uncomfortable"
        )


# --- what a machine module owes, as against what a board owes ---------------


def test_every_machine_view_carries_a_register_called_pc():
    """`webui/static/emulator.js` looks the program counter up **by name**, and
    this is what makes that safe rather than hopeful.

    It used to read `state.registers[15]`, which is the PC on Armv6-M and on
    nothing else -- index 15 of an AVR's view is r15, an ordinary working
    register. Finding it by name is only better if the name is always there, so
    the invariant is asserted here, in Python, where a failure names the core
    instead of leaving the pane to render `undefined`.

    Each board is installed onto a real core first, because `view()` reads a
    configured machine: an AVR that has never been sized has no data space, and
    its register file *is* data space.
    """
    import importlib

    seen = 0
    for module in contract.board_modules():
        core = contract.core_for(module)
        machine = importlib.import_module(f"core.{core}.machine")
        abi = pytest.importorskip(f"core.{core}.abi")
        with abi.Cpu() as cpu:
            machine.blank(cpu)
            module.install(cpu)
            view = machine.view(cpu)
        by_name = {register.name: register for register in view.registers}
        assert "pc" in by_name, f"{core} names no pc: {sorted(by_name)}"
        assert by_name["pc"].value == view.pc, (
            f"{core}: the pc register and View.pc disagree"
        )
        seen += 1
    assert seen >= 2, f"only {seen} board modules; expected at least two machines"


def test_the_machine_modules_agree_on_the_shapes_they_return():
    """The drift guard for the half of the runtime contract `contract.py` does
    not hold.

    `Entry`, `Register` and `View` are declared in **each** `machine.py` rather
    than imported from one place, which is the convention
    `webui/boards/rp2040.py` and `samd21.py` already keep for their `Cpu`
    protocols: a reader sees the whole dependency without chasing an import.
    The price is that two definitions must agree, and `core/avr/cpu.h` says at
    length what happens to two things that must agree and are not checked.

    So they are checked. `webui/api.py` reads these fields positionally by
    name -- `placement.window`, `view.pc` -- and a machine that renamed one
    would fail at the moment a person loaded that board, not here.
    """
    import dataclasses
    import importlib

    shapes = {}
    for core in sorted({contract.core_for(m) for m in contract.board_modules()}):
        machine = importlib.import_module(f"core.{core}.machine")
        shapes[core] = {
            name: tuple(f.name for f in dataclasses.fields(getattr(machine, name)))
            for name in ("Entry", "Register", "View")
        }

    assert len(shapes) >= 2, f"only {len(shapes)} machines to compare"
    first, *rest = shapes.values()
    for other in rest:
        assert other == first, f"machine modules disagree: {shapes}"
    assert first["Entry"] == ("entry", "window", "detail", "notes")
    assert first["Register"] == ("name", "value", "width")
    assert first["View"] == ("registers", "flags", "pc")


def test_a_register_states_its_own_width_rather_than_a_page_assuming_one():
    """An AVR register is eight bits and an Armv6-M one is thirty-two. Rendered
    through a fixed eight hex digits, `r0` on an Uno reads `0x000000A5` --
    which is not a cosmetic problem, it states a width the machine does not
    have."""
    import importlib

    widths = {}
    for module in contract.board_modules():
        core = contract.core_for(module)
        machine = importlib.import_module(f"core.{core}.machine")
        abi = pytest.importorskip(f"core.{core}.abi")
        with abi.Cpu() as cpu:
            machine.blank(cpu)
            module.install(cpu)
            widths[core] = {r.name: r.width for r in machine.view(cpu).registers}

    assert widths["cortexm0"]["r0"] == 32
    assert widths["avr"]["r0"] == 8, "an AVR working register is a byte"
    assert widths["avr"]["sp"] == 16, "its pointers are not"


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
