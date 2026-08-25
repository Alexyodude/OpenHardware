# OpenHardware — an Arduino Uno, driven the way the browser drives it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this proves that `test_blink.py` does not
#
# That file drives `core.avr.abi.Cpu` directly: it configures the machine
# itself, writes the image itself, and sets the PC itself. It proves the
# instruction set works and it is the reason `core/avr` exists.
#
# It proves nothing about whether a *board* can be selected and loaded, and
# that gap is exactly what OH-49 stopped in front of. `webui/api.py` was built
# around one kind of machine -- ten of its twelve `Core` methods are meaningless
# on a Harvard part -- so an `atmega328p.py` could have satisfied the board
# contract while `api.load_firmware` could not enter it. The catalogue would
# then have reported Arduino Uno runnable, which is the claim-you-cannot-keep
# failure `rules/board-claims.md` exists to prevent.
#
# So everything below goes through `webui/api.py`. Nothing here touches
# `configure`, `write_program_block` or `pc` -- a board name and a file of
# bytes go in, and PB5 moves.
#
# ## Why this file is the evidence for ATmega328P
#
# `webui/boards/catalogue.py`'s `FIRMWARE_VERIFIED` names it, which is the only
# thing in this repository that licenses the words "runs firmware". The claim
# is the *board* one, so the board path is what has to be watched -- naming
# `test_blink.py` there would cite evidence for a different claim.
#
# ## What it cannot claim
#
# `docs/architectures.md` records AVR's candidate oracles -- simavr, avr-gdb --
# as neither of them hardware-captured, and neither is installed here. This
# does not reach the standard `core/i8086` meets against SST8088 and nothing
# below says it does. It reaches the standard the RP2040 and SAMD21 met: a real
# compiled image, watched.

import itertools
import pathlib

import pytest

from webui import api
from webui.boards import atmega328p

HERE = pathlib.Path(__file__).resolve().parent

#: The same 46 bytes `test_blink.py` runs: avr-gcc 7.3.0 at -Os from
#: `blink/blink.c`, committed, and rebuilt by
#: `test_the_committed_binary_matches_its_source` wherever a compiler exists.
IMAGE = HERE / "blink" / "blink.bin"

#: The board, spelled as `webui/boards/catalogue.py`'s `IRREGULAR` spells it.
BOARD = "Arduino Uno"

#: PB5 is the Uno's LED, and `atmega328p.LED_PIN` is where that is written
#: down with its citation. Named through the board module rather than as a
#: literal, so this test breaks if the board description ever disagrees.
LED = 1 << atmega328p.LED_PIN

#: Long enough for several toggles at the 1,110-instruction period
#: `tests/avr/test_blink.py` measured.
BUDGET = 20_000


def needs_core() -> None:
    """Skip loudly where avr is not built, rather than failing."""
    pytest.importorskip("core.avr.abi")
    if not IMAGE.is_file():
        pytest.skip(f"{IMAGE} is missing")


def load() -> api.BoardSession:
    """A board name and a file of bytes. `base=0` because a raw `.bin` carries
    no address of its own and an AVR image starts at program byte zero."""
    return api.load_firmware(BOARD, IMAGE.read_bytes(), base=0)


def watch_led(session: api.BoardSession, budget: int = BUDGET) -> list[tuple[int, bool]]:
    """Step, recording every step at which the LED pin changes state.

    Read through `session.cpu.read_data`, which names the **data** space --
    PORTB is a byte of it at 0x25. There is no `read_word` here and no flat
    address: this machine has two spaces and every accessor says which.
    """
    transitions: list[tuple[int, bool]] = []
    last = 0
    for step in range(budget):
        session.step()
        now = session.cpu.read_data(atmega328p.PORTB) & LED
        if now != last:
            transitions.append((step, bool(now)))
            last = now
    return transitions


# --- the headline -----------------------------------------------------------


def test_a_board_name_and_a_compiled_image_are_enough_to_make_the_led_blink():
    """The claim OH-52 exists to make true, and the evidence for ATmega328P.

    Two transitions is a blink. One is a pin that came on and stayed on, which
    is what a broken toggle looks like from the outside.
    """
    needs_core()
    with load() as session:
        transitions = watch_led(session)
    assert len(transitions) >= 2, f"the pin changed state {len(transitions)} times"
    states = [state for _, state in transitions]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]


def test_the_pin_is_configured_as_an_output_and_the_period_is_steady():
    """A toggle on a pin still set to input is a lie the value register alone
    cannot catch, and a wandering period means the delay loop is wrong.

    The period is the assertion that caught the branch-polarity defect in
    `core/avr/exec.cc`: an inverted `brbc` still toggled and still alternated,
    at ten instructions instead of eleven hundred.
    """
    needs_core()
    with load() as session:
        steps = [step for step, _ in watch_led(session)]
        assert session.cpu.read_data(atmega328p.DDRB) & LED, "PB5 is an output"
    periods = {b - a for a, b in itertools.pairwise(steps[1:])}
    assert len(periods) == 1, f"period varies: {sorted(periods)}"


