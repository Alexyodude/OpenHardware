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
from .conftest import load

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


# --- a stream, because a transmit FIFO is not a register (OH-161) ------------
#
# The addresses are the ESP32-C3's UART0, from
# `framework-arduinoespressif32/tools/sdk/esp32c3/include/soc/esp32c3/include/
# soc/uart_reg.h`: `UART_FIFO_REG(i)` at `REG_UART_BASE(i) + 0x0` (:22) and
# `UART_CLK_CONF_REG(i)` at `+ 0x78` (:1160), whose `UART_TX_SCLK_EN` is
# `BIT(24)` (:1181) with `default: 1'b1`. **Those are that file's line
# numbers and not the ESP-IDF v5.5 copy's**, which has the same four defines
# eight lines earlier; the two trees are both in reach here and citing one
# while reading the other is the drift `docs/esp-idf-reference.md` exists to
# prevent. Used here for the same reason the
# GPIO addresses above are: they are the block `webui/boards/esp32c3.py`
# describes, so a change shows up in both places.

UART0 = 0x60000000
UART_FIFO = UART0 + 0x00
UART_CLK_CONF = UART0 + 0x78
UART_TX_SCLK_EN = 1 << 24


@pytest.fixture
def uart():
    """A bare machine with UART0's FIFO and its transmit gate, gate open."""
    cpu = abi.Cpu()
    cpu.map_register(UART_CLK_CONF, UART_TX_SCLK_EN)
    cpu.map_stream(UART_FIFO, enable=UART_CLK_CONF, enable_mask=UART_TX_SCLK_EN)
    return cpu


def test_a_stream_keeps_every_byte_where_a_register_would_keep_the_last(uart):
    """The whole reason this behaviour exists. A `map_register` at the FIFO
    would answer `o` after a program printed `hello`, which reads as a
    plausible single character rather than as a wrong answer."""
    for byte in b"hello":
        uart.write_word(UART_FIFO, byte)
    assert uart.stream(UART_FIFO) == b"hello"


def test_the_fifo_reads_as_zero_rather_than_faulting(uart):
    """A data register that faulted on read would be a board nothing could
    probe, and `is_mapped` has to see it so `webui/api.py`'s memory window
    refuses it by name rather than dumping it as bulk memory."""
    uart.write_word(UART_FIFO, ord("q"))
    assert uart.is_mapped(UART_FIFO)
    assert uart.read_word(UART_FIFO) == 0


def test_nothing_is_captured_while_the_transmit_gate_is_clear(uart):
    """The clear-air case: firmware that switched the transmitter off is
    silent, exactly as the part is. Without the gate a model lets a program
    appear to print before it enabled the peripheral."""
    uart.write_word(UART_CLK_CONF, 0)
    for byte in b"lost":
        uart.write_word(UART_FIFO, byte)
    assert uart.stream(UART_FIFO) == b""

    uart.write_word(UART_CLK_CONF, UART_TX_SCLK_EN)
    uart.write_word(UART_FIFO, ord("k"))
    assert uart.stream(UART_FIFO) == b"k", "and it transmits again when re-enabled"


def test_a_stream_whose_gate_was_never_mapped_faults_rather_than_capturing():
    """A board naming the wrong gate address is a description mistake, and
    faulting says so. Capturing regardless would print bytes a real part
    would have discarded -- the wrong answer this core refuses to give."""
    cpu = abi.Cpu()
    cpu.map_stream(UART_FIFO, enable=UART_CLK_CONF, enable_mask=UART_TX_SCLK_EN)
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.write_word(UART_FIFO, ord("x"))
    assert hex(UART_FIFO) in str(caught.value)
    assert cpu.stream(UART_FIFO) == b""


