# OpenHardware — an RP2350 board, run on its Hazard3 half.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What this file is for
#
# It is the evidence `webui/boards/catalogue.py`'s `FIRMWARE_VERIFIED` names
# for the RP2350, so it does the headline thing the C6's does: a board name
# and a file of bytes go into `webui/api.py`, the image runs on
# `core/riscv32`, and the XIAO's own pad moves -- watched through the pin
# view, at the pad whose `chip_index` is the GPIO the image drives.
#
# The image is `xiao_rp2350/blink.bin` beside this file: `blink.c` there,
# compiled by the ESP32 Arduino core's riscv32-esp-elf GCC 14.2 against
# `blink.ld` there. Its GPIO is never typed: the build is given
# `rp2350.HEADER["D3"]`, which `tools/import_pindefs.py` read out of the
# vendor's board-support packages, and
# `test_the_committed_binary_matches_its_source` rebuilds it byte for byte
# wherever that compiler is installed and skips by name where it is not.
#
# ## Why it is under tests/webui/ and not beside the C6's
#
# The chip's evidence sits where the KB2040's does -- a test here and its
# fixture directory beside it -- rather than in `tests/riscv32/` with the
# ESP32 boards', because that directory is another ticket's claim (OH-157's
# note of 2026-10-08). What it borrows from there, `tests/riscv32/lockstep`,
# it imports unchanged.
#
# ## What it cannot claim
#
# **This is the RP2350's RISC-V half.** A real RP2350 boots its Cortex-M33s
# unless told otherwise, and that half is not modelled here: it is OH-36's.
# The boot ROM is not modelled either -- `webui/boards/rp2350.py` says where
# the image is entered and why that is the instruction the ROM would enter
# it at -- so what runs is a bare-metal image, the standard the RP2040,
# SAMD21 and ESP32 fixtures already meet. A pico-sdk image is not one.
#
# Every oracle here is software (rules/conformance-fixtures.md section 7):
# rvcpp, Hazard3's own model, agrees with this core on the image's
# instruction stream, and pico-sdk's headers agree with the board's numbers.
# Nothing here was measured on silicon.

import itertools
import os
import pathlib
import re
import shutil
import struct
import subprocess
import tempfile

import pytest

from webui import api, firmware, pinmap
from webui.boards import rp2040, rp2350

HERE = pathlib.Path(__file__).resolve().parent
IMAGE = HERE / "xiao_rp2350" / "blink.bin"
SOURCE = HERE / "xiao_rp2350" / "blink.c"
SCRIPT = HERE / "xiao_rp2350" / "blink.ld"

#: One of the two XIAO RP2350 boards. They differ in footprint and not in
#: silicon, so one description serves both; the SMD is run too, below.
BOARD = "XIAO-RP2350-DIP"

#: The label the image drives. Why this one, and not another, is a test.
LABEL = "D3"

#: Several toggles at the measured 604-instruction period.
BUDGET = 3_000

#: The compiler that built `blink.bin`. Another version may emit other bytes
#: for the same source, so the rebuild asks for this one by its own banner.
COMPILER_BANNER = "crosstool-NG esp-14.2.0_20260121"

#: What `blink.bin` was compiled with. `-march=rv32imac`: no Zbb, no Zbkb.
FLAGS = ("-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
         "-nostdlib", "-nostartfiles")

#: The Hazard3's whole ISA as the datasheet spells it, for the two tests
#: that ask what the compiler does with it.
HAZARD3 = f"-march={rp2350.ISA}"

#: The minimum RISC-V IMAGE_DEF, RP2350 Datasheet 80d627281ed5 section
#: 5.9.5.2, Table 504 (PDF p.391), word for word.
IMAGE_DEF = (0xFFFFDED3, 0x11010142, 0x000001FF, 0x00000000, 0xAB123579)

#: RV32I and the compressed instructions an RV32 part with no FPU has, as
#: `core/riscv32/disasm.py` spells them -- everything `-march=rv32imac`
#: can put in an image except M and A, which this one contains none of.
RV32I = frozenset({
    "lui", "auipc", "jal", "jalr", "beq", "bne", "blt", "bge", "bltu", "bgeu",
    "lb", "lh", "lw", "lbu", "lhu", "sb", "sh", "sw", "addi", "slti", "sltiu",
    "xori", "ori", "andi", "slli", "srli", "srai", "add", "sub", "sll", "slt",
    "sltu", "xor", "srl", "sra", "or", "and", "fence", "ecall", "ebreak",
})
RVC = frozenset({
    "c.addi4spn", "c.lw", "c.sw", "c.nop", "c.addi", "c.jal", "c.li",
    "c.addi16sp", "c.lui", "c.srli", "c.srai", "c.andi", "c.sub", "c.xor",
    "c.or", "c.and", "c.j", "c.beqz", "c.bnez", "c.slli", "c.lwsp", "c.jr",
    "c.mv", "c.ebreak", "c.jalr", "c.add", "c.swsp",
})


