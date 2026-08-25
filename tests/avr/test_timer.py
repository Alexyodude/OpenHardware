# OpenHardware — timer 0, and the one interrupt this core delivers.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this checks that test_arduino_sketch.py does not
#
# That file watches a real sketch blink, which is the claim OH-59 exists to
# make. It costs eight seconds and it can only fail one way: the LED does not
# move. These are the individual rules underneath it, each able to fail on its
# own and say which one broke.
#
# ## The flag is set whether or not the interrupt is enabled
#
# Not a detail. `micros()` reads TIFR0's TOV0 **directly**:
#
#     m = timer0_overflow_count;
#     t = TCNT0;
#     if ((TIFR0 & _BV(TOV0)) && (t < 255))
#         m++;
#
# so it notices an overflow that has happened and not yet been serviced, and
# adds one itself. A model that only set the flag on the way into the handler
# would lose a millisecond every time an overflow landed inside a `cli()`.
#
# ## Why these run a real overflow instead of writing the flag
#
# Because writing it clears it. TIFR0 is write-one-to-clear on the silicon --
# "TOV0 is cleared by writing a logic one to the flag" -- and `core/avr/cpu.cc`
# models that, so `write_data(TIFR0, 1)` is an acknowledgement and not a way to
# arm one. `arm()` below runs the 16,384 instructions an overflow actually
# takes, which costs about eight milliseconds and is the honest setup.

import pytest

from core.avr import abi
from webui.boards import atmega328p as board

#: One overflow: 256 counter ticks at 64 retired instructions each.
INSTRUCTIONS_PER_OVERFLOW = 256 * board.INSTRUCTIONS_PER_TICK

#: SREG in the data space, from `iom328p.h`. Written rather than assigned
#: because `core.avr.abi.Cpu.sreg` is read-only -- the register is a byte of
#: memory and there is deliberately no second way to reach it.
SREG = 0x5F

NOP = 0x0000
SEI = 0x9478
RETI = 0x9518

TOV0 = 1 << board.TOV0
TOIE0 = 1 << board.TOIE0
I_FLAG = 1 << 7

#: The words below the vector, used as a place to run for a long time.
#: `TIMER0_OVF_VECTOR` is word 32, so 0..31 is everything before the handler
#: and the lap length divides the overflow exactly -- which is what makes the
#: PC after `arm()` predictable rather than merely bounded.
SPIN_WORDS = board.TIMER0_OVF_VECTOR


@pytest.fixture
def uno(cpu):
    """The `cpu` fixture with the board installed, which is what maps a timer.

    `conftest.py`'s fixture calls `configure` alone: the core ships without a
    timer and only a board description gives it one, which is the boundary
    `webui/boards/atmega328p.py` exists to hold.
    """
    board.install(cpu)
    return cpu


def spin(cpu) -> None:
    """Fill the words below the vector with nops and a branch back to zero.

    So the machine can be run for a long time without walking off into the
    erased 0xFFFF that would stop it -- and without touching the handler.
    """
    for address in range(SPIN_WORDS - 1):
        cpu.write_program(address, NOP)
    # rjmp back to word 0. The displacement is from the word AFTER this one.
    cpu.write_program(SPIN_WORDS - 1, 0xC000 | ((-SPIN_WORDS) & 0x0FFF))
    cpu.pc = 0


def arm(cpu) -> None:
    """Run until the counter really overflows, with delivery disabled.

    TOIE0 and I are both clear here, so nothing is taken and the flag simply
    stays set -- which is exactly the state `micros()` is written to read.
    """
    spin(cpu)
    for _ in range(INSTRUCTIONS_PER_OVERFLOW):
        cpu.step()
    assert cpu.read_data(board.TIFR0) & TOV0, "the overflow did not happen"
    assert cpu.pc == 0, "the spin loop did not land back at word 0"


# --- the counter ------------------------------------------------------------


def test_the_counter_advances_with_retired_instructions(uno):
    """TCNT0 is not a stored byte. It is `executed() / 64`, low eight bits."""
    spin(uno)
    for _ in range(board.INSTRUCTIONS_PER_TICK * 3):
        uno.step()
    assert uno.read_data(board.TCNT0) == 3


def test_the_counter_reads_zero_before_a_whole_tick_has_passed(uno):
    """Sixty-three instructions is not a tick, and rounding up would make
    every busy-wait finish early."""
    spin(uno)
    for _ in range(board.INSTRUCTIONS_PER_TICK - 1):
        uno.step()
    assert uno.read_data(board.TCNT0) == 0


