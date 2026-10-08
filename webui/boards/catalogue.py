#!/usr/bin/env python3
# OpenHardware - what each board is, and whether it can run anything.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Answer, per board: what chip, what instruction set, and can it run firmware?

The board list itself is already generated (`tools/inventory.py`), and the
runnable-core list is already generated (`webui/targets.py`). Neither answers
the question a person actually asks, which is *"does this board work?"* -- and
that question has three separate parts that are easy to blur together:

1. **Which chip is on it.** Derived from the board's own name.
2. **Which instruction set that chip speaks.** A fact about silicon; not
   derivable from anything in this repository, so it is a cited table.
3. **Whether a core for that instruction set exists and is built**, and whether
   a board description exists to give it a memory map and peripherals. Both
   computed from the filesystem.

A board only reports as runnable when all of 3 holds. Nothing here is allowed
to say a board works because its chip is well known.

## The chip comes from the name, matched against the chips we know

A derivation rather than a stored field, because the board files do not carry
one -- they are KiCad footprints with pads, and inventing an `mcu` key in 26
JSON files would be exactly the hand-maintained list this repository keeps
deleting.

**The rule is "longest known chip the name starts with, ending at a `-` or at
the end", not "the middle field".** Both halves of that were learned the hard
way.

The obvious middle-field rule is wrong because the package is not always one
field: `XIAO-ESP32-C3-DIP-SMD` parsed as a chip called `ESP32-C3-DIP` and fell
through to "not in the survey", one board quietly unknown while its two
siblings resolved.

Matching against `CHIPS` fixed that and introduced the same bug in a subtler
place. Without the delimiter check, `startswith` matched any name merely
*beginning* with a known chip, so `XIAO-ESP32-C61-DIP` resolved to `ESP32-C6`
-- and the ESP32-C61 is a real Espressif part, so this is not hypothetical.
An earlier version of this paragraph claimed matching against the table "cannot
do that, because a chip that is not in the table raises instead". It could,
and it did.

The two boards that do not start with `XIAO-` at all (`Arduino Uno`, and
`XIAO-XIAO STM32C5-SMD` with its doubled prefix) are named explicitly rather
than silently mis-parsed. A board that is a row in `tools/board_manifest.py`
takes its chip from that row (OH-176).
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

try:
    from tools import board_manifest, build_core
except ModuleNotFoundError:  # pragma: no cover - exercised only as a script
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from tools import board_manifest, build_core

BOARDS_DIR = pathlib.Path(__file__).resolve().parent

#: Modules beside the board descriptions that are not boards.
#:
#: **Restated here rather than imported from `contract`, and the cycle is the
#: reason**: `webui/boards/contract.py` imports this module, so importing it
#: back would not resolve. Two copies of one list, which
#: `test_the_two_lists_of_non_boards_agree` pins together -- the same
#: arrangement, and the same guard, that `VECTOR_TABLE_OFFSETS` had before it
#: found a single home.
#:
#: `contract` was missing from this set until 2026-08-25, so `described_chips()`
#: returned a phantom chip called `CONTRACT`. Harmless while no chip is called
#: that, and a latent lie.
NOT_A_BOARD = frozenset({"__init__", "catalogue", "contract"})

