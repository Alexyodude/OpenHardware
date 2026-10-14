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

import ctypes

import pytest

from core.riscv32 import abi

from . import encode as e
from .conftest import PC, RAM, load

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
    touched. The record is set first by a fault this test causes -- a fetch,
    at an address that is neither zero nor CONF, so that clearing the record
    instead of putting it back fails here as well as rewriting it does -- and
    read through the C side, because only a `MemoryFault` from `step`
    reports it to Python and none happens here."""
    cpu.map_alias(SYSTIMER_CONF, NOTHING, "store", readable=True)
    cpu.map_snapshot_counter(
        op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
        low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
        enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
        instructions_per_tick=PER_TICK,
    )
    cpu.set_regs([0] * 32, pc=NOTHING)
    with pytest.raises(abi.MemoryFault):
        cpu.step()
    fault_address = cpu._lib.riscv32_fault_address
    was_fetch = cpu._lib.riscv32_fault_was_fetch
    assert (fault_address(cpu._handle), was_fetch(cpu._handle)) == (NOTHING, 1)
    retire(cpu, 40)
    assert (fault_address(cpu._handle), was_fetch(cpu._handle)) == (NOTHING, 1), (
        f"the record names 0x{fault_address(cpu._handle):08x}, fetch "
        f"{was_fetch(cpu._handle)}, after forty instructions that faulted "
        f"nowhere")


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


# --- a register that reads the pins (OH-161 step 3) --------------------------
#
# The ESP32-C3's again, from the same `framework-arduinoespressif32` tree:
# `GPIO_IN_REG` at + 0x3C (`gpio_reg.h:122`); IO_MUX at 0x60009000
# (`soc.h:49`), GPIO0's pad register at + 0x04 (`io_mux_reg.h:175`) and each
# next GPIO's four bytes on (TRM v1.4 Register 5.21, `0x0004+4*n`); and in
# each pad register `FUN_PD` bit 7, `FUN_PU` bit 8 and `FUN_IE` bit 9
# (`io_mux_reg.h:51`, `:56`, `:61`). What the board's tests hold is the
# board; what these hold is the mechanism.

GPIO_IN = GPIO + 0x3C
IO_MUX_GPIO0 = 0x60009004
PAD_STRIDE = 4
FUN_WPD = 1 << 7
FUN_WPU = 1 << 8
FUN_IE = 1 << 9

#: The pins with a pad in these tests, 0 to 3. Pin 4 has none, and nothing
#: maps its pad register, so asking it would fault.
PADS = 0b1111


def map_pins(cpu, pads: int = PADS) -> None:
    """`map_input` over the `gpio` fixture's OUT and ENABLE."""
    cpu.map_input(GPIO_IN, out=GPIO_OUT, enable=GPIO_ENABLE,
                  pad_base=IO_MUX_GPIO0, pad_stride=PAD_STRIDE, pads=pads,
                  input_enable=FUN_IE, pull_up=FUN_WPU, pull_down=FUN_WPD)


def pad(n: int) -> int:
    return IO_MUX_GPIO0 + n * PAD_STRIDE


@pytest.fixture
def pins(gpio):
    """GPIO, four pad registers with their input enabled and no pull, and
    the input register reading them. Takes `gpio` for the reason the `gpio`
    fixture takes `cpu`."""
    for n in range(4):
        gpio.map_register(pad(n), FUN_IE)
    map_pins(gpio)
    return gpio


def test_an_input_reads_what_the_outside_drives_it_to(pins):
    pins.drive_input(GPIO_IN, driven=0b0011, levels=0b0001)
    assert pins.read_word(GPIO_IN) == 0b0001
    pins.drive_input(GPIO_IN, driven=0b0011, levels=0b0010)
    assert pins.read_word(GPIO_IN) == 0b0010


def test_a_driven_output_reads_back_its_own_level_whatever_the_outside_says(pins):
    """The description's own sentence, `IN` follows `OUT` on a driven pin.
    The outside is ignored there; what a pin and a part fighting over a node
    do is the bench's to solve, and `circuit.js` treats the pin as a source."""
    pins.write_word(GPIO_ENABLE, 0b0001)
    pins.write_word(GPIO_OUT, 0b0001)
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0000)
    assert pins.read_word(GPIO_IN) == 0b0001
    pins.write_word(GPIO_OUT, 0b0000)
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    assert pins.read_word(GPIO_IN) == 0b0000


def test_an_undriven_input_reads_its_pull_and_a_floating_one_reads_zero(pins):
    """Pin 0 pulled up, 1 pulled down, 2 both, 3 neither. Only the pull-up
    alone reads high: both pulls are a divider at half the supply, which no
    input threshold answers, and neither is a floating pin -- read as 0 by
    the decision OH-161's step-3 note records."""
    pins.write_word(pad(0), FUN_IE | FUN_WPU)
    pins.write_word(pad(1), FUN_IE | FUN_WPD)
    pins.write_word(pad(2), FUN_IE | FUN_WPU | FUN_WPD)
    pins.write_word(pad(3), FUN_IE)
    assert pins.read_word(GPIO_IN) == 0b0001


def test_the_outside_beats_the_pull(pins):
    """A pin pulled up and driven low reads low: the slice's decision that a
    bench drive beats the internal 45 kohm pull, the Thevenin form deferred."""
    pins.write_word(pad(0), FUN_IE | FUN_WPU)
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0000)
    assert pins.read_word(GPIO_IN) == 0


def test_a_pin_whose_input_is_disabled_reads_zero_whatever_drives_it(pins):
    """`FUN_IE` clear: the C3 TRM's 5.4.4 says reading needs it, and the
    bit reads the gated buffer's 0 -- driven from outside, pulled up and
    driven high as an output all at once."""
    pins.write_word(pad(0), FUN_WPU)
    pins.write_word(GPIO_ENABLE, 0b0001)
    pins.write_word(GPIO_OUT, 0b0001)
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    assert pins.read_word(GPIO_IN) == 0


def test_a_pin_with_no_pad_reads_zero_and_its_register_is_never_asked(pins):
    """Pin 4 is driven high, and nothing maps its pad register: the read
    answers rather than faulting, and pin 4's bit is 0."""
    pins.drive_input(GPIO_IN, driven=0b10001, levels=0b10001)
    assert pins.read_word(GPIO_IN) == 0b00001


def test_a_pad_register_that_cannot_be_read_faults_naming_the_input_register(gpio):
    """A board that named the wrong pad block has described pins that never
    read their own input enable. Pin 3's pad register is not mapped here, and
    the read faults at the input register, the address the instruction used,
    as a stream names its FIFO; executed, because only `step` reports the
    address the core recorded."""
    for n in range(3):
        gpio.map_register(pad(n), FUN_IE)
    map_pins(gpio)
    load(gpio, [e.lui("a4", 0x60004), e.lw("a0", "a4", 0x3C)])
    gpio.step()
    with pytest.raises(abi.MemoryFault) as caught:
        gpio.step()
    assert f"0x{GPIO_IN:08x}" in str(caught.value), str(caught.value)


def test_a_program_reads_the_pins_with_a_word_and_with_a_byte(pins):
    """`lw` and `lbu` both reach the computed word: a byte read that fell
    through to the region lookup would fault at an address the board
    describes."""
    pins.drive_input(GPIO_IN, driven=0b0110, levels=0b0110)
    _run(pins, [e.lui("a4", 0x60004), e.lw("a0", "a4", 0x3C),
                e.lbu("a1", "a4", 0x3C)], {})
    assert (pins.reg(10), pins.reg(11)) == (0b0110, 0b0110)


def test_a_write_to_the_input_register_changes_nothing(pins):
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    pins.write_word(GPIO_IN, 0xFFFFFFFF)
    assert pins.read_word(GPIO_IN) == 0b0001