def test_the_counter_is_eight_bits_and_wraps(uno):
    """`micros()` rebuilds a 32-bit time from an overflow count and this byte,
    so the byte must wrap rather than saturate or keep growing."""
    arm(uno)
    for _ in range(board.INSTRUCTIONS_PER_TICK * 2):
        uno.step()
    assert uno.read_data(board.TCNT0) == 2


def test_the_property_and_the_register_agree(uno):
    """`cpu.timer_count` and a data read of TCNT0 are the same number reached
    two ways, and a test that used only one would not notice the other."""
    spin(uno)
    for _ in range(board.INSTRUCTIONS_PER_TICK * 5):
        uno.step()
    assert uno.timer_count == uno.read_data(board.TCNT0) == 5


def test_the_overflow_flag_is_clear_before_the_wrap(uno):
    """So `test_the_overflow_flag_is_set_with_the_interrupt_disabled` cannot
    pass on a flag that is simply always set."""
    spin(uno)
    for _ in range(INSTRUCTIONS_PER_OVERFLOW - 2):
        uno.step()
    assert not uno.read_data(board.TIFR0) & TOV0


def test_the_overflow_flag_is_set_with_the_interrupt_disabled(uno):
    """**The rule `micros()` depends on**, and the reason the flag is set in
    `note_executed` rather than on the way into the handler. See the header."""
    arm(uno)
    assert not uno.read_data(board.TIMSK0) & TOIE0
    assert not uno.sreg & I_FLAG
    assert uno.read_data(board.TIFR0) & TOV0


def test_writing_one_to_the_flag_clears_it(uno):
    """Write-one-to-clear, as the datasheet specifies for every AVR interrupt
    flag register. A model that stored the byte would let a program *set* a
    pending interrupt by writing the bit it meant to acknowledge."""
    arm(uno)
    uno.write_data(board.TIFR0, TOV0)
    assert not uno.read_data(board.TIFR0) & TOV0


def test_writing_zero_to_the_flag_leaves_it_alone(uno):
    """The other half of write-one-to-clear, and the half a naive
    implementation gets wrong: writing 0x00 must not clear anything."""
    arm(uno)
    uno.write_data(board.TIFR0, 0x00)
    assert uno.read_data(board.TIFR0) & TOV0


def test_writing_the_counter_is_refused_rather_than_dropped(uno):
    """The silicon allows a write to TCNT0 and this model cannot honour one,
    because the count is derived from `executed()`.

    Refusing is the loud answer. Accepting and ignoring would let a program
    reset the counter, read back an unrelated number, and conclude its own
    arithmetic was wrong -- the load-and-report-success failure this repository
    ranks worst. See `core/avr/cpu.cc`.
    """
    with pytest.raises(abi.MemoryFault) as caught:
        uno.write_data(board.TCNT0, 0)
    assert "0x0046" in str(caught.value)


def test_a_timer_outside_the_data_space_is_refused_with_its_numbers(uno):
    """The step path indexes data memory without bounds checks, so the check
    happens once at mapping time -- and the message says which value was
    wrong, not merely that one was."""
    with pytest.raises(abi.AbiError) as caught:
        uno.map_timer(counter=board.TCNT0, flag=0xFFFF, enable=board.TIMSK0,
                      bit=0, vector=board.TIMER0_OVF_VECTOR,
                      instructions_per_tick=64)
    assert "0xffff" in str(caught.value)


def test_a_zero_tick_is_refused_rather_than_dividing_by_it(uno):
    """`timer_count` divides by this. Nothing else needs saying."""
    with pytest.raises(abi.AbiError):
        uno.map_timer(counter=board.TCNT0, flag=board.TIFR0,
                      enable=board.TIMSK0, bit=0,
                      vector=board.TIMER0_OVF_VECTOR, instructions_per_tick=0)


# --- delivery ---------------------------------------------------------------


def test_no_vector_is_taken_while_the_global_flag_is_clear(uno):
    """I clear means no interrupt, whatever the source is doing. That is what
    `cli()` buys, and `micros()` spends it around every read."""
    arm(uno)
    uno.write_data(board.TIMSK0, TOIE0)
    for _ in range(4):
        uno.step()
    assert uno.pc == 4, "a vector was taken with I clear"


