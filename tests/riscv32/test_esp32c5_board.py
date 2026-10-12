# OpenHardware — an ESP32-C5 board, and the part of its ISA this core refuses.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## This file is not evidence that firmware runs, and says so on purpose
#
# `tests/riscv32/test_esp32c6_board.py` is named by `FIRMWARE_VERIFIED` and
# earns it: it loads a compiled image and watches a pin. **This one is not
# named there and must not be** -- still, after OH-146. The core now
# implements the C5's three Zc groups and `install` configures the part
# whole, but executing hand-placed encodings is not a compiled image being
# watched, and the chip stays out of that table until one is.
#
# What it asserts is the pair of facts that make describing it honest:
#
#   1. the board hands the core the part's WHOLE ISA -- `EXECUTES` is the
#      same set as the datasheet's string, in `set_isa`'s grammar
#   2. every encoding in the three groups' space is classified: executed or
#      architecturally refused on this part, refused whole on a C6, and
#      never answered `Unimplemented` on either
#
# The second is the one that matters. A gap that stops and names an address is
# a gap a reader can act on; a gap that decodes to a plausible other
# instruction is twenty thousand steps of nonsense ending somewhere unrelated.
#
# ## Sweeps rather than examples, for a reason this repository already paid for
#
# OH-54 and OH-56 both shipped an accounting list that excused a whole mnemonic
# and therefore excused its bugs -- a core that *wrongly decodes* an excused
# encoding agrees with the oracle perfectly. So "Zcb is not implemented" is
# asserted here over the whole encoding space it occupies, positively, rather
# than on one hand-picked example that a broken decoder might happen to refuse.

import itertools
import os
import pathlib
import re

import pytest

from webui import api
from webui.boards import esp32c5, esp32c6

HERE = pathlib.Path(__file__).resolve().parent

#: One of the two XIAO ESP32-C5 boards in the catalogue. They differ in
#: footprint and not in silicon, so the description serves both.
BOARD = "XIAO-ESP32-C5-DIP"

IMAGE = HERE / "c5blink" / "blink.bin"

LED = 1 << esp32c5.LED_PIN
GPIO_OUT = esp32c5.GPIO + esp32c5.GPIO_OUT
GPIO_ENABLE = esp32c5.GPIO + esp32c5.GPIO_ENABLE

#: Several toggles at the measured 408-instruction period.
BUDGET = 8_000

#: The four Zc halfwords `c5blink/blink.c` hand-places, that image's whole
#: reason to exist: watching it run is watching the part's own instruction
#: set. Each is executed and asserted in `tests/riscv32/test_zc.py` before
#: this file runs them in sequence.
ZC_HALFWORDS = {
    "cm.push {ra,s0},-16": 0xB852,
    "cm.popret {ra,s0},16": 0xBE52,
    "c.not s1": 0x9CF5,
    "cm.jalt 32": 0xA082,
}


def load() -> api.BoardSession:
    """A board name and a file of bytes, at the C5's own flash window."""
    return api.load_firmware(BOARD, IMAGE.read_bytes(), base=esp32c5.IROM)


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


def needs_core() -> None:
    pytest.importorskip("core.riscv32.abi")
    if not IMAGE.is_file():
        pytest.skip(f"{IMAGE} is missing")


def idf_root() -> pathlib.Path | None:
    """The ESP-IDF checkout these numbers were read from, or None.

    The same resolution `tests/riscv32/test_esp32c6_board.py` does, kept local
    to each file rather than shared: two callers in two files is not three
    copies changing together, and a `tests/riscv32/idf.py` would be a module
    whose whole interface is one path.
    """
    named = os.environ.get("ESP_IDF_ROOT")
    candidates = [pathlib.Path(named)] if named else []
    candidates += [
        HERE.parents[1].parent / "esp-idf-reference",
        HERE.parents[1].parent / "esp-idf",
    ]
    for path in candidates:
        if (path / "components" / "soc" / "esp32c5").is_dir():
            return path
    return None


def defines(header: pathlib.Path) -> dict[str, str]:
    """Every `#define NAME VALUE` in `header`, as text rather than as ints."""
    out: dict[str, str] = {}
    for line in header.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "#define":
            out[parts[1]] = parts[2].split("/*")[0].split("//")[0].strip()
    return out


def zc_encodings(group: str):
    """Every 16-bit encoding in the compressed space `group` occupies.

    All three groups live in compressed slots base RVC leaves reserved,
    which is what lets a whole space be swept rather than a list of mnemonics
    transcribed:

        Zcb        quadrant 0, funct3=100  -- 2048 encodings, all reserved
                   quadrant 1, funct3=100, bit12=1, bits[11:10]=11 -- 128 more,
                   which base RVC gives to the RV64-only c.subw/c.addw
        Zcmp/Zcmt  quadrant 2, funct3=101  -- 2048 encodings, the c.fsdsp slot,
                   illegal on any RV32 part without D and so on every ESP32

    Since OH-146 the sweep's question is per-part: on a C6 nothing in here
    may execute, and on a C5 nothing in here may answer `Unimplemented` --
    the space is fully classified, executed or refused.
    """
    if group == "Zcb":
        for low in range(1 << 11):
            yield 0x8000 | (low << 2) | 0b00
        for low in range(1 << 7):
            yield 0x9C00 | (low << 2) | 0b01
    elif group == "Zcmp/Zcmt":
        for low in range(1 << 11):
            yield 0xA000 | (low << 2) | 0b10
    else:                                       # pragma: no cover - typo guard
        raise ValueError(f"no encoding space named {group!r}")


# --- what the board says about itself ---------------------------------------


def test_the_board_agrees_with_the_catalogue_about_the_isa():
    """One fact, one home. `ISA` is the datasheet's string and
    `catalogue.CHIPS` records the same one, so a board that shrank its claim to
    what it can execute would silently disagree with the survey."""
    from webui.boards import catalogue

    assert esp32c5.ISA == "RV32IMAC + Zcb/Zcmp/Zcmt"
    assert catalogue.CHIPS["ESP32-C5"][0] == esp32c5.ISA


def test_the_datasheet_isa_cannot_be_handed_to_the_core_and_that_is_correct():
    """`set_isa` refuses a letter it cannot represent rather than dropping it,
    and this is the part that makes it refuse.

    A core told `RV32IMAC + Zcb/Zcmp/Zcmt` and quietly configured as `RV32IMAC`
    would be a part that looks like a C5 and behaves like a C6 -- the exact
    thing `core/riscv32/abi.py`'s docstring says it will not do. So this
    asserts the raise, and `install` below asserts what the board does about it.
    """
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu, pytest.raises(abi.AbiError) as caught:
        cpu.set_isa(esp32c5.ISA)
    assert "cannot represent" in str(caught.value)


def test_installing_configures_the_part_whole():
    """What the board does since OH-146: it hands over `EXECUTES`, which is
    the datasheet's whole set in `set_isa`'s grammar, and the mask that
    comes back is the C5's own -- not a C6's, which is what this test
    asserted for as long as the Zc groups had no bits.

    The two strings stay two because they are two SPELLINGS: `ISA` is what
    the datasheet prints and prose cannot be parsed; `EXECUTES` is the same
    set the way the core is told it.
    """
    needs_core()
    from core.riscv32 import abi

    assert esp32c5.EXECUTES == "RV32IMAC_ZCB_ZCMP_ZCMT"
    assert esp32c5.EXECUTES != esp32c5.ISA, "two spellings, one set"
    assert esp32c5.ABSENT == (), "nothing withheld since OH-146"

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        assert cpu.extensions() == abi.ESP32_C5, (
            "the C5's own mask, every group the part has"
        )
        assert cpu.extensions() != abi.ESP32_C6, (
            "a C5 stopped being a C6 with three extensions filed off"
        )