def test_a_drive_replaces_the_one_before_it(pins):
    """A pin the second call leaves out is a pin nothing drives any more:
    pin 0 goes back to floating."""
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    pins.drive_input(GPIO_IN, driven=0b0010, levels=0b0010)
    assert pins.read_word(GPIO_IN) == 0b0010


def test_driving_an_address_that_is_no_input_register_is_refused_by_address(pins):
    with pytest.raises(abi.AbiError) as caught:
        pins.drive_input(GPIO_OUT, driven=0b0001, levels=0b0001)
    assert f"0x{GPIO_OUT:08x}" in str(caught.value), str(caught.value)


def test_a_level_for_a_pin_nothing_drives_is_refused_with_both_masks(pins):
    """A level with no drive behind it is a caller's mistake, and the core
    would read past it without a word."""
    with pytest.raises(abi.AbiError) as caught:
        pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0010)
    assert "0x00000001" in str(caught.value) and "0x00000002" in str(caught.value), (
        str(caught.value))


def test_a_mask_past_32_bits_is_refused_with_the_value(pins):
    """ctypes would pass `1 << 32` as 0: a drive of nothing, said nowhere."""
    with pytest.raises(abi.AbiError) as caught:
        pins.drive_input(GPIO_IN, driven=1 << 32, levels=0)
    assert f"{1 << 32}" in str(caught.value), str(caught.value)


def test_mapping_the_input_again_replaces_it_and_forgets_its_drive(pins):
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    map_pins(pins)
    assert pins.read_word(GPIO_IN) == 0


def test_a_machine_with_no_board_keeps_no_input_behind(pins):
    """A drive is state, so one left behind would answer for the next
    board's register at the same address."""
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    pins.clear_regions()
    pins.map_register(GPIO_IN, 0x1234)
    assert pins.read_word(GPIO_IN) == 0x1234


def test_a_reset_machine_keeps_no_input_behind(pins):
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    pins.reset()
    pins.map_register(GPIO_IN, 0x1234)
    assert pins.read_word(GPIO_IN) == 0x1234


def test_anything_mapped_over_an_input_replaces_it(pins):
    """Mapping an address again replaces what was there, which is what
    `map_input` over an input already does. A register or an alias mapped
    over a live input must too: the input would otherwise go on answering
    from a table the new mapping knows nothing about, and refuse no drive.
    Found by OH-161's step-3 review."""
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    pins.map_register(GPIO_IN, 0x1234)
    assert pins.read_word(GPIO_IN) == 0x1234
    with pytest.raises(abi.AbiError):
        pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)

    map_pins(pins)
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    pins.map_alias(GPIO_IN, GPIO_OUT, "store", readable=True)
    pins.write_word(GPIO_OUT, 0x5678)
    assert pins.read_word(GPIO_IN) == 0x5678

    # A stream reads zero, where the input would read pin 0 driven high.
    map_pins(pins)
    pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)
    pins.map_stream(GPIO_IN, enable=GPIO_OUT, enable_mask=1)
    assert pins.read_word(GPIO_IN) == 0
    with pytest.raises(abi.AbiError):
        pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)

    # A counter's three registers each replace an input at their address.
    map_pins(pins)
    pins.map_snapshot_counter(
        op=GPIO_IN, update_mask=1, valid_mask=2, low=GPIO_IN + 0x100,
        high=GPIO_IN + 0x104, high_mask=0xFFFFFFFF, enable=GPIO_OUT,
        enable_mask=1, instructions_per_tick=1)
    with pytest.raises(abi.AbiError):
        pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)

    # A sampler's control register replaces an input there too.
    map_pins(pins)
    pins.map_sampler(GPIO_IN, value=0, start_mask=1, key_mask=2,
                     result=GPIO_OUT, status=GPIO_ENABLE, done_mask=1,
                     enable=GPIO_OUT, enable_mask=1)
    with pytest.raises(abi.AbiError):
        pins.drive_input(GPIO_IN, driven=0b0001, levels=0b0001)


# --- a converter started by a write (OH-161 step 4) ---------------------------
#
# The ESP32-C3's SAR ADC one-time path, from the same `framework-
# arduinoespressif32` tree: APB_SARADC at 0x60040000 (`soc.h:67`);
# `APB_SARADC_CTRL_REG` + 0x00 with `SAR_CLK_GATED` bit 6
# (`apb_saradc_reg.h:22`, `:53`); `ONETIME_SAMPLE_REG` + 0x20 with
# `SARADC1_ONETIME_SAMPLE` bit 31, `SARADC2_ONETIME_SAMPLE` bit 30,
# `ONETIME_START` bit 29, `ONETIME_CHANNEL` [28:25] (default 13) and
# `ONETIME_ATTEN` [24:23] (`:176-206`); `1_DATA_STATUS_REG` + 0x2C (`:278`);
# `INT_RAW_REG` + 0x44 and `INT_CLR_REG` + 0x4C, ADC1's done bit 31 in each
# (`:391-397`, `:467-473`). What the board's tests hold is the board; what
# these hold is the mechanism.

SARADC = 0x60040000
SARADC_CTRL = SARADC + 0x00
SAR_CLK_GATED = 1 << 6
ONETIME = SARADC + 0x20
SAR1_DATA = SARADC + 0x2C
INT_RAW = SARADC + 0x44
INT_CLR = SARADC + 0x4C
SAR1 = 1 << 31
SAR2 = 1 << 30
START = 1 << 29
#: The bits that choose what is converted: both unit-select bits, the
#: channel and the attenuation. START is not among them.
CONVERSION = SAR1 | SAR2 | (0xF << 25) | (0x3 << 23)
DONE = 1 << 31
ONETIME_AT_RESET = 13 << 25


def onetime(channel: int, atten: int = 3) -> int:
    """ADC1's control word for `channel` at `atten`, START clear."""
    return SAR1 | channel << 25 | atten << 23


def map_adc(cpu, *, enable: int = SARADC_CTRL, result: int = SAR1_DATA,
            status: int = INT_RAW) -> None:
    cpu.map_sampler(ONETIME, value=ONETIME_AT_RESET, start_mask=START,
                    key_mask=CONVERSION, result=result, status=status,
                    done_mask=DONE, enable=enable, enable_mask=SAR_CLK_GATED)


@pytest.fixture
def adc(cpu):
    """The clock gate open, the result and status registers, INT_CLR as the
    clear alias it is, the converter, and two channels held at 12 dB. Takes
    `cpu` for the reason the `gpio` fixture does."""
    cpu.map_register(SARADC_CTRL, SAR_CLK_GATED)
    cpu.map_register(SAR1_DATA, 0)
    cpu.map_register(INT_RAW, 0)
    cpu.map_alias(INT_CLR, INT_RAW, "clear", readable=False)
    map_adc(cpu)
    cpu.hold_samples(ONETIME, {onetime(2): 1536, onetime(3): 1024})
    return cpu


def convert(cpu, word: int) -> None:
    """ESP-IDF's start: the word with START clear, then with it set
    (`adc_oneshot_hal.c:116-118` at v5.5)."""
    cpu.write_word(ONETIME, word)
    cpu.write_word(ONETIME, word | START)


def test_a_start_converts_the_word_held_for_the_channel_and_attenuation(adc):
    convert(adc, onetime(2))
    assert adc.read_word(SAR1_DATA) == 1536
    assert adc.read_word(INT_RAW) == DONE


def test_a_start_sets_done_beside_the_status_bits_already_raised(adc):
    """`done_mask` is SET in the status register, as `cpu.h` says, and not
    written over it: `INT_RAW` carries ADC2's done in bit 30 beside ADC1's
    in bit 31 (`apb_saradc_reg.h:392`, `:398`), and a conversion that
    cleared it would lose an interrupt nobody had serviced."""
    adc2_done = 1 << 30
    adc.write_word(INT_RAW, adc2_done)
    convert(adc, onetime(2))
    assert adc.read_word(INT_RAW) == adc2_done | DONE


