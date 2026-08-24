# OpenHardware - pick a board, put a compiled image on it, and step it.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What here is real and what is synthesised
#
# **The image is real.** `tests/cortexm0/blink/blink.bin` is 76 bytes of
# arm-none-eabi-gcc output from `blink.c`, committed, and
# `test_the_committed_binary_matches_its_source` in `tests/cortexm0/` rebuilds
# it wherever a compiler exists so it cannot drift. Every test below that
# executes anything executes those bytes, unmodified.
#
# **Three containers around it are synthesised, and each says so by name.**
# There is no PlatformIO installation and no ARM toolchain on this machine, so:
#
#   * `platformio_tree` builds the `.pio/build/<env>/` layout that
#     `tools/import_firmware.find_platformio` looks for, and puts the real
#     bytes in it as `firmware.bin`. The directory is invented; the artefact
#     inside it is not. Same trade `tests/rules/test_import_firmware.py`
#     makes, and for the same reason: a suite that needs a 5 MB build tree
#     present is a suite that stops running the day the tree is cleared.
#   * `elf_around` wraps those bytes in a hand-packed ELF32 header so the
#     self-identifying path can be exercised without a linker.
#   * `uf2_block` builds UF2 blocks so a wrong-family file can be handed to a
#     board that must refuse it.
#
# Nothing synthesises an instruction, a pin number or a memory map.
#
# ## Why so many of these are refusals
#
# Four joins have to hold and each fails differently: an unknown board, a core
# that is not built, a chip nothing describes, and an image that does not
# belong on the chip. The last is the one worth the most: an image rejected on
# its own addresses is a message, and the same image accepted and stepped is
# twenty thousand instructions of plausible nonsense ending in a fault
# somewhere unrelated.

import pathlib
import struct

import pytest

from webui import api, firmware, targets
from webui.boards import catalogue, rp2040

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The one board a real image has been watched on, and the image.
BOARD = "XIAO-RP2040-DIP"
BLINK = REPO / "tests" / "cortexm0" / "blink" / "blink.bin"

#: `blink.ld` links past boot2 rather than including it, so a raw .bin of it
#: loads here. The other RP2040 convention -- flash base, boot2 first -- is
#: what `test_the_boot2_convention_is_found_rather_than_assumed` covers.
BLINK_LOAD = 0x10000100

#: GP25 on the Pico footprint. The XIAO wires its LED elsewhere; this test is
#: about whether the instructions execute, not about where the light is.
LED = 1 << 25

#: Several toggles at the 453-instruction period `tests/cortexm0/test_blink.py`
#: measured, and still instant.
BUDGET = 20_000


def needs_core() -> None:
    """Skip loudly where cortexm0 is not built, rather than failing."""
    target = targets.find("cortexm0")
    if target is None or not target.selectable:
        pytest.skip("cortexm0 is not built; run python tools/build_core.py")
    if not BLINK.is_file():
        pytest.skip(f"{BLINK} is missing")


def blink_bytes() -> bytes:
    return BLINK.read_bytes()


def watch_led(session: api.BoardSession, budget: int = BUDGET) -> list[tuple[int, bool]]:
    """Step, recording every step at which the LED pin changes state."""
    out = rp2040.SIO + rp2040.SIO_GPIO_OUT
    transitions: list[tuple[int, bool]] = []
    last = 0
    for step in range(budget):
        session.step()
        now = session.cpu.read_word(out) & LED
        if now != last:
            transitions.append((step, bool(now)))
            last = now
    return transitions


# --- the synthesised containers -------------------------------------------

UF2_BLOCK = 512
UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID = 0x00002000
ESP32C3_FAMILY = 0xD42BA06C


def uf2_block(address: int, payload: bytes, family_id: int, block_no: int,
              num_blocks: int) -> bytes:
    """One 512-byte UF2 block. Header and trailer per the UF2 specification."""
    assert len(payload) <= 476, len(payload)
    head = struct.pack(
        "<8I", UF2_MAGIC_START0, UF2_MAGIC_START1, UF2_FLAG_FAMILY_ID, address,
        len(payload), block_no, num_blocks, family_id,
    )
    body = payload.ljust(476, b"\x00")
    return head + body + struct.pack("<I", UF2_MAGIC_END)