#: Instruction set per chip, and which core directory would implement it.
#:
#: **This is a fact table, not a generated one**, and it is the only such table
#: here. What ISA a chip speaks cannot be computed from this repository; it
#: comes from `docs/architectures.md`, which records the evidence class for
#: each row and the contradictions it found. `core` is the directory name a
#: core would live under, whether or not it exists yet -- that existence is
#: looked up, never assumed.
CHIPS: dict[str, tuple[str, str]] = {
    "RP2040": ("Armv6-M (Cortex-M0+)", "cortexm0"),
    "SAMD21": ("Armv6-M (Cortex-M0+)", "cortexm0"),
    # **Two instruction sets and one core column**, and the column names the
    # half this repository runs. An RP2350 carries two Cortex-M33s and two
    # Hazard3s, whichever is unused held in reset (docs/architectures.md 5.4),
    # so the ISA string keeps both: it is a fact about the silicon. The core
    # is `riscv32` because `webui/boards/rp2350.py` describes the Hazard3 half
    # to it (OH-157). The Cortex-M33 half is not modelled; it is OH-36's, and
    # a real RP2350 boots that half by default.
    "RP2350": ("Armv8-M (Cortex-M33) + RV32 (Hazard3)", "riscv32"),
    "MG24": ("Armv8-M (Cortex-M33)", "cortexm33"),
    "nRF54l15": ("Armv8-M (Cortex-M33)", "cortexm33"),
    "nRF54LM20A": ("Armv8-M (Cortex-M33)", "cortexm33"),
    "nRF52840": ("Armv7E-M (Cortex-M4F)", "cortexm4"),
    "ESP32-C3": ("RV32IMC", "riscv32"),
    "ESP32-C5": ("RV32IMAC + Zcb/Zcmp/Zcmt", "riscv32"),
    "ESP32-C6": ("RV32IMAC", "riscv32"),
    "ESP32-S3": ("Xtensa LX7", "xtensa"),
    "ATmega328P": ("AVR", "avr"),
    # **It exists. It was announced after this entry was written.**
    #
    # This read "unknown -- part not confirmed to exist" from 2026-08-24, and
    # that was an honest report of a search rather than a fact about silicon:
    # nobody could place "STM32C5" among ST's families, so the catalogue
    # refused to guess a core. OH-65 checked again on 2026-08-26.
    #
    # ST announced the STM32C5 in **March 2026** -- a Cortex-M33 part, sold as
    # low-cost with more performance than the M0+ STM32C0. Two independent
    # statements in Wikipedia's STM32 article agree: its comparison table gives
    # the core as "Cortex-M33F", and its history timeline reads "March 2026
    # STM32C5 with Cortex-M33, increased performance with cost efficiency and
    # enhanced end-device capabilities".
    #
    # **The corroboration that matters is not Wikipedia.** It is that Seeed's
    # own KiCad library ships `XIAO-STM32C5-SMD.kicad_mod`, in a commit dated
    # 2026-07-15 -- four months after the announcement, from the vendor who
    # would be building the board. A vendor does not draw a footprint for a
    # part that does not exist.
    #
    # st.com could not be reached to cite directly; two attempts timed out.
    # Recorded so the next reader knows which source is missing rather than
    # assuming it was checked.
    #
    # So this board is no longer blocked on identification. It is blocked on
    # exactly what the other Cortex-M33 boards are blocked on -- OH-36's
    # oracle. (This said "the other eight" until OH-157 moved the two RP2350
    # boards to their RISC-V half; `missing_cores()` counts them, and a count
    # written here is the one that goes stale.)
    "STM32C5": ("Armv8-M (Cortex-M33)", "cortexm33"),
}