def load(board: str = BOARD) -> api.BoardSession:
    """A board name and a file of bytes. `base` because a raw `.bin` carries
    no address of its own, and this one is linked at the XIP window."""
    return api.load_firmware(board, IMAGE.read_bytes(), base=rp2350.XIP)


def chip_index(board: str, label: str) -> int:
    """The `chip_index` the board FILE gives the pad labelled `label`."""
    layout = pinmap.load(board)
    assert layout is not None, f"{board} has no pad map"
    indices = {pad.chip_index for pad in layout.pads if pad.label == label}
    assert len(indices) == 1, f"{board}: {label!r} pads carry {indices}"
    return indices.pop()


def watch(session: api.BoardSession, board: str, budget: int = BUDGET) -> list[tuple[int, str]]:
    """Step, recording each change of the watched pad's level as the pin view
    reports it, and failing if any other pad with a GPIO behind it moves."""
    layout = pinmap.load(board)
    others = {pad.label for pad in layout.pads
              if pad.chip_index is not None and pad.label != LABEL}
    seen: list[tuple[int, str]] = []
    for step in range(budget):
        session.step()
        view = api.pin_view(session.runtime, session.cpu, board)
        states = {pad["label"]: pad["state"] for pad in view["pads"]}
        moved = {label: states[label] for label in others if states[label] != "input"}
        assert not moved, f"step {step}: pads other than {LABEL} moved: {moved}"
        if not seen or states[LABEL] != seen[-1][1]:
            seen.append((step, states[LABEL]))
    return seen


def code_of(image: bytes) -> bytes:
    """The image up to its IMAGE_DEF block, which is data and not code."""
    marker = IMAGE_DEF[0].to_bytes(4, "little")
    at = image.find(marker)
    assert at > 0, f"no IMAGE_DEF start marker in {len(image)} bytes"
    return image[:at]


def compiler() -> tuple[pathlib.Path, pathlib.Path] | None:
    """The riscv32-esp-elf gcc and objcopy that built `blink.bin`, or None.

    Looked for on PATH and in the Arduino IDE's package directory, where the
    ESP32 core installs it, and taken only if its banner is
    `COMPILER_BANNER`: PlatformIO's riscv32-esp-elf is GCC 8.4, which emits
    other bytes and cannot be asked for Zbb at all.
    """
    found = shutil.which("riscv32-esp-elf-gcc")
    candidates = [pathlib.Path(found)] if found else []
    for home in (os.environ.get("LOCALAPPDATA"), str(pathlib.Path.home() / ".arduino15"),
                 str(pathlib.Path.home() / "Library")):
        if home:
            root = pathlib.Path(home)
            for arduino in (root / "Arduino15", root):
                candidates += sorted(arduino.glob(
                    "packages/esp32/tools/esp-rv32/*/bin/riscv32-esp-elf-gcc*"))
    for gcc in candidates:
        if gcc.name not in ("riscv32-esp-elf-gcc", "riscv32-esp-elf-gcc.exe"):
            continue
        banner = subprocess.run([str(gcc), "--version"], capture_output=True,
                                text=True).stdout.splitlines()
        objcopy = gcc.with_name(gcc.name.replace("gcc", "objcopy"))
        if banner and COMPILER_BANNER in banner[0] and objcopy.is_file():
            return gcc, objcopy
    return None


def build(work: pathlib.Path, *flags: str) -> bytes:
    """`blink.c` compiled and linked with `FLAGS` and `flags`, as a raw image.

    `-DBLINK_GPIO` is the XIAO's `D3` out of `rp2350.HEADER`, here and in
    every build this file makes, so that no build of this image names a GPIO
    the board's own table does not.
    """
    tools = compiler()
    if tools is None:
        pytest.skip(f"no riscv32-esp-elf-gcc reporting {COMPILER_BANNER!r}")
    gcc, objcopy = tools
    elf, image = work / "blink.elf", work / "blink.raw"
    subprocess.run(
        [str(gcc), *FLAGS, *flags, f"-DBLINK_GPIO={rp2350.HEADER[LABEL]}",
         "-T", str(SCRIPT), "-o", str(elf), str(SOURCE)],
        check=True, capture_output=True,
    )
    subprocess.run([str(objcopy), "-O", "binary", str(elf), str(image)],
                   check=True, capture_output=True)
    return image.read_bytes()


def pico_sdk() -> pathlib.Path | None:
    """pico-sdk's RP2350 register headers, or None: `$PICO_SDK_PATH` first,
    as pico-sdk itself looks, then the submodule path arduino-pico declares,
    where `webui/boards/rp2350.py` says how to fetch it."""
    named = os.environ.get("PICO_SDK_PATH")
    candidates = [pathlib.Path(named)] if named else []
    candidates.append(HERE.parents[1] / "third_party" / "bsp" / "arduino-pico" / "pico-sdk")
    for root in candidates:
        regs = root / "src" / "rp2350" / "hardware_regs" / "include" / "hardware" / "regs"
        if (regs / "sio.h").is_file():
            return regs
    return None