def test_the_chip_is_described_and_the_watching_is_named():
    """The two facts `rules/board-claims.md` keeps apart, both earned now.

    Until OH-147 this test asserted the second half's ABSENCE -- described,
    runnable, and nothing watched. `c5blink` is the watching, this file is
    where it happens, and `FIRMWARE_VERIFIED` names this file.

    The boards named are the XIAOs. A manifest row on the chip is not named
    here, and is held to every line after the names all the same.
    """
    from tools import board_manifest
    from webui.boards import catalogue

    boards = [b for b in catalogue.catalogue() if b.chip == "ESP32-C5"]
    xiaos = [b.name for b in boards if board_manifest.find(b.name) is None]
    assert sorted(xiaos) == ["XIAO-ESP32-C5-DIP", "XIAO-ESP32-C5-SMD"], xiaos
    for board in boards:
        assert board.described, "webui/boards/esp32c5.py exists"
        assert board.runnable, "a built core and a description"
        assert board.firmware_verified, "c5blink has been watched (OH-147)"
    assert catalogue.FIRMWARE_VERIFIED["ESP32-C5"] == (
        "tests/riscv32/test_esp32c5_board.py"
    )


# --- the headline: the blink, with the part's own extensions on --------------


def test_a_board_name_and_a_compiled_image_drive_a_gpio_register():
    """The evidence for ESP32-C5, and the last two of the RISC-V family.

    Two transitions is a blink. One is a bit that came on and stayed on,
    which is what a broken toggle looks like from the outside.
    """
    needs_core()
    with load() as session:
        transitions = watch(session)
    assert len(transitions) >= 2, f"the bit changed {len(transitions)} times"
    states = [state for _, state in transitions]
    assert states[0] is True
    assert all(a != b for a, b in itertools.pairwise(states)), states[:8]


def test_the_pin_is_an_output_and_the_zc_framed_delay_holds_its_period():
    """The delay between toggles runs through cm.push, two hundred c.not
    round-trips and cm.popret, and its period holding steady is those
    instructions computing -- a wandering period here would be a Zcmp frame
    losing its counter."""
    needs_core()
    with load() as session:
        steps = [step for step, _ in watch(session)]
        assert session.cpu.read_word(GPIO_ENABLE) & LED, "GPIO8 is an output"
    periods = {b - a for a, b in itertools.pairwise(steps[1:])}
    assert len(periods) == 1, f"period varies: {sorted(periods)}"
    assert periods.pop() > 400, "two hundred c.not round-trips cost steps"


def test_the_image_this_runs_uses_all_three_zc_groups():
    """The claim "with its own extensions on", checked rather than
    remembered: the watched image contains Zcmp's push and popret, Zcb's
    c.not and Zcmt's cm.jalt -- plus the csrw that aims JVT -- so the blink
    above cannot quietly degrade into the RV32IMAC subset every sibling
    already proves."""
    needs_core()
    image = IMAGE.read_bytes()
    halves = {int.from_bytes(image[at:at + 2], "little")
              for at in range(0, len(image) - 1, 2)}
    for name, encoding in ZC_HALFWORDS.items():
        assert encoding in halves, f"{name} (0x{encoding:04X}) is not in the image"
    words = {int.from_bytes(image[at:at + 4], "little")
             for at in range(0, len(image) - 3, 2)}
    assert 0x01729073 in words, "csrw jvt, t0 aims the table"


# --- the property that makes describing it safe ------------------------------


def test_every_zc_encoding_is_classified_here_and_refused_whole_on_a_c6():
    """The load-bearing test in this file, flipped by OH-146.

    All 4,224 encodings the three Zc groups occupy are stepped twice. On a
    core configured as THIS board configures it, none may answer
    `Unimplemented`: every one is either executed or architecturally
    refused, because a part that has the groups has an answer for their
    whole space. On a core configured as a C6 -- `webui/boards/esp32c6.py`
    installing the same `core.riscv32` -- none may execute and none may
    fault: the refusal must land before any memory is touched, so the only
    answer is `Illegal`. A single misfiled encoding on either side is the
    silent-wrong-answer class rather than a missing feature.

    Asserted positively over the whole space rather than by excusing the
    mnemonics, because an accounting entry that excuses a mnemonic excuses its
    bugs with it -- twice already in this core's history.
    """
    needs_core()
    from core.riscv32 import abi
    from webui.boards import esp32c6

    unimplemented: list[str] = []
    executed = 0
    swept = 0
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        for group in ("Zcb", "Zcmp/Zcmt"):
            for half in zc_encodings(group):
                swept += 1
                # A `c.nop` in the high halfword so the fetch has something
                # after it and a two-byte instruction that *did* execute would
                # land somewhere legal rather than faulting for the wrong
                # reason.
                word = half | (0x0001 << 16)
                cpu.write_block(esp32c5.IROM, word.to_bytes(4, "little"))
                cpu.set_regs([0] * 32, pc=esp32c5.IROM)
                try:
                    cpu.step()
                except abi.Unimplemented:
                    unimplemented.append(f"{group} 0x{half:04x}")
                except (abi.Illegal, abi.MemoryFault):
                    # Refused rows, and loads or stores whose zeroed base
                    # register points at unmapped space: both are answers
                    # about THIS part, not holes in the model.
                    continue
                else:
                    executed += 1
    assert swept == 4224, f"the sweep covered {swept} encodings"
    assert not unimplemented, (
        f"{len(unimplemented)} answered Unimplemented on the part that has "
        f"the groups, e.g. {unimplemented[:5]}"
    )
    # Exactly 160, derivably: with a zeroed register file every load,
    # store, push, pop and table jump faults on an address near zero --
    # refusal about the ADDRESS, not the encoding -- so what completes is
    # the register-only work: 64 cm.mva01s + 56 cm.mvsa01 (the 8 same-
    # register rows are reserved) + 32 c.mul + 8 unaries, the last two
    # halved because the Zcb quadrant-1 sweep's fixed bit 9 reaches only
    # rd' 0..3.
    assert executed == 160, (
        f"{executed} executed; the register-only Zc work is exactly 160"
    )

    misfiled: list[str] = []
    with abi.Cpu() as cpu:
        esp32c6.install(cpu)
        for group in ("Zcb", "Zcmp/Zcmt"):
            for half in zc_encodings(group):
                word = half | (0x0001 << 16)
                cpu.write_block(esp32c6.IROM, word.to_bytes(4, "little"))
                cpu.set_regs([0] * 32, pc=esp32c6.IROM)
                try:
                    cpu.step()
                except abi.Illegal:
                    continue
                except abi.AbiError as error:
                    misfiled.append(f"{group} 0x{half:04x}: {type(error).__name__}")
                else:
                    misfiled.append(f"{group} 0x{half:04x}: executed")
    assert not misfiled, (
        f"a C6 answered something other than Illegal {len(misfiled)} "
        f"times, e.g. {misfiled[:5]}"
    )


