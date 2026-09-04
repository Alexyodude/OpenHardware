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
    """
    from webui.boards import catalogue

    boards = [b for b in catalogue.catalogue() if b.chip == "ESP32-C5"]
    assert len(boards) == 2, [b.name for b in boards]
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


def test_reading_the_input_register_faults_rather_than_answering_wrongly():
    """`GPIO_IN` is unmapped here as on every board that can leave it so. On
    this part the address is + 0x64, and a board that used a C6's + 0x3c would
    be reading its own `GPIO_ENABLE_W1TC` instead -- which is mapped, so it
    would answer rather than fault."""
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        assert not cpu.is_mapped(esp32c5.GPIO + esp32c5.GPIO_IN)
        assert cpu.is_mapped(esp32c5.GPIO + esp32c5.GPIO_ENABLE_W1TC), (
            "and the address a copied board would have read instead is mapped, "
            "so the mistake would have been silent"
        )


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