def elf_around(payload: bytes, paddr: int, entry: int) -> bytes:
    """A 32-bit little-endian ELF with one PT_LOAD carrying `payload`.

    Hand-packed rather than compiled, because this machine has no ARM
    toolchain. The header is real ELF32; the bytes it carries are the real
    blink. `parse_elf` reads `p_paddr`, `e_entry`, `e_phoff`, `e_phentsize`
    and `e_phnum`, and every one of those is filled in here.
    """
    ehsize, phentsize = 52, 32
    offset = ehsize + phentsize
    header = (
        b"\x7fELF" + bytes([1, 1, 1, 0, 0]) + b"\x00" * 7
        + struct.pack("<HHI", 2, 40, 1)          # ET_EXEC, EM_ARM, version
        + struct.pack("<III", entry, ehsize, 0)  # e_entry, e_phoff, e_shoff
        + struct.pack("<IHHHHHH", 0, ehsize, phentsize, 1, 0, 0, 0)
    )
    assert len(header) == ehsize, len(header)
    program = struct.pack(
        "<8I", 1, offset, paddr, paddr, len(payload), len(payload), 5, 4,
    )
    return header + program + payload


@pytest.fixture
def platformio_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """`.pio/build/pico/firmware.bin`, holding the real compiled blink.

    The layout is the one `tools/import_firmware.find_platformio` documents
    from a measured three-environment build. The directory is synthesised
    here; the artefact in it is the committed compiler output, byte for byte.
    """
    build = tmp_path / ".pio" / "build" / "pico"
    build.mkdir(parents=True)
    (build / "firmware.bin").write_bytes(blink_bytes())
    # A .map sits beside a real firmware.bin and must not be mistaken for one.
    (build / "firmware.map").write_text("this is a link map, not an image\n")
    (tmp_path / "platformio.ini").write_text("[env:pico]\nboard = pico\n")
    return tmp_path


# --- resolving a board to what would run it -------------------------------


def test_every_board_the_catalogue_calls_runnable_resolves():
    """And every board it does not call runnable is refused, with a reason.

    Asserted as an invariant over the whole catalogue rather than against a
    list of board names, because cores land while this suite is being written:
    riscv32 became built between one run and the next, which moved seven
    boards from one refusal to the other.
    """
    for board in catalogue.catalogue():
        if board.runnable:
            runtime = api.runtime_for(board.name)
            assert runtime.chip == board.chip
            assert runtime.core == board.core
            assert hasattr(runtime.description, "install")
            assert hasattr(runtime.abi, "Cpu")
        else:
            with pytest.raises(api.BoardRunError) as caught:
                api.runtime_for(board.name)
            assert board.name in str(caught.value)
            assert board.chip in str(caught.value)


def test_a_core_that_is_not_built_is_named_before_anything_else():
    """The core decides: a memory map for a chip nothing executes buys nothing."""
    unbuilt = [b for b in catalogue.catalogue() if not b.core_built]
    if not unbuilt:
        pytest.skip("every core is built on this machine")
    for board in unbuilt:
        with pytest.raises(api.BoardRunError) as caught:
            api.runtime_for(board.name)
        assert board.core in str(caught.value), board.name


def test_a_chip_nothing_describes_is_refused_even_with_a_built_core():
    """The second join. A built core with no memory map has nowhere to load."""
    undescribed = [
        b for b in catalogue.catalogue() if b.core_built and not b.described
    ]
    if not undescribed:
        pytest.skip("every board with a built core is described")
    for board in undescribed:
        with pytest.raises(api.BoardRunError) as caught:
            api.runtime_for(board.name)
        assert "describes" in str(caught.value), board.name
        assert board.chip in str(caught.value)


def test_an_unknown_board_says_what_there_is():
    with pytest.raises(api.BoardRunError) as caught:
        api.runtime_for("Raspberry Pi Pico")
    assert "Raspberry Pi Pico" in str(caught.value)
    assert "XIAO" in str(caught.value)


def test_a_chip_name_maps_to_its_description_module():
    assert api.description_module("RP2040") == "webui.boards.rp2040"
    assert api.description_module("ESP32-C3") == "webui.boards.esp32c3"
    # The inverse of catalogue's own rule, so the two cannot drift apart.
    for chip in catalogue.described_chips():
        module = api.description_module(chip)
        stem = module.rsplit(".", 1)[1]
        assert stem.upper().replace("-", "") == chip


# --- a real image on a real board -----------------------------------------