def test_an_executed_store_through_an_unmapped_gate_names_the_fifo():
    """A fault's whole job is to say WHICH address the board does not model.

    **No `uart` fixture**, deliberately and unlike every test around it: that
    fixture maps the gate, which is the one thing this test needs absent. It
    took the fixture and ignored it until the OH-161 review pointed out that
    a reader following the signature would be sent the wrong way.

    **Through `step()` and not `write_word`**, because only `step()` reads
    the address the core recorded: `abi.py`'s `write_word` formats the
    address the caller just passed, so it prints the right number whatever
    the core stored, and the sibling test above cannot see this at all.

    Found by review after a fix of mine deleted the `note_fault` in that
    branch, on the assumption `mmio_read` had already recorded it. It has
    not: `mmio_read`'s `mmio_.find` miss returns false WITHOUT noting,
    because every other caller falls through to the region lookup after it.
    So the fault kept its reset value and this store reported `access at
    0x00000000` -- a wrong address rather than a missing one, which is the
    failure `cpu.h` argues hardest against.
    """
    cpu = abi.Cpu()
    cpu.map_stream(UART_FIFO, enable=UART_CLK_CONF, enable_mask=UART_TX_SCLK_EN)
    cpu.add_region(0x42000000, 0x100, executable=True)
    program = [
        e.lui("a4", 0x60000),        # a4 = UART0
        e.addi("a5", "x0", 0x41),    # 'A'
        e.sb("a5", "a4", 0),         # the gate was never mapped
    ]
    for index, word in enumerate(program):
        cpu.write_word(0x42000000 + index * 4, word)
    cpu.set_regs([0] * 32, pc=0x42000000)
    cpu.step()
    cpu.step()
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    message = str(caught.value)
    assert f"0x{UART_FIFO:08x}" in message, message
    assert "0x00000000" not in message, "the reset value, which is not an address"
    assert cpu.stream(UART_FIFO) == b""


def test_an_address_that_is_not_a_stream_has_no_bytes(uart):
    """Empty, not an error: the caller registered the address and knows. The
    fixture that must report nothing."""
    assert uart.stream(UART_CLK_CONF) == b""
    assert uart.stream(GPIO_OUT) == b""


def test_a_reset_machine_has_no_stream_and_no_bytes(uart):
    """Bytes as well as a mapping, so a second board cannot answer with what
    the first one printed -- which is the state that makes one test pass only
    when another ran first."""
    uart.write_word(UART_FIFO, ord("a"))
    assert uart.stream(UART_FIFO) == b"a"
    uart.clear_regions()
    assert uart.stream(UART_FIFO) == b""
    assert not uart.is_mapped(UART_FIFO)


def test_a_gate_mapped_as_an_alias_is_read_through_to_its_target(uart):
    """Found by review, not by a board: no description here aliases a clock
    register, so nothing was wrong on the three ESP32 parts.

    The write path used to read the gate's stored word straight off its
    `Mapped` entry, which ignores `target` -- so a gate mapped as a readable
    ALIAS held its own zero, the stream went silent, and `read_word` on that
    same address answered the bit correctly. A peripheral that reads right and
    transmits nothing is the wrong-value class this core refuses, and it would
    have waited for the next board that aliases a clock register.
    """
    alias = UART_CLK_CONF + 0x18
    uart.map_alias(alias, UART_CLK_CONF, "store", readable=True)
    uart.map_stream(UART_FIFO, enable=alias, enable_mask=UART_TX_SCLK_EN)
    uart.write_word(UART_FIFO, ord("A"))
    assert uart.stream(UART_FIFO) == b"A", "the alias answers what its target holds"

    # And it keeps following: clearing the TARGET closes the gate the alias
    # only points at.
    uart.write_word(UART_CLK_CONF, 0)
    uart.write_word(UART_FIFO, ord("B"))
    assert uart.stream(UART_FIFO) == b"A"


def test_a_write_only_gate_reads_zero_and_so_captures_nothing(uart):
    """The other half, and it is not a bug: a W1TS-style register reads as
    zero on the part, so a board that gated a stream on one has described a
    transmitter that never transmits. The model says what the architecture
    says rather than second-guessing the description."""
    write_only = UART_CLK_CONF + 0x1C
    uart.map_alias(write_only, UART_CLK_CONF, "store", readable=False)
    uart.map_stream(UART_FIFO, enable=write_only, enable_mask=UART_TX_SCLK_EN)
    uart.write_word(UART_FIFO, ord("C"))
    assert uart.stream(UART_FIFO) == b""