#: Chips on which a real compiled image has been watched executing, and the
#: test that watched it.
#:
#: **This is the only thing that licenses the words "runs firmware".** Having a
#: built core and a board description means a board *could* run something; it
#: is not evidence that anything has. The distinction is small on a good day
#: and the whole difference on a bad one, so the claim is tied to a named file
#: and `test_every_firmware_claim_names_a_test_that_exists` checks the file is
#: there.
#: **Coupled to `test_only_the_board_a_real_image_ran_on_claims_to_have_run_one`,
#: which pins the set to {"RP2040", "SAMD21"}.** That pin is what stops a
#: further entry being added by pointing at a file that merely exists and
#: merely mentions the right symbols; adding a chip here means editing that
#: test too, and its name says what it is protecting.
#:
#: The SAMD21 entry is the first one added since the pin existed, and it is
#: worth saying what made it admissible, because "the core was already built"
#: is exactly the argument the pin is there to refuse. The core being shared
#: with the RP2040 bought nothing: the entry is here because
#: `tests/cortexm0/test_samd21_blink.py` loads a 48-byte image compiled by
#: arm-none-eabi-gcc from `tests/cortexm0/samd21/blink.c` and watches PA17
#: change state 45 times. Different chip, different flash address, different
#: peripheral, its own compiled image.
#: The ATmega328P entry is the first on a machine that is not Arm, and it is
#: worth saying what made it admissible, because "the core was built and there
#: is a blink test" is not the argument. `tests/avr/test_blink.py` has watched a
#: real image toggle PB5 since 2026-08-25 and is *not* the evidence named here:
#: it drives `core.avr.abi.Cpu` directly, configuring the machine and setting
#: the PC itself, which proves the instruction set rather than the board. The
#: claim this table makes is a board claim, so the evidence is
#: `tests/avr/test_uno_board.py`, where a board name and a file of bytes go
#: into `webui/api.py` and PB5 moves.
#: The ESP32-C3 entry is the first RISC-V one and the first to unlock three
#: boards at once. What made it admissible is the same thing that made the
#: ATmega328P admissible: `tests/riscv32/test_esp32c3_board.py` puts a board
#: name and a real `riscv32-esp-elf-gcc` image into `webui/api.py` and watches
#: GPIO8 alternate at a constant period. `tests/riscv32/test_rvc.py` also runs
#: that image and is **not** named here, because it drives the ABI directly and
#: so proves the decoder rather than the board.
#: The ESP32-C6 entry is the second RISC-V one, and what it had to survive is
#: the argument its own predecessor makes available: the core was already
#: built, the C3 board already worked, and the two parts share an instruction
#: set. None of that is evidence. `tests/riscv32/test_esp32c6_board.py` loads
#: `tests/riscv32/c6blink/blink.bin` -- its own image, compiled `-march=rv32imac`
#: against its own linker script, at its own GPIO base of 0x60091000 -- and
#: watches GPIO8 alternate at a constant period. The C3's image would fault on
#: this board at its first store, which is the shortest statement of why the
#: entry is not inherited.
#:
#: The ESP32-C5 entry is the third RISC-V one. For a while this paragraph said
#: the C5 was "deliberately absent from this table" -- true when it was
#: written, when `core/riscv32` implemented none of the C5's three Zc groups
#: and the board was configured with the subset it could execute -- and it was
#: left standing after OH-146 implemented Zcb, Zcmp and Zcmt and OH-147's
#: `tests/riscv32/test_esp32c5_board.py` watched a real image drive the pin.
#: Found and corrected by OH-158 (2026-09-04), whose whole subject is claims
#: that outlived what they described; the table below is the fact and this
#: comment follows it, not the other way round.
#:
#: The RP2350 entry is the first for a chip with two instruction sets, and it
#: is evidence for one of them. `tests/webui/test_xiao_rp2350_board.py`
#: loads `xiao_rp2350/blink.bin` beside it -- compiled `-march=rv32imac`, carrying the
#: boot ROM's minimum RISC-V IMAGE_DEF -- onto the XIAO by name, steps it on
#: `core/riscv32`, and watches the pad the board file gives GPIO5 alternate
#: through the pin view, after the image has selected SIO and opened the
#: pad's isolation latch. That is the Hazard3 half. The Cortex-M33 half, which
#: a real RP2350 boots by default, has no core here and is OH-36's.
FIRMWARE_VERIFIED: dict[str, str] = {
    "RP2040": "tests/cortexm0/test_blink.py",
    "SAMD21": "tests/cortexm0/test_samd21_blink.py",
    "ATmega328P": "tests/avr/test_uno_board.py",
    "ESP32-C3": "tests/riscv32/test_esp32c3_board.py",
    "ESP32-C6": "tests/riscv32/test_esp32c6_board.py",
    "ESP32-C5": "tests/riscv32/test_esp32c5_board.py",
    "RP2350": "tests/webui/test_xiao_rp2350_board.py",
}