def defines(header: pathlib.Path) -> dict[str, tuple[int, str]]:
    """Every `#define NAME VALUE` in `header`: its 1-based line and its text."""
    out: dict[str, tuple[int, str]] = {}
    for number, line in enumerate(header.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0] == "#define":
            out[parts[1]] = (number, parts[2].strip())
    return out


def value(text: str) -> int | str:
    """A header's value as an integer -- `_u(0x40)`, or `(_u(0x3) << _u(12))`
    -- or its string, for an `_ACCESS` like `"WO"`."""
    single = re.fullmatch(r"_u\((0x[0-9a-fA-F]+)\)", text)
    if single:
        return int(single.group(1), 16)
    shifted = re.fullmatch(r"\(_u\((0x[0-9a-fA-F]+)\) << _u\((\d+)\)\)", text)
    if shifted:
        return int(shifted.group(1), 16) << int(shifted.group(2))
    quoted = re.fullmatch(r'"([^"]*)"', text)
    if quoted:
        return quoted.group(1)
    raise AssertionError(f"cannot read {text!r} as a value")


# --- the headline -----------------------------------------------------------


def test_a_board_name_and_a_compiled_image_drive_the_xiaos_d3_pad():
    """The evidence for the RP2350.

    The pad is found the way the page finds it: by the board file's
    `chip_index`, which must be the GPIO `rp2350.HEADER` gives `D3`, and its
    level read through `api.pin_view`. Before the image selects SIO and opens
    the pad's isolation latch, the pad reads `input`; then `low` when its
    output is enabled at zero; then it alternates. Every other pad with a GPIO
    behind it reads `input` throughout, which `watch` checks at each step.

    And by the end the image has released IO_BANK0 and PADS_BANK0 from
    reset, as silicon requires. The pad cannot say so: RESETS is stored and
    not obeyed here (`rp2350.install_resets`), so an image that never
    releases the banks drives its pad all the same. The register can.
    """
    assert chip_index(BOARD, LABEL) == rp2350.HEADER[LABEL]
    banks = rp2350.RESET_IO_BANK0 | rp2350.RESET_PADS_BANK0
    with load() as session:
        seen = watch(session, BOARD)
        reset = session.cpu.read_word(rp2350.RESETS + rp2350.RESETS_RESET)
    assert not reset & banks, (
        f"RESETS.RESET is {reset:#010x}: the image left {reset & banks:#x} of "
        f"IO_BANK0|PADS_BANK0 ({banks:#x}) held in reset")
    states = [state for _, state in seen]
    assert states[:3] == ["input", "low", "high"], seen[:6]
    assert len(states) >= 5, f"the pad changed {len(states) - 1} times: {seen}"
    assert all(a != b and {a, b} == {"low", "high"}
               for a, b in itertools.pairwise(states[1:])), seen


def test_the_pad_alternates_at_a_steady_period():
    """A wandering period means the delay loop is wrong; the AVR's inverted
    branch was found that way. 100 iterations cost more than 100 steps."""
    with load() as session:
        seen = watch(session, BOARD)
    steps = [step for step, _ in seen[2:]]
    periods = {b - a for a, b in itertools.pairwise(steps)}
    assert len(periods) == 1, f"period varies: {sorted(periods)} over {seen}"
    assert periods.pop() > 100


def test_the_smd_board_runs_the_same_image_on_its_own_d3_pad():
    """`FIRMWARE_VERIFIED` is keyed by chip because the DIP and the SMD build
    one image from one variant (rules/board-claims.md section 1). That is a
    claim about both files, so the SMD's own pad map is asked too."""
    board = "XIAO-RP2350-SMD"
    assert chip_index(board, LABEL) == rp2350.HEADER[LABEL]
    with load(board) as session:
        states = [state for _, state in watch(session, board)]
    assert states[:3] == ["input", "low", "high"], states


def test_why_d3_and_not_another_pad():
    """`D3` is the one label of `D0` to `D10` that the XIAO RP2350 and the
    XIAO RP2040 send to different GPIOs, so an image built against the
    RP2040's table drives another pin -- one that is no pad of this board at
    all. Any other label would pass whichever XIAO's table the build read.

    And it is a GPIO the vendor names too: the board file's `chip_pin` for
    the pad, from the board-support packages, is the module's `PIN_NAMES`.
    """
    differ = {label for label in (f"D{n}" for n in range(11))
              if rp2040.HEADER[label] != rp2350.HEADER[label]}
    assert differ == {LABEL}, differ
    pads = {pad.chip_index for pad in pinmap.load(BOARD).pads}
    assert rp2040.HEADER[LABEL] not in pads, (
        f"GPIO{rp2040.HEADER[LABEL]}, the RP2040's {LABEL}, is a pad here")
    stated = {pad.chip_pin for pad in pinmap.load(BOARD).pads if pad.label == LABEL}
    assert stated == {rp2350.PIN_NAMES[LABEL]}, stated


