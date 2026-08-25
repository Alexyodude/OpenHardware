# OpenHardware — memory-mapped registers on the RV32 core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What these are protecting
#
# One sentence from `core/riscv32/cpu.h`, which is the whole reason MMIO exists
# separately from `add_region`: *mapping peripheral space as a plain region
# turns every wait-for-ready poll into an infinite loop*. A region gives back
# what was written; a peripheral does not.
#
# So the tests below are mostly about the three answers that are **not** "what
# you wrote":
#
#   * an unmodelled address in a peripheral **faults**, and says which address
#   * a write-only register reads as **zero**, which is the part's answer
#   * a W1TS/W1TC alias **modifies another register** rather than storing
#
# ## And one that is about neither
#
# `test_a_register_is_not_a_region` pins that `in_range` and `is_mapped` are
# exclusive. `webui/api.py` leans on that: its memory window refuses a mapped
# register by name and tells the caller to use `words=` instead, and the two
# predicates agreeing would make that refusal unreachable.

import pytest

from core.riscv32 import abi

from . import encode as e

#: ESP32-C3 GPIO, from the Technical Reference Manual chapter 5. Used because
#: it is the block `webui/boards/esp32c3.py` describes, so a change to these
#: offsets shows up here as well as there.
GPIO = 0x60004000
GPIO_OUT = GPIO + 0x04
GPIO_OUT_W1TS = GPIO + 0x08
GPIO_OUT_W1TC = GPIO + 0x0C
GPIO_ENABLE = GPIO + 0x20
UNMODELLED = GPIO + 0x40

#: Where the little programs below are placed. The C3's flash execute
#: window, so the addresses read like a real image's.
PROGRAM = 0x42000000


@pytest.fixture
def gpio(cpu):
    """The session core with GPIO mapped the way a board would map it.

    **Takes `cpu` rather than defining one**, and that is not a style choice.
    `conftest.py` has an autouse `_fresh_board` that un-installs whatever the
    previous test described -- so a fixture of the same name here is set up
    first and then wiped, and every mapping silently vanishes before the test
    body runs. Depending on `cpu` puts this after the reset instead of under
    it.

    No peripheral region is added: every address these tests touch is either a
    mapped register or nothing, so a result that came from bulk memory would be
    visible rather than plausible.
    """
    cpu.map_register(GPIO_OUT, 0)
    cpu.map_register(GPIO_ENABLE, 0)
    cpu.map_alias(GPIO_OUT_W1TS, GPIO_OUT, "set", readable=False)
    cpu.map_alias(GPIO_OUT_W1TC, GPIO_OUT, "clear", readable=False)
    return cpu


def test_a_mapped_register_reads_back_what_was_written(gpio):
    gpio.write_word(GPIO_OUT, 0xDEADBEEF)
    assert gpio.read_word(GPIO_OUT) == 0xDEADBEEF


def test_a_register_starts_at_the_reset_value_the_board_gave_it(gpio):
    """The reset value is a chip fact and comes from the board, so a register
    mapped with one answers it before anything has written."""
    with abi.Cpu() as fresh:
        fresh.map_register(GPIO_ENABLE, 0x0000_00FF)
        assert fresh.read_word(GPIO_ENABLE) == 0x0000_00FF


def test_an_unmodelled_address_in_the_same_peripheral_faults(gpio):
    """**The one that matters most.** 0x60004040 is inside GPIO and is not
    described, and answering zero there is how firmware polling a status bit
    spins forever. The fault names the address, which is what says which
    register the board description is missing."""
    with pytest.raises(abi.MemoryFault) as caught:
        gpio.read_word(UNMODELLED)
    assert "60004040" in str(caught.value).lower()


def test_a_write_to_an_unmodelled_address_faults_too(gpio):
    """Both directions. A write that silently vanished would let firmware
    configure a peripheral this model does not have and then behave as though
    it had been configured."""
    with pytest.raises(abi.MemoryFault):
        gpio.write_word(UNMODELLED, 1)


# --- the aliases, which is what an ESP32 GPIO block is made of --------------