def test_the_c_side_reports_the_true_length_even_into_a_small_buffer(uart):
    """`riscv32_stream`'s contract, which `abi.py`'s wrapper depends on for
    sizing and which nothing else exercises: the return is what the stream
    HOLDS, not what was copied, so a caller with its own buffer can tell it
    was short rather than reading a prefix and believing it whole."""
    import ctypes

    for byte in b"12345678":
        uart.write_word(UART_FIFO, byte)
    buffer = (ctypes.c_uint8 * 3)()
    held = uart._lib.riscv32_stream(uart._handle, UART_FIFO, buffer, 3)
    assert held == 8, "the true length, not the three copied"
    assert bytes(buffer) == b"123"
    assert uart.stream(UART_FIFO) == b"12345678", "and the wrapper sizes correctly"


def test_a_program_can_print_through_the_fifo(uart):
    """Executed rather than called, and the one place the byte-lane rule can
    be reached: `sb` is what a compiler emits for a character store.

    Byte 0 of the FIFO word carries the data field -- `UART_RXFIFO_RD_BYTE` is
    `0x000000FF` at uart_reg.h:25 -- so a store to lane 1 lands in a reserved
    lane and transmits nothing. Taking the low byte of that access regardless
    would append a zero the part never sent.
    """
    uart.add_region(0x42000000, 0x100, executable=True)
    program = [
        e.lui("a4", 0x60000),        # a4 = UART0
        e.addi("a5", "x0", 0x48),  # 'H'
        e.sb("a5", "a4", 0),         # the data lane: transmits
        e.addi("a5", "x0", 0x49),  # 'I'
        e.sb("a5", "a4", 1),         # a reserved lane: transmits nothing
        e.addi("a5", "x0", 0x21),  # '!'
        e.sb("a5", "a4", 0),
    ]
    for index, word in enumerate(program):
        uart.write_word(0x42000000 + index * 4, word)
    uart.set_regs([0] * 32, pc=0x42000000)
    for _ in program:
        uart.step()
    assert uart.stream(UART_FIFO) == b"H!"


# --- a counter read through a snapshot (OH-161 step 2) -----------------------
#
# The addresses are the ESP32-C3's SYSTIMER, from the same
# `framework-arduinoespressif32` tree as the UART above: `soc.h:61`
# (`DR_REG_SYSTIMER_BASE 0x60023000`), and in `systimer_reg.h` CONF at + 0x0
# (:26), whose `SYSTIMER_TIMER_UNIT0_WORK_EN` is `BIT(30)` (:90); UNIT0_OP at
# + 0x4 (:108), `VALUE_VALID` `BIT(29)` (:109) and `UPDATE` `BIT(30)` (:116);
# VALUE_HI at + 0x40 (:344), `[19:0]` (:345); VALUE_LO at + 0x44 (:356).
# Used because they are the block `webui/boards/esp32c3.py` describes; what
# the boards' tests hold is the board, and what these hold is the mechanism.

SYSTIMER_CONF = 0x60023000
UNIT0_OP = 0x60023004
UNIT0_VALUE_HI = 0x60023040
UNIT0_VALUE_LO = 0x60023044
UNIT0_WORK_EN = 1 << 30
UNIT0_UPDATE = 1 << 30
UNIT0_VALUE_VALID = 1 << 29
VALUE_HI_BITS = 0x000FFFFF

#: Retired instructions per tick in these tests. **No chip's rate** -- each
#: board states its own -- and not 1 either, so a counter that forgot to
#: divide reads a different number from one that did.
PER_TICK = 4

NOP = e.addi("x0", "x0", 0)