def test_the_parts_own_instructions_run_on_the_boards_own_description():
    """The flip the predecessor of this test promised.

    `test_an_absent_group_is_refused_as_illegal_which_is_the_weaker_true
    _thing` asserted, until OH-146, that `cm.push` stopped with the wrong
    word -- `Illegal` on a part that has Zcmp -- and said that when the
    classification bits arrived it should become the test of the change.
    This is that test: the same `cm.push {ra}` encoding, on the same
    `install`, now executes against the board's own SRAM -- and round-trips,
    because `cm.pop {ra}` hands the pushed value back.
    """
    needs_core()
    from core.riscv32 import abi

    sp = esp32c5.SRAM + 0x1000
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        program = (0xB842 | (0xBA42 << 16)).to_bytes(4, "little")
        cpu.write_block(esp32c5.IROM, program)
        regs = [0] * 32
        regs[1] = 0x1234
        regs[2] = sp
        cpu.set_regs(regs, pc=esp32c5.IROM)
        cpu.step()
        assert cpu.reg(2) == sp - 16, "cm.push moved sp on this board's SRAM"
        assert cpu.read_word(sp - 4) == 0x1234, "and parked ra there"
        regs = [0] * 32
        regs[2] = sp - 16
        cpu.set_regs(regs, pc=esp32c5.IROM + 2)
        cpu.step()
        assert cpu.reg(1) == 0x1234, "cm.pop handed ra back"
        assert cpu.reg(2) == sp


def test_the_named_instructions_from_each_group_are_among_them():
    """The sweep above proves nothing executes; this says the space really does
    contain the instructions the board's `ABSENT` names, so the sweep is not
    quietly covering somewhere else.

    Encodings written out from the Zc specification's tables:

        c.lbu  a0, 0(a1)      100 000 001 00 010 00   Zcb, quadrant 0
        c.mul  a0, a1         100 1 11 010 10 011 01  Zcb, quadrant 1
        cm.push {ra}, -16     101 11000 0100 00 10    Zcmp
        cm.jt  0              101 000 00000000 10     Zcmt
    """
    named = {
        "c.lbu a0,0(a1)": (0x8088, "Zcb"),
        "c.mul a0,a1": (0x9D4D, "Zcb"),
        "cm.push {ra},-16": (0xB842, "Zcmp/Zcmt"),
        "cm.jt 0": (0xA002, "Zcmp/Zcmt"),
    }
    for text, (half, group) in named.items():
        assert half in set(zc_encodings(group)), f"{text} is outside {group}"


# --- runnable is a claim this board can keep --------------------------------


def test_a_board_name_and_bytes_load_and_step_on_this_description():
    """`runnable` says an image can be *attempted*, and a board reporting it
    while `install` raised would be the claim-you-cannot-keep failure arriving
    through a new door -- which is what would have happened had this file
    passed `ISA` to `set_isa`.

    **Four hand-written instructions, deliberately not a compiled image.**
    Producing a `c5blink/blink.bin` would create an artefact that looks exactly
    like the evidence the other boards' entries rest on, sitting beside a chip
    that has earned no such entry. These four words are written here, in this
    file, and disassembled by this repository's own decoder before they run, so
    a mis-transcription fails naming the mnemonic it actually got.
    """
    needs_core()
    from core.riscv32 import disasm

    #: lui a4, 0x60091 ; li a5, 0x100 ; sw a5, 0x34(a4) ; sw a5, 4(a4)
    #: -- GPIO_ENABLE and then GPIO_OUT, at *this part's* offsets.
    program = [0x60091737, 0x10000793, 0x02F72A23, 0x00F72223]
    image = b"".join(word.to_bytes(4, "little") for word in program)

    # `	` between mnemonic and operands is how this disassembler renders, the
    # same as objdump; written out rather than normalised away so the expected
    # strings are what a reader would see in the listing pane.
    lines = disasm.disassemble(image, esp32c5.IROM)
    assert [line.text for line in lines] == [
        "lui	a4,0x60091",
        "addi	a5,zero,256",
        f"sw	a5,{esp32c5.GPIO_ENABLE}(a4)",
        f"sw	a5,{esp32c5.GPIO_OUT}(a4)",
    ], [line.text for line in lines]

    with api.load_firmware(BOARD, image, base=esp32c5.IROM) as session:
        for _ in program:
            session.step()
        enabled = session.cpu.read_word(esp32c5.GPIO + esp32c5.GPIO_ENABLE)
        driven = session.cpu.read_word(esp32c5.GPIO + esp32c5.GPIO_OUT)
    assert enabled & (1 << esp32c5.LED_PIN)
    assert driven & (1 << esp32c5.LED_PIN)


# --- the register file that a copied board would have got wrong -------------


def test_the_c5_register_file_is_not_the_c6_one():
    """The concrete reason this repository does not accept remembered numbers.

    A C5 shares a C6's GPIO **base** and not its **offsets**, which is the
    worst arrangement: the number a copy would check is the one that matches.
    And the collision is not a near miss -- + 0x3c is `GPIO_IN` on a C6 and
    `GPIO_ENABLE_W1TC` here, so a copied board would map a write-one-to-clear
    enable register at the address it believed was a read-only input. That does
    not fault. It works, wrongly.
    """
    assert esp32c5.GPIO == esp32c6.GPIO, "the same base, which is the trap"

    assert esp32c5.GPIO_OUT == esp32c6.GPIO_OUT
    assert esp32c5.GPIO_OUT_W1TS == esp32c6.GPIO_OUT_W1TS
    assert esp32c5.GPIO_OUT_W1TC == esp32c6.GPIO_OUT_W1TC

    assert esp32c5.GPIO_ENABLE != esp32c6.GPIO_ENABLE
    assert esp32c5.GPIO_ENABLE_W1TS != esp32c6.GPIO_ENABLE_W1TS
    assert esp32c5.GPIO_ENABLE_W1TC != esp32c6.GPIO_ENABLE_W1TC
    assert esp32c5.GPIO_IN != esp32c6.GPIO_IN

    assert esp32c5.GPIO_ENABLE_W1TC == esp32c6.GPIO_IN == 0x3C, (
        "the collision this test is named for"
    )


GPIO_IN = esp32c5.GPIO + esp32c5.GPIO_IN


def test_a_pin_driven_high_reads_zero_until_its_input_is_enabled():
    """**The input enable, watched on a real image.** The C5's GPIO8 comes
    out of reset with `FUN_IE` clear (TRM Table 8.13-1, Reset "0"), and the
    bare-metal blink drives it high without touching IO_MUX -- so `GPIO_IN`
    reads 0 for it, as the silicon's does. Set `FUN_IE` in GPIO8's pad
    register and the same high pin reads 1.

    `GPIO_IN` is at + 0x64 on this part; a C6's + 0x3c is this part's
    `GPIO_ENABLE_W1TC`, which reads 0 whatever the pins do, so a board that
    used it would pass the first half of this and fail the second."""
    needs_core()
    pad = esp32c5.IO_MUX + esp32c5.IO_MUX_GPIO0 + 8 * esp32c5.IO_MUX_STRIDE
    with load() as session:
        for _ in range(BUDGET):
            session.step()
            if session.cpu.read_word(GPIO_OUT) & LED:
                break
        assert session.cpu.read_word(GPIO_OUT) & LED, "GPIO8 is driven high"
        assert not session.cpu.read_word(GPIO_IN) & LED, "its input is off"
        session.cpu.write_word(pad, session.cpu.read_word(pad) | esp32c5.IO_MUX_FUN_IE)
        assert session.cpu.read_word(GPIO_IN) & LED, "and on, it reads the pin"