# --- a UF2 says which half of the chip it was built for ---------------------

#: "Table of standard UF2 family IDs understood by the RP2350 bootrom", RP2350
#: Datasheet 80d627281ed5, section 5.5.3, Table 469 (PDF p.368).
UF2_ABSOLUTE = 0xE48BFF57
UF2_DATA = 0xE48BFF58
UF2_RP2040 = 0xE48BFF56
UF2_RP2350_ARM_S = 0xE48BFF59
UF2_RP2350_RISCV = 0xE48BFF5A
UF2_RP2350_ARM_NS = 0xE48BFF5B


def uf2(*images: tuple[int, bytes]) -> bytes:
    """One UF2 block per `(family_id, payload)`, each at `rp2350.XIP` with the
    familyID flag set and each the only block of its family: block 0 of 1."""
    blocks = b""
    for family_id, payload in images:
        assert len(payload) <= 476, f"{len(payload)} bytes is more than one UF2 block"
        head = struct.pack("<8I", firmware.UF2_MAGIC_START0, firmware.UF2_MAGIC_START1,
                           firmware.UF2_FLAG_FAMILY_ID, rp2350.XIP, len(payload), 0, 1,
                           family_id)
        blocks += head + payload.ljust(476, b"\x00") + struct.pack("<I", firmware.UF2_MAGIC_END)
    return blocks


def test_a_uf2_for_the_arm_half_or_for_an_rp2040_is_refused_as_not_for_this_chip():
    """`blink.bin`'s bytes under each family this board cannot run. Without
    a family to ask for, a file of one family loaded whatever it held, so an
    Arm or an RP2040 image alone in its file landed at 0x10000000 and stopped
    at an illegal encoding, which reads as the part refusing the program
    rather than the file being for another chip or the other half. The XIAO
    RP2350's default Arm build is not that file: the first `arch` in
    arduino-pico 33201a6's `boards.txt` writes `--family rp2350-arm-s
    --abs-block` (:36734), two families, which was refused as unreadable.
    Each is now refused as not for this chip, and so are the `absolute` and
    `data` families alone, which say nothing of which half an image is for."""
    image = IMAGE.read_bytes()
    for data, name in ((uf2((UF2_RP2350_ARM_S, image)), "RP2350_ARM_S"),
                       (uf2((UF2_RP2350_ARM_NS, image)), "RP2350_ARM_NS"),
                       (uf2((UF2_RP2040, image)), "RP2040"),
                       (uf2((UF2_ABSOLUTE, image)), "RP2XXX_ABSOLUTE"),
                       (uf2((UF2_DATA, image)), "RP2XXX_DATA"),
                       (uf2((UF2_RP2350_ARM_S, image), (UF2_ABSOLUTE, image)),
                        "RP2350_ARM_S")):
        with pytest.raises(api.BoardRunError) as caught:
            api.load_firmware(BOARD, data).close()
        assert caught.value.reason == "nothing-for-this-chip", (name, str(caught.value))
        message = str(caught.value)
        assert "holds nothing for a RP2350" in message and name in message, message


def test_a_uf2_for_the_risc_v_half_loads_even_beside_an_arm_image_and_drives_d3():
    """An RP2350_RISCV UF2 of `blink.bin` needs no `base`: its block names
    the address. A file carrying an Arm image at the same addresses -- 0xFF
    filler here, which would stop on its first word -- loads the RISC-V one
    rather than refusing to choose. So does one with an `absolute` block
    beside it, the two families arduino-pico's own RISC-V build writes:
    `--family rp2350-riscv --abs-block` (`boards.txt:36741`)."""
    image = IMAGE.read_bytes()
    filler = b"\xff" * len(image)
    for data in (uf2((UF2_RP2350_RISCV, image)),
                 uf2((UF2_RP2350_ARM_S, filler), (UF2_RP2350_RISCV, image)),
                 uf2((UF2_RP2350_RISCV, image), (UF2_ABSOLUTE, filler))):
        with api.load_firmware(BOARD, data) as session:
            assert session.image.family == "RP2350_RISCV", session.image
            assert [(s.address, s.data) for s in session.image.segments] == [
                (rp2350.XIP, image)], session.image.segments
            states = [state for _, state in watch(session, BOARD)]
        assert states[:3] == ["input", "low", "high"], states


# --- the image: what the boot ROM would see, and what the core decodes ------