@pytest.fixture
def systimer(cpu):
    """The session core, its RAM, and one SYSTIMER unit counting.

    Takes `cpu` for the reason the `gpio` fixture gives: `_fresh_board`
    clears every mapping first, so this has to run after it.
    """
    cpu.map_register(SYSTIMER_CONF, UNIT0_WORK_EN)
    cpu.map_snapshot_counter(
        op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
        low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
        enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
        instructions_per_tick=PER_TICK,
    )
    return cpu


def retire(cpu, count: int) -> None:
    """Execute `count` NOPs, from wherever `load` puts them."""
    load(cpu, [NOP] * count)
    for _ in range(count):
        cpu.step()


def test_before_any_snapshot_all_three_registers_read_zero(systimer):
    """`VALUE_VALID` is `default: 0` (:109) and both value fields too (:345,
    :357): a unit that has counted and never been asked has nothing to show,
    and a live count here would be the right number read the wrong way."""
    retire(systimer, 40)
    assert systimer.read_word(UNIT0_OP) == 0
    assert systimer.read_word(UNIT0_VALUE_LO) == 0
    assert systimer.read_word(UNIT0_VALUE_HI) == 0


def test_a_snapshot_is_the_retired_instructions_divided_by_the_rate(systimer):
    """41 instructions at four a tick is ten ticks and one left over: the
    remainder is not rounded up, and the copy says it is valid."""
    retire(systimer, 41)
    systimer.write_word(UNIT0_OP, UNIT0_UPDATE)
    assert systimer.read_word(UNIT0_OP) == UNIT0_VALUE_VALID
    assert systimer.read_word(UNIT0_VALUE_LO) == 10
    assert systimer.read_word(UNIT0_VALUE_HI) == 0


def test_the_copy_stands_still_until_the_next_snapshot(systimer):
    """**The reason this is not `core/cortexm0`'s `map_counter`.** ESP-IDF's
    HAL writes UPDATE and then reads the two halves; a live count read
    between them would tear, and one read later would show time nobody
    asked for."""
    retire(systimer, 40)
    systimer.write_word(UNIT0_OP, UNIT0_UPDATE)
    retire(systimer, 40)
    assert systimer.read_word(UNIT0_VALUE_LO) == 10, "the copy, not the count"
    systimer.write_word(UNIT0_OP, UNIT0_UPDATE)
    assert systimer.read_word(UNIT0_VALUE_LO) == 20, "and a new copy moves"


def test_a_write_without_the_update_bit_takes_no_copy(systimer):
    """UPDATE is one bit of the register (:116) and every other bit of a
    write to it is not a request for anything."""
    retire(systimer, 40)
    systimer.write_word(UNIT0_OP, ~UNIT0_UPDATE & 0xFFFFFFFF)
    assert systimer.read_word(UNIT0_OP) == 0
    assert systimer.read_word(UNIT0_VALUE_LO) == 0


def test_the_count_holds_while_the_unit_is_disabled_and_resumes_from_it(systimer):
    """`TIMER_UNIT0_WORK_EN` is the unit's enable (:90). Cleared, the 400
    instructions in the middle are not counted; set again, counting resumes
    from where it stopped rather than jumping by what it missed."""
    retire(systimer, 40)
    systimer.write_word(SYSTIMER_CONF, 0)
    retire(systimer, 400)
    systimer.write_word(SYSTIMER_CONF, UNIT0_WORK_EN)
    retire(systimer, 40)
    systimer.write_word(UNIT0_OP, UNIT0_UPDATE)
    assert systimer.read_word(UNIT0_VALUE_LO) == 20


def test_an_instruction_that_faults_does_not_age_the_counter(systimer):
    """A program stopped by a fault is stopped: a caller stepping it in a
    loop must not watch its timer run on. The load is from address zero,
    which nothing maps."""
    load(systimer, [e.lw("a0", "x0", 0)])
    for _ in range(40):
        with pytest.raises(abi.MemoryFault):
            systimer.step()
    systimer.write_word(UNIT0_OP, UNIT0_UPDATE)
    assert systimer.read_word(UNIT0_VALUE_LO) == 0