def test_the_write_only_aliases_read_as_zero_and_still_reach_their_target():
    """The W1TS/W1TC pairs, on this part's own offsets. A read of a write-only
    register answering zero is what the silicon does; the write landing in the
    target is what makes it an alias rather than a hole."""
    needs_core()
    from core.riscv32 import abi

    enable = esp32c5.GPIO + esp32c5.GPIO_ENABLE
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        cpu.write_word(esp32c5.GPIO + esp32c5.GPIO_ENABLE_W1TS, 1 << 8)
        assert cpu.read_word(enable) == 1 << 8
        assert cpu.read_word(esp32c5.GPIO + esp32c5.GPIO_ENABLE_W1TS) == 0
        cpu.write_word(esp32c5.GPIO + esp32c5.GPIO_ENABLE_W1TC, 1 << 8)
        assert cpu.read_word(enable) == 0


# --- the memory map, against the header it cites ----------------------------


def test_the_c5_numbers_this_board_carries_are_the_ones_in_the_header():
    """Every constant read back out of the file it cites, so a transcription
    error is a red test rather than a wrong emulator."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    soc = defines(root / "components/soc/esp32c5/include/soc/soc.h")
    caps = defines(root / "components/soc/esp32c5/include/soc/soc_caps.h")
    base = defines(root / "components/soc/esp32c5/register/soc/reg_base.h")
    gpio = defines(root / "components/soc/esp32c5/register/soc/gpio_reg.h")

    assert int(soc["SOC_IROM_LOW"], 16) == esp32c5.IROM
    assert int(soc["SOC_IROM_HIGH"], 16) == esp32c5.IROM + esp32c5.IROM_SIZE
    assert int(soc["SOC_IRAM_LOW"], 16) == esp32c5.SRAM
    assert int(soc["SOC_IRAM_HIGH"], 16) == esp32c5.SRAM + esp32c5.SRAM_SIZE
    assert int(base["DR_REG_GPIO_BASE"], 16) == esp32c5.GPIO

    # One flash window for both busses, one address for SRAM -- the two claims
    # `install_memory` makes about why it maps two regions and not four.
    assert soc["SOC_DROM_LOW"] == "SOC_IROM_LOW"
    assert soc["SOC_DRAM_LOW"] == soc["SOC_IRAM_LOW"]
    assert soc["SOC_DRAM_HIGH"] == soc["SOC_IRAM_HIGH"]
    assert caps["SOC_MMU_DI_VADDR_SHARED"].startswith("(1)")

    for name, offset in (
        ("GPIO_OUT_REG", esp32c5.GPIO_OUT),
        ("GPIO_OUT_W1TS_REG", esp32c5.GPIO_OUT_W1TS),
        ("GPIO_OUT_W1TC_REG", esp32c5.GPIO_OUT_W1TC),
        ("GPIO_ENABLE_REG", esp32c5.GPIO_ENABLE),
        ("GPIO_ENABLE_W1TS_REG", esp32c5.GPIO_ENABLE_W1TS),
        ("GPIO_ENABLE_W1TC_REG", esp32c5.GPIO_ENABLE_W1TC),
        ("GPIO_IN_REG", esp32c5.GPIO_IN),
    ):
        written = gpio[name].strip("()").replace("DR_REG_GPIO_BASE + ", "")
        assert int(written, 16) == offset, f"{name} is {gpio[name]}"


def test_the_flash_window_is_a_constant_here_and_a_build_option_on_a_c6():
    """`esp32c6.py` spells its window as `MMU_PAGE_SIZE * MMU_ENTRY_NUM`
    because `soc.h` writes the top as a formula and `soc_caps.h` marks the page
    size configurable. This part's `soc.h:148-149` prints both ends as
    literals, so the same shape here would be inventing a variability the
    header does not claim -- which is why the two files differ.
    """
    assert esp32c5.IROM_SIZE == 0x2000000, "32 MB"
    assert not hasattr(esp32c5, "MMU_PAGE_SIZE"), (
        "the C5's window is a chip constant; a page-size constant here would "
        "imply a build option its header does not have"
    )
    assert esp32c6.IROM_SIZE == esp32c6.MMU_PAGE_SIZE * esp32c6.MMU_ENTRY_NUM


def test_this_part_and_the_c6_share_a_base_and_not_a_size():
    """The pattern across all three ESP32-C boards described here, stated once:
    a base repeating is not a memory map repeating."""
    assert esp32c5.SRAM == esp32c6.SRAM
    assert esp32c5.SRAM_SIZE != esp32c6.SRAM_SIZE, "384 KB against 512"
    assert esp32c5.IROM == esp32c6.IROM
    assert esp32c5.IROM_SIZE != esp32c6.IROM_SIZE, "32 MB against 16"


def test_the_undescribed_low_power_memory_faults_rather_than_reading_zero():
    """`soc.h:162-163` gives this part 16 KB of LP memory at 0x50000000, and
    this board does not map it -- the growth rule the other boards keep. It
    faults, which is what says which peripheral to describe next."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        with pytest.raises(abi.MemoryFault) as caught:
            cpu.read_word(0x50000000)
    assert "50000000" in str(caught.value).lower()


def test_the_three_described_esp32_c_boards_have_distinct_memory_maps():
    """The claim OH-57 was filed to test, over all three at once: describing
    these parts is chip work rather than architecture work.

    Any two of the three agreeing on their whole map would mean one of the
    files could have been an import of another, and this ticket was wrong to
    write it.
    """
    from webui.boards import esp32c3

    maps = {
        "ESP32-C3": (esp32c3.IROM, esp32c3.IROM_SIZE, esp32c3.DRAM,
                     esp32c3.DRAM_SIZE, esp32c3.GPIO, esp32c3.GPIO_ENABLE),
        "ESP32-C5": (esp32c5.IROM, esp32c5.IROM_SIZE, esp32c5.SRAM,
                     esp32c5.SRAM_SIZE, esp32c5.GPIO, esp32c5.GPIO_ENABLE),
        "ESP32-C6": (esp32c6.IROM, esp32c6.IROM_SIZE, esp32c6.SRAM,
                     esp32c6.SRAM_SIZE, esp32c6.GPIO, esp32c6.GPIO_ENABLE),
    }
    for (one, first), (other, second) in itertools.combinations(maps.items(), 2):
        assert first != second, f"{one} and {other} describe the same machine"


# --- UART0: what a program printed (OH-161) ---------------------------------


def test_the_transmit_gate_holds_the_vendors_reset_value():
    """`register/soc/uart_reg.h:1554` gives `UART_TX_SCLK_EN` as `BIT(24)`
    with `default: 1`, and this part documents only bits 24-27 in that
    register.

    A bare-metal image transmits without touching the clock register, because
    the vendor sets the bit out of reset -- so this is a fact about the part
    that the model must not quietly improve on.
    """
    needs_core()
    from core.riscv32 import abi

    assert esp32c5.UART_CLK_CONF_AT_RESET & esp32c5.UART_TX_SCLK_EN, "bit 24 is set at reset"
    assert esp32c5.UART_CLK_CONF_AT_RESET == (1 << 24) | (1 << 25)
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        assert cpu.read_word(esp32c5.UART0 + esp32c5.UART_CLK_CONF) == (
            esp32c5.UART_CLK_CONF_AT_RESET
        )


def test_every_byte_written_to_the_fifo_comes_back_and_not_just_the_last():
    """The reason the FIFO is a stream rather than a register: a register
    there would answer `o` after a program printed `hello`, which reads as a
    plausible letter rather than as a wrong answer."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        for byte in b"hello":
            cpu.write_word(esp32c5.UART0 + esp32c5.UART_FIFO, byte)
        assert esp32c5.uart0_output(cpu) == b"hello"


def test_nothing_is_transmitted_while_the_clock_bit_is_clear():
    """The clear-air case: firmware that switched the transmitter off is
    silent, which is what the part does and the whole reason the stream takes
    a gate."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        cpu.write_word(esp32c5.UART0 + esp32c5.UART_CLK_CONF, 0)
        for byte in b"lost":
            cpu.write_word(esp32c5.UART0 + esp32c5.UART_FIFO, byte)
        assert esp32c5.uart0_output(cpu) == b""