def test_one_result_register_answers_whichever_channel_the_last_start_named(adc):
    """The reason this is a behaviour of the core and not a register a board
    sets between runs: firmware picks the channel in the same few
    instructions that read the answer."""
    convert(adc, onetime(2))
    assert adc.read_word(SAR1_DATA) == 1536
    convert(adc, onetime(3))
    assert adc.read_word(SAR1_DATA) == 1024
    convert(adc, onetime(2))
    assert adc.read_word(SAR1_DATA) == 1536


def test_a_start_is_a_rising_edge_and_not_a_level(adc):
    """ESP-IDF writes the word again with START still set when it clears the
    unit bits (`adc_oneshot_hal.c:166`), and that is no new conversion."""
    convert(adc, onetime(2))
    adc.write_word(INT_CLR, DONE)
    adc.write_word(ONETIME, onetime(3) | START)
    assert (adc.read_word(SAR1_DATA), adc.read_word(INT_RAW)) == (1536, 0)
    convert(adc, onetime(3))
    assert (adc.read_word(SAR1_DATA), adc.read_word(INT_RAW)) == (1024, DONE)


def test_a_write_without_start_converts_nothing(adc):
    adc.write_word(ONETIME, onetime(2))
    assert (adc.read_word(SAR1_DATA), adc.read_word(INT_RAW)) == (0, 0)


def test_the_control_register_reads_its_reset_value_and_then_what_was_written(adc):
    assert adc.read_word(ONETIME) == ONETIME_AT_RESET
    convert(adc, onetime(2))
    assert adc.read_word(ONETIME) == onetime(2) | START


def test_nothing_converts_while_the_gate_is_clear(adc):
    """As on silicon with the clock off: the word stores, and no conversion
    happens and nothing is flagged."""
    adc.write_word(SARADC_CTRL, 0)
    convert(adc, onetime(2))
    assert (adc.read_word(SAR1_DATA), adc.read_word(INT_RAW)) == (0, 0)
    assert adc.read_word(ONETIME) == onetime(2) | START


def _start(cpu, word: int) -> abi.MemoryFault:
    """Execute the store of `word | START` after `word`, and return the fault
    the store raised. Executed, because the core's own fault record names
    the address and `write_word` formats the one it was passed."""
    cpu.write_word(ONETIME, word)
    high = (word | START) >> 12
    load(cpu, [e.lui("a4", SARADC >> 12), e.lui("a5", high), e.sw("a5", "a4", 0x20)])
    cpu.step()
    cpu.step()
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    return caught.value


def test_a_start_whose_key_holds_nothing_faults_naming_the_control_register(adc):
    """Channel 5, ADC2's bit, the reset channel 13: nothing is held for any
    of them, and a 0 would read as a voltage."""
    for word in (onetime(5), onetime(2) | SAR2, ONETIME_AT_RESET | SAR1):
        fault = _start(adc, word)
        assert f"0x{ONETIME:08x}" in str(fault), (hex(word), str(fault))
        assert adc.read_word(ONETIME) == word, "a faulted store changed the word"
        assert (adc.read_word(SAR1_DATA), adc.read_word(INT_RAW)) == (0, 0)


def test_a_start_through_a_gate_that_cannot_be_read_faults_naming_the_control(cpu):
    """A board naming a clock register it never mapped has described a
    converter that could never convert."""
    cpu.map_register(SAR1_DATA, 0)
    cpu.map_register(INT_RAW, 0)
    map_adc(cpu)
    cpu.hold_samples(ONETIME, {onetime(2): 1536})
    fault = _start(cpu, onetime(2))
    assert f"0x{ONETIME:08x}" in str(fault), str(fault)


def test_a_start_whose_result_or_status_is_unmapped_faults_naming_the_control(cpu):
    cpu.map_register(SARADC_CTRL, SAR_CLK_GATED)
    cpu.map_register(INT_RAW, 0)
    map_adc(cpu)
    cpu.hold_samples(ONETIME, {onetime(2): 1536})
    fault = _start(cpu, onetime(2))
    assert f"0x{ONETIME:08x}" in str(fault), str(fault)
    assert cpu.read_word(INT_RAW) == 0, "done was set for a result nowhere"

    cpu.map_register(SAR1_DATA, 0)
    map_adc(cpu, status=INT_RAW + 0x100)
    cpu.hold_samples(ONETIME, {onetime(2): 1536})
    fault = _start(cpu, onetime(2))
    assert f"0x{ONETIME:08x}" in str(fault), str(fault)
    assert cpu.read_word(SAR1_DATA) == 0, "a result was stored with no done"


def test_a_hold_replaces_the_one_before_it(adc):
    adc.hold_samples(ONETIME, {onetime(3): 2048})
    convert(adc, onetime(3))
    assert adc.read_word(SAR1_DATA) == 2048
    fault = _start(adc, onetime(2))
    assert f"0x{ONETIME:08x}" in str(fault), str(fault)


def test_holding_samples_for_an_address_that_is_no_sampler_is_refused_by_address(adc):
    with pytest.raises(abi.AbiError) as caught:
        adc.hold_samples(SAR1_DATA, {onetime(2): 1536})
    assert f"0x{SAR1_DATA:08x}" in str(caught.value), str(caught.value)


def test_a_key_or_word_past_32_bits_is_refused_with_the_value(adc):
    """ctypes would pass `1 << 32` as 0 without saying so."""
    for samples in ({1 << 32: 1}, {onetime(2): 1 << 32}, {onetime(2): -1}):
        with pytest.raises(abi.AbiError) as caught:
            adc.hold_samples(ONETIME, samples)
        bad = next(value for pair in samples.items() for value in pair
                   if not 0 <= value <= 0xFFFFFFFF)
        assert f"{bad}" in str(caught.value), str(caught.value)


def test_a_program_converts_the_way_esp_idf_does(adc):
    """Clear done, write the word, write it with START, spin until done,
    read the result: `adc_oneshot_hal_convert` (`adc_oneshot_hal.c:136-168`
    at v5.5) less what this model has no use for, executed against the
    mechanism alone. Then a byte store of the top byte alone, which carries
    START: the key is taken from the whole stored word, not from the bytes
    the store carried."""
    program = [
        e.lui("a4", SARADC >> 12),
        e.lui("a2", DONE >> 12),
        e.sw("a2", "a4", 0x4C),           # INT_CLR
        e.lui("a5", onetime(2) >> 12),
        e.sw("a5", "a4", 0x20),           # the word, START clear
        e.lui("a6", (onetime(2) | START) >> 12),
        e.sw("a6", "a4", 0x20),           # START rising
        e.lw("a0", "a4", 0x44),           # spin on done, bit 31 ...
        e.bge("a0", "x0", -4),            # ... which reads negative when set
        e.lw("a1", "a4", 0x2C),
        e.lui("a7", onetime(3) >> 12),
        e.sw("a7", "a4", 0x20),           # channel 3, START clear
        e.srli("a3", "a7", 24),           # channel 3's top byte ...
        e.ori("a3", "a3", START >> 24),   # ... with START
        e.sb("a3", "a4", 0x23),
        e.lw("a3", "a4", 0x2C),
    ]
    load(adc, program)
    for _ in program:
        adc.step()
    assert adc.reg(11) == 1536, "a1: channel 2's word"
    assert adc.reg(13) == 1024, "a3: channel 3's, by a byte store of START"


def test_mapping_the_sampler_again_replaces_it_and_forgets_what_it_held(adc):
    map_adc(adc)
    fault = _start(adc, onetime(2))
    assert f"0x{ONETIME:08x}" in str(fault), str(fault)