def test_the_image_begins_with_its_stack_and_ends_with_the_minimum_image_def():
    """The two ends of the image are the two facts the board's entry
    argument rests on. The first instruction loads `sp` with this part's
    SRAM top (`lui sp`: opcode 0x37, rd 2); the last twenty bytes are Table
    504's IMAGE_DEF, inside the first 4 kB, with nothing after it."""
    image = IMAGE.read_bytes()
    first = int.from_bytes(image[:4], "little")
    assert first & 0x7F == 0x37 and (first >> 7) & 0x1F == 2, hex(first)
    assert first & 0xFFFFF000 == rp2350.SRAM + rp2350.SRAM_SIZE, hex(first)
    words = tuple(int.from_bytes(image[i:i + 4], "little")
                  for i in range(len(image) - 20, len(image), 4))
    assert words == IMAGE_DEF, [hex(w) for w in words]
    assert len(code_of(image)) == len(image) - 20 and len(image) <= 4096


def test_every_instruction_is_rv32i_or_compressed_and_this_core_decodes_it():
    """Read with this repository's own disassembler, because the question is
    what `core/riscv32` sees. An encoding it cannot render prints as a bare
    `0x...`, so a Zbb or Zbkb instruction -- which it has no rendering for --
    fails the first assertion, and an M, A, Zba, Zbs, Zcb or Zcmp one the
    second."""
    from core.riscv32 import disasm

    lines = disasm.disassemble(code_of(IMAGE.read_bytes()), rp2350.XIP)
    undecoded = [line for line in lines if line.text.startswith("0x")]
    assert not undecoded, [(hex(line.address), line.raw) for line in undecoded]
    mnemonics = {line.text.split()[0] for line in lines}
    assert mnemonics <= RV32I | RVC, sorted(mnemonics - (RV32I | RVC))


# --- step 1, falsifiable: Zbb is absent because of the program --------------


def test_the_committed_binary_matches_its_source():
    """Rebuilt byte for byte where `COMPILER_BANNER`'s compiler is
    installed, and skipped by name where it is not."""
    with tempfile.TemporaryDirectory() as work:
        rebuilt = build(pathlib.Path(work))
    assert rebuilt == IMAGE.read_bytes()


def test_this_compiler_emits_zbb_when_the_march_names_it():
    """The control that makes the next test mean something. GCC 8.4, which
    is what the ticket first had, rejects `_zbb` and turned
    `__builtin_clz` into a library call under every flag -- so "no Zbb
    appeared" said nothing about the image. GCC 14.2 emits `clz`, `minu` and
    `rev8` for these three functions under the Hazard3's string, and none of
    them under `-march=rv32imac`."""
    tools = compiler()
    if tools is None:
        pytest.skip(f"no riscv32-esp-elf-gcc reporting {COMPILER_BANNER!r}")
    gcc = tools[0]
    objdump = gcc.with_name(gcc.name.replace("gcc", "objdump"))
    probe = ("unsigned a(unsigned x) { return __builtin_clz(x); }\n"
             "unsigned b(unsigned x, unsigned y) { return x < y ? x : y; }\n"
             "unsigned c(unsigned x) { return __builtin_bswap32(x); }\n")
    with tempfile.TemporaryDirectory() as work:
        source = pathlib.Path(work) / "probe.c"
        source.write_text(probe, encoding="utf-8")
        listings = []
        for march in (HAZARD3, "-march=rv32imac"):
            obj = pathlib.Path(work) / "probe.o"
            subprocess.run([str(gcc), march, "-mabi=ilp32", "-Os", "-c", "-o",
                            str(obj), str(source)], check=True, capture_output=True)
            listings.append(subprocess.run(
                [str(objdump), "-d", "-M", "no-aliases", str(obj)],
                check=True, capture_output=True, text=True).stdout)
    zbb = re.compile(r"\t(clz|minu|rev8)\t")
    assert set(zbb.findall(listings[0])) == {"clz", "minu", "rev8"}, listings[0]
    assert not zbb.findall(listings[1]), listings[1]


def test_the_image_is_the_same_bytes_under_the_hazard3s_whole_isa():
    """Step 1's answer, run rather than argued: given every extension the
    silicon has, Zbb and Zbkb among them, the compiler that emits them above
    emits this blink unchanged. So the absence of Zbb from `blink.bin` is a
    property of the program, not of `-march=rv32imac` and not of the
    compiler."""
    with tempfile.TemporaryDirectory() as work:
        whole = build(pathlib.Path(work), HAZARD3)
    assert whole == IMAGE.read_bytes()


# --- the oracle: Hazard3's own model, on the image's instruction stream -----