def test_a_board_that_has_run_nothing_has_printed_nothing():
    """Empty, and it is the truth rather than a missing feature: `uart_view`
    tells this apart from a board that models no UART at all by whether
    `uart0_output` exists, which is why the callable is asserted too."""
    needs_core()
    from core.riscv32 import abi

    assert callable(esp32c5.uart0_output)
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        assert esp32c5.uart0_output(cpu) == b""


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
        esp32c5.install(cpu)
        with pytest.raises(abi.MemoryFault) as caught:
            cpu.read_word(esp32c5.UART0 + 0x1C)
    assert "0x6000001c" in str(caught.value)


def test_the_c5_and_c6_gate_the_transmitter_where_the_c3_does_not():
    """The same collision shape as the GPIO one above, in a second peripheral.

    All three parts put `UART_TX_SCLK_EN` at bit 24 of a clock register at the
    same UART base, and the C3 puts that register at + 0x78 where these two
    put it at + 0x88.

    **What this asserts is that a correctly installed C5 leaves + 0x78
    unmapped**, and that is all it can assert. The first version of this
    docstring said a copied board "faults rather than working wrongly", which
    is not what would happen: a copied `install_uart0` calls `map_register` on
    its own gate address, so it would MAP + 0x78 itself and nothing would
    fault there at all. It would run silently wrong, and the loud failure
    would arrive later and elsewhere, when firmware touched the real + 0x88.
    Corrected after the OH-161 review; the assertion was right and the story
    bolted onto it was not.
    """
    needs_core()
    from core.riscv32 import abi
    from webui.boards import esp32c3

    assert esp32c5.UART0 == esp32c6.UART0 == esp32c3.UART0, "one base, as with GPIO"
    assert esp32c5.UART_FIFO == esp32c6.UART_FIFO == esp32c3.UART_FIFO
    assert esp32c5.UART_CLK_CONF == esp32c6.UART_CLK_CONF == 0x88
    assert esp32c3.UART_CLK_CONF == 0x78
    assert esp32c5.UART_TX_SCLK_EN == esp32c6.UART_TX_SCLK_EN == esp32c3.UART_TX_SCLK_EN

    # The reset words differ because the register does: a C3 carries
    # `SCLK_SEL` and three divisor fields that moved to PCR on these parts:
    # `register/soc/pcr_reg.h:58` puts `PCR_UART0_SCLK_DIV_NUM` at the same
    # `[19:12]` a C3 carries inside `UART_CLK_CONF_REG`.
    assert esp32c5.UART_CLK_CONF_AT_RESET == esp32c6.UART_CLK_CONF_AT_RESET
    assert esp32c3.UART_CLK_CONF_AT_RESET != esp32c5.UART_CLK_CONF_AT_RESET

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        assert not cpu.is_mapped(esp32c5.UART0 + esp32c3.UART_CLK_CONF), (
            "a C3-shaped gate address is unmapped here, so a copy faults loudly"
        )


# --- SYSTIMER unit 0: what a program reads the time from (OH-161 step 2) ----


#: `jal x0, 0`: a jump to itself, so a test can retire any number of
#: instructions from one word of flash.
SPIN = 0x0000006F


def field_defaults(header: pathlib.Path, register: str, after: str) -> dict[str, tuple[int, int]]:
    """Every field ESP-IDF documents between `#define <register>` and
    `#define <after>`, as name -> (lowest bit, default), read from the field
    comments, which are where the defaults live."""
    text = header.read_text(encoding="utf-8", errors="replace")
    start = text.index(f"#define {register} ")
    block = text[start:text.index(f"#define {after} ", start)]
    # `[hi:lo]` or `[bit]`: the LOW bit is the field's position. Every
    # field this read until OH-161's step 4 was one bit wide, where the two
    # are the same number; `SAR_CLK_DIV`'s `[14:7]` is where they are not.
    found = re.findall(
        r"/\*\* (\w+) : [\w/]+; bitpos: \[(\d+)(?::(\d+))?\]; default: (\d+);", block)
    if not found:
        raise AssertionError(f"no field comments between {register} and {after} in {header}")
    return {name: (int(low or high), int(default)) for name, high, low, default in found}


def test_the_systimer_numbers_this_board_carries_are_the_ones_in_the_header():
    """Every SYSTIMER constant in `esp32c5.py` read back out of this part's
    own header by define name. They equal the C6's, and that is the point of
    reading them: this file's GPIO block shares the C6's base and not its
    offsets, so agreeing with a neighbour proves nothing until the header
    says so."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    base = defines(root / "components/soc/esp32c5/register/soc/reg_base.h")
    timer = defines(root / "components/soc/esp32c5/register/soc/systimer_reg.h")

    assert int(base["DR_REG_SYSTIMER_BASE"], 16) == esp32c5.SYSTIMER
    for name, offset in (
        ("SYSTIMER_CONF_REG", esp32c5.SYSTIMER_CONF),
        ("SYSTIMER_UNIT0_OP_REG", esp32c5.SYSTIMER_UNIT0_OP),
        ("SYSTIMER_UNIT0_VALUE_HI_REG", esp32c5.SYSTIMER_UNIT0_VALUE_HI),
        ("SYSTIMER_UNIT0_VALUE_LO_REG", esp32c5.SYSTIMER_UNIT0_VALUE_LO),
    ):
        written = timer[name].strip("()").replace("DR_REG_SYSTIMER_BASE + ", "")
        assert int(written, 16) == offset, f"{name} is {timer[name]}"
    for name, bit in (
        ("SYSTIMER_TIMER_UNIT0_WORK_EN", esp32c5.SYSTIMER_TIMER_UNIT0_WORK_EN),
        ("SYSTIMER_TIMER_UNIT0_UPDATE", esp32c5.SYSTIMER_TIMER_UNIT0_UPDATE),
        ("SYSTIMER_TIMER_UNIT0_VALUE_VALID", esp32c5.SYSTIMER_TIMER_UNIT0_VALUE_VALID),
    ):
        assert timer[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {timer[name]}"
    assert int(timer["SYSTIMER_TIMER_UNIT0_VALUE_HI"].rstrip("U"), 16) == (
        esp32c5.SYSTIMER_TIMER_UNIT0_VALUE_HI)


def test_the_conf_reset_value_is_every_default_the_header_states():
    """`SYSTIMER_CONF_AT_RESET` composed from this header's own field
    defaults, not from the one bit the model reads."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    fields = field_defaults(root / "components/soc/esp32c5/register/soc/systimer_reg.h",
                            "SYSTIMER_CONF_REG", "SYSTIMER_UNIT0_OP_REG")
    composed = sum(default << low for low, default in fields.values())
    assert composed == esp32c5.SYSTIMER_CONF_AT_RESET, (
        f"the header's defaults compose to {composed:#010x}, the board says "
        f"{esp32c5.SYSTIMER_CONF_AT_RESET:#010x}: {fields}")