def test_anything_mapped_over_a_sampler_replaces_it(adc):
    """A register mapped over the control address must stop it converting,
    or the sampler goes on answering for an address it no longer owns."""
    adc.map_register(ONETIME, 0)
    convert(adc, onetime(2))
    assert (adc.read_word(SAR1_DATA), adc.read_word(INT_RAW)) == (0, 0)
    with pytest.raises(abi.AbiError):
        adc.hold_samples(ONETIME, {onetime(2): 1536})

    map_adc(adc)
    adc.map_alias(ONETIME, SAR1_DATA, "store", readable=True)
    with pytest.raises(abi.AbiError):
        adc.hold_samples(ONETIME, {onetime(2): 1536})

    map_adc(adc)
    adc.map_stream(ONETIME, enable=SARADC_CTRL, enable_mask=SAR_CLK_GATED)
    with pytest.raises(abi.AbiError):
        adc.hold_samples(ONETIME, {onetime(2): 1536})

    map_adc(adc)
    adc.map_snapshot_counter(
        op=ONETIME, update_mask=1, valid_mask=2, low=ONETIME + 0x100,
        high=ONETIME + 0x104, high_mask=0xFFFFFFFF, enable=SARADC_CTRL,
        enable_mask=SAR_CLK_GATED, instructions_per_tick=1)
    with pytest.raises(abi.AbiError):
        adc.hold_samples(ONETIME, {onetime(2): 1536})

    map_adc(adc)
    adc.map_input(ONETIME, out=SAR1_DATA, enable=INT_RAW, pad_base=SARADC_CTRL,
                  pad_stride=0, pads=0, input_enable=1, pull_up=0, pull_down=0)
    with pytest.raises(abi.AbiError):
        adc.hold_samples(ONETIME, {onetime(2): 1536})


def test_a_machine_with_no_board_keeps_no_sampler_behind(adc):
    """What a sampler holds is state, so one left behind would take the next
    board's samples for an address that board never made a sampler. Asked
    through `hold_samples`, because mapping anything at the address would
    replace a sampler left there and hide it."""
    adc.clear_regions()
    with pytest.raises(abi.AbiError) as caught:
        adc.hold_samples(ONETIME, {onetime(2): 1536})
    assert f"0x{ONETIME:08x}" in str(caught.value), str(caught.value)


def test_a_reset_machine_keeps_no_sampler_behind(adc):
    adc.reset()
    with pytest.raises(abi.AbiError) as caught:
        adc.hold_samples(ONETIME, {onetime(2): 1536})
    assert f"0x{ONETIME:08x}" in str(caught.value), str(caught.value)


# --- the doorbell and the byte FIFO (OH-161 step 5, ABI 7) --------------------
#
# Two behaviours that know nothing about any bus, so these tests are about the
# mechanism and not an I2C controller: a doorbell rings when a write carries a
# ring bit, and a FIFO holds the bytes firmware wrote and the bytes it will
# read. The addresses are the ESP32-C3's I2C0, from the framework copy
# `soc/i2c_reg.h` (3.20017.241212): CTR at + 0x04, whose TRANS_START is bit 5
# and CLK_EN bit 8; DATA at + 0x1C; CLK_CONF at + 0x54, whose SCLK_ACTIVE is
# bit 21. Used because they are the block step 5 describes; what a board's
# tests hold is the board.

I2C0 = 0x60013000
BELL = I2C0 + 0x04
BELL2 = I2C0 + 0x08
RING = 1 << 5
CLK_EN = 1 << 8
I2C_DATA = I2C0 + 0x1C
I2C_CLK_CONF = I2C0 + 0x54
SCLK_ACTIVE = 1 << 21


def ring_program(word: int, offset: int = 4) -> list[int]:
    """Three instructions: write `word` (under 0x800, an `addi`'s reach) to
    I2C0 + `offset`. The third retires the store."""
    return [e.lui("a4", I2C0 >> 12), e.addi("a5", "x0", word),
            e.sw("a5", "a4", offset)]


def raw_step(cpu) -> int:
    """One `riscv32_step`, its number and not an exception: `Cpu.step` runs
    the service for a ring, which would hide what the core returned."""
    return cpu._lib.riscv32_step(cpu._handle)


@pytest.fixture
def bell(cpu):
    """CTR as a doorbell whose TRANS_START both rings and stores as 0. Takes
    `cpu` for the reason the `gpio` fixture does."""
    cpu.map_doorbell(BELL, value=0, ring_mask=RING, write_trigger=RING)
    return cpu


def test_a_write_carrying_a_ring_bit_rings_and_one_without_does_not(bell):
    for word, rings in ((RING, True), (RING | CLK_EN, True), (CLK_EN, False),
                        (0, False)):
        load(bell, ring_program(word))
        results = [raw_step(bell) for _ in range(3)]
        want = abi.RANG if rings else abi.OK
        assert results == [abi.OK, abi.OK, want], (hex(word), results)


def test_the_ringing_store_has_retired_when_the_step_returns_rang(bell):
    load(bell, ring_program(RING | CLK_EN))
    assert [raw_step(bell) for _ in range(2)] == [abi.OK, abi.OK]
    assert raw_step(bell) == abi.RANG
    assert bell.pc == PC + 12, "past the store, as for any retired instruction"
    assert bell.read_word(BELL) == CLK_EN, "the store landed, trigger bit aside"
    assert abi.RANG == 4


def test_rang_at_names_the_doorbell_that_rang(bell):
    bell.map_doorbell(BELL2, value=0, ring_mask=1, write_trigger=0)
    for offset, doorbell, word in ((8, BELL2, 1), (4, BELL, RING)):
        load(bell, ring_program(word, offset))
        assert [raw_step(bell) for _ in range(3)][-1] == abi.RANG
        assert bell._lib.riscv32_rang_at(bell._handle) == doorbell


def test_a_ring_is_forgotten_by_the_next_step(bell):
    load(bell, ring_program(RING) + [NOP, NOP])
    assert [raw_step(bell) for _ in range(5)] == [
        abi.OK, abi.OK, abi.RANG, abi.OK, abi.OK]


def test_a_write_that_is_no_instruction_leaves_no_ring_behind(bell):
    """A harness poking CTR through `write_word` rang nothing. Its ring must
    not end the next, unrelated step."""
    bell.write_word(BELL, RING)
    load(bell, [NOP])
    assert raw_step(bell) == abi.OK


def test_a_ring_bit_in_a_lane_the_access_does_not_carry_does_not_ring(bell):
    """`sb` to CTR's second byte carries 0x20 into bits 15:8; TRANS_START is
    bit 5, in byte 0, so only a store to byte 0 rings."""
    for offset, want in ((5, abi.OK), (4, abi.RANG)):
        load(bell, [e.lui("a4", I2C0 >> 12), e.addi("a5", "x0", RING),
                    e.sb("a5", "a4", offset)])
        results = [raw_step(bell) for _ in range(3)]
        assert results[-1] == want, (offset, results)
        bell.write_word(BELL, 0)


def test_write_trigger_bits_read_back_zero_and_the_others_stay(bell):
    bell.write_word(BELL, RING | CLK_EN)
    assert bell.read_word(BELL) == CLK_EN
    bell.map_doorbell(BELL, value=RING | CLK_EN, ring_mask=RING,
                      write_trigger=RING)
    assert bell.read_word(BELL) == CLK_EN, "a trigger bit does not reset to 1"


def test_a_ringing_store_ages_the_machine_exactly_once(bell):
    """One tick per instruction, so the count after the three-instruction
    program is the number of times the machine aged. A ringing store that
    aged it twice, or not at all, reads 4 or 2."""
    bell.map_register(SYSTIMER_CONF, UNIT0_WORK_EN)
    bell.on_ring(BELL, lambda cpu, address: None)
    for word in (RING, CLK_EN):
        bell.map_snapshot_counter(
            op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
            low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
            enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
            instructions_per_tick=1)
        load(bell, ring_program(word))
        for _ in range(3):
            bell.step()
        bell.write_word(UNIT0_OP, UNIT0_UPDATE)
        assert bell.read_word(UNIT0_VALUE_LO) == 3, hex(word)