def test_the_images_instruction_stream_runs_in_lockstep_with_rvcpp():
    """rvcpp is the oracle `core/riscv32` rests on (docs/architectures.md
    2.1b), and its testbench maps RAM at 0x80000000 and nothing at RESETS,
    IO_BANK0, PADS_BANK0 or SIO -- so the committed image's first store would
    fault there. The same source is built again with those four bases and
    the stack moved into the testbench's RAM, and that image is asserted to
    differ from `blink.bin` only in `lui` immediates: the same instructions,
    in the same order, at the same offsets. Then both models run it and agree
    on all 32 registers and the PC after every instruction.

    Skips where the compiler or the built oracle is absent. rvcpp has no
    extension gating, so agreement says this core runs the image as Hazard3's
    author's model does, and nothing about what the part refuses.
    """
    from tests.riscv32 import lockstep
    from core.riscv32 import abi, disasm

    if lockstep.executable() is None:
        pytest.skip(f"no rvcpp under {lockstep.ORACLE}")
    with tempfile.TemporaryDirectory() as work:
        moved = build(pathlib.Path(work), "-DRESETS_BASE=0x80004000u",
                      "-DIO_BANK0_BASE=0x80008000u", "-DPADS_BANK0_BASE=0x80009000u",
                      "-DSIO_BASE=0x8000a000u", "-DSTACK_TOP=0x80010000u")
        ours = disasm.disassemble(code_of(IMAGE.read_bytes()), rp2350.XIP)
        theirs = disasm.disassemble(code_of(moved), rp2350.XIP)
        assert [line.width for line in ours] == [line.width for line in theirs]
        changed = [(a.text, b.text) for a, b in zip(ours, theirs) if a.raw != b.raw]
        assert changed and all(
            a.split(",")[0] == b.split(",")[0] and a.startswith("lui")
            for a, b in changed), changed
        padding = bytes(lockstep.ENTRY_OFFSET)
        report = lockstep.run(padding + moved, pathlib.Path(work),
                              extensions=abi.RP2350_MODELLED, cycles=BUDGET)
    assert report.matched_the_oracle, (report.divergence, report.stopped)
    assert report.traced == BUDGET


# --- the board description --------------------------------------------------


def test_a_pad_reads_sio_only_once_funcsel_selects_it_and_its_latch_is_open():
    """The chain `pin_states` reads, link by link, on a real core: SIO
    driving GPIO5 high is `input` until FUNCSEL selects SIO, still `input`
    while the pad is isolated, `high` once it is not, `input` again under the
    pad's output disable, `unknown` under a function nothing here models (2,
    UART1 RX on GPIO5, `io_bank0.h:833`), and `input` with FUNCSEL back at
    NULL and the latch open -- the one reading where NULL alone decides,
    because the first is decided by the latch."""
    from core.riscv32 import abi

    gpio = rp2350.HEADER[LABEL]
    with abi.Cpu() as cpu:
        rp2350.install(cpu)
        cpu.write_word(rp2350.SIO + rp2350.SIO_GPIO_OE, 1 << gpio)
        cpu.write_word(rp2350.SIO + rp2350.SIO_GPIO_OUT, 1 << gpio)
        readings = [rp2350.pin_states(cpu)[LABEL]]
        cpu.write_word(rp2350.gpio_ctrl(gpio), rp2350.FUNCSEL_SIO)
        readings.append(rp2350.pin_states(cpu)[LABEL])
        cpu.write_word(rp2350.pad(gpio), rp2350.PAD_AT_RESET & ~rp2350.PAD_ISO)
        readings.append(rp2350.pin_states(cpu)[LABEL])
        cpu.write_word(rp2350.pad(gpio), rp2350.PAD_OD)
        readings.append(rp2350.pin_states(cpu)[LABEL])
        cpu.write_word(rp2350.pad(gpio), 0)
        cpu.write_word(rp2350.gpio_ctrl(gpio), 2)
        readings.append(rp2350.pin_states(cpu)[LABEL])
        cpu.write_word(rp2350.gpio_ctrl(gpio), rp2350.FUNCSEL_NULL)
        readings.append(rp2350.pin_states(cpu)[LABEL])
    assert readings == ["input", "input", "high", "input", "unknown", "input"], readings


def test_an_isolated_pad_reads_its_latch_whatever_function_is_selected():
    """ISO is the stage nearest the pad -- "all signals passing from the
    switched core power domain to the pads pass through isolation latches"
    (section 9.7, PDF p.545) -- and OD the next, "overriding the Output
    Enable signal from the function controlling the pad" (section 9.6, the
    same page). So under a peripheral this module does not model, an
    isolated pad still reads as the latch holds it from reset, `input`, and
    so does one whose output is disabled; with both open, the function
    decides, and that one is `unknown`."""
    from core.riscv32 import abi

    gpio = rp2350.HEADER[LABEL]
    with abi.Cpu() as cpu:
        rp2350.install(cpu)
        cpu.write_word(rp2350.SIO + rp2350.SIO_GPIO_OE, 1 << gpio)
        cpu.write_word(rp2350.SIO + rp2350.SIO_GPIO_OUT, 1 << gpio)
        cpu.write_word(rp2350.gpio_ctrl(gpio), 2)
        readings = []
        for control in (rp2350.PAD_AT_RESET, rp2350.PAD_OD, 0):
            cpu.write_word(rp2350.pad(gpio), control)
            readings.append(rp2350.pin_states(cpu)[LABEL])
    assert readings == ["input", "input", "unknown"], readings


