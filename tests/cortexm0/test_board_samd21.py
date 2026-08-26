# OpenHardware — the SAMD21's registers over the Cortex-M0+ core.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# The core knows no addresses and this file is where this chip's are tested.
# Register facts come from Microchip's generated CMSIS headers, shipped in
# `framework-arduino-samd@1.8.14`; `webui/boards/samd21.py` cites the file and
# line for each one.
#
# Read this against `test_board_rp2040.py`. The pair is the evidence that the
# core is the architecture and the board files are the chips -- and the places
# they *disagree* are more informative than the places they match.

import pytest

from core.cortexm0.abi import MemoryFault
from webui.boards import samd21


@pytest.fixture
def board(cpu):
    """A whole SAMD21, replacing the bare SRAM the conftest fixture installs.

    `clear_regions` first for the reason the RP2040 fixture gives: the conftest
    hands every test a flat SRAM at 0x20000000 for the instruction suites, the
    board adds its own there too, and overlapping regions are refused.
    """
    cpu.clear_memory()
    cpu.clear_regions()
    samd21.install(cpu)
    return cpu


# --- the memory map, which is the point of the file -------------------------


def test_flash_is_at_zero_and_is_executable(board):
    """`FLASH_ADDR` is 0x00000000 on this part. The RP2040 puts it at
    0x10000000, and a core holding either as a constant could not serve both --
    which it did, until the map moved out."""
    assert samd21.FLASH == 0x00000000
    board.write_word(samd21.FLASH, 0x2000)
    assert board.read_word(samd21.FLASH) == 0x2000


def test_untouched_flash_reads_as_erased_rather_than_as_zeros(board):
    """0xFF is what an erased part reads, and 0xFFFF is not a valid Thumb
    encoding, so a program running off the end of its image stops. Zeros decode
    as `MOVS r0, r0` and would run quietly forever."""
    assert board.read_word(samd21.FLASH + 0x10000) == 0xFFFFFFFF


def test_sram_is_thirty_two_kilobytes_not_the_rp2040s_two_hundred_and_sixty_four(board):
    """The G18A has 32K. Sharing a core does not mean sharing a size, and the
    last addressable word is the cheapest place for an off-by-one to show."""
    assert samd21.SRAM_SIZE == 32 * 1024
    last = samd21.SRAM + samd21.SRAM_SIZE - 4
    board.write_word(last, 0xA5A5A5A5)
    assert board.read_word(last) == 0xA5A5A5A5
    with pytest.raises(MemoryFault):
        board.read_word(samd21.SRAM + samd21.SRAM_SIZE)


def test_there_is_no_boot_rom_stub_because_flash_is_what_lives_at_zero(board):
    """The RP2040 needs a non-executable 16 KB stub at zero for mask ROM this
    project cannot ship. Modelling one here would put an unshippable ROM over
    the address the vector table is actually at, so its absence is the accurate
    model rather than an omission."""
    assert board.in_range(0x00000000)
    assert board.in_range(0x00003FFC)     # inside what would be the RP2040 ROM


# --- PORT -------------------------------------------------------------------


def test_dirset_sets_only_the_bits_written(board):
    base = samd21.group(samd21.PORTA)
    board.write_word(base + samd21.PORT_DIR, 0b0100)
    board.write_word(base + samd21.PORT_DIRSET, 0b0001)
    assert board.read_word(base + samd21.PORT_DIR) == 0b0101


def test_dirclr_clears_only_the_bits_written(board):
    base = samd21.group(samd21.PORTA)
    board.write_word(base + samd21.PORT_DIR, 0b1111)
    board.write_word(base + samd21.PORT_DIRCLR, 0b0110)
    assert board.read_word(base + samd21.PORT_DIR) == 0b1001


def test_outtgl_toggles_the_bits_written(board):
    """This is how the blink blinks. A plain store here would set the pin once
    and never clear it, because the image writes the mask rather than a
    value."""
    base = samd21.group(samd21.PORTA)
    board.write_word(base + samd21.PORT_OUT, 0b1010)
    board.write_word(base + samd21.PORT_OUTTGL, 0b0110)
    assert board.read_word(base + samd21.PORT_OUT) == 0b1100


def test_direction_and_value_are_separate_registers(board):
    """Driving a pin high and making it an output are two different writes, and
    a model that aliased both onto one word would blink a pin that is still an
    input."""
    base = samd21.group(samd21.PORTA)
    board.write_word(base + samd21.PORT_DIRSET, 1 << 17)
    assert board.read_word(base + samd21.PORT_DIR) == 1 << 17
    assert board.read_word(base + samd21.PORT_OUT) == 0