def test_anything_mapped_over_a_doorbell_replaces_it(bell):
    bell.map_register(SYSTIMER_CONF, UNIT0_WORK_EN)
    mappers = (
        lambda cpu: cpu.map_register(BELL, 0),
        lambda cpu: cpu.map_alias(BELL, SYSTIMER_CONF, "store"),
        lambda cpu: cpu.map_stream(BELL, enable=SYSTIMER_CONF,
                                   enable_mask=UNIT0_WORK_EN),
        lambda cpu: cpu.map_fifo(BELL, enable=SYSTIMER_CONF,
                                 enable_mask=UNIT0_WORK_EN),
        lambda cpu: cpu.map_input(BELL, out=SYSTIMER_CONF, enable=SYSTIMER_CONF,
                                  pad_base=SYSTIMER_CONF, pad_stride=0, pads=0,
                                  input_enable=1, pull_up=0, pull_down=0),
        lambda cpu: cpu.map_sampler(BELL, value=0, start_mask=1 << 31,
                                    key_mask=0, result=SYSTIMER_CONF,
                                    status=SYSTIMER_CONF, done_mask=1,
                                    enable=SYSTIMER_CONF,
                                    enable_mask=UNIT0_WORK_EN),
    )
    for index, mapper in enumerate(mappers):
        bell.map_doorbell(BELL, value=0, ring_mask=RING, write_trigger=RING)
        mapper(bell)
        load(bell, ring_program(RING))
        results = [raw_step(bell) for _ in range(3)]
        assert results == [abi.OK] * 3, (index, results)


def test_on_ring_runs_its_service_after_the_store_retired(bell):
    seen = []

    def service(cpu, address):
        seen.append((address, cpu.read_word(BELL), cpu.pc))

    bell.on_ring(BELL, service)
    load(bell, ring_program(RING | CLK_EN))
    for _ in range(3):
        bell.step()
    assert seen == [(BELL, CLK_EN, PC + 12)]


def test_on_ring_replaces_the_service_it_had(bell):
    called = []
    bell.on_ring(BELL, lambda cpu, address: called.append("first"))
    bell.on_ring(BELL, lambda cpu, address: called.append("second"))
    load(bell, ring_program(RING))
    for _ in range(3):
        bell.step()
    assert called == ["second"]


def test_a_device_refusal_from_the_service_is_refused_with_the_pc_and_address(bell):
    reason = abi.DeviceRefusal("a third byte was read (DS25095A 4.1.1)")

    def service(cpu, address):
        raise reason

    bell.on_ring(BELL, service)
    load(bell, ring_program(RING))
    bell.step()
    bell.step()
    with pytest.raises(abi.Refused) as caught:
        bell.step()
    refused = caught.value
    assert isinstance(refused, abi.AbiError)
    assert refused.pc == PC + 8, "where the ringing store began"
    assert refused.address == BELL
    assert refused.__cause__ is reason
    assert "a third byte was read (DS25095A 4.1.1)" in str(refused)
    assert f"pc=0x{PC + 8:08x}" in str(refused) and f"0x{BELL:08x}" in str(refused)
    assert bell.pc == PC + 12, "the store retired"
    assert refused.retired is True


def test_a_ring_with_no_service_is_refused_by_name(bell):
    load(bell, ring_program(RING))
    bell.step()
    bell.step()
    with pytest.raises(abi.Refused) as caught:
        bell.step()
    assert "no service" in str(caught.value) and "on_ring" in str(caught.value)
    assert caught.value.address == BELL and caught.value.pc == PC + 8


def test_a_service_that_raises_anything_else_is_a_service_fault(bell):
    """A host-side bug is not the device refusing: a plain `ValueError`
    (`int("x")`), a `KeyError`, and an `AbiError` from the service's own call
    into the core (a `hold_readable` on a non-FIFO) are all the service's."""
    def plain_value_error(cpu, address):
        int("x")

    def key_error(cpu, address):
        {}["missing"]

    def core_error(cpu, address):
        cpu.hold_readable(BELL, b"\x01")

    for service, name in ((plain_value_error, "ValueError"),
                          (key_error, "KeyError"), (core_error, "AbiError")):
        bell.on_ring(BELL, service)
        load(bell, ring_program(RING))
        bell.step()
        bell.step()
        with pytest.raises(abi.ServiceFault) as caught:
            bell.step()
        fault = caught.value
        assert not isinstance(fault, abi.Refused), name
        assert isinstance(fault, abi.AbiError) and fault.retired is True
        assert fault.__cause__ is not None and type(fault.__cause__).__name__ == name
        assert name in str(fault) and f"0x{BELL:08x}" in str(fault), str(fault)
        assert (fault.pc, fault.address) == (PC + 8, BELL)
        assert bell.pc == PC + 12, "the store retired"


def test_a_device_refusal_is_a_value_error_and_only_it_is_a_refusal():
    assert issubclass(abi.DeviceRefusal, ValueError)
    assert not issubclass(abi.ServiceFault, abi.Refused)
    assert not issubclass(abi.Refused, abi.ServiceFault)


def test_mapping_the_doorbell_again_drops_the_service_it_had(bell):
    bell.on_ring(BELL, lambda cpu, address: None)
    bell.map_doorbell(BELL, value=0, ring_mask=RING, write_trigger=RING)
    load(bell, ring_program(RING))
    bell.step()
    bell.step()
    with pytest.raises(abi.Refused, match="no service"):
        bell.step()


def test_a_doorbell_that_can_never_ring_is_refused_with_the_values(bell):
    with pytest.raises(abi.AbiError) as caught:
        bell.map_doorbell(BELL2, value=0, ring_mask=0)
    assert f"0x{BELL2:08x}" in str(caught.value), str(caught.value)
    for name, kwargs in (("ring_mask", {"ring_mask": 1 << 32}),
                         ("write_trigger", {"ring_mask": 1,
                                            "write_trigger": 1 << 32})):
        with pytest.raises(abi.AbiError) as caught:
            bell.map_doorbell(BELL2, value=0, **kwargs)
        assert name in str(caught.value) and str(1 << 32) in str(caught.value)