def test_a_set_alias_sets_bits_in_its_target_without_touching_the_others(gpio):
    """W1TS: write-one-to-set. The bits written are set and the rest are left,
    which is the whole point of the register existing -- firmware uses it to
    avoid a read-modify-write that could race an interrupt."""
    gpio.write_word(GPIO_OUT, 0b1010)
    gpio.write_word(GPIO_OUT_W1TS, 0b0101)
    assert gpio.read_word(GPIO_OUT) == 0b1111


def test_a_clear_alias_clears_only_the_bits_written(gpio):
    gpio.write_word(GPIO_OUT, 0b1111)
    gpio.write_word(GPIO_OUT_W1TC, 0b0101)
    assert gpio.read_word(GPIO_OUT) == 0b1010


def test_writing_zero_to_an_alias_changes_nothing(gpio):
    """Not a special case in the code, and worth pinning anyway: a W1TS write
    of zero sets no bits. A model that stored instead of setting would clear
    the register, and firmware that used W1TS as a no-op guard would silently
    turn its outputs off."""
    gpio.write_word(GPIO_OUT, 0b1111)
    gpio.write_word(GPIO_OUT_W1TS, 0)
    assert gpio.read_word(GPIO_OUT) == 0b1111


def test_a_write_only_alias_reads_as_zero_and_not_as_its_target(gpio):
    """The architecture's answer, not this model shrugging.

    Hardware reads W1TS as zero. Returning `GPIO_OUT` there would be a *wrong
    value* rather than a missing feature -- and `webui/boards/samd21.py`
    documents the opposite case, where the vendor header marks the same-shaped
    registers readable, so this is a per-chip fact and not a default.
    """
    gpio.write_word(GPIO_OUT, 0xFFFF)
    assert gpio.read_word(GPIO_OUT_W1TS) == 0
    assert gpio.read_word(GPIO_OUT_W1TC) == 0


def test_a_readable_alias_answers_its_target(gpio):
    """The other half of `readable`, so the flag is exercised both ways. A
    bus alias window is a second view of the register and reads as it."""
    gpio.map_alias(GPIO + 0x30, GPIO_OUT, "set", readable=True)
    gpio.write_word(GPIO_OUT, 0x1234)
    assert gpio.read_word(GPIO + 0x30) == 0x1234


def test_an_alias_onto_an_unmapped_target_faults_rather_than_inventing_one(gpio):
    """A board description mistake, and faulting says so. Answering zero would
    be the silent hang this whole design refuses, arriving by a different
    door."""
    gpio.map_alias(GPIO + 0x34, GPIO + 0x800, "set", readable=True)
    with pytest.raises(abi.MemoryFault):
        gpio.read_word(GPIO + 0x34)
    with pytest.raises(abi.MemoryFault):
        gpio.write_word(GPIO + 0x34, 1)


def test_an_unknown_write_op_is_refused_by_name(gpio):
    """At the binding, before it reaches C. A board that meant `clear` and got
    `store` would turn a W1TC register into one that overwrites -- so an
    unknown name raises rather than falling back to a default."""
    with pytest.raises(abi.AbiError) as caught:
        gpio.map_alias(GPIO + 0x38, GPIO_OUT, "toggle")
    assert "toggle" in str(caught.value)
    assert "store" in str(caught.value), "and says what the choices are"


# --- sub-word access, which is where the Arm core had to be fixed ------------


def _run(cpu, program: list[int], regs: dict[int, int]) -> None:
    """Execute `program` at PROGRAM with `regs` preloaded.

    The sub-word paths are exercised through **executed instructions** rather
    than through the binding, and deliberately: `abi.Cpu` exposes only word and
    block access, and a real `sb` against a peripheral is how this path is
    actually reached. Adding byte accessors to the ABI to test it would test
    the accessors instead.
    """
    cpu.add_region(PROGRAM, 0x100, executable=True)
    for index, word in enumerate(program):
        cpu.write_word(PROGRAM + index * 4, word)
    values = [0] * 32
    for index, value in regs.items():
        values[index] = value
    cpu.set_regs(values, pc=PROGRAM)
    for _ in program:
        cpu.step()


