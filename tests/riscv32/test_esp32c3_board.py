# OpenHardware — an ESP32-C3 board, driven the way the browser drives it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this proves that test_rvc.py does not
#
# That file drives `core.riscv32.abi.Cpu` directly: it adds its own regions,
# writes the image itself, and sets the PC and the stack pointer itself. It
# proves the compressed decoder works.
#
# It proves nothing about whether a *board* can be selected and loaded, which
# is a different claim and the one `webui/boards/catalogue.py`'s
# `FIRMWARE_VERIFIED` makes. So everything below goes through `webui/api.py`: a
# board name and a file of bytes go in, and GPIO8 moves.
#
# ## What it cannot claim
#
# **An ESP-IDF application will not run on this board**, and nothing here
# suggests otherwise. An ESP32-C3 resets into 384 KB of Espressif mask ROM that
# sets up the cache, the clock and its own function table before `app_main`;
# that ROM is not redistributable and is not modelled. `docs/architectures.md`
# records that PICSimLab's own ESP route runs the vendor's QEMU rather than
# modelling any of it.
#
# What runs is a bare-metal image, which is the standard `tests/cortexm0/
# test_blink.py`, `test_samd21_blink.py` and `tests/avr/test_uno_board.py`
# already meet.
#
# ## And there is no LED to watch
#
# Measured, not assumed: Seeed's own `XIAO_ESP32C3/pins_arduino.h` is 34 lines
# and contains the string "LED" zero times, where the Arduino Uno's variant
# defines `LED_BUILTIN 13`. So this watches the GPIO register the firmware
# drives rather than a pin something is wired to -- a smaller claim than the
# RP2040's, and a true one.

import itertools
import pathlib
import shutil
import subprocess

import pytest

from webui import api
from webui.boards import esp32c3

HERE = pathlib.Path(__file__).resolve().parent
IMAGE = HERE / "c3blink" / "blink.bin"
SOURCE = HERE / "c3blink" / "blink.c"
SCRIPT = HERE / "c3blink" / "blink.ld"

#: One of the three XIAO ESP32-C3 boards in the catalogue. They differ in
#: footprint and not in silicon, so the description serves all three.
BOARD = "XIAO-ESP32-C3-DIP"

LED = 1 << esp32c3.LED_PIN
GPIO_OUT = esp32c3.GPIO + esp32c3.GPIO_OUT
GPIO_ENABLE = esp32c3.GPIO + esp32c3.GPIO_ENABLE

#: Several toggles at the measured 606-instruction period.
BUDGET = 20_000


def needs_core() -> None:
    pytest.importorskip("core.riscv32.abi")
    if not IMAGE.is_file():
        pytest.skip(f"{IMAGE} is missing")


def load() -> api.BoardSession:
    """A board name and a file of bytes. `base` because a raw `.bin` carries no
    address of its own, and this one is linked into the flash execute window."""
    return api.load_firmware(BOARD, IMAGE.read_bytes(), base=esp32c3.IROM)


def watch(session: api.BoardSession, budget: int = BUDGET) -> list[tuple[int, bool]]:
    """Step, recording every step at which GPIO8 changes state."""
    transitions: list[tuple[int, bool]] = []
    last = 0
    for step in range(budget):
        session.step()
        now = session.cpu.read_word(GPIO_OUT) & LED
        if now != last:
            transitions.append((step, bool(now)))
            last = now
    return transitions


# --- the headline -----------------------------------------------------------


def test_a_board_name_and_a_compiled_image_drive_a_gpio_register():
    """The evidence for ESP32-C3, and the seven-board unlock's first three.

    Two transitions is a blink. One is a bit that came on and stayed on, which
    is what a broken toggle looks like from the outside.
    """
    needs_core()
    with load() as session:
        transitions = watch(session)
    assert len(transitions) >= 2, f"the bit changed {len(transitions)} times"
    states = [state for _, state in transitions]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]