def test_the_mailbox_to_core_1_is_there_and_core_1_is_not():
    """Core 1 does not exist, so the FIFO is a stub that faults nothing:
    room to send, nothing received, a write kept nowhere. CPUID is core
    0's."""
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        rp2350.install(cpu)
        sio = rp2350.SIO
        cpu.write_word(sio + rp2350.SIO_FIFO_WR, 0xC0FFEE)
        cpu.write_word(sio + rp2350.SIO_FIFO_RD, 0x5EED)
        assert cpu.read_word(sio + rp2350.SIO_FIFO_ST) == 0x2, "RDY set, VLD clear"
        assert cpu.read_word(sio + rp2350.SIO_FIFO_WR) == 0
        assert cpu.read_word(sio + rp2350.SIO_FIFO_RD) == 0
        assert cpu.read_word(sio + rp2350.SIO_CPUID) == 0


def test_what_this_board_cannot_compute_faults_rather_than_answering():
    """RESET_DONE is RESET's inverse and GPIO_IN the pins' levels; neither is
    a stored word, and `core/riscv32` can compute neither, so both fault and
    name the address."""
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        rp2350.install(cpu)
        for address in (rp2350.RESETS + rp2350.RESETS_RESET_DONE,
                        rp2350.SIO + rp2350.SIO_GPIO_IN):
            with pytest.raises(abi.MemoryFault) as caught:
                cpu.read_word(address)
            assert f"{address:08x}" in str(caught.value), caught.value


def test_the_board_configures_the_modelled_part_of_the_hazard3():
    """`abi.RP2350_MODELLED`: Zba and Zbs, which no ESP32 here has, and no
    Zbb, because the core has no bit for it -- see `rp2350.EXTENSIONS`."""
    from core.riscv32 import abi

    with abi.Cpu() as cpu:
        rp2350.install(cpu)
        assert cpu.extensions() == abi.RP2350_MODELLED
        assert cpu.extensions() & abi.EXT_ZBA and cpu.extensions() & abi.EXT_ZBS