def test_the_c5_divider_comment_would_time_this_board_wrongly():
    """**Why this board's rate cites a sentence and not a sum.** The C6 takes
    16 MHz as its crystal over the 2.5 its `SOC_SYSTIMER_FIXED_DIVIDER`
    comment states. This part's `soc_caps.h` still says 2.5, and the XIAO
    ESP32-C5's crystal -- `X1` in Seeed's own board file -- is 48 MHz, so
    the sum gives 19.2. ESP-IDF's `systimer.c` for this part says the
    divider follows the crystal and the counter is 16 MHz either way; that
    file is outside the sparse checkout, so this holds the two facts that
    make the comment the wrong source, and fails if either stops being true
    -- or if the board ever takes the sum."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    board_file = HERE.parents[1] / "third_party" / "seeed-pcb" / "ESP32-C5.kicad_pcb"
    if not board_file.is_file():
        pytest.skip(f"SKIPPED: no {board_file}; python tools/compose_board_3d.py fetches it")
    caps = (root / "components/soc/esp32c5/include/soc/soc_caps.h").read_text(encoding="utf-8")
    (divider,) = re.findall(r"#define SOC_SYSTIMER_FIXED_DIVIDER .*fixed: ([\d.]+)", caps)
    lines = board_file.read_text(encoding="utf-8", errors="replace").splitlines()
    (at,) = [index for index, line in enumerate(lines) if '(property "Reference" "X1"' in line]
    value = next(line for line in lines[at:at + 20] if '(property "Value"' in line)
    (megahertz,) = re.findall(r'"Value" "(\d+)Mhz"', value)

    by_the_comment = int(megahertz) * 1_000_000 / float(divider)
    assert (int(megahertz), float(divider)) == (48, 2.5), (megahertz, divider)
    assert by_the_comment == 19_200_000
    assert esp32c5.SYSTIMER_HZ == 16_000_000 != by_the_comment


def test_every_c5_boards_arduino_build_declares_the_clock_the_rate_assumes():
    """The rate is per chip and a board is built against its own variant, so
    every ESP32-C5 board this repository builds must declare `CPU_HZ` as its
    `build.f_cpu` -- 240 MHz on this part, where a C3 and a C6 run at 160.
    Skips, naming the fetch, where the checkout is absent."""
    from tools import board_manifest
    from webui import compile as compiler

    boards_txt = compiler.BOARD_SUPPORT / "arduino-esp32" / "boards.txt"
    if not boards_txt.is_file():
        pytest.skip(f"SKIPPED: no {boards_txt}; python tools/import_pindefs.py --fetch")
    text = boards_txt.read_text(encoding="utf-8", errors="replace")
    (xiao,) = compiler.RECIPES["ESP32-C5"].bsp_includes
    variants = {xiao.rsplit("/", 1)[1]} | {
        row.variant for row in board_manifest.ROWS if row.chip == "ESP32-C5"}
    for variant in sorted(variants):
        keys = re.findall(rf"^([\w.-]+)\.build\.variant={re.escape(variant)}\s*$", text, re.M)
        assert keys, f"no boards.txt entry builds variant {variant}"
        for key in keys:
            (clock,) = re.findall(rf"^{re.escape(key)}\.build\.f_cpu=(\d+)L\s*$", text, re.M)
            assert int(clock) == esp32c5.CPU_HZ, f"{key} ({variant}) runs at {clock}"


def test_the_installed_unit_reads_the_vendors_reset_values():
    """Out of reset `CONF` is its composed default and unit 0 has given no
    copy: `VALUE_VALID` is `default: 0` (:122) and both value fields too
    (:371, :383)."""
    needs_core()
    from core.riscv32 import abi

    timer = esp32c5.SYSTIMER
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        assert cpu.read_word(timer + esp32c5.SYSTIMER_CONF) == esp32c5.SYSTIMER_CONF_AT_RESET
        assert cpu.read_word(timer + esp32c5.SYSTIMER_UNIT0_OP) == 0
        assert cpu.read_word(timer + esp32c5.SYSTIMER_UNIT0_VALUE_HI) == 0
        assert cpu.read_word(timer + esp32c5.SYSTIMER_UNIT0_VALUE_LO) == 0


def test_the_unit_counts_at_the_stated_rate_and_holds_while_its_enable_is_clear():
    """1,505 instructions at fifteen a tick is 100 ticks -- fifteen, not a
    C3's or a C6's ten, because this board's Arduino build runs at 240 MHz.
    Then `WORK_EN` alone is cleared and 1,500 more count nothing; set again,
    1,500 more are another 100."""
    needs_core()
    from core.riscv32 import abi

    timer = esp32c5.SYSTIMER
    conf = timer + esp32c5.SYSTIMER_CONF
    op = timer + esp32c5.SYSTIMER_UNIT0_OP
    low = timer + esp32c5.SYSTIMER_UNIT0_VALUE_LO
    assert esp32c5.SYSTIMER_INSTRUCTIONS_PER_TICK == 15, "240 MHz over 16"
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        cpu.write_block(esp32c5.IROM, SPIN.to_bytes(4, "little"))
        cpu.set_regs([0] * 32, pc=esp32c5.IROM)
        for _ in range(1_505):
            cpu.step()
        cpu.write_word(op, esp32c5.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(op) == esp32c5.SYSTIMER_TIMER_UNIT0_VALUE_VALID
        assert cpu.read_word(low) == 100

        cpu.write_word(conf, esp32c5.SYSTIMER_CONF_AT_RESET & ~esp32c5.SYSTIMER_TIMER_UNIT0_WORK_EN)
        for _ in range(1_500):
            cpu.step()
        cpu.write_word(op, esp32c5.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(low) == 100, "a disabled unit holds its count"

        cpu.write_word(conf, esp32c5.SYSTIMER_CONF_AT_RESET)
        for _ in range(1_500):
            cpu.step()
        cpu.write_word(op, esp32c5.SYSTIMER_TIMER_UNIT0_UPDATE)
        assert cpu.read_word(low) == 200


def test_the_systimer_registers_this_board_does_not_model_fault_by_name():
    """`UNIT0_LOAD_LO` (+ 0x10, :177) would set the count and `UNIT1_OP`
    (+ 0x8, :143) would ask the other unit for a copy. Neither is modelled,
    so each faults at its own address."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        for offset in (0x10, 0x08):
            address = esp32c5.SYSTIMER + offset
            with pytest.raises(abi.MemoryFault) as caught:
                cpu.read_word(address)
            assert f"0x{address:08x}" in str(caught.value)


# --- the pins read: GPIO_IN and IO_MUX (OH-161 step 3) -----------------------


def offset_of(text: str, base: str) -> int:
    """`(BASE + 0x24)` as the integer after the plus."""
    inner = text.strip("()").replace(" ", "")
    assert inner.startswith(base + "+"), f"{text!r} is not an offset from {base}"
    return int(inner[len(base) + 1:], 16)


#: The pads `io_mux_reg.h` names that the TRM's table and register leave
#: out, which `esp32c5.IO_MUX_PADS` says are the SPI flash pads.
SPI_FLASH_PADS = set(range(15, 23))


