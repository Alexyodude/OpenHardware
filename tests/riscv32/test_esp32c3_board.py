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
import re
import shutil
import subprocess
import typing

import pytest

from core.riscv32 import abi
from webui import api
from webui.boards import esp32c3
from webui.devices.mcp9808 import Mcp9808

from . import encode as e

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


GPIO_IN = esp32c3.GPIO + esp32c3.GPIO_IN


def test_the_input_register_reads_back_the_pin_the_blink_drives():
    """`GPIO_IN` reads the electrical level on the pins, so on GPIO8 driven
    high it reads high and driven low it reads low: `IN` follows `OUT`.

    **This address faulted until OH-161's step 3**, on purpose, because the
    model had no way to say that and a stored zero would have answered
    wrongly. The bare-metal blink never touches IO_MUX, so this reads
    GPIO8's pad as reset leaves it: input enabled (TRM Table 5.12-1, Reset
    "1"). Stepped until each level rather than for a fixed budget, because
    the pin toggles every 606 instructions and any constant is a coin flip
    on which phase it lands in.
    """
    needs_core()
    seen: list[tuple[bool, bool]] = []
    with load() as session:
        last = None
        for _ in range(BUDGET):
            session.step()
            out = bool(session.cpu.read_word(GPIO_OUT) & LED)
            if out != last:
                seen.append((out, bool(session.cpu.read_word(GPIO_IN) & LED)))
                last = out
    assert (True, True) in seen and (False, False) in seen, seen
    assert all(out == read for out, read in seen), seen


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

#: Steps to the sketch's second high, where the test below stops. A
#: `delay(1)` waits a millisecond of SYSTIMER since OH-161 moved it there,
#: 160,000 steps at this description's ten steps a tick, so two highs are a
#: whole period apart: the second lands at step 320,155 (measured
#: 2026-10-12, after OH-161's step 3 gave `pinMode` its pad writes).
#: 330,000 leaves about 9,800 to spare.
SKETCH_BUDGET = 330_000


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


# --- SYSTIMER unit 0: what a program reads the time from (OH-161 step 2) ----


#: `jal x0, 0`: a jump to itself, so a test can retire any number of
#: instructions from one word of flash.
SPIN = 0x0000006F


def framework_soc() -> pathlib.Path | None:
    """The `soc` headers `webui/boards/esp32c3.py` cites, inside PlatformIO's
    `framework-arduinoespressif32` (ESP-IDF 4.4.7), or None where it is not
    installed -- found where `webui/compile.py` finds the toolchain."""
    from webui import compile as compiler

    soc = (compiler.PACKAGES / "framework-arduinoespressif32" / "tools" / "sdk"
           / "esp32c3" / "include" / "soc" / "esp32c3" / "include" / "soc")
    return soc if (soc / "systimer_reg.h").is_file() else None


def header_defines(header: pathlib.Path) -> dict[str, str]:
    """Every `#define NAME VALUE` in `header`, as text, comments stripped."""
    out: dict[str, str] = {}
    for line in header.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "#define":
            out[parts[1]] = parts[2].split("/*")[0].split("//")[0].strip()
    return out