def test_every_byte_of_the_operation_register_names_the_unit(systimer):
    """`sb` to the register's top byte is a store a compiler may emit for
    bit 30, and it reaches the unit at its word; one to the bottom byte
    cannot carry the bit, so it takes no copy. Executed, because only the
    store paths position a byte in its lane."""
    program = [NOP] * 8 + [
        e.lui("a4", 0x60023),        # a4 = SYSTIMER
        e.addi("a5", "x0", 0x40),    # bit 6 of a byte: bit 30 of the word
        e.sb("a5", "a4", 4),         # the bottom byte: no UPDATE in it
        e.lw("a0", "a4", 4),
        e.sb("a5", "a4", 7),         # the top byte: UPDATE
        e.lw("a1", "a4", 4),
        e.lw("a2", "a4", 0x44),
    ]
    load(systimer, program)
    for _ in program:
        systimer.step()
    assert systimer.reg(10) == 0, "a0: the bottom byte took no copy"
    assert systimer.reg(11) == UNIT0_VALUE_VALID, "a1: the top byte did"
    assert systimer.reg(12) == 12 // PER_TICK, "a2: twelve retired before the store"


def test_a_program_reads_the_count_the_way_esp_idf_does(systimer):
    """Write UPDATE, spin until VALUE_VALID, read HI, read LO: ESP-IDF's
    `systimer_hal_get_counter_value` less the second LO read only an
    interrupt needs, and the sequence the openhardware core's `millis`
    compiles to -- executed here against the mechanism alone.

    38 NOPs, then `lui`, `lui` and the store: the copy is taken with 40
    retired, which is ten ticks."""
    program = [NOP] * 38 + [
        e.lui("a4", 0x60023),        # a4 = SYSTIMER
        e.lui("a5", 0x40000),        # a5 = UPDATE
        e.sw("a5", "a4", 4),
        e.lw("a0", "a4", 4),         # spin on VALUE_VALID ...
        e.beq("a0", "x0", -4),       # ... which UPDATE reads as zero
        e.lw("a1", "a4", 0x40),
        e.lw("a2", "a4", 0x44),
    ]
    load(systimer, program)
    for _ in program:
        systimer.step()
    assert systimer.reg(10) == UNIT0_VALUE_VALID
    assert (systimer.reg(11), systimer.reg(12)) == (0, 10)


def test_a_snapshot_through_an_unmapped_enable_register_faults_naming_the_unit(cpu):
    """A board naming an enable register it never mapped has described a
    counter that could never count. The snapshot faults at the unit's own
    address, through `step()` because only that reads the address the core
    recorded -- the lesson `test_an_executed_store_through_an_unmapped_gate_
    names_the_fifo` paid for."""
    cpu.map_snapshot_counter(
        op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
        low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
        enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
        instructions_per_tick=PER_TICK,
    )
    load(cpu, [e.lui("a4", 0x60023), e.lui("a5", 0x40000), e.sw("a5", "a4", 4)])
    cpu.step()
    cpu.step()
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    assert f"0x{UNIT0_OP:08x}" in str(caught.value), str(caught.value)


#: An address inside SYSTIMER's block that nothing here maps, for a gate to
#: be an alias onto. The header's last register is `SYSTIMER_DATE_REG` at
#: + 0xfc (:556), so nothing is described at + 0xf00.
NOTHING = 0x60023F00


def test_a_snapshot_through_an_alias_gate_onto_nothing_faults_naming_the_unit(cpu):
    """A readable alias whose target nothing maps IS mapped, and cannot be
    read: `is_mapped` says yes and `mmio_read` fails. The snapshot used to
    ask the first and the count the second, so this unit handed out copies
    of a count that never moved and nothing faulted anywhere. Found by the
    OH-161 review. Executed, for the reason the test above gives."""
    cpu.map_alias(SYSTIMER_CONF, NOTHING, "store", readable=True)
    cpu.map_snapshot_counter(
        op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
        low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
        enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
        instructions_per_tick=PER_TICK,
    )
    load(cpu, [e.lui("a4", 0x60023), e.lui("a5", 0x40000), e.sw("a5", "a4", 4)])
    cpu.step()
    cpu.step()
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    assert f"0x{UNIT0_OP:08x}" in str(caught.value), str(caught.value)