def test_the_pin_is_configured_as_an_output_and_the_period_is_steady():
    """A toggle on a pin still configured as an input is a lie the output
    register alone cannot catch, and a wandering period means the delay loop is
    wrong. The period is what caught the AVR's inverted branch."""
    needs_core()
    with load() as session:
        steps = [step for step, _ in watch(session)]
        assert session.cpu.read_word(GPIO_ENABLE) & LED, "GPIO8 is an output"
    periods = {b - a for a, b in itertools.pairwise(steps[1:])}
    assert len(periods) == 1, f"period varies: {sorted(periods)}"
    assert periods.pop() > 100, "a loop counting to 100 costs more than 100 steps"


# --- what this machine reports, which is not what an Arm one does ------------


def test_the_board_reports_no_vector_table_because_it_has_none():
    """An RV32 part resets to a chip-defined address and reads no table. The
    two words an Arm report carries are **absent** rather than null: null would
    claim there is a stack-pointer word whose value is unknown."""
    needs_core()
    with load() as session:
        report = session.as_json()
    assert report["chip"] == "ESP32-C3"
    assert report["core"] == "riscv32"
    assert report["entry"] == esp32c3.IROM, "the image's first byte"
    assert "vector_table" not in report
    assert "stack_pointer" not in report


def test_the_state_reports_thirty_three_registers_and_no_flags():
    """RV32 has no condition-code register: a comparison writes a register and
    a branch compares two. So an empty `flags` is the true answer rather than a
    missing feature, and the page renders nothing rather than four wrong
    letters."""
    needs_core()
    with load() as session:
        state = session.state()
    names = [register["name"] for register in state["registers"]]
    assert len(names) == 33, "x0..x31 and pc"
    assert names[:3] == ["zero", "ra", "sp"], "the ABI names, as objdump spells them"
    assert names[-1] == "pc"
    assert state["flags"] == []
    assert all(register["width"] == 32 for register in state["registers"])