def test_a_compiled_image_loads_onto_the_board_it_was_built_for():
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        report = session.as_json()
    assert report["board"] == BOARD
    assert report["chip"] == "RP2040"
    assert report["core"] == "cortexm0"
    assert report["format"] == "bin"
    assert report["bytes"] == BLINK.stat().st_size
    assert report["vector_table"] == BLINK_LOAD
    assert report["stack_pointer"] == 0x20042000, "top of the RP2040's 264 KB"
    assert report["entry"] & 1 == 0, "the Thumb bit is stripped before it is a PC"
    assert report["segments"] == [{"address": BLINK_LOAD, "bytes": 76}]


def test_the_loaded_image_executes_and_the_led_changes_state():
    """The headline. A board name and a compiled artefact went in; the pin moves.

    Two transitions is a blink. One is a pin that came on and stayed on, which
    is what a broken toggle looks like from the outside.
    """
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        transitions = watch_led(session)
    assert len(transitions) >= 2, f"the pin changed state {len(transitions)} times"
    states = [state for _, state in transitions]
    assert states[0] is True
    assert all(a != b for a, b in zip(states, states[1:])), states[:8]


def test_the_pin_is_configured_as_an_output_and_the_period_is_steady():
    """A toggle on a pin still set to input is a lie the value register alone
    cannot catch, and a wandering period means the delay loop is wrong."""
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        steps = [step for step, _ in watch_led(session)]
        assert session.cpu.read_word(rp2040.SIO + rp2040.SIO_GPIO_OE) & LED
    periods = {b - a for a, b in zip(steps[1:], steps[2:])}
    assert len(periods) == 1, f"period varies: {sorted(periods)}"


def test_the_board_left_reset_before_it_reached_its_loop():
    """The program spins on RESET_DONE until IO_BANK0 and PADS_BANK0 are out
    of reset. Their bits being clear is the evidence that loop terminated,
    which is evidence the board description and not just the core was used."""
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        watch_led(session, budget=200)
        reset = session.cpu.read_word(rp2040.RESETS + rp2040.RESETS_RESET)
    assert reset & (1 << 5) == 0, "IO_BANK0 still held in reset"
    assert reset & (1 << 8) == 0, "PADS_BANK0 still held in reset"


def test_a_platformio_artefact_is_discovered_and_then_executes(platformio_tree):
    """The join OH-10 left open: discovery hands bytes, this puts them on a board.

    The tree is synthesised (see the module header); the bytes in it are the
    committed compiler output. `find_platformio` is called rather than
    reimplemented, and `firmware.map` sitting beside the image is there to
    check discovery does not hand a link map to a firmware parser.
    """
    needs_core()
    from tools import import_firmware

    artefacts = import_firmware.find_platformio(platformio_tree)
    names = {artefact.path.name for artefact in artefacts}
    assert "firmware.bin" in names
    assert "firmware.map" not in names, "a link map is not an image"

    binary = next(a for a in artefacts if a.path.name == "firmware.bin")
    assert binary.path.read_bytes() == blink_bytes(), "discovery altered nothing"

    with api.load_firmware(BOARD, binary.path.read_bytes(), base=BLINK_LOAD) as session:
        transitions = watch_led(session)
    assert len(transitions) >= 2


def test_a_self_identifying_image_needs_no_base():
    """A raw .bin needs `base`; an ELF carries its own addresses.

    Also pins the note `as_json` adds when the declared entry point and the
    reset vector disagree -- allowed, but the reader has to be told which one
    the core took.
    """
    needs_core()
    payload = blink_bytes()
    declared_entry = struct.unpack_from("<I", payload, 4)[0]
    elf = elf_around(payload, paddr=BLINK_LOAD, entry=declared_entry)

    with api.load_firmware(BOARD, elf) as session:
        report = session.as_json()
        transitions = watch_led(session)
    assert report["format"] == "elf"
    assert report["vector_table"] == BLINK_LOAD
    assert report["entry"] == declared_entry & ~1
    assert not [note for note in report["notes"] if "entered at" in note]
    assert len(transitions) >= 2

    # The same ELF with a disagreeing e_entry: still runs, and says so.
    odd = elf_around(payload, paddr=BLINK_LOAD, entry=BLINK_LOAD | 1)
    with api.load_firmware(BOARD, odd) as session:
        notes = session.as_json()["notes"]
    assert any("entered at" in note for note in notes), notes


# --- images that do not belong on this board ------------------------------

#: The first word of a real RP2040 boot2 stage, quoted in
#: `firmware.read_vector_table`'s docstring as the value it once returned and
#: called a stack pointer. Used here as filler that must be *rejected* as one.
BOOT2_FIRST_WORD = 0x4B32B500