def test_no_vector_is_taken_while_the_source_is_disabled(uno):
    """TOIE0 clear means this source is not delivered even with I set. The
    other term of the three-term condition."""
    arm(uno)
    uno.write_data(SREG, I_FLAG)
    for _ in range(4):
        uno.step()
    assert uno.pc == 4, "a vector was taken with TOIE0 clear"


def test_an_enabled_overflow_takes_the_vector(uno):
    """All three terms true, so the next step is the vector and not the next
    instruction."""
    arm(uno)
    uno.write_data(board.TIMSK0, TOIE0)
    uno.write_data(SREG, I_FLAG)
    uno.step()
    assert uno.pc == board.TIMER0_OVF_VECTOR


def test_taking_the_vector_clears_the_flag_and_the_global_enable(uno):
    """Both, and each for its own reason.

    The flag, because otherwise the handler is re-entered the instant it
    returns. I, because an AVR handler runs with interrupts off until it says
    otherwise -- and `reti` is what says otherwise.
    """
    arm(uno)
    uno.write_data(board.TIMSK0, TOIE0)
    uno.write_data(SREG, I_FLAG)
    uno.step()
    assert not uno.read_data(board.TIFR0) & TOV0
    assert not uno.sreg & I_FLAG


def test_taking_the_vector_pushes_the_instruction_that_did_not_run(uno):
    """An interrupt is taken *instead of* an instruction rather than after
    one, so the return address is the word that never executed -- and nothing
    is run twice on the way back."""
    arm(uno)
    uno.write_data(board.TIMSK0, TOIE0)
    top = uno.sp
    uno.step()
    uno.step()                       # two nops, still undeliverable: I is clear
    assert uno.pc == 2

    uno.write_data(SREG, I_FLAG)
    uno.step()
    assert uno.pc == board.TIMER0_OVF_VECTOR
    assert uno.sp == top - 2
    assert (uno.read_data(top - 1) << 8) | uno.read_data(top) == 2


def test_reti_returns_to_the_interrupted_word_and_restores_the_global_flag(uno):
    """The round trip, which is what keeps `millis()` counting.

    The handler here is a single `reti`, so the machine goes out and straight
    back -- and must arrive at the instruction it never ran.
    """
    arm(uno)
    uno.write_program(board.TIMER0_OVF_VECTOR, RETI)
    uno.write_data(board.TIMSK0, TOIE0)
    uno.step()                       # a nop at word 0
    uno.write_data(SREG, I_FLAG)

    uno.step()                       # the vector, instead of word 1
    assert uno.pc == board.TIMER0_OVF_VECTOR
    uno.step()                       # reti
    assert uno.pc == 1, "returned somewhere other than the interrupted word"
    assert uno.sreg & I_FLAG, "reti did not restore I"


def test_sei_protects_exactly_one_following_instruction(uno):
    """A datasheet rule, and the one that stops a handler which re-enables
    early from re-entering before the interrupted code has moved at all.

    Without it the vector would be taken at word 1. With it, word 1 runs and
    the vector is taken at word 2.
    """
    arm(uno)
    uno.write_data(board.TIMSK0, TOIE0)
    uno.write_program(0, SEI)
    uno.pc = 0

    uno.step()                       # sei
    assert uno.sreg & I_FLAG
    assert uno.interrupt_inhibited
    uno.step()                       # the protected nop at word 1
    assert uno.pc == 2, "the vector was taken during sei's protected step"
    assert not uno.interrupt_inhibited
    uno.step()
    assert uno.pc == board.TIMER0_OVF_VECTOR


def test_reti_protects_one_instruction_the_same_way(uno):
    """`reti` restores I and must protect the next instruction too.

    Asserted on the machine's own inhibit rather than on a re-entry, because
    with one interrupt source a re-entry cannot be arranged: the flag is
    cleared on the way in, so the next one is 16,384 instructions away. An ISA
    rule nothing can assert is an ISA rule that quietly rots, which is what
    `Cpu.interrupt_inhibited` is for.
    """
    arm(uno)
    uno.write_program(board.TIMER0_OVF_VECTOR, RETI)
    uno.write_data(board.TIMSK0, TOIE0)
    uno.write_data(SREG, I_FLAG)

    uno.step()                       # the vector
    assert not uno.interrupt_inhibited, "entering a handler protects nothing"
    uno.step()                       # reti
    assert uno.interrupt_inhibited