def test_the_set_registers_read_back_their_target_unlike_sios(board):
    """**The one place this file departs from `rp2040.py`'s shape, on
    evidence.** SIO's `GPIO_OUT_SET` is a dedicated write-only register and
    reads zero. PORT's `OUTSET` looks identical and is not: Microchip's own
    header marks it `__IO ... (R/W 32)`, and marks `WRCONFIG` `__O ... ( /W
    32)` in the same struct -- so the header does draw the write-only
    distinction and declines to draw it here.

    Pinning it because the pull toward copying SIO's answer across is strong
    and would be a wrong value rather than a loud fault, which is the failure
    class this project treats as worst."""
    base = samd21.group(samd21.PORTA)
    board.write_word(base + samd21.PORT_OUT, 0xABC)
    assert board.read_word(base + samd21.PORT_OUTSET) == 0xABC
    assert board.read_word(base + samd21.PORT_OUTCLR) == 0xABC
    assert board.read_word(base + samd21.PORT_OUTTGL) == 0xABC
    assert board.read_word(base + samd21.PORT_DIRSET) == 0


def test_there_are_no_bus_level_atomic_alias_windows(board):
    """The RP2040's +0x1000/+0x2000/+0x3000 windows are a property of that
    chip's bus, not of Arm. Modelling them here would invent three registers
    per register that the part does not have."""
    base = samd21.group(samd21.PORTA)
    for offset in (0x1000, 0x2000, 0x3000):
        with pytest.raises(MemoryFault):
            board.read_word(base + samd21.PORT_OUT + offset)


def test_port_group_b_is_a_separate_set_of_registers_at_the_stride(board):
    """Two groups at 0x80, from `REG_PORT_DIR0` and `REG_PORT_DIR1` in the
    instance header. Writing PA must not move PB."""
    assert samd21.group(1) - samd21.group(0) == 0x80
    board.write_word(samd21.group(0) + samd21.PORT_OUT, 0xF0)
    board.write_word(samd21.group(1) + samd21.PORT_OUT, 0x0F)
    assert board.read_word(samd21.group(0) + samd21.PORT_OUT) == 0xF0
    assert board.read_word(samd21.group(1) + samd21.PORT_OUT) == 0x0F


def test_a_third_port_group_is_refused_by_name_rather_than_computed(board):
    """`group(2)` is an address this part does not have. Returning one would
    hand back a plausible number inside PORT's window, and the caller would
    read zeros from a group that does not exist."""
    with pytest.raises(ValueError) as caught:
        samd21.group(2)
    assert "2" in str(caught.value)


# --- the clock tree, and the four polls that have to terminate --------------
#
# `tests/cortexm0/test_samd21_arduino.py` proves these end to end by running a
# real image, and it needs an Arm toolchain to do it. These four run
# everywhere, because a wrong poll direction is a HANG rather than a fault --
# the one failure `core/cortexm0/cpu.h` cannot make loud, since the address is
# modelled and the read does answer -- and it should not take a toolchain to
# catch it.


#: The five `PCLKSR` bits `startup.c` waits on, by position from
#: `component/sysctrl.h:270-283`.
#:
#: **Spelled out here rather than compared against `samd21.CLOCKS_ALL_READY`**,
#: and the first version of these tests did exactly that and stayed green when
#: the constant was mutated to zero. A test whose expectation is read from the
#: thing it is testing pins nothing -- the same defect
#: `tests/cortexm0/test_conformance.py` records under a different name, where a
#: floor of `len(FAMILIES)` moved with the corpus it was meant to hold still.
XOSC32KRDY = 1 << 1
OSC32KRDY = 1 << 2
DFLLRDY = 1 << 4
DFLLLCKF = 1 << 6
DFLLLCKC = 1 << 7


def test_every_clock_reports_ready_because_nothing_here_has_to_start(board):
    """`PCLKSR` is waited on until a bit is SET, ten times in `SystemInit`.
    Reading zero hangs the very first wait, before a sketch runs at all."""
    status = board.read_word(samd21.SYSCTRL + samd21.SYSCTRL_PCLKSR)
    for bit in (XOSC32KRDY, OSC32KRDY, DFLLRDY, DFLLLCKF, DFLLLCKC):
        assert status & bit, f"PCLKSR bit 0x{bit:x} clear in 0x{status:08x}"


def test_the_ready_register_is_read_only_as_the_header_marks_it(board):
    """`__I` in `component/sysctrl.h:918`. A write that stuck would let one
    line of firmware turn every ready bit off and hang the next wait -- and
    `map_constant` is what makes the write inert, as hardware does."""
    board.write_word(samd21.SYSCTRL + samd21.SYSCTRL_PCLKSR, 0)
    status = board.read_word(samd21.SYSCTRL + samd21.SYSCTRL_PCLKSR)
    assert status & DFLLRDY, f"a write cleared PCLKSR: 0x{status:08x}"


def test_the_three_syncbusy_bits_read_clear_and_not_set(board):
    """**The other direction, and getting it backwards hangs just as hard.**

    `GCLK`, `ADC` and `DAC` are each waited on until `SYNCBUSY` is CLEAR, and
    all three of those bits are bit 7 of a `STATUS` byte that shares a word
    with registers firmware does write. So this checks the byte, not the word:
    a model that mapped the word as a constant of all-ones, or that let a
    neighbouring write spill into it, would spin forever with no diagnostic.
    """
    syncbusy = 1 << 7
    # GCLK STATUS is byte 1 of the word at GCLK+0x00, ADC STATUS byte 1 of
    # ADC+0x18, DAC STATUS byte 3 of DAC+0x04.
    for address, byte in (
        (samd21.GCLK + samd21.GCLK_CTRL, 1),
        (samd21.ADC + samd21.ADC_INTFLAG, 1),
        (samd21.DAC + samd21.DAC_INTENCLR, 3),
    ):
        status = (board.read_word(address) >> (8 * byte)) & 0xFF
        assert status & syncbusy == 0, f"0x{address:08x} byte {byte} reads busy"