def test_the_memory_window_shows_the_data_space_at_the_datasheet_addresses():
    """Which of two address spaces the hexdump shows, decided and pinned.

    An AVR has program memory and data memory and a pane can only show one.
    **Data**, because the disassembly pane is what shows the program side, and
    a hexdump of the register file, the IO window and SRAM is what a person
    watching a running board actually wants. So the window opens at 0x0000 of
    the *data* space -- r0 -- and DDRB and PORTB appear at 0x24 and 0x25, which
    is `_SFR_IO8(0x04)` and `_SFR_IO8(0x05)` plus the 0x20 that separates an
    `in`/`out` address from a data one.

    **This test exists because a mutation survived.** `read` returning
    `cpu.read_data(address)` for every byte -- the same byte repeated, offset
    ignored -- passed all 371 tests. A browser saw the difference and nothing
    else did.
    """
    needs_core()
    with load() as session:
        watch_led(session)
        window = session.state(memory_at=0, memory_length=64)["memory"]
    assert window["at"] == 0, "the register file, which is where a data space starts"
    assert len(window["bytes"]) == 64
    assert window["bytes"][atmega328p.DDRB] & LED, "DDRB at 0x24, PB5 an output"
    assert window["bytes"][atmega328p.PORTB] & LED, "PORTB at 0x25, PB5 driven"
    assert window["bytes"][atmega328p.PINB] == 0, "PINB at 0x23, and not modelled"


def test_the_window_is_the_data_space_and_not_the_program_one():
    """The same claim from the other side, because "shows data memory" is only
    a real decision if the two spaces disagree.

    Program word 0 of the blink is `0x93cf` -- `push r28` -- so its low byte is
    0xCF. Data byte 0 is r0, which is zero. If the pane were reading program
    memory the first byte of the dump would be 0xCF.
    """
    needs_core()
    with load() as session:
        window = session.state(memory_at=0, memory_length=16)["memory"]
        assert session.cpu.read_program(0) == 0x93CF, "push r28, the first word"
    assert window["bytes"][0] == 0x00, "r0, not the low byte of the first opcode"


# --- entering a machine that has no vector table -----------------------------


def test_the_board_enters_at_zero_and_reports_no_words_it_does_not_have():
    """The design decision, stated as a fact on the wire.

    An Arm board's report carries `vector_table` and `stack_pointer` because it
    entered through two words of the image. This board has neither, and they
    are **absent** rather than null: null would say there is a stack-pointer
    word whose value is unknown, and absence says the machine has no such word.
    """
    needs_core()
    with load() as session:
        report = session.as_json()
    assert report["board"] == BOARD
    assert report["chip"] == "ATmega328P"
    assert report["core"] == "avr"
    assert report["entry"] == 0, "an AVR begins executing at word zero"
    assert "vector_table" not in report
    assert "stack_pointer" not in report


def test_no_vector_table_is_asked_for_and_none_is_offered_as_advice():
    """The board declares no `VECTOR_TABLE_OFFSETS` and is not asked for one.

    The second half matters as much as the first. `api.load_firmware` suggests
    `vector_table=` when a search fails, and suggesting it here would send a
    reader looking for a table this part does not have -- so the advice is
    conditional on the board declaring offsets at all.
    """
    from webui.boards import contract

    assert not hasattr(atmega328p, "VECTOR_TABLE_OFFSETS")
    assert contract.core_requirements("avr") == ()
    assert contract.missing(atmega328p, "avr") == []


def test_the_stack_pointer_comes_up_at_ramend_through_the_board_path():
    """`install` calls `configure`, which resets the machine and puts SP at the
    top of the data space. A bare-metal image built with `-nostartfiles` never
    writes SP itself, so left at zero the first `push` would run off the bottom
    and fault on an image the silicon runs happily.

    Asserted here as well as in `test_blink.py` because the two arrive by
    different routes: there the fixture calls `configure` directly, and here it
    has to survive `blank`, `install`, the image write and `enter` in that
    order.
    """
    needs_core()
    with load() as session:
        registers = {r["name"]: r for r in session.state()["registers"]}
    assert registers["sp"]["value"] == atmega328p.STACK_TOP
    assert registers["pc"]["value"] == 0


def test_writing_the_image_first_would_erase_it():
    """Why `webui/api.py` installs before it loads, pinned rather than assumed.

    `configure` fills program memory with the erased word, so a caller that
    wrote the image and then described the board would be left with a blank
    flash and no error. The order is a precondition `webui/boards/atmega328p.py`
    states in its docstring; this is what makes it a measurement.
    """
    needs_core()
    abi = pytest.importorskip("core.avr.abi")
    with abi.Cpu() as cpu:
        cpu.configure(atmega328p.PROGRAM_WORDS, atmega328p.DATA_BYTES)
        cpu.write_program_block(0, IMAGE.read_bytes())
        assert cpu.read_program(0) != 0xFFFF, "the image is there"
        atmega328p.install(cpu)
        assert cpu.read_program(0) == 0xFFFF, "and installing again erased it"