def test_a_byte_write_reaches_a_register_and_leaves_its_neighbours(gpio):
    """ESP32 peripheral registers are word-accessed by convention, but nothing
    stops a compiler emitting `sb` against one.

    `core/cortexm0` shipped without this and had to have it added: a byte
    access that fell through to the region lookup faults at an address the
    board describes perfectly well.
    """
    gpio.write_word(GPIO_OUT, 0xAABBCCDD)
    #: t0 holds GPIO_OUT, t1 the byte. `sb t1, 1(t0)` -- the second byte only.
    _run(gpio, [e.sb("t1", "t0", 1)], {5: GPIO_OUT, 6: 0x11})
    assert gpio.read_word(GPIO_OUT) == 0xAABB11DD


def test_a_byte_read_takes_the_right_byte_of_the_register(gpio):
    gpio.write_word(GPIO_OUT, 0xAABBCCDD)
    got = []
    for offset in range(4):
        _run(gpio, [e.lbu("t2", "t0", offset)], {5: GPIO_OUT})
        got.append(gpio.reg(7))
        gpio.clear_regions()
        gpio.map_register(GPIO_OUT, 0xAABBCCDD)
    assert got == [0xDD, 0xCC, 0xBB, 0xAA]


def test_a_halfword_write_reaches_the_right_half(gpio):
    gpio.write_word(GPIO_OUT, 0xAABBCCDD)
    _run(gpio, [e.sh("t1", "t0", 2)], {5: GPIO_OUT, 6: 0x1234})
    assert gpio.read_word(GPIO_OUT) == 0x1234CCDD


def test_every_byte_of_a_register_names_the_same_entry(gpio):
    """The address is masked to a word boundary when mapped, so all four bytes
    are the register. Otherwise `is_mapped` would answer true for one address
    in four and a byte access to the others would fault."""
    assert all(gpio.is_mapped(GPIO_OUT + offset) for offset in range(4))


# --- registers and regions are exclusive ------------------------------------


def test_a_register_is_not_a_region(gpio):
    """`webui/api.py` leans on this: its memory window refuses a mapped
    register by name and points the caller at `words=`. If both predicates
    answered true, that refusal would be unreachable and a hexdump would try to
    block-read a peripheral."""
    assert gpio.is_mapped(GPIO_OUT)
    assert not gpio.in_range(GPIO_OUT, 4)


def test_a_region_is_not_a_register(gpio):
    gpio.add_region(0x3FC80000, 0x1000, executable=False)
    assert gpio.in_range(0x3FC80000, 4)
    assert not gpio.is_mapped(0x3FC80000)


def test_clearing_the_regions_forgets_the_peripherals_too(gpio):
    """A machine with no board has no peripherals either. Leaving them behind
    would let a second board inherit the first one's registers, which is the
    kind of state that makes one test pass only when another ran first."""
    assert gpio.is_mapped(GPIO_OUT)
    gpio.clear_regions()
    assert not gpio.is_mapped(GPIO_OUT)


def test_a_reset_machine_has_no_peripherals(gpio):
    """`reset` is what `core/riscv32/machine.py`'s `blank` calls, so a board
    installing onto a used core starts from nothing."""
    assert gpio.is_mapped(GPIO_OUT)
    gpio.reset()
    assert not gpio.is_mapped(GPIO_OUT)


# --- and firmware can actually drive one ------------------------------------


def test_a_program_can_set_a_gpio_bit_through_the_alias(gpio):
    """The point of all of the above, executed rather than called.

    `lui a4, 0x60004` then `sw a5, 8(a4)` is what a compiler emits for a W1TS
    write, and it is the sequence `tests/riscv32/c3blink/blink.c` compiles to
    a variant of.
    """
    gpio.add_region(0x42000000, 0x100, executable=True)
    program = [
        0x60004737,          # lui  a4, 0x60004
        0x10000793,          # li   a5, 0x100
        0x00F72423,          # sw   a5, 8(a4)     -- GPIO_OUT_W1TS
    ]
    for index, word in enumerate(program):
        gpio.write_word(0x42000000 + index * 4, word)
    gpio.set_regs([0] * 32, pc=0x42000000)
    for _ in range(len(program)):
        gpio.step()
    assert gpio.read_word(GPIO_OUT) == 0x100