def test_the_io_mux_numbers_this_board_carries_are_the_ones_in_the_header():
    """The base (`reg_base.h`), every pad register the board maps, through
    the `PERIPHS_IO_MUX_U_PAD_*` each `IO_MUX_GPIOn_REG` names -- GPIO0's at
    **+ 0x0**, where a C6's is at + 0x4 -- and the pad bits and fields
    (`io_mux_reg.h`). The header names pads for GPIO15 to GPIO22 too; they
    are the SPI flash pads the TRM's table leaves out, and this holds both
    that the board leaves them out and why."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    base = defines(root / "components/soc/esp32c5/register/soc/reg_base.h")
    mux = defines(root / "components/soc/esp32c5/register/soc/io_mux_reg.h")

    assert int(base["DR_REG_IO_MUX_BASE"], 16) == esp32c5.IO_MUX
    pads = {int(name[len("IO_MUX_GPIO"):-len("_REG")]): value
            for name, value in mux.items()
            if re.fullmatch(r"IO_MUX_GPIO\d+_REG", name)}
    assert set(pads) - set(esp32c5.IO_MUX_PADS) == SPI_FLASH_PADS, sorted(pads)
    assert set(esp32c5.IO_MUX_PADS) <= set(pads)
    assert all("SPI" in pads[gpio] for gpio in SPI_FLASH_PADS), {
        gpio: pads[gpio] for gpio in SPI_FLASH_PADS}
    for gpio in esp32c5.IO_MUX_PADS:
        assert offset_of(mux[pads[gpio]], "REG_IO_MUX_BASE") == (
            esp32c5.IO_MUX_GPIO0 + gpio * esp32c5.IO_MUX_STRIDE), (
            f"IO_MUX_GPIO{gpio}_REG is {pads[gpio]}, {mux[pads[gpio]]}")
    for name, bit in (("FUN_PD", esp32c5.IO_MUX_FUN_PD),
                      ("FUN_PU", esp32c5.IO_MUX_FUN_PU),
                      ("FUN_IE", esp32c5.IO_MUX_FUN_IE)):
        assert mux[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {mux[name]}"
    assert int(mux["FUN_DRV_S"]) == esp32c5.IO_MUX_FUN_DRV_SHIFT
    assert int(mux["MCU_SEL_S"]) == esp32c5.IO_MUX_MCU_SEL_SHIFT


def test_the_pad_reset_row_is_every_default_the_struct_states():
    """`IO_MUX_RESET_ROW` composed from `io_mux_struct.h`'s own field
    comments -- `mcu_sel` 1 and `fun_drv` 2, and 0 for the rest, `fun_ie`
    among them -- which restate the TRM's Register 8.25. Read from the LOW
    bit of each `bitpos`, which for `[14:12]` is the second number."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    text = (root / "components/soc/esp32c5/register/soc/io_mux_struct.h").read_text(
        encoding="utf-8", errors="replace")
    block = text[:text.index("} io_mux_gpio_reg_t;")]
    fields = re.findall(
        r"/\*\* (\w+) : [\w/]+; bitpos: \[(\d+)(?::(\d+))?\]; default: (\d+);", block)
    assert fields, "no field comments in io_mux_gpio_reg_t"
    composed = sum(int(default) << int(low or high) for _name, high, low, default in fields)
    assert composed == esp32c5.IO_MUX_RESET_ROW, (
        f"the struct's defaults compose to {composed:#010x}, the board says "
        f"{esp32c5.IO_MUX_RESET_ROW:#010x}: {fields}")


def test_each_pad_comes_out_of_reset_as_its_row_of_the_table_says():
    """Installed, every pad register reads its composed reset word, and
    `GPIO_IN` with nothing driven reads exactly the pads Table 8.13-1 pulls
    up with their input on: "3", and MTCK's "1*" at the eFuse's default.
    GPIO11's "4" and GPIO14's "3*" have their input on and no pull of the
    pad's own, so they float and read 0. And the pins `install_gpio_in`
    says come out with their input off -- a XIAO ESP32-C5's D1, D8, D9 and
    D10 -- do."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        for gpio, word in esp32c5.IO_MUX_AT_RESET.items():
            address = esp32c5.IO_MUX + esp32c5.IO_MUX_GPIO0 + gpio * esp32c5.IO_MUX_STRIDE
            assert cpu.read_word(address) == word, f"GPIO{gpio} at 0x{address:08x}"
        pulled_up = {4, 27, 28}
        assert cpu.read_word(GPIO_IN) == sum(1 << gpio for gpio in pulled_up), (
            f"{cpu.read_word(GPIO_IN):#010x}")
        for gpio in SPI_FLASH_PADS:
            assert not cpu.is_mapped(
                esp32c5.IO_MUX + esp32c5.IO_MUX_GPIO0 + gpio * esp32c5.IO_MUX_STRIDE)

    for label in ("D1", "D8", "D9", "D10"):
        gpio = esp32c5.HEADER[label]
        assert not esp32c5.IO_MUX_AT_RESET[gpio] & esp32c5.IO_MUX_FUN_IE, (label, gpio)


def test_a_flash_pad_is_refused_a_drive_by_name():
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        with pytest.raises(ValueError) as caught:
            esp32c5.drive_pins(cpu, {16: True})
        assert "GPIO16" in str(caught.value), str(caught.value)


# --- ADC1's one-time sample (OH-161 step 4) -----------------------------------

ADC_ONETIME = esp32c5.APB_SARADC + esp32c5.APB_SARADC_ONETIME_SAMPLE


def onetime(channel: int, atten: int = 3) -> int:
    """ADC1's control word for `channel` at `atten`, START clear."""
    return (esp32c5.ONETIME_SAR1 | channel << esp32c5.ONETIME_CHANNEL_SHIFT
            | atten << esp32c5.ONETIME_ATTEN_SHIFT)


def convert(cpu, word: int) -> tuple[int, bool]:
    """Clear done, start `word` as ESP-IDF does -- the word, then with START
    -- and answer the result and whether done was set."""
    adc = esp32c5.APB_SARADC
    cpu.write_word(adc + esp32c5.APB_SARADC_INT_CLR, esp32c5.ADC1_DONE)
    cpu.write_word(adc + esp32c5.APB_SARADC_ONETIME_SAMPLE, word)
    cpu.write_word(adc + esp32c5.APB_SARADC_ONETIME_SAMPLE, word | esp32c5.ONETIME_START)
    done = bool(cpu.read_word(adc + esp32c5.APB_SARADC_INT_RAW) & esp32c5.ADC1_DONE)
    return cpu.read_word(adc + esp32c5.APB_SARADC_SAR1_DATA), done