def test_every_number_this_board_carries_is_the_one_in_pico_sdks_header():
    """Read back out of the headers `webui/boards/rp2350.py` cites, so a
    transcription error is a failure rather than a wrong emulator; and, at
    the pinned commit, each cited line is the line that defines it. Skips
    where the checkout is absent -- see the fetch in rp2350.py."""
    regs = pico_sdk()
    if regs is None:
        pytest.skip("no pico-sdk rp2350 headers; see webui/boards/rp2350.py")
    cited = (
        ("addressmap.h", 19, "REG_ALIAS_XOR_BITS", rp2350.ALIAS_XOR),
        ("addressmap.h", 20, "REG_ALIAS_SET_BITS", rp2350.ALIAS_SET),
        ("addressmap.h", 21, "REG_ALIAS_CLR_BITS", rp2350.ALIAS_CLR),
        ("addressmap.h", 24, "XIP_BASE", rp2350.XIP),
        ("addressmap.h", 34, "SRAM_BASE", rp2350.SRAM),
        ("addressmap.h", 42, "SRAM_END", rp2350.SRAM + rp2350.SRAM_SIZE),
        ("addressmap.h", 47, "RESETS_BASE", rp2350.RESETS),
        ("addressmap.h", 48, "IO_BANK0_BASE", rp2350.IO_BANK0),
        ("addressmap.h", 50, "PADS_BANK0_BASE", rp2350.PADS_BANK0),
        ("addressmap.h", 105, "SIO_BASE", rp2350.SIO),
        ("resets.h", 17, "RESETS_RESET_OFFSET", rp2350.RESETS_RESET),
        ("resets.h", 19, "RESETS_RESET_RESET", rp2350.RESETS_RESET_AT_RESET),
        ("resets.h", 156, "RESETS_RESET_PADS_BANK0_BITS", rp2350.RESET_PADS_BANK0),
        ("resets.h", 177, "RESETS_RESET_IO_BANK0_BITS", rp2350.RESET_IO_BANK0),
        ("resets.h", 433, "RESETS_RESET_DONE_OFFSET", rp2350.RESETS_RESET_DONE),
        ("io_bank0.h", 55, "IO_BANK0_GPIO0_CTRL_OFFSET", rp2350.IO_BANK0_GPIO_CTRL),
        ("io_bank0.h", 57, "IO_BANK0_GPIO0_CTRL_RESET", rp2350.GPIO_CTRL_AT_RESET),
        ("io_bank0.h", 137, "IO_BANK0_GPIO0_CTRL_FUNCSEL_BITS", rp2350.GPIO_CTRL_FUNCSEL),
        ("io_bank0.h", 146, "IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_SIO_0", rp2350.FUNCSEL_SIO),
        ("io_bank0.h", 152, "IO_BANK0_GPIO0_CTRL_FUNCSEL_VALUE_NULL", rp2350.FUNCSEL_NULL),
        ("io_bank0.h", 193, "IO_BANK0_GPIO1_CTRL_OFFSET",
         rp2350.IO_BANK0_GPIO_CTRL + rp2350.IO_BANK0_GPIO_STRIDE),
        ("pads_bank0.h", 30, "PADS_BANK0_GPIO0_OFFSET", rp2350.PADS_BANK0_GPIO),
        ("pads_bank0.h", 32, "PADS_BANK0_GPIO0_RESET", rp2350.PAD_AT_RESET),
        ("pads_bank0.h", 38, "PADS_BANK0_GPIO0_ISO_BITS", rp2350.PAD_ISO),
        ("pads_bank0.h", 47, "PADS_BANK0_GPIO0_OD_BITS", rp2350.PAD_OD),
        ("pads_bank0.h", 109, "PADS_BANK0_GPIO1_OFFSET",
         rp2350.PADS_BANK0_GPIO + rp2350.PADS_BANK0_STRIDE),
        ("sio.h", 23, "SIO_CPUID_OFFSET", rp2350.SIO_CPUID),
        ("sio.h", 35, "SIO_GPIO_IN_OFFSET", rp2350.SIO_GPIO_IN),
        ("sio.h", 113, "SIO_GPIO_OUT_OFFSET", rp2350.SIO_GPIO_OUT),
        ("sio.h", 188, "SIO_GPIO_OUT_SET_OFFSET", rp2350.SIO_GPIO_OUT_SET),
        ("sio.h", 249, "SIO_GPIO_OUT_CLR_OFFSET", rp2350.SIO_GPIO_OUT_CLR),
        ("sio.h", 310, "SIO_GPIO_OUT_XOR_OFFSET", rp2350.SIO_GPIO_OUT_XOR),
        ("sio.h", 380, "SIO_GPIO_OE_OFFSET", rp2350.SIO_GPIO_OE),
        ("sio.h", 456, "SIO_GPIO_OE_SET_OFFSET", rp2350.SIO_GPIO_OE_SET),
        ("sio.h", 517, "SIO_GPIO_OE_CLR_OFFSET", rp2350.SIO_GPIO_OE_CLR),
        ("sio.h", 578, "SIO_GPIO_OE_XOR_OFFSET", rp2350.SIO_GPIO_OE_XOR),
        ("sio.h", 645, "SIO_FIFO_ST_OFFSET", rp2350.SIO_FIFO_ST),
        ("sio.h", 647, "SIO_FIFO_ST_RESET", rp2350.SIO_FIFO_ST_AT_RESET),
        ("sio.h", 687, "SIO_FIFO_WR_OFFSET", rp2350.SIO_FIFO_WR),
        ("sio.h", 696, "SIO_FIFO_RD_OFFSET", rp2350.SIO_FIFO_RD),
    )
    pinned = subprocess.run(["git", "-C", str(regs), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    tables = {name: defines(regs / name) for name in {row[0] for row in cited}}
    for name, line, macro, expected in cited:
        number, text = tables[name][macro]
        assert value(text) == expected, f"{name}:{number} {macro} is {text}"
        if pinned == "98a542c1a62fb549ffb5d66a3e5892b06276b670":
            assert number == line, f"{macro} is at {name}:{number}, cited as :{line}"
    # The write-only registers read as zero because the header says "WO".
    for register in ("OUT_SET", "OUT_CLR", "OUT_XOR", "OE_SET", "OE_CLR", "OE_XOR"):
        assert value(tables["sio.h"][f"SIO_GPIO_{register}_ACCESS"][1]) == "WO"
    # And every GPIO the board maps sits where the stride says, at the reset
    # the board gives it, with SIO at function 5.
    io_bank0, pads = defines(regs / "io_bank0.h"), defines(regs / "pads_bank0.h")
    for gpio in range(rp2350.GPIOS):
        assert value(io_bank0[f"IO_BANK0_GPIO{gpio}_CTRL_OFFSET"][1]) == (
            rp2350.gpio_ctrl(gpio) - rp2350.IO_BANK0), gpio
        assert value(io_bank0[f"IO_BANK0_GPIO{gpio}_CTRL_RESET"][1]) == (
            rp2350.GPIO_CTRL_AT_RESET), gpio
        assert value(io_bank0[f"IO_BANK0_GPIO{gpio}_CTRL_FUNCSEL_VALUE_SIO_{gpio}"][1]) == (
            rp2350.FUNCSEL_SIO), gpio
        assert value(pads[f"PADS_BANK0_GPIO{gpio}_OFFSET"][1]) == (
            rp2350.pad(gpio) - rp2350.PADS_BANK0), gpio
        assert value(pads[f"PADS_BANK0_GPIO{gpio}_RESET"][1]) == rp2350.PAD_AT_RESET, gpio