def test_the_masks_start_at_the_reset_values_the_header_gives(board):
    """`SystemInit` does `PM->APBAMASK.reg |= PM_APBAMASK_GCLK`, a
    read-modify-write. A register starting at zero would write back six
    enables cleared that a real part has set before the first instruction --
    the class of wrong answer this board's own comments spend their length
    refusing."""
    assert board.read_word(samd21.PM + samd21.PM_APBAMASK) == 0x0000007F
    assert board.read_word(samd21.PM + samd21.PM_APBCMASK) == 0x00010000
    assert board.read_word(samd21.SYSCTRL + samd21.SYSCTRL_OSC8M) == 0x87070382


def test_the_calibration_row_is_readable_flash_and_not_a_register(board):
    """`NVMCTRL_OTP4` at 0x00806020, outside the 256K program flash. Erased,
    because this model has no factory trim to offer -- see `install_memory`,
    which says what that costs."""
    assert board.in_range(samd21.CALIBRATION)
    assert board.read_word(samd21.CALIBRATION) == 0xFFFFFFFF
    assert board.read_word(samd21.CALIBRATION + 4) == 0xFFFFFFFF


def test_pin_configuration_is_a_stored_byte_per_pin(board):
    """`pinMode` read-modify-writes one byte of `PINCFG`, so a write to pin 17
    must not disturb pin 16 -- which is the whole reason the core masks a byte
    write rather than storing the word."""
    base = samd21.group(samd21.PORTA) + samd21.PORT_PINCFG
    board.write_word(base + 16, 0x00000002)
    board.write_word(base + 16, board.read_word(base + 16) | 0x00020000)
    assert board.read_word(base + 16) == 0x00020002


# --- what this board does not model ----------------------------------------


def test_an_unmodelled_register_inside_port_still_faults(board):
    """`WRCONFIG` at 0x28 is real silicon and is not modelled, because no image
    here has reached it. It must fault rather than answer zero."""
    with pytest.raises(MemoryFault):
        board.read_word(samd21.group(samd21.PORTA) + 0x28)


def test_reading_the_input_register_faults_rather_than_answering_a_stale_zero(board):
    """`IN` is unmapped deliberately. It reads the pin's electrical level, so
    on a pin driven as an output it follows `OUT` -- and a stored register
    reading zero would tell firmware that drove PA17 high that the pin is low.

    This is the whole distinction between the two ways a model can be
    incomplete. Faulting says "nobody has modelled this"; answering zero says
    "the pin is low", which is a different sentence and sometimes a false one.
    Pinned so that adding `map_register(base + PORT_IN, 0)` -- the obvious
    change, and the one `rp2040.py`'s `GPIO_IN` makes look right -- fails here
    rather than passing quietly."""
    base = samd21.group(samd21.PORTA)
    board.write_word(base + samd21.PORT_DIRSET, 1 << 17)
    board.write_word(base + samd21.PORT_OUTSET, 1 << 17)
    with pytest.raises(MemoryFault):
        board.read_word(base + samd21.PORT_IN)


def test_a_peripheral_this_board_does_not_model_still_faults(board):
    """Absent must mean loud: a poll of an unmodelled ready bit that answered
    zero would hang silently, which is the failure `docs/architectures.md` §3
    is about.

    **This list shrank on 2026-08-26 and GCLK left it, deliberately.** It used
    to hold `0x40000C00` as well, on the reasoning that PORT is clocked at
    reset so a blink never reaches GCLK. That is still true of a blink and
    stopped being true of the board: a vendor Arduino image configures the
    whole clock tree before `main`, so GCLK is modelled now and
    `tests/cortexm0/test_samd21_arduino.py` is the image that reaches it.

    What is left is the two words of PM that **still** nothing reaches --
    `CTRL`/`SLEEP` at 0x00, and `APBBMASK` at 0x1C, whose absence is the same
    claim `test_samd21_blink.py` makes from the other end: PORT is already
    clocked, so nobody has to enable it.
    """
    for address in (0x40000400, 0x4000041C):
        with pytest.raises(MemoryFault):
            board.read_word(address)


def test_the_rp2040s_peripherals_are_not_at_home_on_this_board(board):
    """SIO at 0xD0000000 and RESETS at 0x4000C000 belong to the other chip. If
    installing one board left the other's registers mapped, every test here
    would be checking a merged fiction of both parts."""
    for address in (0xD0000000, 0x4000C000):
        with pytest.raises(MemoryFault):
            board.read_word(address)