#: A row of `tools/board_manifest.py` to the test that compiled a sketch for
#: it against its own variant and watched the image run (rules/board-claims.md
#: §7), or on an RP2040 a bare-metal image (§11). A row does not inherit
#: its chip's `FIRMWARE_VERIFIED` entry (§6), so this is its only
#: licence; `tools/check_board_claims.py` holds each entry
#: as it holds that table's, and to loading its board by name (§7).
BOARD_FIRMWARE_VERIFIED: dict[str, str] = {
    "Adafruit Feather ESP32-C6": "tests/webui/test_feather_esp32c6_board.py",
    "SparkFun Thing Plus ESP32-C6": "tests/webui/test_sparkfun_esp32c6_board.py",
    "Adafruit QT Py ESP32-C3": "tests/webui/test_qtpy_esp32c3_board.py",
    "SparkFun Pro Micro ESP32-C3": "tests/webui/test_sparkfun_pro_micro_esp32c3_board.py",
    "SparkFun Qwiic Pocket ESP32-C6":
        "tests/webui/test_sparkfun_qwiic_pocket_esp32c6_board.py",
    "Adafruit KB2040": "tests/webui/test_kb2040_board.py",
    "PCBCUPID Glyph Mini RP2040": "tests/webui/test_glyph_mini_rp2040_board.py",
    "PCBCUPID Glyph C3": "tests/webui/test_pcbcupid_glyph_c3_board.py",
    "PCBCUPID Glyph C6": "tests/webui/test_pcbcupid_glyph_c6_board.py",
    "Olimex ESP32-C3-DevKit-Lipo":
        "tests/webui/test_olimex_esp32c3_devkit_lipo_board.py",
    "SparkFun Thing Plus ESP32-C5": "tests/webui/test_sparkfun_esp32c5_board.py",
}

#: What each instruction set would need before a core for it could be trusted.
#: From `docs/architectures.md`, which records the evidence class for each.
#: Ordering the backlog needs this: "how many boards" says what to build first,
#: and this says what it would cost.
ORACLES: dict[str, str] = {
    "cortexm0": "rp2040js (MIT, hand-written from DDI0419) -- in use here",
    "cortexm33": "none free that models Armv8-M security extensions; QEMU has m33 "
                 "but not the RP2350's Hazard3 half. A prebuilt Windows QEMU exists "
                 "(qemu.weilnetz.de, checked 2026-09-04, not installed), so its "
                 "absence is not what blocks this; being a single source is "
                 "(docs/architectures.md 4.6)",
    "cortexm4": "QEMU has cortex-m4; no independent second source, so a "
                "disagreement could not be adjudicated. The same prebuilt Windows "
                "QEMU applies here (docs/architectures.md 4.6): obtainable, not "
                "installed, and single-source either way",
    "riscv32": "Hazard3's rvcpp (Apache-2.0) builds here, but has no extension "
               "gating at all -- right on the legal space, wrong at the "
               "illegal-instruction edge",
    "xtensa": "NONE. QEMU-xtensa and binutils-xtensa both derive from the same "
              "Tensilica archive via import_core.sh, so their agreement is a "
              "tautology (docs/architectures.md 2.1c)",
    "avr": "avr8js (MIT, hand-written from the Microchip datasheet) -- in use "
           "here, and WRONG about the half-carry and about neg's overflow, so "
           "those two are checked against the manual instead "
           "(tests/avr/test_datasheet_edges.py). simavr and avr-gdb exist and "
           "neither is hardware-captured either",
    "unknown": "the part is not confirmed to exist",
}