def test_the_systimer_numbers_this_board_carries_are_the_ones_in_the_header():
    """Every SYSTIMER constant in `esp32c3.py` read back, by define name, out
    of the tree it cites: the base (`soc.h`), the four offsets and the bit
    patterns (`systimer_reg.h`), and the rate -- `SOC_SYSTIMER_FIXED_TICKS_US`
    in `soc_caps.h`, sixteen ticks a microsecond, the one header of the three
    parts' that states the rate as a value. Skips where PlatformIO's
    framework is not installed."""
    soc = framework_soc()
    if soc is None:
        pytest.skip("SKIPPED: no framework-arduinoespressif32; pio pkg install")
    base = header_defines(soc / "soc.h")
    timer = header_defines(soc / "systimer_reg.h")
    caps = header_defines(soc / "soc_caps.h")

    assert int(base["DR_REG_SYSTIMER_BASE"], 16) == esp32c3.SYSTIMER
    for name, offset in (
        ("SYSTIMER_CONF_REG", esp32c3.SYSTIMER_CONF),
        ("SYSTIMER_UNIT0_OP_REG", esp32c3.SYSTIMER_UNIT0_OP),
        ("SYSTIMER_UNIT0_VALUE_HI_REG", esp32c3.SYSTIMER_UNIT0_VALUE_HI),
        ("SYSTIMER_UNIT0_VALUE_LO_REG", esp32c3.SYSTIMER_UNIT0_VALUE_LO),
    ):
        written = timer[name].strip("()").replace("DR_REG_SYSTIMER_BASE + ", "")
        assert int(written, 16) == offset, f"{name} is {timer[name]}"
    for name, bit in (
        ("SYSTIMER_TIMER_UNIT0_WORK_EN", esp32c3.SYSTIMER_TIMER_UNIT0_WORK_EN),
        ("SYSTIMER_TIMER_UNIT0_UPDATE", esp32c3.SYSTIMER_TIMER_UNIT0_UPDATE),
        ("SYSTIMER_TIMER_UNIT0_VALUE_VALID", esp32c3.SYSTIMER_TIMER_UNIT0_VALUE_VALID),
    ):
        assert timer[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {timer[name]}"
    assert int(timer["SYSTIMER_TIMER_UNIT0_VALUE_HI"], 16) == esp32c3.SYSTIMER_TIMER_UNIT0_VALUE_HI
    assert int(caps["SOC_SYSTIMER_FIXED_TICKS_US"].strip("()")) * 1_000_000 == (
        esp32c3.SYSTIMER_HZ)


def test_the_conf_reset_value_is_every_default_the_header_states():
    """`SYSTIMER_CONF_AT_RESET` composed from the header's own field
    defaults -- the comments the generator writes above each field, where
    the defaults live -- and not from the one bit the model reads."""
    soc = framework_soc()
    if soc is None:
        pytest.skip("SKIPPED: no framework-arduinoespressif32; pio pkg install")
    text = (soc / "systimer_reg.h").read_text(encoding="utf-8", errors="replace")
    start = text.index("#define SYSTIMER_CONF_REG ")
    block = text[start:text.index("#define SYSTIMER_UNIT0_OP_REG ", start)]
    fields = re.findall(
        r"/\*\* (\w+) : [\w/]+; bitpos: \[(\d+)(?::\d+)?\]; default: (\d+);", block)
    assert fields, "no field comments between CONF and UNIT0_OP"
    composed = sum(int(default) << int(low) for _name, low, default in fields)
    assert composed == esp32c3.SYSTIMER_CONF_AT_RESET, (
        f"the header's defaults compose to {composed:#010x}, the board says "
        f"{esp32c3.SYSTIMER_CONF_AT_RESET:#010x}: {fields}")


def test_every_c3_boards_arduino_build_declares_the_clock_the_rate_assumes():
    """The rate is per chip -- `SYSTIMER_INSTRUCTIONS_PER_TICK` is `CPU_HZ`
    over the counter's -- and a board is built against its own variant, so
    every ESP32-C3 board this repository builds must declare the same
    `build.f_cpu` in arduino-esp32's `boards.txt`. A row at another clock
    would have its `millis()` timed by a rate that is not its own. The
    XIAO's variant is the one its recipe includes, which on this part comes
    from PlatformIO's framework; its name is the same in both trees. Skips,
    naming the fetch, where the checkout is absent."""
    from tools import board_manifest
    from webui import compile as compiler

    boards_txt = compiler.BOARD_SUPPORT / "arduino-esp32" / "boards.txt"
    if not boards_txt.is_file():
        pytest.skip(f"SKIPPED: no {boards_txt}; python tools/import_pindefs.py --fetch")
    text = boards_txt.read_text(encoding="utf-8", errors="replace")
    recipe = compiler.RECIPES["ESP32-C3"]
    (xiao,) = recipe.extra_includes + recipe.bsp_includes
    variants = {xiao.rsplit("/", 1)[1]} | {
        row.variant for row in board_manifest.ROWS if row.chip == "ESP32-C3"}
    for variant in sorted(variants):
        keys = re.findall(rf"^([\w.-]+)\.build\.variant={re.escape(variant)}\s*$", text, re.M)
        assert keys, f"no boards.txt entry builds variant {variant}"
        for key in keys:
            (clock,) = re.findall(rf"^{re.escape(key)}\.build\.f_cpu=(\d+)L\s*$", text, re.M)
            assert int(clock) == esp32c3.CPU_HZ, f"{key} ({variant}) runs at {clock}"


def test_the_installed_unit_reads_the_vendors_reset_values():
    """Out of reset `CONF` is its composed default, and unit 0 has given no
    copy: `VALUE_VALID` is `default: 0` (:109) and both value fields too
    (:345, :357)."""
    needs_core()
    from core.riscv32 import abi

    timer = esp32c3.SYSTIMER
    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        assert cpu.read_word(timer + esp32c3.SYSTIMER_CONF) == esp32c3.SYSTIMER_CONF_AT_RESET
        assert cpu.read_word(timer + esp32c3.SYSTIMER_UNIT0_OP) == 0
        assert cpu.read_word(timer + esp32c3.SYSTIMER_UNIT0_VALUE_HI) == 0
        assert cpu.read_word(timer + esp32c3.SYSTIMER_UNIT0_VALUE_LO) == 0


def test_the_unit_counts_at_the_stated_rate_and_holds_while_its_enable_is_clear():
    """1,005 instructions at ten a tick is 100 ticks. Then `WORK_EN` alone is
    cleared -- the other bits of `CONF` left at reset, so an enable read from
    the wrong bit would keep counting -- and 1,000 more count nothing; set
    again, 1,000 more are another 100."""
    needs_core()
    from core.riscv32 import abi

    timer = esp32c3.SYSTIMER
    conf = timer + esp32c3.SYSTIMER_CONF
    op = timer + esp32c3.SYSTIMER_UNIT0_OP
    low = timer + esp32c3.SYSTIMER_UNIT0_VALUE_LO
    assert esp32c3.SYSTIMER_INSTRUCTIONS_PER_TICK == 10, "160 MHz over 16"
    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        cpu.write_block(esp32c3.IROM, SPIN.to_bytes(4, "little"))
        cpu.set_regs([0] * 32, pc=esp32c3.IROM)
        for _ in range(1_005):
            cpu.step()
        cpu.write_word(op, esp32c3.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(op) == esp32c3.SYSTIMER_TIMER_UNIT0_VALUE_VALID
        assert cpu.read_word(low) == 100

        cpu.write_word(conf, esp32c3.SYSTIMER_CONF_AT_RESET & ~esp32c3.SYSTIMER_TIMER_UNIT0_WORK_EN)
        for _ in range(1_000):
            cpu.step()
        cpu.write_word(op, esp32c3.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(low) == 100, "a disabled unit holds its count"

        cpu.write_word(conf, esp32c3.SYSTIMER_CONF_AT_RESET)
        for _ in range(1_000):
            cpu.step()
        cpu.write_word(op, esp32c3.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(low) == 200


def test_the_systimer_registers_this_board_does_not_model_fault_by_name():
    """`UNIT0_LOAD_LO` (+ 0x10, :158) would set the count and `UNIT1_OP`
    (+ 0x8, :127) would ask the other unit for a copy. Neither is modelled,
    so each faults at its own address rather than answering a zero a
    program would take for the time."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        for offset in (0x10, 0x08):
            address = esp32c3.SYSTIMER + offset
            with pytest.raises(abi.MemoryFault) as caught:
                cpu.read_word(address)
            assert f"0x{address:08x}" in str(caught.value)


# --- the pins read: GPIO_IN and IO_MUX (OH-161 step 3) -----------------------


def offset_of(text: str, base: str) -> int:
    """`(BASE +0x24)` or `(BASE + 0x24)` as the integer after the plus."""
    inner = text.strip("()").replace(" ", "")
    assert inner.startswith(base + "+"), f"{text!r} is not an offset from {base}"
    return int(inner[len(base) + 1:], 16)


def test_the_io_mux_numbers_this_board_carries_are_the_ones_in_the_header():
    """The base (`soc.h`), every GPIO's pad register (`IO_MUX_GPIOn_REG`,
    each through the `PERIPHS_IO_MUX_*_U` it names), the three pad bits and
    the drive field (`io_mux_reg.h`), and the GPIO count (`soc_caps.h`),
    read out of the tree `esp32c3.py` cites. Every pad's address is held,
    not only GPIO0's, so a stride or a gap the board got wrong fails here.
    Skips where PlatformIO's framework is not installed."""
    soc = framework_soc()
    if soc is None:
        pytest.skip("SKIPPED: no framework-arduinoespressif32; pio pkg install")
    base = header_defines(soc / "soc.h")
    mux = header_defines(soc / "io_mux_reg.h")
    caps = header_defines(soc / "soc_caps.h")

    assert int(base["DR_REG_IO_MUX_BASE"], 16) == esp32c3.IO_MUX
    pads = {int(name[len("IO_MUX_GPIO"):-len("_REG")]): value
            for name, value in mux.items()
            if re.fullmatch(r"IO_MUX_GPIO\d+_REG", name)}
    assert set(pads) == set(esp32c3.IO_MUX_PADS), sorted(pads)
    assert len(pads) == int(caps["SOC_GPIO_PIN_COUNT"].strip("()")), (
        "every GPIO this part counts has a pad")
    for gpio, periphs in pads.items():
        assert offset_of(mux[periphs], "REG_IO_MUX_BASE") == (
            esp32c3.IO_MUX_GPIO0 + gpio * esp32c3.IO_MUX_STRIDE), (
            f"IO_MUX_GPIO{gpio}_REG is {periphs}, {mux[periphs]}")
    for name, bit in (("FUN_PD", esp32c3.IO_MUX_FUN_PD),
                      ("FUN_PU", esp32c3.IO_MUX_FUN_PU),
                      ("FUN_IE", esp32c3.IO_MUX_FUN_IE)):
        assert mux[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {mux[name]}"
    assert int(mux["FUN_DRV_S"]) == esp32c3.IO_MUX_FUN_DRV_SHIFT


def test_each_pad_comes_out_of_reset_as_its_row_of_the_table_says():
    """Installed, every pad register reads its composed reset word, and
    `GPIO_IN` with nothing driven and no output enabled reads exactly the
    pads the TRM's Table 5.12-1 pulls up with their input on: "3", and
    MTCK's "1*" at the eFuse's default. GPIO21's "4" pulls up with its input
    off, so it reads 0; every "1" floats and reads 0.

    The floating pins are the ones `install_gpio_in`'s docstring names, a
    XIAO's D0 to D3, D5, D8 and D10, and this holds that sentence too."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        for gpio, word in esp32c3.IO_MUX_AT_RESET.items():
            address = esp32c3.IO_MUX + esp32c3.IO_MUX_GPIO0 + gpio * esp32c3.IO_MUX_STRIDE
            assert cpu.read_word(address) == word, f"GPIO{gpio} at 0x{address:08x}"
        pulled_up = {6, 9, 12, 13, 14, 15, 16, 17, 20}
        assert cpu.read_word(GPIO_IN) == sum(1 << gpio for gpio in pulled_up), (
            f"{cpu.read_word(GPIO_IN):#010x}")

    pulls = esp32c3.IO_MUX_FUN_PU | esp32c3.IO_MUX_FUN_PD
    floating = {label for label, gpio in esp32c3.HEADER.items()
                if esp32c3.IO_MUX_AT_RESET[gpio] & esp32c3.IO_MUX_FUN_IE
                and not esp32c3.IO_MUX_AT_RESET[gpio] & pulls}
    assert floating == {"D0", "D1", "D2", "D3", "D5", "D8", "D10"}
    assert sorted(esp32c3.HEADER[label] for label in floating) == [2, 3, 4, 5, 7, 8, 10]


def test_a_gpio_with_no_pad_is_refused_a_drive_by_name():
    """The C3's pads are GPIO0 to GPIO21; a drive on GPIO22 names it."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        with pytest.raises(ValueError) as caught:
            esp32c3.drive_pins(cpu, {22: True})
        assert "GPIO22" in str(caught.value), str(caught.value)
        esp32c3.drive_pins(cpu, {3: True})
        assert cpu.read_word(GPIO_IN) & (1 << 3), "GPIO3 is a pad, input on, driven high"


# --- ADC1's one-time sample (OH-161 step 4) -----------------------------------

ADC = esp32c3.APB_SARADC
ONETIME = ADC + esp32c3.APB_SARADC_ONETIME_SAMPLE
SAR1_DATA = ADC + esp32c3.APB_SARADC_SAR1_DATA
INT_RAW = ADC + esp32c3.APB_SARADC_INT_RAW
INT_CLR = ADC + esp32c3.APB_SARADC_INT_CLR
CTRL = ADC + esp32c3.APB_SARADC_CTRL


def onetime(channel: int, atten: int = 3) -> int:
    """ADC1's control word for `channel` at `atten`, START clear."""
    return (esp32c3.ONETIME_SAR1 | channel << esp32c3.ONETIME_CHANNEL_SHIFT
            | atten << esp32c3.ONETIME_ATTEN_SHIFT)


def convert(cpu, word: int) -> int:
    """Clear done, start a conversion of `word` the way ESP-IDF does -- the
    word, then the word with START -- and answer the result."""
    cpu.write_word(INT_CLR, esp32c3.ADC1_DONE)
    cpu.write_word(ONETIME, word)
    cpu.write_word(ONETIME, word | esp32c3.ONETIME_START)
    assert cpu.read_word(INT_RAW) & esp32c3.ADC1_DONE, f"no done for {word:#010x}"
    return cpu.read_word(SAR1_DATA)


def test_the_adc_numbers_this_board_carries_are_the_ones_in_the_header():
    """Every ADC constant in `esp32c3.py` read back, by define name, out of
    the tree it cites: the base (`soc.h`), the five offsets and every bit
    (`apb_saradc_reg.h`), and ADC1's channels (`adc_channel.h`), with
    GPIO5 on ADC2 and so out of them. Skips where PlatformIO's framework is
    not installed."""
    soc = framework_soc()
    if soc is None:
        pytest.skip("SKIPPED: no framework-arduinoespressif32; pio pkg install")
    base = header_defines(soc / "soc.h")
    adc = header_defines(soc / "apb_saradc_reg.h")
    channels = header_defines(soc / "adc_channel.h")

    assert int(base["DR_REG_APB_SARADC_BASE"], 16) == esp32c3.APB_SARADC
    for name, offset in (
        ("APB_SARADC_CTRL_REG", esp32c3.APB_SARADC_CTRL),
        ("APB_SARADC_ONETIME_SAMPLE_REG", esp32c3.APB_SARADC_ONETIME_SAMPLE),
        ("APB_SARADC_1_DATA_STATUS_REG", esp32c3.APB_SARADC_SAR1_DATA),
        ("APB_SARADC_INT_RAW_REG", esp32c3.APB_SARADC_INT_RAW),
        ("APB_SARADC_INT_CLR_REG", esp32c3.APB_SARADC_INT_CLR),
    ):
        assert offset_of(adc[name], "DR_REG_APB_SARADC_BASE") == offset, (
            f"{name} is {adc[name]}")
    for name, bit in (
        ("APB_SARADC_SAR_CLK_GATED", esp32c3.APB_SARADC_SAR_CLK_GATED),
        ("APB_SARADC1_ONETIME_SAMPLE", esp32c3.ONETIME_SAR1),
        ("APB_SARADC2_ONETIME_SAMPLE", esp32c3.ONETIME_SAR2),
        ("APB_SARADC_ONETIME_START", esp32c3.ONETIME_START),
        ("APB_SARADC_ADC1_DONE_INT_RAW", esp32c3.ADC1_DONE),
        ("APB_SARADC_ADC1_DONE_INT_CLR", esp32c3.ADC1_DONE),
    ):
        assert adc[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {adc[name]}"
    assert int(adc["APB_SARADC_ONETIME_CHANNEL_S"]) == esp32c3.ONETIME_CHANNEL_SHIFT
    assert int(adc["APB_SARADC_ONETIME_ATTEN_S"]) == esp32c3.ONETIME_ATTEN_SHIFT
    assert esp32c3.ONETIME_CONVERSION == (
        esp32c3.ONETIME_SAR1 | esp32c3.ONETIME_SAR2
        | int(adc["APB_SARADC_ONETIME_CHANNEL_V"], 16) << esp32c3.ONETIME_CHANNEL_SHIFT
        | int(adc["APB_SARADC_ONETIME_ATTEN_V"], 16) << esp32c3.ONETIME_ATTEN_SHIFT)
    adc1 = {int(channels[f"ADC1_CHANNEL_{n}_GPIO_NUM"]): n
            for n in range(8) if f"ADC1_CHANNEL_{n}_GPIO_NUM" in channels}
    assert adc1 == esp32c3.ADC1_CHANNELS
    assert int(channels["ADC2_CHANNEL_0_GPIO_NUM"]) not in esp32c3.ADC1_CHANNELS


def test_the_adc_reset_values_are_every_default_the_header_states():
    """`APB_SARADC_CTRL_AT_RESET` and `ONETIME_SAMPLE_AT_RESET` composed from
    the header's own field comments, `/* NAME : R/W ;bitpos:[hi:lo]
    ;default: 2'd1 ; */`, and not from the bits the model reads."""
    soc = framework_soc()
    if soc is None:
        pytest.skip("SKIPPED: no framework-arduinoespressif32; pio pkg install")
    text = (soc / "apb_saradc_reg.h").read_text(encoding="utf-8", errors="replace")

    def composed(register: str, following: str) -> int:
        start = text.index(f"#define {register} ")
        block = text[start:text.index(f"#define {following} ", start)]
        fields = re.findall(
            r"/\* (\w+) : [\w/]+ ;bitpos:\[(\d+)(?::(\d+))?\] ;default: \d+'([bdh])(\w+) ; \*/",
            block)
        assert fields, f"no field comments between {register} and {following}"
        radix = {"b": 2, "d": 10, "h": 16}
        return sum(int(value, radix[kind]) << int(low or high)
                   for _name, high, low, kind, value in fields)

    assert composed("APB_SARADC_CTRL_REG", "APB_SARADC_CTRL2_REG") == (
        esp32c3.APB_SARADC_CTRL_AT_RESET)
    assert composed("APB_SARADC_ONETIME_SAMPLE_REG", "APB_SARADC_APB_ADC_ARB_CTRL_REG") == (
        esp32c3.ONETIME_SAMPLE_AT_RESET)


def test_the_installed_adc_reads_the_vendors_reset_values():
    """Out of reset `CTRL` and `ONETIME_SAMPLE` are their composed defaults,
    and nothing has converted: the result and done are 0."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        assert cpu.read_word(CTRL) == esp32c3.APB_SARADC_CTRL_AT_RESET
        assert cpu.read_word(ONETIME) == esp32c3.ONETIME_SAMPLE_AT_RESET
        assert (cpu.read_word(SAR1_DATA), cpu.read_word(INT_RAW)) == (0, 0)


def test_each_channel_converts_its_own_pin_at_the_attenuation_its_start_names():
    """GPIO2 held at 1.65 V and GPIO3 at 1.1 V: each start answers its own
    channel's pin, at its own attenuation -- 12 dB, k 25%, gives 1536 and
    1024; 6 dB, k 50%, gives 3071 for 1.65 V; 0 dB holds it to 4095."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        esp32c3.hold_volts(cpu, {2: 1.65, 3: 1.1})
        assert convert(cpu, onetime(2)) == 1536
        assert convert(cpu, onetime(3)) == 1024
        assert convert(cpu, onetime(2, atten=2)) == 3071
        assert convert(cpu, onetime(2, atten=0)) == 4095
        assert convert(cpu, onetime(4)) == 0, "GPIO4 is held at nothing: it floats"


def test_a_hold_is_a_whole_statement():
    """A pin the next hold leaves out floats, and converts to 0."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        esp32c3.hold_volts(cpu, {2: 1.65})
        esp32c3.hold_volts(cpu, {3: 1.1})
        assert convert(cpu, onetime(2)) == 0
        assert convert(cpu, onetime(3)) == 1024


def test_nothing_converts_with_the_adc_clock_gated():
    """`SAR_CLK_GATED` clear: the start stores, and no done comes."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        esp32c3.hold_volts(cpu, {2: 1.65})
        cpu.write_word(CTRL, esp32c3.APB_SARADC_CTRL_AT_RESET & ~esp32c3.APB_SARADC_SAR_CLK_GATED)
        cpu.write_word(ONETIME, onetime(2))
        cpu.write_word(ONETIME, onetime(2) | esp32c3.ONETIME_START)
        assert (cpu.read_word(SAR1_DATA), cpu.read_word(INT_RAW)) == (0, 0)


def test_a_start_on_adc2_or_on_no_channel_faults_naming_the_control_register():
    """ADC2's bit, the reset channel 13, and channel 5 -- GPIO5 is ADC2's --
    are held at nothing, so each start faults rather than answering a 0
    that would read as a voltage."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        for word in (esp32c3.ONETIME_SAR2 | 0 << esp32c3.ONETIME_CHANNEL_SHIFT,
                     esp32c3.ONETIME_SAR1 | esp32c3.ONETIME_SAMPLE_AT_RESET,
                     onetime(5)):
            cpu.write_word(ONETIME, word)
            with pytest.raises(abi.MemoryFault):
                cpu.write_word(ONETIME, word | esp32c3.ONETIME_START)
            assert cpu.read_word(INT_RAW) == 0, f"{word:#010x} flagged done"


def test_the_code_is_the_trms_formula_rounded_half_up_and_held_to_4095():
    """`Vref / k * data / 4095` solved for `data`: 1.65 V at 12 dB is
    1535.625, so 1536; 1.1 V is 1023.75, so 1024; 2.2 V is 2047.5 exactly,
    so half up gives 2048 where rounding half to even would too and floor
    would give 2047; 3.3 V is 3071.25, 3071; 5 V would be 4652.8 and is
    held to 4095."""
    assert [esp32c3.adc_code(v, 3) for v in (0, 1.65, 1.1, 2.2, 3.3, 5.0)] == [
        0, 1536, 1024, 2048, 3071, 4095]
    assert esp32c3.adc_code(0.55, 0) == 2048, "0 dB, k 100%: 2047.5 half up"
    for volts, atten in ((-0.1, 3), (float("nan"), 3), (float("inf"), 3), (True, 3),
                         (10 ** 400, 3), (1.0, 4)):
        with pytest.raises(ValueError) as caught:
            esp32c3.adc_code(volts, atten)
        assert repr(volts if atten == 3 else atten) in str(caught.value), str(caught.value)


def test_a_voltage_on_a_gpio_with_no_pad_is_refused_by_name():
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        with pytest.raises(ValueError) as caught:
            esp32c3.hold_volts(cpu, {22: 1.0})
        assert "GPIO22" in str(caught.value), str(caught.value)


# --- I2C0: the controller a Wire.endTransmission drives (OH-161 step 5, slice 1b) ----
#
# The registers, bits and opcodes are read back out of the framework copy
# 3.20017.241212 (ESP-IDF 4.4.7) by define name; the transactions are run from
# hand-assembled RISC-V stores, so the doorbell is rung by an executed
# instruction and not by a harness poking a register.


def framework_include() -> pathlib.Path | None:
    from webui import compile as compiler

    include = (compiler.PACKAGES / "framework-arduinoespressif32" / "tools" / "sdk"
               / "esp32c3" / "include")
    return include if (include / "hal" / "esp32c3" / "include" / "hal"
                       / "i2c_ll.h").is_file() else None


def header_text(relative: str) -> str:
    include = framework_include()
    if include is None:
        pytest.skip("SKIPPED: no framework-arduinoespressif32; pio pkg install")
    return (include / relative).read_text(encoding="utf-8", errors="replace")


I2C_REG_H = "soc/esp32c3/include/soc/i2c_reg.h"
SYSTEM_REG_H = "soc/esp32c3/include/soc/system_reg.h"


def register_block(text: str, register: str) -> str:
    """The lines from `#define <register>_REG` to the next `_REG` define."""
    start = text.index(f"#define {register}_REG")
    following = re.search(r"#define \w+_REG\b", text[start + 10:])
    return text[start:start + 10 + following.start()] if following else text[start:]


def header_reset_word(text: str, register: str) -> int:
    """A register's reset word composed from every field's `default:` comment."""
    word = 0
    for match in re.finditer(
            r"bitpos:\[(\d+)(?::(\d+))?\] ;default: \d+'([hbd])(\w+)",
            register_block(text, register)):
        high, low, base, digits = match.groups()
        word |= int(digits, {"h": 16, "b": 2, "d": 10}[base]) << int(low or high)
    return word


def header_offset(text: str, register: str) -> int:
    line = re.search(rf"#define {register}_REG\(i\)\s+\(REG_I2C_BASE\(i\) \+ (0x[0-9A-Fa-f]+)\)",
                     text)
    assert line, register
    return int(line.group(1), 16)


def header_bit(text: str, name: str) -> int:
    line = re.search(rf"#define {name}\s+\(BIT\((\d+)\)\)", text)
    assert line, name
    return 1 << int(line.group(1))


def defines_of(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "#define":
            out[parts[1]] = parts[2].split("/*")[0].split("//")[0].strip()
    return out


def test_the_i2c_numbers_this_board_carries_are_the_ones_in_the_header():
    i2c = header_text(I2C_REG_H)
    soc = defines_of(header_text("soc/esp32c3/include/soc/soc.h"))
    system = header_text(SYSTEM_REG_H)
    sigs = defines_of(header_text("soc/esp32c3/include/soc/gpio_sig_map.h"))
    gpio = header_text("soc/esp32c3/include/soc/gpio_reg.h")
    assert int(soc["DR_REG_I2C_EXT_BASE"], 16) == esp32c3.I2C
    for register, offset in (
        ("I2C_CTR", esp32c3.I2C_CTR), ("I2C_FIFO_CONF", esp32c3.I2C_FIFO_CONF),
        ("I2C_DATA", esp32c3.I2C_DATA), ("I2C_INT_RAW", esp32c3.I2C_INT_RAW),
        ("I2C_INT_CLR", esp32c3.I2C_INT_CLR), ("I2C_CLK_CONF", esp32c3.I2C_CLK_CONF),
        ("I2C_COMD0", esp32c3.I2C_COMD0), ("I2C_COMD7", esp32c3.I2C_COMD0 + 7 * 4),
    ):
        assert header_offset(i2c, register) == offset, register
    for name, bit in (
        ("I2C_TRANS_START", esp32c3.I2C_TRANS_START), ("I2C_MS_MODE", esp32c3.I2C_MS_MODE),
        ("I2C_CONF_UPGATE", esp32c3.I2C_CONF_UPGATE),
        ("I2C_NACK_INT_RAW", esp32c3.I2C_INT_NACK),
        ("I2C_TRANS_COMPLETE_INT_RAW", esp32c3.I2C_INT_TRANS_COMPLETE),
        ("I2C_END_DETECT_INT_RAW", esp32c3.I2C_INT_END_DETECT),
        ("I2C_COMMAND0_DONE", esp32c3.I2C_COMD_DONE),
    ):
        assert header_bit(i2c, name) == bit, name
    # The header marks these three WT (write-trigger), which is why I2C_CTR_AT stores
    # them as 0: a write to I2C_CTR_AT must not leave TRANS_START set for a poll.
    for name in ("I2C_TRANS_START", "I2C_CONF_UPGATE", "I2C_FSM_RST"):
        assert re.search(rf"/\* {name} : WT ;", i2c), name
    assert esp32c3.I2C_WRITE_TRIGGER == (esp32c3.I2C_TRANS_START
                                         | esp32c3.I2C_CONF_UPGATE | 1 << 10)
    assert int(soc["DR_REG_SYSTEM_BASE"], 16) == esp32c3.SYSTEM
    assert esp32c3.I2C_GATE == (esp32c3.SYSTEM + 0x10,
                                header_bit(system, "SYSTEM_I2C_EXT0_CLK_EN"))
    assert re.search(r"SYSTEM_PERIP_CLK_EN0_REG\s+\(DR_REG_SYSTEM_BASE \+ 0x010\)", system)
    assert esp32c3.I2C_GATE[1] == 1 << 7
    assert int(sigs["I2CEXT0_SCL_IN_IDX"]) == esp32c3.I2CEXT0_SCL_IDX
    assert int(sigs["I2CEXT0_SDA_OUT_IDX"]) == esp32c3.I2CEXT0_SDA_IDX
    assert re.search(r"GPIO_FUNC0_IN_SEL_CFG_REG\s+\(DR_REG_GPIO_BASE \+ 0x154\)", gpio)
    assert re.search(r"GPIO_FUNC0_OUT_SEL_CFG_REG\s+\(DR_REG_GPIO_BASE \+ 0x554\)", gpio)
    assert (esp32c3.GPIO_FUNC_IN_SEL_CFG0, esp32c3.GPIO_FUNC_OUT_SEL_CFG0) == (0x154, 0x554)
    assert header_bit(gpio, "GPIO_SIG0_IN_SEL") == esp32c3.GPIO_SIG_IN_SEL


def test_the_opcodes_are_held_to_i2c_ll_h_and_not_to_a_header_comment():
    """TRAP 1: the opcode encoding is i2c_ll.h's, RSTART 6, WRITE 1, READ 3,
    STOP 2, END 4 -- the original ESP32's is a different one, and a comment
    in a register header has been copied from it."""
    ll = defines_of(header_text("hal/esp32c3/include/hal/i2c_ll.h"))
    assert esp32c3.I2C_OP == {
        "RSTART": int(ll["I2C_LL_CMD_RESTART"]), "WRITE": int(ll["I2C_LL_CMD_WRITE"]),
        "READ": int(ll["I2C_LL_CMD_READ"]), "STOP": int(ll["I2C_LL_CMD_STOP"]),
        "END": int(ll["I2C_LL_CMD_END"])}
    assert esp32c3.I2C_OP == {"RSTART": 6, "WRITE": 1, "READ": 3, "STOP": 2, "END": 4}


def test_the_installed_i2c_registers_read_the_words_the_header_gives():
    i2c = header_text(I2C_REG_H)
    system = header_text(SYSTEM_REG_H)
    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        for register, offset in (
            ("I2C_CTR", esp32c3.I2C_CTR), ("I2C_FIFO_CONF", esp32c3.I2C_FIFO_CONF),
            ("I2C_INT_RAW", esp32c3.I2C_INT_RAW), ("I2C_CLK_CONF", esp32c3.I2C_CLK_CONF),
            *((f"I2C_COMD{n}", esp32c3.I2C_COMD0 + 4 * n) for n in range(8)),
        ):
            assert cpu.read_word(esp32c3.I2C + offset) == header_reset_word(i2c, register), (
                register, hex(cpu.read_word(esp32c3.I2C + offset)))
        gate_at, gate_bit = esp32c3.I2C_GATE
        assert cpu.read_word(gate_at) == header_reset_word(system, "SYSTEM_PERIP_CLK_EN0")
        assert not cpu.read_word(gate_at) & gate_bit, "TRAP 2: the clock resets closed"
        for gpio in esp32c3.IO_MUX_PADS:
            assert cpu.read_word(out_sel(gpio)) == 0x80, f"GPIO{gpio} resets to OUT_SEL 128"


# --- hand-assembled transactions --------------------------------------------


def li(rd: str, value: int) -> list[int]:
    value &= 0xFFFFFFFF
    high = ((value + 0x800) >> 12) & 0xFFFFF
    low = value - (high << 12)
    if low >= 0x80000000:
        low -= 1 << 32
    return [e.lui(rd, high), e.addi(rd, rd, low)]


def stores(*pairs: tuple[int, int]) -> list[int]:
    program: list[int] = []
    for address, value in pairs:
        program += li("a4", address) + li("a5", value) + [e.sw("a5", "a4", 0)]
    return program


def loads(*addresses: int) -> list[int]:
    """`lw` each address into x16, x17, ... in turn."""
    program: list[int] = []
    for number, address in enumerate(addresses):
        program += li("a4", address) + [e.lw(16 + number, "a4", 0)]
    return program


SDA_GPIO, SCL_GPIO = 6, 7
#: The op codes as `hal/esp32c3/include/hal/i2c_ll.h:72-76` gives them, typed
#: out here so that the transactions below do not depend on the module's own
#: table (the header-parity test holds the table to the HAL).
OP = {"RSTART": 6, "WRITE": 1, "READ": 3, "STOP": 2, "END": 4}


def command(op: str, n: int = 0, *, ack_en: bool = False, ack_val: int = 0) -> int:
    return n | ack_en << 8 | ack_val << 10 | OP[op] << 11


def comd(index: int) -> int:
    return esp32c3.I2C + esp32c3.I2C_COMD0 + 4 * index


def pad(gpio: int) -> int:
    return esp32c3.IO_MUX + esp32c3.IO_MUX_GPIO0 + gpio * esp32c3.IO_MUX_STRIDE


def out_sel(gpio: int) -> int:
    return esp32c3.GPIO + esp32c3.GPIO_FUNC_OUT_SEL_CFG0 + 4 * gpio


def in_sel(signal: int) -> int:
    return esp32c3.GPIO + esp32c3.GPIO_FUNC_IN_SEL_CFG0 + 4 * signal


MCU_GPIO = 1 << 12 | esp32c3.IO_MUX_FUN_IE


def wiring() -> list[tuple[int, int]]:
    """What Wire.begin writes: both pads to function 1 with the input on, each
    signal out of its pad and back in from it."""
    return [
        (pad(SDA_GPIO), MCU_GPIO), (pad(SCL_GPIO), MCU_GPIO),
        (out_sel(SDA_GPIO), esp32c3.I2CEXT0_SDA_IDX),
        (out_sel(SCL_GPIO), esp32c3.I2CEXT0_SCL_IDX),
        (in_sel(esp32c3.I2CEXT0_SDA_IDX), esp32c3.GPIO_SIG_IN_SEL | SDA_GPIO),
        (in_sel(esp32c3.I2CEXT0_SCL_IDX), esp32c3.GPIO_SIG_IN_SEL | SCL_GPIO),
    ]


I2C_CTR_AT = esp32c3.I2C + esp32c3.I2C_CTR
I2C_DATA_AT = esp32c3.I2C + esp32c3.I2C_DATA
I2C_RAW_AT = esp32c3.I2C + esp32c3.I2C_INT_RAW
I2C_CLR_AT = esp32c3.I2C + esp32c3.I2C_INT_CLR
I2C_START = esp32c3.I2C_TRANS_START | esp32c3.I2C_MS_MODE


def transaction(commands: list[int], data: list[int]) -> list[tuple[int, int]]:
    return ([(I2C_CTR_AT, esp32c3.I2C_MS_MODE), (I2C_CLR_AT, 0x3FFFF)]
            + [(I2C_DATA_AT, byte) for byte in data]
            + [(comd(n), word) for n, word in enumerate(commands)]
            + [(I2C_CTR_AT, I2C_START)])


def run_program(program: list[int], bus: typing.Sequence = (), *, gate: bool = True,
                ) -> tuple[api.BoardSession, api.RunResult]:
    """A C3 session over `program` at the flash window, `bus` held on its
    pins, run for exactly the program's length (the gate store first)."""
    words = (stores((esp32c3.I2C_GATE[0], esp32c3.I2C_GATE[1])) if gate else []) + program
    image = b"".join(word.to_bytes(4, "little") for word in words)
    session = api.load_firmware(BOARD, image, base=esp32c3.IROM)
    esp32c3.hold_bus(session.cpu, bus)
    return session, session.run(len(words))


def needs_riscv32() -> None:
    pytest.importorskip("core.riscv32.abi")
    try:
        abi.Cpu().close()
    except abi.AbiError as error:  # the core is not built
        pytest.skip(f"SKIPPED: riscv32 core unavailable: {error}")


def write_pointer(pointer: int, address: int = 0x18) -> list[tuple[int, int]]:
    return transaction([command("RSTART"), command("WRITE", 2, ack_en=True),
                        command("STOP")], [address << 1, pointer])


def read_two(address: int = 0x18) -> list[tuple[int, int]]:
    return transaction([command("RSTART"), command("WRITE", 1, ack_en=True),
                        command("READ", 1), command("READ", 1, ack_val=1),
                        command("STOP")], [address << 1 | 1])


def attached(straps: int = 0) -> tuple[tuple[int, int, Mcp9808], ...]:
    return ((SDA_GPIO, SCL_GPIO, Mcp9808(straps=straps, celsius=25.0, vdd=3.3)),)


def test_a_pointer_write_and_a_two_byte_read_return_the_manufacturer_and_device_ids():
    needs_riscv32()
    for pointer, want in ((6, (0x00, 0x54)), (7, (0x04, 0x00))):
        program = (stores(*wiring()) + stores(*write_pointer(pointer))
                   + stores(*read_two()) + loads(I2C_DATA_AT, I2C_DATA_AT))
        session, result = run_program(program, attached())
        with session:
            assert result.status == "running", (pointer, result)
            regs = session.cpu.get_regs().as_list()
            assert (regs[16], regs[17]) == want, (pointer, regs[16:18])
            assert session.cpu.read_word(I2C_RAW_AT) & esp32c3.I2C_INT_TRANS_COMPLETE
            assert session.cpu.read_word(I2C_CTR_AT) == esp32c3.I2C_MS_MODE, (
                "TRANS_START rang and stored as 0")


def test_every_command_the_transaction_ran_reads_done_and_no_more():
    needs_riscv32()
    program = stores(*wiring()) + stores(*write_pointer(6))
    session, _ = run_program(program, attached())
    with session:
        for n in range(3):
            assert session.cpu.read_word(comd(n)) >> 31 == 1, n
        assert session.cpu.read_word(comd(3)) >> 31 == 0


def test_with_no_device_on_the_pads_the_address_is_nacked_and_its_command_not_done():
    needs_riscv32()
    program = stores(*wiring()) + stores(*write_pointer(6))
    session, result = run_program(program, ())
    with session:
        assert result.status == "running", result
        raw = session.cpu.read_word(I2C_RAW_AT)
        assert raw & esp32c3.I2C_INT_NACK, hex(raw)
        assert raw & esp32c3.I2C_INT_TRANS_COMPLETE, "the STOP after a NACK (TRM p.685, p.707)"
        assert session.cpu.read_word(comd(0)) >> 31 == 1, "RSTART ran"
        assert session.cpu.read_word(comd(1)) >> 31 == 0, "COMD1, the address, did not"


def test_a_device_on_other_pads_is_a_nack_too():
    needs_riscv32()
    elsewhere = ((2, 3, Mcp9808(straps=0, celsius=25.0, vdd=3.3)),)
    session, result = run_program(stores(*wiring()) + stores(*write_pointer(6)), elsewhere)
    with session:
        assert result.status == "running", result
        assert session.cpu.read_word(I2C_RAW_AT) & esp32c3.I2C_INT_NACK


def test_a_closed_clock_gate_answers_nothing():
    """TRAP 2: the function clock resets closed, and a transaction started
    behind it raises no interrupt, which is what Wire's 50 ms timeout waits
    out. The pads are wired, so that only the gate is wrong."""
    needs_riscv32()
    program = stores(*wiring()) + stores(*write_pointer(6))
    session, result = run_program(program, attached(), gate=False)
    with session:
        assert result.status == "running", result
        assert session.cpu.read_word(I2C_RAW_AT) == 0, "cleared by the program, set by nothing"
        assert session.cpu.read_word(comd(0)) >> 31 == 0


def test_incoherent_routing_is_refused_by_naming_what_was_found():
    needs_riscv32()
    sda = esp32c3.I2CEXT0_SDA_IDX
    cases = {
        "no pad": ([(out_sel(SDA_GPIO), 128)], ("SDA", "no pad")),
        "two pads": ([(out_sel(8), esp32c3.I2CEXT0_SCL_IDX)], ("SCL", "GPIO7", "GPIO8")),
        "wrong pad back in": ([(in_sel(sda), esp32c3.GPIO_SIG_IN_SEL | 5)],
                              ("SDA", "IN_SEL", "GPIO5")),
        "matrix not selected": ([(in_sel(sda), SDA_GPIO)], ("SDA", "SIG_IN_SEL")),
        "not the GPIO function": ([(pad(SDA_GPIO), esp32c3.IO_MUX_FUN_IE)],
                                  ("SDA", "MCU_SEL", "GPIO6")),
        "input off": ([(pad(SCL_GPIO), 1 << 12)], ("SCL", "FUN_IE", "GPIO7")),
    }
    for name, (changes, words) in cases.items():
        program = stores(*wiring()) + stores(*changes) + stores(*write_pointer(6))
        session, result = run_program(program, attached())
        with session:
            assert result.status == "stopped", (name, result)
            for word in words:
                assert word in result.detail, (name, word, result.detail)


def test_the_third_byte_read_stops_the_session_and_does_not_fault_it():
    """4.1.1 as a device refusal: the part is not a bug, the firmware asked for
    something DS25095A does not describe."""
    needs_riscv32()
    third = transaction([command("RSTART"), command("WRITE", 1, ack_en=True),
                         command("READ", 3), command("STOP")], [0x18 << 1 | 1])
    program = stores(*wiring()) + stores(*write_pointer(6)) + stores(*third)
    session, result = run_program(program, attached())
    with session:
        assert result.status == "stopped", result
        assert session.status == "stopped" and "4.1.1" in result.detail, result


def test_a_device_that_breaks_is_a_host_bug_and_faults_the_session():
    needs_riscv32()

    class Broken:
        address = 0x18

        def start(self, read: bool) -> bool:
            return {}["missing"]

    program = stores(*wiring()) + stores(*write_pointer(6))
    session, result = run_program(program, ((SDA_GPIO, SCL_GPIO, Broken()),))
    with session:
        assert result.status == "faulted", result


def test_a_pad_routed_to_a_peripheral_reports_unknown_and_the_others_do_not():
    with abi.Cpu() as cpu:
        esp32c3.install(cpu)
        before = esp32c3.pin_states(cpu)
        assert set(before.values()) == {"input"}
        cpu.write_word(out_sel(SDA_GPIO), esp32c3.I2CEXT0_SDA_IDX)
        after = esp32c3.pin_states(cpu)
        assert after["D4"] == "unknown"
        assert {label: state for label, state in after.items() if label != "D4"} == {
            label: state for label, state in before.items() if label != "D4"}


def test_two_parts_on_one_pad_pair_answer_each_at_its_own_address_in_either_order():
    """The bus is modelled: the part whose address the byte names answers,
    wherever it sits in the dict, and a byte that names none is a NACK."""
    needs_riscv32()
    for order in ((0, 1), (1, 0)):
        parts = [(SDA_GPIO, SCL_GPIO, Mcp9808(straps=straps, celsius=25.0, vdd=3.3))
                 for straps in (0, 1)]
        bus = tuple(parts[i] for i in order)
        program = (stores(*wiring()) + stores(*write_pointer(7, 0x19))
                   + stores(*read_two(0x19)) + loads(I2C_DATA_AT, I2C_DATA_AT))
        session, result = run_program(program, bus)
        with session:
            assert result.status == "running", (order, result)
            regs = session.cpu.get_regs().as_list()
            assert (regs[16], regs[17]) == (0x04, 0x00), order
            assert not session.cpu.read_word(I2C_RAW_AT) & esp32c3.I2C_INT_NACK, order
        assert parts[1][2].pointer == 7 and parts[0][2].pointer == 0, order

        program = stores(*wiring()) + stores(*write_pointer(7, 0x1A))
        session, result = run_program(program, bus)
        with session:
            assert session.cpu.read_word(I2C_RAW_AT) & esp32c3.I2C_INT_NACK, order


def test_a_data_byte_after_an_unacknowledged_address_does_not_address_the_part():
    """ack_en clear means the master does not stop at the NACK, but the bytes
    that follow go to nobody: byte 0x30 is data here and not an address."""
    needs_riscv32()
    part = Mcp9808(straps=0, celsius=25.0, vdd=3.3)
    lists = [command("RSTART"), command("WRITE", 1), command("WRITE", 2), command("STOP")]
    program = stores(*wiring()) + stores(*transaction(lists, [0x1A << 1, 0x18 << 1, 6]))
    session, result = run_program(program, ((SDA_GPIO, SCL_GPIO, part),))
    with session:
        assert result.status == "running", result
        assert part.pointer == 0, "the pointer byte reached the part"


def test_a_nacked_data_byte_completes_the_transfer_as_a_nacked_address_does():
    """The STOP after a NACK (TRM p.685, p.707) follows a data byte too. The
    MCP9808 never NACKs a byte it accepts, so the byte here goes to nobody: the
    address before it was not acknowledged and that command's ack_en was clear."""
    needs_riscv32()
    part = Mcp9808(straps=0, celsius=25.0, vdd=3.3)
    lists = [command("RSTART"), command("WRITE", 1), command("WRITE", 1, ack_en=True),
             command("STOP")]
    program = stores(*wiring()) + stores(*transaction(lists, [0x1A << 1, 6]))
    session, result = run_program(program, ((SDA_GPIO, SCL_GPIO, part),))
    with session:
        assert result.status == "running", result
        raw = session.cpu.read_word(I2C_RAW_AT)
        assert raw & esp32c3.I2C_INT_NACK, hex(raw)
        assert raw & esp32c3.I2C_INT_TRANS_COMPLETE, hex(raw)


def test_a_read_from_a_part_addressed_for_writing_is_refused():
    needs_riscv32()
    lists = [command("RSTART"), command("WRITE", 1, ack_en=True), command("READ", 1),
             command("STOP")]
    program = stores(*wiring()) + stores(*transaction(lists, [0x18 << 1]))
    session, result = run_program(program, attached())
    with session:
        assert result.status == "stopped", result
        assert "no device addressed for reading" in result.detail, result.detail


def test_each_thing_the_controller_model_does_not_do_is_refused_by_its_message():
    needs_riscv32()
    rstart, stop = command("RSTART"), command("STOP")
    cases = {
        "a WRITE longer than the TX FIFO": (
            [rstart, command("WRITE", 3, ack_en=True), stop], [0x30, 6], "holds 2"),
        "TX bytes no WRITE consumed": (
            [rstart, command("WRITE", 2, ack_en=True), stop], [0x30, 6, 7],
            "no WRITE command consumed"),
        "an END command": ([rstart, command("END")], [], "END"),
        "a list with no STOP": ([rstart] * 8, [], "reached no STOP"),
        "a READ with nothing addressed": ([rstart, command("READ", 1), stop], [],
                                          "no device addressed for reading"),
    }
    for name, (lists, data, message) in cases.items():
        program = stores(*wiring()) + stores(*transaction(lists, data))
        session, result = run_program(program, attached())
        with session:
            assert result.status == "stopped", (name, result)
            assert message in result.detail, (name, result.detail)
    program = stores(*wiring()) + stores((I2C_CTR_AT, esp32c3.I2C_TRANS_START))
    session, result = run_program(program, attached())
    with session:
        assert result.status == "stopped" and "MS_MODE clear" in result.detail, result


def test_a_bus_pad_this_part_does_not_have_is_refused_before_anything_is_held():
    with pytest.raises(ValueError) as caught:
        esp32c3.check_bus(((SDA_GPIO, 99, None),))
    assert "GPIO99" in str(caught.value)


def test_a_repeated_start_inside_one_list_addresses_the_part_again():
    """DS25095A 4.1.1's own read: pointer write, repeated START, read. Also the
    path a deferred `endTransmission(false)` takes. The second address byte
    must be an address, not data after the first."""
    needs_riscv32()
    lists = [command("RSTART"), command("WRITE", 2, ack_en=True), command("RSTART"),
             command("WRITE", 1, ack_en=True), command("READ", 1),
             command("READ", 1, ack_val=1), command("STOP")]
    program = (stores(*wiring()) + stores(*transaction(lists, [0x18 << 1, 6, 0x18 << 1 | 1]))
               + loads(I2C_DATA_AT, I2C_DATA_AT))
    session, result = run_program(program, attached())
    with session:
        assert result.status == "running", result
        regs = session.cpu.get_regs().as_list()
        assert (regs[16], regs[17]) == (0x00, 0x54)


def test_an_unpowered_part_on_the_bus_does_not_acknowledge_its_address():
    needs_riscv32()
    dark = ((SDA_GPIO, SCL_GPIO, Mcp9808(straps=0, celsius=25.0, vdd=1.0)),)
    session, result = run_program(stores(*wiring()) + stores(*write_pointer(6)), dark)
    with session:
        assert result.status == "running", result
        assert session.cpu.read_word(I2C_RAW_AT) & esp32c3.I2C_INT_NACK
