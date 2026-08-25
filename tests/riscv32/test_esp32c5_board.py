# OpenHardware — an ESP32-C5 board, and the part of its ISA this core refuses.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## This file is not evidence that firmware runs, and says so on purpose
#
# `tests/riscv32/test_esp32c6_board.py` is named by `FIRMWARE_VERIFIED` and
# earns it: it loads a compiled image and watches a pin. **This one is not
# named there and must not be.** An ESP32-C5 is `RV32IMAC + Zcb/Zcmp/Zcmt` and
# `core/riscv32` implements none of the three Zc groups, so no image compiled
# for this part with its own extensions on has been watched, and describing the
# board does not change that.
#
# What it does assert is the pair of facts that make describing it *safe*:
#
#   1. the board configures the core as the subset it can represent, and says
#      in `EXECUTES` that this is a subset rather than the part
#   2. every encoding in the three absent groups' space is **refused** rather
#      than decoded as something else
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


def needs_core() -> None:
    pytest.importorskip("core.riscv32.abi")


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

    All three absent groups live in compressed slots base RVC leaves reserved,
    which is what lets a whole space be swept rather than a list of mnemonics
    transcribed:

        Zcb        quadrant 0, funct3=100  -- 2048 encodings, all reserved
                   quadrant 1, funct3=100, bit12=1, bits[11:10]=11 -- 128 more,
                   which base RVC gives to the RV64-only c.subw/c.addw
        Zcmp/Zcmt  quadrant 2, funct3=101  -- 2048 encodings, the c.fsdsp slot,
                   illegal on any RV32 part without D and so on every ESP32

    Both groups' verdict is the same either way -- reserved and RV64-only are
    both refused on this part -- so the sweep asserts a single thing: **nothing
    in here executes.**
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


def test_installing_configures_the_subset_and_names_it_separately():
    """What the board does about the raise above: it hands over `EXECUTES`,
    which is a smaller and true thing, and keeps `ISA` as the part's own claim.

    The resulting mask is a C6's, and **that is the fact worth pinning** rather
    than hiding: configured this way a C5 and a C6 are the same machine here,
    and the only thing that distinguishes them is that this file says so and
    `FIRMWARE_VERIFIED` does not name this chip.
    """
    needs_core()
    from core.riscv32 import abi

    assert esp32c5.EXECUTES == "RV32IMAC"
    assert esp32c5.EXECUTES != esp32c5.ISA, "a subset, not the part"
    assert esp32c5.ABSENT == ("Zcb", "Zcmp", "Zcmt")
    for group in esp32c5.ABSENT:
        assert group not in esp32c5.EXECUTES

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        assert cpu.extensions() == abi.ESP32_C6, (
            "told RV32IMAC, this core is configured exactly as a C6 -- which "
            "is why the difference has to be written down somewhere a reader "
            "will look"
        )


def test_the_chip_is_described_and_claims_no_firmware():
    """The two facts `rules/board-claims.md` keeps apart, asserted together so
    neither can drift into the other.

    Describing a part makes its boards *runnable* -- an image can be attempted.
    It is not evidence that one has run, and for this chip none has.
    """
    from webui.boards import catalogue

    boards = [b for b in catalogue.catalogue() if b.chip == "ESP32-C5"]
    assert len(boards) == 2, [b.name for b in boards]
    for board in boards:
        assert board.described, "webui/boards/esp32c5.py exists"
        assert board.runnable, "a built core and a description"
        assert not board.firmware_verified, "and nothing has been watched"
    assert "ESP32-C5" not in catalogue.FIRMWARE_VERIFIED


# --- the property that makes describing it safe ------------------------------


def test_every_encoding_in_the_absent_groups_is_refused_rather_than_decoded():
    """The load-bearing test in this file.

    All 4,224 encodings the three Zc groups occupy are stepped on a core
    configured as this board configures it, and **none may execute**. A single
    one that did would mean this core decodes a C5 instruction as some other
    instruction, which is the silent-wrong-answer class rather than a missing
    feature.

    Asserted positively over the whole space rather than by excusing the
    mnemonics, because an accounting entry that excuses a mnemonic excuses its
    bugs with it -- twice already in this core's history.
    """
    needs_core()
    from core.riscv32 import abi

    executed: list[str] = []
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
                except abi.AbiError:
                    continue
                executed.append(f"{group} 0x{half:04x}")
    assert swept == 4224, f"the sweep covered {swept} encodings"
    assert not executed, f"{len(executed)} executed, e.g. {executed[:5]}"


def test_an_absent_group_is_refused_as_illegal_which_is_the_weaker_true_thing():
    """The cost of describing this part before the core can represent its ISA,
    asserted rather than left in prose.

    `Illegal` and `Unimplemented` are two different claims, and telling them
    apart is the whole reason `set_isa` exists. An ESP32-C6 gets the right one:
    `core/riscv32/cpu.h` classifies A, so `amoor.w` is `Unimplemented` on a C6
    board and `Illegal` on a C3 board, which
    `tests/riscv32/test_esp32c6_board.py` pins as the strongest evidence those
    two are different parts.

    **A C5 does not get that.** There is no bit for Zcb, Zcmp or Zcmt, so
    `set_isa` cannot be told the part has them -- it refuses letters it cannot
    represent -- and the core answers with the only word it has. The address
    and the encoding in the message are right and the word is wrong: it reads
    as "an ESP32-C5 does not have cm.push", and an ESP32-C5 does.

    This is asserted, not tolerated. Adding the three classification bits is
    core work, it is what the withheld `FIRMWARE_VERIFIED` entry is waiting on,
    and when someone does it **this test fails** -- naming the change it should
    become rather than passing quietly on a message that improved.
    """
    needs_core()
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        esp32c5.install(cpu)
        cpu.write_block(esp32c5.IROM, (0xB842 | (0x0001 << 16)).to_bytes(4, "little"))
        cpu.set_regs([0] * 32, pc=esp32c5.IROM)
        with pytest.raises(abi.Illegal) as caught:
            cpu.step()
    assert "illegal" in str(caught.value)
    assert "b842" in str(caught.value).lower(), "and it names the encoding"

    # If this stops raising `Illegal` and starts raising `Unimplemented`, the
    # bits exist -- and then `EXECUTES`, `ABSENT` and this test are all things
    # to revisit together.


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