def boot2_filler() -> bytes:
    """256 bytes standing in for boot2. Never executed; only skipped over."""
    return struct.pack("<I", BOOT2_FIRST_WORD) * (api.RP2040_BOOT2_BYTES // 4)


def test_an_image_for_another_chip_is_refused_on_its_addresses():
    """0x42000020 is where an ESP32-C3 application image loads. An RP2040 maps
    nothing there, and the board's own map is what says so."""
    needs_core()
    with pytest.raises(api.BoardRunError) as caught:
        api.load_firmware(BOARD, blink_bytes(), base=0x42000020)
    message = str(caught.value)
    assert "0x42000020" in message
    assert "RP2040" in message
    assert "maps nothing" in message


def test_a_uf2_for_another_family_is_refused_rather_than_loaded_empty():
    """`parse_uf2` disregards every block of a family it was not asked for --
    correct per the specification, and it leaves an Image with no segments and
    no exception. Loading nothing and reporting success is the failure this
    ticket exists to stop, so the empty result is caught here."""
    needs_core()
    wrong = uf2_block(0x42000020, blink_bytes(), ESP32C3_FAMILY, 0, 1)
    assert firmware.parse_uf2(wrong, family="RP2040").segments == ()

    with pytest.raises(api.BoardRunError) as caught:
        api.load_firmware(BOARD, wrong)
    message = str(caught.value)
    assert "holds nothing for a RP2040" in message
    assert "ESP32C3" in message, "say what the file did hold"


def test_the_boot2_convention_is_found_rather_than_assumed():
    """A flash-base RP2040 image puts 256 bytes of boot2 before the vector
    table. Both candidates are tried and checked; the first is rejected
    because 0x4b32b500 is not an address this board maps."""
    needs_core()
    data = boot2_filler() + blink_bytes()
    with api.load_firmware(BOARD, data, base=rp2040.FLASH) as session:
        report = session.as_json()
        transitions = watch_led(session)
    assert report["vector_table"] == rp2040.FLASH + api.RP2040_BOOT2_BYTES
    assert report["stack_pointer"] == 0x20042000
    assert len(transitions) >= 2, "the image past boot2 still runs"


def test_an_image_with_no_vector_table_is_refused_with_what_was_tried():
    needs_core()
    with pytest.raises(api.BoardRunError) as caught:
        api.load_firmware(BOARD, b"\x00" * 64, base=rp2040.FLASH)
    message = str(caught.value)
    assert "0x10000000" in message, "the first candidate"
    assert "0x10000100" in message, "and the second"
    assert "vector_table=" in message, "and how to override the search"


def test_a_vector_table_can_be_named_when_neither_convention_fits():
    needs_core()
    padding = 128
    data = b"\x00" * padding + blink_bytes()
    with pytest.raises(api.BoardRunError):
        api.load_firmware(BOARD, data, base=rp2040.FLASH)

    with api.load_firmware(
        BOARD, data, base=rp2040.FLASH, vector_table=rp2040.FLASH + padding
    ) as session:
        report = session.as_json()
    assert report["vector_table"] == rp2040.FLASH + padding
    assert report["stack_pointer"] == 0x20042000


def test_a_named_vector_table_is_still_checked():
    """The override says where to look, not what to believe."""
    needs_core()
    with pytest.raises(api.BoardRunError) as caught:
        api.load_firmware(
            BOARD, blink_bytes(), base=BLINK_LOAD, vector_table=BLINK_LOAD + 32
        )
    assert f"0x{BLINK_LOAD + 32:08x}" in str(caught.value)


def test_a_raw_bin_with_no_base_is_refused_by_the_format_layer():
    """`load_firmware` invents no base of its own: 0x10000000 is right for a
    pico-sdk image and wrong for the bare-metal one this suite runs."""
    needs_core()
    with pytest.raises(firmware.FirmwareError) as caught:
        api.load_firmware(BOARD, blink_bytes())
    assert "base=" in str(caught.value)


def test_a_refusal_leaves_the_next_load_working():
    """Every refusal after the core is constructed has to release it. A leak
    would show up as a machine that runs a handful of images and then stops."""
    needs_core()
    for _ in range(8):
        with pytest.raises(api.BoardRunError):
            api.load_firmware(BOARD, blink_bytes(), base=0x42000020)
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        assert len(watch_led(session)) >= 2