def test_the_adc_numbers_this_board_carries_are_the_ones_in_the_header():
    """Every ADC constant in `esp32c5.py` read back, by define name, out of
    this part's own headers: the block's base and PCR's (`reg_base.h`), the
    five offsets and every bit (`apb_saradc_reg.h`), the two PCR registers
    and their bits (`pcr_reg.h`), and ADC1's channels (`adc_channel.h`) --
    GPIO1 to GPIO6, so a XIAO's A0, GPIO1, is channel 0."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    soc = root / "components/soc/esp32c5"
    base = defines(soc / "register/soc/reg_base.h")
    adc = defines(soc / "register/soc/apb_saradc_reg.h")
    pcr = defines(soc / "register/soc/pcr_reg.h")
    channels = defines(soc / "include/soc/adc_channel.h")

    assert int(base["DR_REG_APB_SARADC_BASE"], 16) == esp32c5.APB_SARADC
    assert int(base["DR_REG_PCR_BASE"], 16) == esp32c5.PCR
    for name, offset in (
        ("APB_SARADC_CTRL_REG", esp32c5.APB_SARADC_CTRL),
        ("APB_SARADC_ONETIME_SAMPLE_REG", esp32c5.APB_SARADC_ONETIME_SAMPLE),
        ("APB_SARADC_SAR1DATA_STATUS_REG", esp32c5.APB_SARADC_SAR1_DATA),
        ("APB_SARADC_INT_RAW_REG", esp32c5.APB_SARADC_INT_RAW),
        ("APB_SARADC_INT_CLR_REG", esp32c5.APB_SARADC_INT_CLR),
    ):
        assert offset_of(adc[name], "DR_REG_APB_SARADC_BASE") == offset, f"{name} is {adc[name]}"
    for name, offset in (("PCR_SARADC_CONF_REG", esp32c5.PCR_SARADC_CONF),
                         ("PCR_SARADC_CLKM_CONF_REG", esp32c5.PCR_SARADC_CLKM_CONF)):
        assert offset_of(pcr[name], "DR_REG_PCR_BASE") == offset, f"{name} is {pcr[name]}"
    for table, name, bit in (
        (adc, "APB_SARADC_SARADC_SAR_CLK_GATED", esp32c5.APB_SARADC_SAR_CLK_GATED),
        (adc, "APB_SARADC_SARADC1_ONETIME_SAMPLE", esp32c5.ONETIME_SAR1),
        (adc, "APB_SARADC_SARADC2_ONETIME_SAMPLE", esp32c5.ONETIME_SAR2),
        (adc, "APB_SARADC_SARADC_ONETIME_START", esp32c5.ONETIME_START),
        (adc, "APB_SARADC_APB_SARADC1_DONE_INT_RAW", esp32c5.ADC1_DONE),
        (adc, "APB_SARADC_APB_SARADC1_DONE_INT_CLR", esp32c5.ADC1_DONE),
        (pcr, "PCR_SARADC_REG_CLK_EN", esp32c5.PCR_SARADC_REG_CLK_EN),
        (pcr, "PCR_SARADC_CLKM_EN", esp32c5.PCR_SARADC_CLKM_EN),
    ):
        assert table[name] == f"(BIT({bit.bit_length() - 1}))", f"{name} is {table[name]}"
    assert int(adc["APB_SARADC_SARADC_ONETIME_CHANNEL_S"]) == esp32c5.ONETIME_CHANNEL_SHIFT
    assert int(adc["APB_SARADC_SARADC_ONETIME_ATTEN_S"]) == esp32c5.ONETIME_ATTEN_SHIFT
    assert esp32c5.ONETIME_CONVERSION == (
        esp32c5.ONETIME_SAR1 | esp32c5.ONETIME_SAR2
        | int(adc["APB_SARADC_SARADC_ONETIME_CHANNEL_V"].rstrip("U"), 16)
        << esp32c5.ONETIME_CHANNEL_SHIFT
        | int(adc["APB_SARADC_SARADC_ONETIME_ATTEN_V"].rstrip("U"), 16)
        << esp32c5.ONETIME_ATTEN_SHIFT)
    adc1 = {int(channels[f"ADC1_CHANNEL_{n}_GPIO_NUM"]): n
            for n in range(8) if f"ADC1_CHANNEL_{n}_GPIO_NUM" in channels}
    assert adc1 == esp32c5.ADC1_CHANNELS
    assert esp32c5.ADC_GATE == (esp32c5.PCR + esp32c5.PCR_SARADC_CLKM_CONF,
                                esp32c5.PCR_SARADC_CLKM_EN)


def test_the_adc_reset_values_are_every_default_the_header_states():
    """`CTRL`, `ONETIME_SAMPLE` and the two PCR registers out of reset,
    composed from this part's own field comments -- among them
    `PCR_SARADC_CLKM_EN` and `PCR_SARADC_REG_CLK_EN`, both `default: 0`
    here and both 1 on a C6."""
    root = idf_root()
    if root is None:
        pytest.skip("no ESP-IDF checkout; see docs/esp-idf-reference.md")
    regs = root / "components/soc/esp32c5/register/soc"
    for header, register, after, board in (
        ("apb_saradc_reg.h", "APB_SARADC_CTRL_REG", "APB_SARADC_CTRL2_REG",
         esp32c5.APB_SARADC_CTRL_AT_RESET),
        ("apb_saradc_reg.h", "APB_SARADC_ONETIME_SAMPLE_REG", "APB_SARADC_ARB_CTRL_REG",
         esp32c5.ONETIME_SAMPLE_AT_RESET),
        ("pcr_reg.h", "PCR_SARADC_CONF_REG", "PCR_SARADC_CLKM_CONF_REG",
         esp32c5.PCR_SARADC_CONF_AT_RESET),
        ("pcr_reg.h", "PCR_SARADC_CLKM_CONF_REG", "PCR_TSENS_CLK_CONF_REG",
         esp32c5.PCR_SARADC_CLKM_CONF_AT_RESET),
    ):
        fields = field_defaults(regs / header, register, after)
        composed = sum(default << low for low, default in fields.values())
        assert composed == board, (
            f"{register}: the header's defaults compose to {composed:#010x}, the "
            f"board says {board:#010x}: {fields}")


def test_the_adc_converts_nothing_until_its_clock_is_on():
    """**The C5's ADC clock resets off**, `PCR_SARADC_CLKM_EN` `default: 0`,
    where a C6's resets on. A start with it clear stores and is never done,
    as on silicon; with it set, GPIO1 -- channel 0 -- held at 1.65 V
    converts to 1536. A C5 copied from a C6 would gate at + 0x84, an address
    this part's PCR has for something else."""
    needs_core()
    from core.riscv32 import abi

    gate, bit = esp32c5.ADC_GATE
    assert gate != esp32c6.ADC_GATE[0], "the neighbour's gate is elsewhere"
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        esp32c5.hold_volts(cpu, {1: 1.65})
        assert not cpu.read_word(gate) & bit
        assert convert(cpu, onetime(0)) == (0, False)
        cpu.write_word(gate, cpu.read_word(gate) | bit)
        assert convert(cpu, onetime(0)) == (1536, True)


def test_each_channel_converts_its_own_pin_on_this_parts_numbering():
    """GPIO1 and GPIO2 are channels 0 and 1 here. A board that took the GPIO
    for the channel, as a C3's and a C6's numbering allows, would answer
    channel 0 with GPIO0's nothing and channel 1 with GPIO1's 1.65 V."""
    needs_core()
    from core.riscv32 import abi

    gate, bit = esp32c5.ADC_GATE
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        cpu.write_word(gate, cpu.read_word(gate) | bit)
        esp32c5.hold_volts(cpu, {1: 1.65, 2: 1.1})
        assert convert(cpu, onetime(0)) == (1536, True)
        assert convert(cpu, onetime(1)) == (1024, True)
        assert convert(cpu, onetime(2)) == (0, True), "GPIO3 holds nothing"


def test_a_start_on_adc2_or_on_no_channel_faults_and_a_flash_pad_is_refused():
    """ADC2's bit, the reset channel 13 and channel 6 -- the part has six,
    0 to 5 -- are held at nothing and fault; a voltage on GPIO16, an SPI
    flash pad this board maps no register for, is refused by name."""
    needs_core()
    from core.riscv32 import abi

    gate, bit = esp32c5.ADC_GATE
    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        cpu.write_word(gate, cpu.read_word(gate) | bit)
        for word in (esp32c5.ONETIME_SAR2, esp32c5.ONETIME_SAR1 | esp32c5.ONETIME_SAMPLE_AT_RESET,
                     onetime(6)):
            cpu.write_word(ADC_ONETIME, word)
            with pytest.raises(abi.MemoryFault):
                cpu.write_word(ADC_ONETIME, word | esp32c5.ONETIME_START)
        with pytest.raises(ValueError) as caught:
            esp32c5.hold_volts(cpu, {16: 1.0})
        assert "GPIO16" in str(caught.value), str(caught.value)