#: Boards whose name does not follow `XIAO-<CHIP>-<PACKAGE>`. Named here so
#: they are handled, rather than parsed into something plausible and wrong.
IRREGULAR: dict[str, str] = {
    "Arduino Uno": "ATmega328P",
    # Seeed's own footprint really is doubled; `XIAO-XIAO STM32C5-SMD.kicad_mod`
    # exists in their KiCad library. Faithful, and still unparseable by rule.
    "XIAO-XIAO STM32C5-SMD": "STM32C5",
}


class CatalogueError(Exception):
    """A board this module cannot describe."""


@dataclasses.dataclass(frozen=True)
class Board:
    """One board, and the three separate facts about whether it works."""

    name: str
    chip: str
    isa: str
    core: str
    core_exists: bool
    core_built: bool
    described: bool
    firmware_evidence: str | None
    #: Why the chip's evidence is not this board's, where it is not. A row in
    #: `tools/board_manifest.py` does not inherit it (rules/board-claims.md
    #: §6), and has only what `BOARD_FIRMWARE_VERIFIED` gives it (§7).
    firmware_withheld: str | None = None

    @property
    def runnable(self) -> bool:
        """Everything needed to *attempt* an image exists.

        A built core with no board description has no memory map and no
        peripherals; a description with no core has nothing to execute it.
        This is emphatically **not** "firmware has run" -- see
        `firmware_verified`, which is the claim that needs evidence.
        """
        return self.core_built and self.described

    @property
    def firmware_verified(self) -> bool:
        """A real compiled image has been watched executing on this chip, or,
        for a row of `tools/board_manifest.py`, on this board."""
        return self.firmware_evidence is not None

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "chip": self.chip,
            "isa": self.isa,
            "core": self.core,
            "core_exists": self.core_exists,
            "core_built": self.core_built,
            "described": self.described,
            "runnable": self.runnable,
            "firmware_verified": self.firmware_verified,
            "firmware_evidence": self.firmware_evidence,
            "firmware_withheld": self.firmware_withheld,
        }


def chip_for(board_name: str) -> str:
    """The chip on a board, from its name.

    Raises rather than guessing. A board whose name this cannot parse is a
    board someone must look at -- silently filing it under an invented chip is
    how a catalogue starts lying.
    """
    row = board_manifest.find(board_name)
    if board_name in IRREGULAR and row is not None:
        raise CatalogueError(
            f"{board_name!r} is in IRREGULAR as {IRREGULAR[board_name]} and a row "
            f"in tools/board_manifest.py as {row.chip}; name it in one place"
        )
    if board_name in IRREGULAR:
        return IRREGULAR[board_name]
    if row is not None:
        return row.chip
    if not board_name.startswith("XIAO-"):
        raise CatalogueError(
            f"cannot tell which chip is on {board_name!r}: it does not start "
            f"with XIAO- and is not a row in tools/board_manifest.py. Add a "
            f"row there, or name it in IRREGULAR."
        )
    rest = board_name[len("XIAO-"):]
    # Longest first, so `ESP32-C3` wins over a hypothetical `ESP32`, and
    # case-insensitively, because Seeed spells nRF54l15 and nRF54LM20A
    # differently from each other.
    #
    # **The delimiter check is the load-bearing part.** A bare `startswith`
    # matches any name that merely *begins* with a known chip, so
    # `XIAO-ESP32-C61-DIP` resolved to `ESP32-C6` -- and ESP32-C61 is a real
    # Espressif part, not a hypothetical. That is the same failure class as the
    # `ESP32-C3-DIP` bug this rule was rewritten to fix: a name silently
    # assigned to the wrong chip instead of raising. Requiring the chip to end
    # at a `-` or at the end of the string is what makes an unknown part loud.
    for chip in sorted(CHIPS, key=len, reverse=True):
        if not rest.lower().startswith(chip.lower()):
            continue
        tail = rest[len(chip):]
        if tail == "" or tail.startswith("-"):
            return chip
    raise CatalogueError(
        f"{board_name!r} names no chip in CHIPS. Add the chip with its "
        f"instruction set, citing docs/architectures.md."
    )