def test_a_gate_that_cannot_be_read_leaves_no_fault_behind_between_instructions(cpu):
    """Counting reads the gate after every retired instruction, where there
    is no access to fault, and `mmio_read` records the alias's own address
    when its target is missing. So until the OH-161 review every NOP here
    rewrote the fault record to name CONF, an address no instruction
    touched. The record is set first by a fault this test causes, at zero,
    and read through the C side, because only a `MemoryFault` from `step`
    reports it to Python and none happens here."""
    cpu.map_alias(SYSTIMER_CONF, NOTHING, "store", readable=True)
    cpu.map_snapshot_counter(
        op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
        low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
        enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
        instructions_per_tick=PER_TICK,
    )
    with pytest.raises(abi.MemoryFault):
        cpu.read_word(0)
    fault_address = cpu._lib.riscv32_fault_address
    assert fault_address(cpu._handle) == 0
    retire(cpu, 40)
    assert fault_address(cpu._handle) == 0, (
        f"the record names 0x{fault_address(cpu._handle):08x} after forty "
        f"instructions that faulted nowhere")


def test_mapping_the_same_unit_twice_replaces_it(systimer):
    """The fixture maps the unit at four instructions a tick and this maps
    it again at eight: forty instructions are then five ticks. Two counters
    left on one address would answer in whichever order the scan met them,
    and the first -- the one the board replaced -- would say ten."""
    systimer.map_snapshot_counter(
        op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
        low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
        enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
        instructions_per_tick=8,
    )
    retire(systimer, 40)
    systimer.write_word(UNIT0_OP, UNIT0_UPDATE)
    assert systimer.read_word(UNIT0_VALUE_LO) == 5


def test_a_rate_below_one_is_refused_with_the_value(cpu):
    """Zero would be a counter that never advances, which is the hang this
    behaviour exists to end. The C side corrects it to one rather than
    divide by it; the binding refuses it first, saying what it was given."""
    with pytest.raises(abi.AbiError) as caught:
        cpu.map_snapshot_counter(
            op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
            low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
            enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
            instructions_per_tick=0,
        )
    assert "got 0" in str(caught.value)


def test_a_rate_past_32_bits_is_refused_with_the_value(cpu):
    """The C side's rate is a `uint32_t`, and ctypes truncates a larger int
    without a word: 2**32 would arrive as zero, which the core corrects to
    one -- a counter 2**32 times faster than the board asked for, with
    nothing said anywhere. The binding refuses it, naming the value."""
    with pytest.raises(abi.AbiError) as caught:
        cpu.map_snapshot_counter(
            op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
            low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
            enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
            instructions_per_tick=1 << 32,
        )
    assert f"got {1 << 32}" in str(caught.value), str(caught.value)


def test_a_machine_with_no_board_keeps_no_counter_behind(systimer):
    """A counter carries a COUNT and a copy, so one left behind would answer
    for the next board's register at the same address: a plain register
    mapped there after `clear_regions` must read what it was given."""
    retire(systimer, 40)
    systimer.write_word(UNIT0_OP, UNIT0_UPDATE)
    systimer.clear_regions()
    systimer.map_register(UNIT0_OP, 0x1234)
    assert systimer.read_word(UNIT0_OP) == 0x1234


def test_a_reset_machine_keeps_no_counter_behind(systimer):
    """`reset` is what `core/riscv32/machine.py`'s `blank` calls, so a board
    installing onto a used core starts with no counter either."""
    retire(systimer, 40)
    systimer.write_word(UNIT0_OP, UNIT0_UPDATE)
    systimer.reset()
    systimer.map_register(UNIT0_OP, 0x1234)
    assert systimer.read_word(UNIT0_OP) == 0x1234