# --- the image counts bytes and the machine counts words ---------------------


def test_a_segment_above_zero_lands_in_the_words_it_should():
    """The bytes-to-words conversion, witnessed.

    **This test exists because a mutation survived.** Replacing
    `write_program_block(address // 2, data)` with `write_program_block(address,
    data)` left every test here passing, for the reason `docs/` calls a blind
    fixture rather than a bad test: the blink is one segment at address zero,
    and `0 // 2 == 0`. The conversion is real -- an image linked above zero
    puts byte 0x100 in word 0x80 -- and nothing was looking at it.

    Eight bytes rather than the blink, because what is being measured is where
    they land and not what they do.
    """
    needs_core()
    payload = bytes(range(8))
    with api.load_firmware(BOARD, payload, base=0x100) as session:
        assert session.cpu.read_program(0x80) == 0x0100, "bytes 00 01, low first"
        assert session.cpu.read_program(0x83) == 0x0706, "and the last pair"
        assert session.cpu.read_program(0x7F) == 0xFFFF, "below it is erased flash"


def test_an_image_above_zero_is_told_that_the_machine_still_enters_at_zero():
    """Not refused -- a linker script may start an image above zero and the gap
    is erased flash. But the AVR enters at 0x0000 regardless, so a reader
    watching it execute 0xFFFF is told why rather than left to work it out."""
    needs_core()
    with api.load_firmware(BOARD, bytes(range(8)), base=0x100) as session:
        report = session.as_json()
    assert report["entry"] == 0
    assert any("enters at 0x0000" in note for note in report["notes"]), report["notes"]


def test_an_odd_program_address_is_refused_for_the_reason_it_is_refused():
    """The message a bool could not carry.

    This board maps 0x0101 perfectly well; what it cannot do is put half a word
    there. Reported as "maps nothing at 0x0101" -- which is what a
    bool-returning predicate forced, because the caller composing the sentence
    knows the board's name and not what a word is -- the refusal sends a reader
    to check their linker script against a memory map that was never the
    problem.
    """
    needs_core()
    with pytest.raises(api.BoardRunError) as caught:
        api.load_firmware(BOARD, bytes(8), base=0x101)
    message = str(caught.value)
    assert caught.value.reason == "outside-the-board-map"
    assert "odd program address" in message
    assert "halfway through a word" in message
    assert "maps nothing" not in message, "it maps it; it cannot split it"


def test_write_refuses_an_odd_program_address_rather_than_truncating():
    """The precondition stated where it is relied on.

    `webui/api.py` calls `refuses` first so this never fires through that path,
    which is exactly why it is asserted directly: an unreachable guard nobody
    exercises is one that silently stops working. Truncating instead would put
    the segment half a word early and run a program nobody wrote.
    """
    needs_core()
    from core.avr import machine

    abi = pytest.importorskip("core.avr.abi")
    with abi.Cpu() as cpu:
        atmega328p.install(cpu)
        with pytest.raises(machine.MachineError) as caught:
            machine.write(cpu, 0x101, b"\x00\x01")
    assert "odd program address" in str(caught.value)


# --- what this board does not model, said out loud ---------------------------


def test_reading_the_input_register_is_not_yet_modelled():
    """`PINB` reads the electrical level on the pins, so on PB5 driven high it
    should read high. This model returns the stored zero.

    Pinned as the limitation it is rather than left to be discovered. Unlike
    `webui/boards/samd21.py`, which leaves its `PORT_IN` unmapped so a read
    faults instead of lying, there is nothing to unmap here -- every byte of an
    AVR's data space exists. The fix is a mirror of `PORTB` masked by `DDRB`,
    which needs a mapping mechanism `core/avr` does not have.

    When that lands, this test fails, and the failure is the notification.
    """
    needs_core()
    with load() as session:
        watch_led(session)
        assert session.cpu.read_data(atmega328p.PORTB) & LED, "PB5 is driven high"
        assert session.cpu.read_data(atmega328p.PINB) & LED == 0, (
            "and PINB still reads zero, which is wrong on real silicon"
        )


def test_the_core_has_no_disassembler_and_the_listing_says_so():
    """An empty listing would be a claim about the image; `present: false` is a
    claim about this repository, and they are different facts. The board still
    steps and its registers still read.
    """
    needs_core()
    with load() as session:
        listing = session.state()["listing"]
    assert listing["present"] is False
    assert "avr" in listing["note"]
    assert listing["lines"] == []