def board_names(directory: pathlib.Path | None = None) -> list[str]:
    """Every imported board, from the files rather than from a list."""
    directory = BOARDS_DIR if directory is None else directory
    return sorted(path.stem for path in directory.glob("*.json"))


def described_chips(directory: pathlib.Path | None = None) -> set[str]:
    """Chips with a board description module beside this file.

    `rp2040.py` describing an RP2040 is the convention, and it is a convention
    rather than a registry so that adding a chip is adding one file.
    """
    directory = BOARDS_DIR if directory is None else directory
    return {
        path.stem.upper().replace("-", "")
        for path in directory.glob("*.py")
        # `contract` is not a board either, and was counted as one until
        # 2026-08-25: `described_chips()` returned a phantom "CONTRACT".
        # Harmless while no chip is called that, and a latent lie -- so it is
        # taken from `contract.NOT_A_BOARD`, which is the list that already
        # knows, rather than repeated here as a third copy.
        if path.stem not in NOT_A_BOARD
    }


def catalogue(directory: pathlib.Path | None = None) -> list[Board]:
    """Every board, with all three facts looked up rather than assumed."""
    cores = set(build_core.cores())
    described = described_chips(directory)

    out: list[Board] = []
    for name in board_names(directory):
        chip = chip_for(name)
        isa, core = CHIPS.get(chip, ("unknown -- not in the survey", "unknown"))
        core_exists = core in cores
        built = False
        if core_exists:
            try:
                built = build_core.library_path(core).is_file()
            except build_core.BuildError:
                built = False
        evidence = FIRMWARE_VERIFIED.get(chip)
        withheld = None
        row = board_manifest.find(name)
        if row is not None:
            own = BOARD_FIRMWARE_VERIFIED.get(name)
            if own is None and evidence is not None:
                withheld = (
                    f"{evidence} is the {chip}'s evidence, and it does not carry "
                    f"to this board: it is a row in tools/board_manifest.py, and "
                    f"BOARD_FIRMWARE_VERIFIED names no test that built a sketch "
                    f"against its own variant, {row.package} variants/"
                    f"{row.variant}, and watched it run (rules/board-claims.md §7)"
                )
            evidence = own
        out.append(Board(
            name=name,
            chip=chip,
            isa=isa,
            core=core,
            core_exists=core_exists,
            core_built=built,
            described=chip.upper().replace("-", "") in described,
            firmware_evidence=evidence,
            firmware_withheld=withheld,
        ))
    return out


def missing_cores(directory: pathlib.Path | None = None) -> list[dict[str, object]]:
    """The cores that would unlock the remaining boards, and what each needs.

    **Grouped by core, not by instruction-set string.** Grouping by the string
    split `cortexm33` into "Armv8-M (Cortex-M33)" and "Armv8-M (Cortex-M33) +
    RV32 (Hazard3)", and `riscv32` into three, so ten rows described five
    pieces of work -- and one of the rows was `cortexm0`, a core that is
    already built, sitting under a heading about missing ones.

    Ordered by boards unlocked, which is the only ordering that is not a
    guess; `oracle` says what each would cost, which is the other half of the
    decision.
    """
    boards = catalogue(directory)
    cores = set(build_core.cores())

    waiting: dict[str, list[str]] = {}
    for board in boards:
        if not board.runnable:
            waiting.setdefault(board.core, []).append(board.name)

    rows = [
        {
            "core": core,
            "isas": sorted({b.isa for b in boards if b.core == core}),
            "boards": names,
            "exists": core in cores,
            "oracle": ORACLES.get(core, "not surveyed"),
        }
        for core, names in waiting.items()
    ]
    return sorted(rows, key=lambda r: (-len(r["boards"]), str(r["core"])))