def test_the_listing_shows_the_instructions_around_the_program_counter():
    """The fourth pane, and the last one this board was missing.

    **This asserted `present: false` until OH-56.** What it checks now is the
    property that breaks first: an RV32 listing interleaves 16-bit and 32-bit
    instructions, so a disassembler advancing by a constant produces a
    plausible listing offset by two bytes from the second line on.
    """
    needs_core()
    with load() as session:
        session.run(2000)
        state = session.state()
        listing = state["listing"]

    assert listing["present"] is True
    assert listing["at"] == state["pc"]
    assert listing["lines"], "a listing with no lines is not a listing"

    current = [line for line in listing["lines"] if line["current"]]
    assert len(current) == 1, "exactly one line is where execution is"
    assert current[0]["address"] == state["pc"]

    # Widths interleave, and each address is the previous one plus its width.
    widths = [len(line["raw"]) // 2 for line in listing["lines"]]
    assert 2 in widths and 4 in widths, f"expected both widths, got {widths}"
    for previous, following in itertools.pairwise(listing["lines"]):
        assert following["address"] == previous["address"] + len(previous["raw"]) // 2


def test_the_listing_is_riscv_rather_than_whatever_ran_last():
    """The class of defect a stale server produced once before: panes showing
    another machine's disassembly with no console error. `c.` mnemonics and ABI
    register names are RISC-V and appear in no Thumb or AVR listing."""
    needs_core()
    with load() as session:
        session.run(2000)
        text = " ".join(line["text"] for line in session.state()["listing"]["lines"])
    assert "c." in text, f"no compressed instruction in {text!r}"
    assert any(name in text for name in ("sp", "a5", "zero")), text


# --- the board description's own claims -------------------------------------


def test_the_board_agrees_with_the_catalogue_about_the_isa():
    """One fact, one home. The board declares `RV32IMC` because that is what
    the datasheet prints; `catalogue.CHIPS` records the same string for the
    same reason, and a board that drifted from it would configure a part the
    catalogue describes differently."""
    from webui.boards import catalogue

    assert esp32c3.ISA == "RV32" + catalogue.CHIPS["ESP32-C3"][0][len("RV32"):]
    assert catalogue.CHIPS["ESP32-C3"][0] == esp32c3.ISA


def test_the_board_configures_the_part_and_not_some_other_one():
    """The C is load-bearing in one direction and the absent A in the other.

    This part must **trap** an atomic and an ESP32-C6 must execute one, and no
    lockstep run against rvcpp could ever say so -- it runs both. So the board
    saying which part this is is the only thing standing between the two.
    """
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        assert cpu.extensions() == abi.ESP32_C3
        assert cpu.extensions() != abi.ESP32_C6, "an ESP32-C6 has A and this does not"


def test_reading_the_input_register_faults_rather_than_answering_wrongly():
    """`GPIO_IN` reads the electrical level on the pins, so on GPIO8 driven
    high it should read high. This model has no way to express that, so the
    address is left unmapped and a read **faults**.

    The same decision `webui/boards/samd21.py` makes about its `PORT_IN`, and
    the opposite of what `webui/boards/atmega328p.py` could do -- an AVR's data
    space has no holes, so its `PINB` returns a wrong zero and is pinned as a
    limitation instead. Faulting is available here and is better.
    """
    needs_core()
    from core.riscv32 import abi

    with load() as session:
        # Stepped until the bit is *high* rather than for a fixed budget: it
        # toggles every 606 instructions, so any constant is a coin flip on
        # which phase it lands in.
        for _ in range(BUDGET):
            session.step()
            if session.cpu.read_word(GPIO_OUT) & LED:
                break
        assert session.cpu.read_word(GPIO_OUT) & LED, "GPIO8 is driven high"
        with pytest.raises(abi.MemoryFault):
            session.cpu.read_word(esp32c3.GPIO + esp32c3.GPIO_IN)


def test_the_instruction_bus_view_of_sram_faults_and_the_data_view_does_not():
    """0x3FC80000 and 0x4037C000 are two views of one 384 KB array, and
    `add_region` cannot express an alias -- mapping both would make two
    independent arrays, so a program writing through one and reading through
    the other would see zeros.

    So only the data view is mapped and the instruction view faults, naming an
    address `webui/boards/esp32c3.py`'s `install_memory` explains. Pinned
    because it is a real limitation rather than an oversight, and because the
    fix is a feature the core does not have.
    """
    needs_core()
    from core.riscv32 import abi

    with load() as session:
        session.cpu.write_word(esp32c3.DRAM, 0xC0FFEE)
        assert session.cpu.read_word(esp32c3.DRAM) == 0xC0FFEE
        with pytest.raises(abi.MemoryFault):
            session.cpu.read_word(esp32c3.IRAM)


def test_an_undescribed_peripheral_faults_rather_than_reading_zero():
    """The whole reason MMIO is not a region. Firmware polling a clock or reset
    status bit that answered zero would spin forever, which reads as a hang
    rather than as a missing feature -- and the fault names the address, which
    is what says which peripheral to describe next."""
    needs_core()
    from core.riscv32 import abi

    with load() as session, pytest.raises(abi.MemoryFault) as caught:
        # RTC_CNTL, `soc.h:48` -- the clock and reset block, and NOT UART0,
        # which this comment said until OH-161 described UART0 and made the
        # example wrong twice over: 0x60008000 was never UART0 (that is
        # 0x60000000, `soc.h:42`), and UART0 now answers.
        session.cpu.read_word(0x60008000)
    assert "60008000" in str(caught.value).lower()


# --- the fixture cannot drift from its source -------------------------------


def test_the_committed_binary_matches_its_source():
    """Skipped where no toolchain exists rather than failing, the same contract
    `tests/avr/test_blink.py` keeps."""
    home = pathlib.Path.home() / ".platformio/packages/toolchain-riscv32-esp/bin"
    compiler = shutil.which("riscv32-esp-elf-gcc") or home / "riscv32-esp-elf-gcc.exe"
    objcopy = shutil.which("riscv32-esp-elf-objcopy") or home / "riscv32-esp-elf-objcopy.exe"
    if not pathlib.Path(compiler).is_file() or not pathlib.Path(objcopy).is_file():
        pytest.skip("no riscv32-esp-elf toolchain")

    import tempfile

    with tempfile.TemporaryDirectory() as work:
        elf = pathlib.Path(work) / "blink.elf"
        rebuilt = pathlib.Path(work) / "blink.bin"
        subprocess.run(
            [str(compiler), "-march=rv32imc", "-mabi=ilp32", "-Os", "-ffreestanding",
             "-nostdlib", "-nostartfiles", "-T", str(SCRIPT), "-o", str(elf),
             str(SOURCE)],
            check=True, capture_output=True,
        )
        subprocess.run([str(objcopy), "-O", "binary", str(elf), str(rebuilt)],
                       check=True, capture_output=True)
        assert rebuilt.read_bytes() == IMAGE.read_bytes()


def test_the_image_begins_with_its_startup_and_not_with_main():
    """The defect the linker script exists to prevent, pinned.

    Without a script the linker placed `main` first and `_start` after it, so
    the stack setup was skipped and the first push faulted. An image that links
    cleanly and runs the wrong instruction first is exactly the silent class --
    so the first instruction is asserted to be the one that loads `sp`.

    `lui sp, 0x3fce0` is `0x3fce0137`: opcode 0x37 (LUI), rd 2 (sp).
    """
    needs_core()
    first = int.from_bytes(IMAGE.read_bytes()[:4], "little")
    assert first & 0x7F == 0x37, "the first instruction is a LUI"
    assert (first >> 7) & 0x1F == 2, "and its destination is sp"


# --- the pin view: a pad answers for the register behind it (OH-160) ---------

#: The ticket's sentence as a sketch: the vendor's own name for the pad, from
#: the same `pins_arduino.h` the module's `HEADER` was generated from.
D10_BLINK = """
void setup() { pinMode(D10, OUTPUT); }
void loop() { digitalWrite(D10, HIGH); delay(1); digitalWrite(D10, LOW); delay(1); }
"""

#: `delay(1)` is ~24,000 steps on this core (`oh_board.h` says what kind of
#: number that is), so two highs need two of them and a little.
SKETCH_BUDGET = 80_000


def test_the_pad_the_blink_drives_follows_the_register_in_the_pin_view():
    """GPIO8 is the pad silkscreened `D8` on a XIAO ESP32-C3 -- the vendor's
    table, read into `esp32c3.HEADER` -- so the level the pin view reports
    for `D8` must be the bit `watch` already reads, at every change, through
    `pin_states` and not through the register. The three power pads stay
    unanswerable: nothing is behind them."""
    needs_core()
    seen: list[tuple[bool, str]] = []
    with load() as session:
        last = 0
        for _ in range(BUDGET):
            session.step()
            now = session.cpu.read_word(GPIO_OUT) & LED
            if now != last:
                seen.append((bool(now), api.pin_levels(session.runtime, session.cpu)["D8"]))
                last = now
        view = api.pin_view(session.runtime, session.cpu, BOARD)
    assert len(seen) >= 2, seen
    assert all(level == ("high" if bit else "low") for bit, level in seen), seen
    pad = next(pad for pad in view["pads"] if pad["label"] == "D8")
    assert (pad["pin"], pad["chip_pin"]) == ("D8", "GPIO8")
    assert pad["state"] in ("high", "low")
    assert view["unknown"] == 3, "3V3_OUT, GND and VBUS have no register behind them"
    assert {pad["label"] for pad in view["pads"] if pad["state"] == "unknown"} == {
        "3V3_OUT", "GND", "VBUS"
    }


def test_a_sketch_naming_d10_moves_the_d10_pad():
    """A wire from the pad silkscreened `D10` reaches GPIO10 in the model.

    Three tables meet here and none of them is this test's: the sketch names
    `D10` through the vendor's `pins_arduino.h`, the core's `digitalWrite`
    lands in `GPIO_OUT` at the bit that header says, and the pin view -- which
    knows only the generated `HEADER` -- reports the pad. A `HEADER` row that
    sent `D10` anywhere but GPIO10 would read as a pad that never moves, and a
    `pinMode` that never reached `ENABLE` as one that never leaves `input`.
    Skips by name where the toolchain is not installed.
    """
    needs_core()
    from webui import compile as compiler

    try:
        built = compiler.build(BOARD, D10_BLINK)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    seen: list[str] = []
    with api.load_firmware(BOARD, built.image, base=compiler.recipe_for(BOARD).base) as session:
        for _ in range(SKETCH_BUDGET):
            session.step()
            level = api.pin_levels(session.runtime, session.cpu)["D10"]
            if not seen or level != seen[-1]:
                seen.append(level)
            if seen.count("high") == 2:
                break
    assert seen == ["input", "low", "high", "low", "high"], (
        "before setup() nothing is enabled; pinMode enables the driver at zero; "
        "then the sketch's own sequence, watched until its second high"
    )


# --- UART0: what a program printed (OH-161) ---------------------------------


def test_the_transmit_gate_holds_the_vendors_reset_value():
    """`uart_reg.h:1181` gives `UART_TX_SCLK_EN` as `BIT(24)` with
    `default: 1'b1`, and the rest of the word is that header's own field
    defaults rather than the one bit this model reads.

    A bare-metal image transmits without touching the clock register, because
    the vendor sets the bit out of reset -- so this is a fact about the part
    that the model must not quietly improve on.
    """
    needs_core()
    from core.riscv32 import abi

    assert esp32c3.UART_CLK_CONF_AT_RESET & esp32c3.UART_TX_SCLK_EN, "bit 24 is set at reset"
    assert esp32c3.UART_CLK_CONF_AT_RESET == 0x03701000
    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        assert cpu.read_word(esp32c3.UART0 + esp32c3.UART_CLK_CONF) == (
            esp32c3.UART_CLK_CONF_AT_RESET
        )


def test_every_byte_written_to_the_fifo_comes_back_and_not_just_the_last():
    """The reason the FIFO is a stream rather than a register: a register
    there would answer `o` after a program printed `hello`, which reads as a
    plausible letter rather than as a wrong answer."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        for byte in b"hello":
            cpu.write_word(esp32c3.UART0 + esp32c3.UART_FIFO, byte)
        assert esp32c3.uart0_output(cpu) == b"hello"


def test_nothing_is_transmitted_while_the_clock_bit_is_clear():
    """The clear-air case: firmware that switched the transmitter off is
    silent, which is what the part does and the whole reason the stream takes
    a gate."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        cpu.write_word(esp32c3.UART0 + esp32c3.UART_CLK_CONF, 0)
        for byte in b"lost":
            cpu.write_word(esp32c3.UART0 + esp32c3.UART_FIFO, byte)
        assert esp32c3.uart0_output(cpu) == b""


def test_a_board_that_has_run_nothing_has_printed_nothing():
    """Empty, and it is the truth rather than a missing feature: `uart_view`
    tells this apart from a board that models no UART at all by whether
    `uart0_output` exists, which is why the callable is asserted too."""
    needs_core()
    from core.riscv32 import abi

    assert callable(esp32c3.uart0_output)
    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        assert esp32c3.uart0_output(cpu) == b""


def test_the_status_register_this_uart_does_not_model_faults_by_name():
    """`UART_TXFIFO_CNT` lives in `UART_STATUS_REG` (+ 0x1c) and is what
    firmware polls for room in the FIFO. Unmapped on purpose, so that wait
    faults at a named address instead of spinning on a zero that never
    changes. `docs/research/peripheral-layer/design.md` states that
    failure mode generally and `core/cortexm0/cpu.h:246-249` cites it for
    the same reason; this said `docs/architectures.md` 3 until the OH-161
    review pointed out that section 3 is Arm Cortex-M and these are not
    Arm parts."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        with pytest.raises(abi.MemoryFault) as caught:
            cpu.read_word(esp32c3.UART0 + 0x1C)
    assert "0x6000001c" in str(caught.value)