@pytest.fixture
def fifo(cpu):
    """DATA as a FIFO behind CLK_CONF's SCLK_ACTIVE, gate open."""
    cpu.map_register(I2C_CLK_CONF, SCLK_ACTIVE)
    cpu.map_fifo(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
    return cpu


def test_a_write_to_the_fifo_appends_its_low_byte_while_the_gate_is_open(fifo):
    for word in (0x41, 0x00, 0x1234):
        fifo.write_word(I2C_DATA, word)
    assert fifo.take_written(I2C_DATA) == b"\x41\x00\x34"


def test_nothing_is_appended_while_the_gate_is_clear(fifo):
    fifo.write_word(I2C_CLK_CONF, 0)
    fifo.write_word(I2C_DATA, 0x41)
    assert fifo.take_written(I2C_DATA) == b""
    fifo.write_word(I2C_CLK_CONF, SCLK_ACTIVE)
    fifo.write_word(I2C_DATA, 0x42)
    assert fifo.take_written(I2C_DATA) == b"B"


def test_a_byte_store_to_a_lane_above_the_data_appends_nothing(fifo):
    _run(fifo, [e.sb("a5", "a4", 1), e.sb("a5", "a4", 0)],
         {14: I2C_DATA, 15: 0x41})
    assert fifo.take_written(I2C_DATA) == b"A", "only the store to byte 0"


def test_taking_the_written_bytes_forgets_them(fifo):
    fifo.write_word(I2C_DATA, 0x41)
    assert fifo.take_written(I2C_DATA) == b"A"
    assert fifo.take_written(I2C_DATA) == b""
    fifo.write_word(I2C_DATA, 0x42)
    assert fifo.take_written(I2C_DATA) == b"B"


def test_an_address_that_is_no_fifo_has_nothing_written(fifo):
    assert fifo.take_written(I2C_CLK_CONF) == b""


def test_a_buffer_too_small_for_the_written_bytes_takes_nothing(fifo):
    for byte in b"abc":
        fifo.write_word(I2C_DATA, byte)
    small = (ctypes.c_uint8 * 2)()
    assert fifo._lib.riscv32_take_written(fifo._handle, I2C_DATA, small, 2) == 3
    assert fifo.take_written(I2C_DATA) == b"abc", "still there to be taken"


def test_a_write_through_an_unmapped_gate_faults_naming_the_fifo(cpu):
    cpu.map_fifo(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
    load(cpu, ring_program(0x41, 0x1C))
    cpu.step()
    cpu.step()
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    assert f"0x{I2C_DATA:08x}" in str(caught.value), str(caught.value)
    assert cpu.take_written(I2C_DATA) == b""


def test_held_bytes_are_read_oldest_first_and_then_the_read_faults(fifo):
    fifo.hold_readable(I2C_DATA, b"\x01\x02\x03")
    assert [fifo.read_word(I2C_DATA) for _ in range(3)] == [1, 2, 3]
    with pytest.raises(abi.MemoryFault):
        fifo.read_word(I2C_DATA)


def test_holding_again_replaces_what_was_held(fifo):
    fifo.hold_readable(I2C_DATA, b"\x01\x02")
    fifo.hold_readable(I2C_DATA, b"\x09")
    assert fifo.read_word(I2C_DATA) == 9
    with pytest.raises(abi.MemoryFault):
        fifo.read_word(I2C_DATA)


def test_a_read_with_nothing_held_faults_at_the_read_and_changes_nothing(fifo):
    """The empty read is the program's, at its pc, not a plausible byte one
    instruction late; and it leaves everything as it was, so holding a byte
    and retrying the same instruction reads it."""
    fifo.write_word(I2C_DATA, 0x5A)
    fifo.hold_readable(I2C_DATA, b"\x07")
    # Seed the fault record with another address, so the address asserted
    # below is the one this read noted and not the last test's leftover.
    with pytest.raises(abi.MemoryFault):
        fifo.read_word(0x10)
    load(fifo, [e.lui("a4", I2C0 >> 12), e.lw("a5", "a4", 0x1C),
                e.lw("a6", "a4", 0x1C)])
    for _ in range(2):
        fifo.step()
    assert fifo.reg(15) == 7
    with pytest.raises(abi.MemoryFault) as caught:
        fifo.step()
    assert f"pc=0x{PC + 8:08x}" in str(caught.value), str(caught.value)
    assert f"0x{I2C_DATA:08x}" in str(caught.value), str(caught.value)
    assert "holds nothing to read" in str(caught.value), "not 'unmapped'"
    assert "unmapped" not in str(caught.value), str(caught.value)
    assert fifo.pc == PC + 8 and fifo.reg(16) == 0
    assert fifo.take_written(I2C_DATA) == b"\x5a", "the written side is untouched"
    fifo.hold_readable(I2C_DATA, b"\x08")
    fifo.step()
    assert fifo.reg(16) == 8 and fifo.pc == PC + 12


def test_holding_bytes_for_an_address_that_is_no_fifo_is_refused_by_address(fifo):
    with pytest.raises(abi.AbiError) as caught:
        fifo.hold_readable(I2C_CLK_CONF, b"\x01")
    assert f"0x{I2C_CLK_CONF:08x}" in str(caught.value), str(caught.value)


def test_a_machine_with_no_board_keeps_no_fifo_behind(fifo):
    """Held bytes and written ones are state. Asked through the FIFO's own
    calls, because mapping anything at the address would replace one left
    there and hide it."""
    for forget in (lambda cpu: cpu.reset(), lambda cpu: cpu.clear_regions(),
                   lambda cpu: cpu.clear_mmio()):
        fifo.map_fifo(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
        fifo.write_word(I2C_CLK_CONF, SCLK_ACTIVE)
        fifo.write_word(I2C_DATA, 0x41)
        fifo.hold_readable(I2C_DATA, b"\x01")
        forget(fifo)
        assert fifo.take_written(I2C_DATA) == b""
        with pytest.raises(abi.AbiError):
            fifo.hold_readable(I2C_DATA, b"\x01")
        fifo.map_register(I2C_CLK_CONF, SCLK_ACTIVE)


def test_anything_mapped_over_a_fifo_replaces_it(fifo):
    fifo.map_register(SYSTIMER_CONF, UNIT0_WORK_EN)
    mappers = (
        lambda cpu: cpu.map_register(I2C_DATA, 0),
        lambda cpu: cpu.map_alias(I2C_DATA, SYSTIMER_CONF, "store"),
        lambda cpu: cpu.map_stream(I2C_DATA, enable=SYSTIMER_CONF,
                                   enable_mask=UNIT0_WORK_EN),
        lambda cpu: cpu.map_doorbell(I2C_DATA, value=0, ring_mask=1),
        lambda cpu: cpu.map_input(I2C_DATA, out=SYSTIMER_CONF,
                                  enable=SYSTIMER_CONF, pad_base=SYSTIMER_CONF,
                                  pad_stride=0, pads=0, input_enable=1,
                                  pull_up=0, pull_down=0),
        lambda cpu: cpu.map_sampler(I2C_DATA, value=0, start_mask=1 << 31,
                                    key_mask=0, result=SYSTIMER_CONF,
                                    status=SYSTIMER_CONF, done_mask=1,
                                    enable=SYSTIMER_CONF,
                                    enable_mask=UNIT0_WORK_EN),
        lambda cpu: cpu.map_snapshot_counter(
            op=I2C_DATA, update_mask=1, valid_mask=2, low=I2C_DATA + 0x100,
            high=I2C_DATA + 0x104, high_mask=0xFFFFFFFF, enable=SYSTIMER_CONF,
            enable_mask=UNIT0_WORK_EN, instructions_per_tick=1),
    )
    for index, mapper in enumerate(mappers):
        fifo.map_fifo(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
        mapper(fifo)
        with pytest.raises(abi.AbiError):
            fifo.hold_readable(I2C_DATA, b"\x01")
        assert fifo.take_written(I2C_DATA) == b"", index


def test_a_fifo_mapped_over_a_stream_takes_its_writes(fifo):
    """A stream left at the address would capture the write first and the
    FIFO would see none of it."""
    fifo.map_stream(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
    fifo.map_fifo(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
    fifo.write_word(I2C_DATA, 0x41)
    assert fifo.take_written(I2C_DATA) == b"A"
    assert fifo.stream(I2C_DATA) == b""


def test_the_binding_refuses_a_library_of_another_abi_version(monkeypatch):
    """7 is the ring and the FIFO. A binding that expected 6 against this
    library, or 7 against an older one, would call a symbol that is not there
    or miss one that is."""
    assert abi.ABI_VERSION == 7
    assert abi.load().riscv32_abi_version() == 7
    monkeypatch.setattr(abi, "_library", None)
    monkeypatch.setattr(abi, "ABI_VERSION", 6)
    with pytest.raises(abi.AbiError) as caught:
        abi.load(build_if_missing=False)
    assert "7" in str(caught.value) and "6" in str(caught.value), str(caught.value)


# --- the fix round after the independent review of 1886d19 ---------------------


def test_a_fifo_fault_says_why_and_a_plain_unmapped_address_still_says_unmapped(fifo):
    """The empty read names a mapped address, so 'unmapped' would send the
    reader to the wrong file. Asserted in the words, through all three ways
    the fault reaches a person: `read_word`, an executed load, and a store
    through an unmapped gate."""
    with pytest.raises(abi.MemoryFault) as caught:
        fifo.read_word(I2C_DATA)
    assert "mapped, and refuses" in str(caught.value), str(caught.value)
    assert "holds nothing to read" in str(caught.value), str(caught.value)
    assert "outside the modelled memory" not in str(caught.value)

    with pytest.raises(abi.MemoryFault) as caught:
        fifo.read_word(0x10)
    assert "outside the modelled memory" in str(caught.value), str(caught.value)

    cpu = abi.Cpu()
    cpu.map_fifo(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
    cpu.add_region(0x42000000, 0x100, executable=True)
    for index, word in enumerate(ring_program(0x41, 0x1C)):
        cpu.write_word(0x42000000 + index * 4, word)
    cpu.set_regs([0] * 32, pc=0x42000000)
    cpu.step()
    cpu.step()
    with pytest.raises(abi.MemoryFault) as caught:
        cpu.step()
    assert "enable register is not mapped" in str(caught.value), str(caught.value)
    assert "unmapped" not in str(caught.value)


def test_a_sub_word_read_of_a_fifo_above_byte_zero_faults_before_it_pops(fifo):
    fifo.hold_readable(I2C_DATA, b"\x11\x22")
    for instruction, offset in ((e.lbu, 1), (e.lbu, 3), (e.lhu, 2)):
        load(fifo, [e.lui("a4", I2C0 >> 12), instruction("a5", "a4", 0x1C + offset)])
        fifo.step()
        with pytest.raises(abi.MemoryFault) as caught:
            fifo.step()
        assert "above byte 0" in str(caught.value), str(caught.value)
        assert f"0x{I2C_DATA + offset:08x}" in str(caught.value), str(caught.value)
    # Nothing was popped by any of them.
    load(fifo, [e.lui("a4", I2C0 >> 12), e.lbu("a5", "a4", 0x1C),
                e.lhu("a6", "a4", 0x1C)])
    for _ in range(3):
        fifo.step()
    assert (fifo.reg(15), fifo.reg(16)) == (0x11, 0x22), (
        "byte 0 pops one byte whatever the width")


def test_peeking_a_fifo_shows_the_next_byte_and_takes_nothing(fifo):
    fifo.hold_readable(I2C_DATA, b"\x31\x32")
    assert [fifo.peek_word(I2C_DATA) for _ in range(3)] == [0x31] * 3
    assert [fifo.read_word(I2C_DATA) for _ in range(2)] == [0x31, 0x32]
    with pytest.raises(abi.MemoryFault) as caught:
        fifo.peek_word(I2C_DATA)
    assert "holds nothing to read" in str(caught.value), str(caught.value)
    fifo.write_word(I2C_CLK_CONF, SCLK_ACTIVE | 1)
    assert fifo.peek_word(I2C_CLK_CONF) == fifo.read_word(I2C_CLK_CONF)
    assert fifo.peek_word(PC) == fifo.read_word(PC), "memory too"


def test_a_doorbell_mapped_over_a_stream_still_rings(bell):
    bell.map_register(SYSTIMER_CONF, UNIT0_WORK_EN)
    bell.map_stream(BELL, enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN)
    bell.map_doorbell(BELL, value=0, ring_mask=RING, write_trigger=RING)
    load(bell, ring_program(RING | CLK_EN))
    assert [raw_step(bell) for _ in range(3)][-1] == abi.RANG
    assert bell.stream(BELL) == b"", "the stream captured nothing"
    assert bell.read_word(BELL) == CLK_EN, "and the doorbell stored"



def test_a_doorbell_or_a_fifo_over_any_register_of_a_snapshot_counter_is_refused(cpu):
    """Replacing one of a counter's three registers dropped the counter and
    left the other two as plain words: a write of 0x55 to the old HIGH read
    back 0x55, a timer with no fault. Refused by name, the counter intact."""
    cpu.map_register(SYSTIMER_CONF, UNIT0_WORK_EN)
    mapped = (lambda: cpu.map_snapshot_counter(
        op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
        low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
        enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN,
        instructions_per_tick=1))
    for register in (UNIT0_OP, UNIT0_VALUE_LO, UNIT0_VALUE_HI):
        for name, attempt in (
                ("doorbell", lambda: cpu.map_doorbell(register, value=0,
                                                      ring_mask=1)),
                ("FIFO", lambda: cpu.map_fifo(register, enable=SYSTIMER_CONF,
                                              enable_mask=UNIT0_WORK_EN))):
            mapped()
            with pytest.raises(abi.AbiError) as caught:
                attempt()
            assert f"0x{register:08x}" in str(caught.value), str(caught.value)
            assert "snapshot counter" in str(caught.value), (name, str(caught.value))
            cpu.write_word(UNIT0_OP, UNIT0_UPDATE)
            assert cpu.read_word(UNIT0_OP) == UNIT0_VALUE_VALID, "still a counter"
            cpu.write_word(UNIT0_VALUE_HI, 0x55)
            assert cpu.read_word(UNIT0_VALUE_HI) != 0x55, "and not a stored word"


def test_a_stream_left_under_a_replaced_fifo_would_capture_the_register(fifo):
    """`map_stream`, `map_fifo`, `map_register`: nothing forgets a stream but
    the FIFO's own mapping, so a stream it did not erase captures the writes
    of the plain register that replaced it, and the register reads back 0."""
    fifo.map_stream(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
    fifo.map_fifo(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=SCLK_ACTIVE)
    fifo.map_register(I2C_DATA, 0)
    fifo.write_word(I2C_DATA, 0x41)
    assert fifo.read_word(I2C_DATA) == 0x41
    assert fifo.stream(I2C_DATA) == b""


def test_a_doorbell_at_address_zero_is_refused_by_name(cpu):
    with pytest.raises(abi.AbiError) as caught:
        cpu.map_doorbell(0, value=0, ring_mask=1)
    assert "address 0x0" in str(caught.value), str(caught.value)
    with pytest.raises(abi.AbiError):
        cpu.map_doorbell(3, value=0, ring_mask=1)


def test_an_alias_onto_a_fifo_or_a_doorbell_is_refused_by_name(bell, fifo):
    for target, kind in ((BELL, "doorbell"), (I2C_DATA, "FIFO")):
        for op in ("store", "set"):
            with pytest.raises(abi.AbiError) as caught:
                fifo.map_alias(BELL2 + 0x100, target, op)
            assert kind in str(caught.value), str(caught.value)
            assert f"0x{target:08x}" in str(caught.value), str(caught.value)
            assert not fifo.is_mapped(BELL2 + 0x100)


def test_a_service_for_an_address_that_is_no_doorbell_is_refused_by_name(bell):
    with pytest.raises(abi.AbiError) as caught:
        bell.on_ring(BELL2, lambda cpu, address: None)
    assert f"0x{BELL2:08x}" in str(caught.value) and "no doorbell" in str(caught.value)


def test_a_fifo_gate_that_is_never_open_or_does_not_fit_is_refused_with_the_value(cpu):
    for mask in (0, 1 << 32, -1):
        with pytest.raises(abi.AbiError) as caught:
            cpu.map_fifo(I2C_DATA, enable=I2C_CLK_CONF, enable_mask=mask)
        assert repr(mask) in str(caught.value), str(caught.value)


def test_a_zcmp_push_into_a_doorbell_is_a_fault_that_stores_and_rings_nothing(bell):
    """`cm.push {ra,s0}` stores s0 at sp-4 and ra at sp-8: with sp at
    BELL + 4 the first store would ring the doorbell. Here BELL is outside
    every region, and `exec.cc`'s preflight asks only the regions, so the
    push faults before storing anything. A register mapped INSIDE a region
    passes that preflight and is the case that reaches the `result == Ok`
    guard on a ring: `test_a_push_that_rings_and_then_faults_is_a_fault_and_
    not_a_ring`."""
    bell.set_extensions(abi.ESP32_C5)
    load(bell, [0xB852])
    regs = [0] * 32
    regs[2] = BELL + 4
    regs[8] = RING
    bell.set_regs(regs, pc=PC)
    assert raw_step(bell) == abi.MEMORY_FAULT
    assert bell.read_word(BELL) == 0, "nothing was stored"
    load(bell, [NOP])
    assert raw_step(bell) == abi.OK, "and the ring is not carried to the next"


def test_a_ring_through_a_byte_store_names_the_doorbells_word_address(cpu):
    cpu.map_doorbell(BELL, value=0, ring_mask=1 << 13, write_trigger=0)
    load(cpu, [e.lui("a4", I2C0 >> 12), e.addi("a5", "x0", RING),
               e.sb("a5", "a4", 5)])
    assert [raw_step(cpu) for _ in range(3)][-1] == abi.RANG
    assert cpu._lib.riscv32_rang_at(cpu._handle) == BELL, "not BELL + 1"


def test_a_doorbell_store_keeps_the_bytes_the_access_does_not_carry(cpu):
    cpu.map_doorbell(BELL, value=0x11223344, ring_mask=RING,
                     write_trigger=RING)
    _run(cpu, [e.sb("a5", "a4", 5), e.sh("a6", "a4", 6)],
         {14: I2C0, 15: 0xAA, 16: 0xBBCC})
    assert cpu.read_word(BELL) == 0xBBCCAA44


def test_a_reset_forgets_which_doorbell_rang(bell):
    load(bell, ring_program(RING))
    assert [raw_step(bell) for _ in range(3)][-1] == abi.RANG
    assert bell._lib.riscv32_rang_at(bell._handle) == BELL
    bell.reset()
    assert bell._lib.riscv32_rang_at(bell._handle) == 0


# --- the second fix round ----------------------------------------------------


def test_a_push_that_rings_and_then_faults_is_a_fault_and_not_a_ring(cpu):
    """The case the preflight does not catch: registers mapped INSIDE a
    region. `cm.push {ra,s0},-16` with sp at RAM + 0x208 stores s0 to a
    doorbell at +0x204, which rings, and then ra to a FIFO at +0x200 whose
    enable register is not mapped, which faults. The instruction never
    retired, so reporting a ring would run a service for it."""
    ram = RAM
    cpu.set_extensions(abi.ESP32_C5)
    cpu.map_doorbell(ram + 0x204, value=0, ring_mask=RING)
    cpu.map_fifo(ram + 0x200, enable=I2C_CLK_CONF, enable_mask=1)
    load(cpu, [0xB852])
    regs = [0] * 32
    regs[2] = ram + 0x208
    regs[8] = RING
    cpu.set_regs(regs, pc=PC)
    assert raw_step(cpu) == abi.MEMORY_FAULT
    assert cpu.pc == PC, "unretired: the PC did not move"
    assert cpu._lib.riscv32_rang_at(cpu._handle) == 0
    load(cpu, [NOP])
    assert raw_step(cpu) == abi.OK, "and no ring is carried to the next step"


def test_an_alias_made_before_the_fifo_or_the_doorbell_faults_at_the_access(cpu):
    """The reverse order of the refusal in `map_alias`: register, alias, then
    FIFO. The alias reaches the stored word and none of what the target does,
    so a read answered 0 with nothing held and a write stored a trigger bit."""
    alias = I2C0 + 0x200
    cpu.map_register(I2C_CLK_CONF, SCLK_ACTIVE)
    for target, make in (
            (I2C_DATA, lambda: cpu.map_fifo(I2C_DATA, enable=I2C_CLK_CONF,
                                            enable_mask=SCLK_ACTIVE)),
            (BELL, lambda: cpu.map_doorbell(BELL, value=0, ring_mask=RING,
                                            write_trigger=RING))):
        for op in ("store", "set"):
            cpu.map_register(target, 0)
            cpu.map_alias(alias, target, op, readable=(op == "store"))
            make()
            accesses = [lambda: cpu.write_word(alias, RING)]
            if op == "store":
                accesses.append(lambda: cpu.read_word(alias))
            for access in accesses:
                with pytest.raises(abi.MemoryFault) as caught:
                    access()
                assert "alias onto a FIFO or a doorbell" in str(caught.value), (
                    op, str(caught.value))


def test_an_address_past_32_bits_is_refused_and_not_truncated_to_zero(cpu):
    with pytest.raises(abi.AbiError) as caught:
        cpu.map_doorbell(1 << 32, value=0, ring_mask=1)
    assert "0x100000000" in str(caught.value), str(caught.value)
    assert not cpu._lib.riscv32_is_doorbell(cpu._handle, 0)
    for field in ("address", "enable"):
        kwargs = {"address": I2C_DATA, "enable": I2C_CLK_CONF}
        kwargs[field] = 1 << 32
        with pytest.raises(abi.AbiError) as caught:
            cpu.map_fifo(kwargs["address"], enable=kwargs["enable"],
                         enable_mask=1)
        assert field in str(caught.value) and "4294967296" in str(caught.value)
    assert not cpu._lib.riscv32_is_fifo(cpu._handle, 0)


def test_retiring_an_instruction_keeps_the_reason_of_the_last_fault(fifo):
    """`note_executed` reads a snapshot counter's gate, which may note a fault
    of its own (a readable alias onto nothing); it put the address back and
    left the reason it had noted, so a `MemoryFault` worded after the next
    instruction said 'unmapped' for an empty FIFO read."""
    fifo.map_alias(SYSTIMER_CONF, SYSTIMER_CONF + 0x10, "store", readable=True)
    fifo.map_snapshot_counter(
        op=UNIT0_OP, update_mask=UNIT0_UPDATE, valid_mask=UNIT0_VALUE_VALID,
        low=UNIT0_VALUE_LO, high=UNIT0_VALUE_HI, high_mask=VALUE_HI_BITS,
        enable=SYSTIMER_CONF, enable_mask=UNIT0_WORK_EN, instructions_per_tick=1)
    with pytest.raises(abi.MemoryFault):
        fifo.read_word(I2C_DATA)
    assert fifo._lib.riscv32_fault_reason(fifo._handle) == 1
    load(fifo, [NOP])
    fifo.step()
    assert fifo._lib.riscv32_fault_address(fifo._handle) == I2C_DATA
    assert fifo._lib.riscv32_fault_reason(fifo._handle) == 1


def test_a_peek_leaves_the_fault_record_as_the_last_instruction_left_it(fifo):
    """Succeeding or failing: a viewer's read is no access of the firmware's,
    so the address, the kind and the reason of its last fault stay."""
    with pytest.raises(abi.MemoryFault):
        fifo.read_word(0x10)
    record = (fifo._lib.riscv32_fault_address(fifo._handle),
              fifo._lib.riscv32_fault_was_fetch(fifo._handle),
              fifo._lib.riscv32_fault_reason(fifo._handle))
    assert record == (0x10, 0, 0)
    with pytest.raises(abi.MemoryFault) as caught:
        fifo.peek_word(I2C_DATA)
    assert "holds nothing to read" in str(caught.value), (
        "the failed peek still says why")
    fifo.hold_readable(I2C_DATA, b"\x05")
    assert fifo.peek_word(I2C_DATA) == 5
    after = (fifo._lib.riscv32_fault_address(fifo._handle),
             fifo._lib.riscv32_fault_was_fetch(fifo._handle),
             fifo._lib.riscv32_fault_reason(fifo._handle))
    assert after == record


def test_a_reset_value_past_32_bits_is_refused_and_not_truncated(cpu):
    """`1 << 33` reached the core as 0 on every call that takes a `value`."""
    calls = (
        lambda: cpu.map_register(I2C_CLK_CONF, 1 << 33),
        lambda: cpu.map_register(I2C_CLK_CONF, -1),
        lambda: cpu.map_doorbell(BELL, value=1 << 33, ring_mask=RING),
        lambda: cpu.map_sampler(
            BELL, value=1 << 33, start_mask=1 << 31, key_mask=0,
            result=I2C_CLK_CONF, status=I2C_CLK_CONF, done_mask=1,
            enable=I2C_CLK_CONF, enable_mask=1),
    )
    for index, call in enumerate(calls):
        with pytest.raises(abi.AbiError) as caught:
            call()
        assert "value" in str(caught.value) and "32 bits" in str(caught.value), (
            index, str(caught.value))
    assert not cpu.is_mapped(I2C_CLK_CONF) and not cpu.is_mapped(BELL)
