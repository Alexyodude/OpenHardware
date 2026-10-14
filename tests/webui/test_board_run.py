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
# **Four things around it are synthesised, and each says so by name.** There is
# no PlatformIO installation and no ARM toolchain on this machine, so:
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
#   * `only_undescribed` builds a one-board catalogue whose core is built and
#     whose chip nothing describes. Unlike the three above, this one is not a
#     stand-in for something absent from the machine -- it stands in for
#     something absent from the *repository*, and deliberately so. See
#     `UNDESCRIBED`.
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


#: The board name the synthesised catalogue below contains.
#:
#: **A real name in a fake catalogue**, which is the arrangement two tests here
#: need: `chip-not-described` requires a board that is core-built and
#: *undescribed*, and after OH-57 the real catalogue holds none.
#:
#: It held one every time anyone looked, and never the same one for long. The
#: SAMD21 was the example until `webui/boards/samd21.py` landed under OH-39
#: (`bdcc8c9`); the ESP32-C3 took over until OH-48 (`3ccfe87`); the ESP32-C6
#: took over until this ticket. Each replacement was a test that kept working
#: right up until somebody did the obvious next piece of work, and then either
#: failed or -- worse, and this is what happened to
#: `test_a_chip_nothing_describes_is_refused_even_with_a_built_core` --
#: skipped, announcing that it had nothing left to check.
#:
#: There is no fifth name to move to: every remaining chip needs a core that is
#: not built, so they answer `core-not-built` instead. So the case is built
#: rather than found, which is what `test_a_built_core_without_a_board_
#: description_is_not_runnable` has done since the SAMD21 evaporated.
#:
#: This one keeps the ESP32-C6's name because that is what it displaced, and
#: because the name is now arbitrary: nothing about the chip matters, only that
#: `riscv32` is built.
UNDESCRIBED = "XIAO-ESP32-C6-DIP"


def only_undescribed(monkeypatch, tmp_path) -> None:
    """Replace the catalogue with one board: `UNDESCRIBED`, and no description.

    `catalogue.catalogue(directory)` reads board JSON **and** board
    descriptions out of the directory it is given, so a `tmp_path` holding one
    `.json` and no `.py` is a catalogue whose single board has a built core and
    nothing describing it -- the case that no longer occurs naturally.

    Patched on the `catalogue` module rather than on `api`, because `api.py`
    does `from webui.boards import catalogue` and then `catalogue.catalogue()`
    -- so both names are the one module object, and the live server's thread
    reads the patched attribute at request time rather than a copy taken at
    import.
    """
    (tmp_path / f"{UNDESCRIBED}.json").write_text("{}", encoding="utf-8")
    real = catalogue.catalogue
    monkeypatch.setattr(catalogue, "catalogue", lambda directory=None: real(tmp_path))


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


def test_a_chip_nothing_describes_is_refused_even_with_a_built_core(
    monkeypatch, tmp_path
):
    """The second join. A built core with no memory map has nowhere to load.

    **This searched the real catalogue for an example until OH-57**, with a
    `pytest.skip("every board with a built core is described")` for the day
    there was none. That day arrived when `webui/boards/esp32c6.py` and
    `esp32c5.py` landed, and the test went from checking a rule to announcing
    that it had nothing to check -- which is better than passing vacuously and
    is still not a test.

    So it builds the case rather than finding one. See `UNDESCRIBED`.

    `runtime_for` asks about the core first and the description second, and
    reaching this refusal at all is what proves the two joins are separate
    rather than collapsed into one "cannot run this": the synthetic board's
    core *is* built.
    """
    needs_core()
    only_undescribed(monkeypatch, tmp_path)

    board, = catalogue.catalogue()
    assert board.core_built and not board.described, "the case being built"

    with pytest.raises(api.BoardRunError) as caught:
        api.runtime_for(board.name)
    assert caught.value.reason == "chip-not-described"
    assert "no module describes" in str(caught.value)
    assert board.chip in str(caught.value)


def test_an_unknown_board_says_what_there_is():
    with pytest.raises(api.BoardRunError) as caught:
        api.runtime_for("Raspberry Pi Pico")
    assert "Raspberry Pi Pico" in str(caught.value)
    # The refusal names boards that exist. Which ones is sort order, and a
    # non-XIAO board sorting first (OH-177) is not a regression.
    assert sorted(catalogue.board_names())[0] in str(caught.value)


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
    return struct.pack("<I", BOOT2_FIRST_WORD) * (rp2040.BOOT2_BYTES // 4)


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
    correct per the specification, and it used to leave an Image with no
    segments and no exception. Loading nothing and reporting success is the
    failure this ticket exists to stop.

    **This asserted the empty result until OH-10 fixed the parser.** It read

        assert firmware.parse_uf2(wrong, family="RP2040").segments == ()

    which pinned the defect in place: a test can hold a workaround steady just
    as well as it holds a fix, and the seam catching it here meant every
    *other* caller of `firmware.load_image` still had the bug. The parser
    raises now, and what this checks is that the refusal still arrives as
    itself rather than as a broken-file error.
    """
    needs_core()
    wrong = uf2_block(0x42000020, blink_bytes(), ESP32C3_FAMILY, 0, 1)

    # The library half: a specific type, so a caller can tell "not for you"
    # from "unreadable" without reading the message.
    with pytest.raises(firmware.EmptyImage) as parsed:
        firmware.parse_uf2(wrong, family="RP2040")
    assert "RP2040" in str(parsed.value), "name what was asked for"
    assert "ESP32C3" in str(parsed.value), "and what the file did hold"

    # The board half: the chip, which the parser has no way to know.
    with pytest.raises(api.BoardRunError) as caught:
        api.load_firmware(BOARD, wrong)
    assert caught.value.reason == "nothing-for-this-chip", (
        "an artefact built for another chip is not an unreadable one, and the "
        "two send a person to different places"
    )
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
    # `rp2040.BOOT2_BYTES` and not `api.RP2040_BOOT2_BYTES`: api.py no longer
    # keeps a copy of where an RP2040 puts its vector table, because that is a
    # fact about the chip. See webui/boards/contract.py.
    assert report["vector_table"] == rp2040.FLASH + rp2040.BOOT2_BYTES
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


# --- running, stopping, and looking ---------------------------------------


def test_a_run_reports_where_it_got_to():
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        result = session.run(5000)
    assert result.steps == 5000
    assert result.status == "running", "a blink loops forever, so it never ends"
    assert result.detail == ""


def test_a_fault_is_reported_rather_than_raised():
    """A program running off into memory that is not there is a fact about
    that program. The core's message names the access, the address and the
    instruction, and losing it to a traceback in a request handler would be a
    waste of the most useful sentence anyone gets all day."""
    needs_core()
    cases = (
        # A reset vector into the boot ROM stub, which is mapped and
        # deliberately not executable -- see webui/boards/rp2040.py.
        (0x00000001, "not executable"),
        # And one that lands in erased flash, where 0xFFFF is not an encoding.
        (BLINK_LOAD + 0x700 + 1, "no implementation"),
    )
    for reset, expected in cases:
        image = struct.pack("<II", 0x20042000, reset)
        with api.load_firmware(BOARD, image, base=BLINK_LOAD) as session:
            result = session.run(50)
        assert result.status == "stopped", reset
        assert expected in result.detail, result.detail
        assert "0x" in result.detail, "the address that caused it"


def test_a_stopped_board_stays_stopped():
    needs_core()
    image = struct.pack("<II", 0x20042000, 0x00000001)
    with api.load_firmware(BOARD, image, base=BLINK_LOAD) as session:
        first = session.run(50)
        again = session.run(50)
    assert first.status == "stopped"
    assert again == api.RunResult(0, "stopped", first.detail)


def test_a_run_budget_has_to_be_usable():
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        for budget in (0, -1, api.MAX_RUN_STEPS + 1):
            with pytest.raises(api.BoardRunError) as caught:
                session.run(budget)
            assert caught.value.reason == "budget-refused"
            assert str(budget) in str(caught.value)


def test_state_shows_the_registers_and_a_window_of_memory():
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        at_reset = session.state()
        session.run(5000)
        later = session.state()
    # Registers arrive named rather than positional, because an AVR has
    # thirty-two eight-bit ones and no sixteen-name Arm table can render them.
    # Looked up by name here rather than by index for the same reason.
    by_name = {r["name"]: r for r in at_reset["registers"]}
    assert by_name["sp"]["value"] == 0x20042000, "SP"
    assert by_name["pc"]["value"] == BLINK_LOAD + 8, "PC at the reset handler"
    assert by_name["r0"]["width"] == 32, "an Armv6-M register is a word"
    assert at_reset["pc"] == by_name["pc"]["value"], (
        "the explicit field agrees with the register, so no caller has to "
        "mean 'index 15'"
    )
    assert at_reset["memory"]["at"] == BLINK_LOAD, "the vector table by default"
    assert bytes(at_reset["memory"]["bytes"][:4]) == struct.pack("<I", 0x20042000)
    assert later["pc"] != at_reset["pc"], "it moved"
    assert later["status"] == "running"


def test_a_memory_window_off_the_board_is_refused_by_name():
    """Asking about an address is not the same as executing one, so this is a
    named refusal rather than a fault."""
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        with pytest.raises(api.BoardRunError) as caught:
            session.state(memory_at=0x42000020)
        assert caught.value.reason == "window-outside-the-map"
        assert "0x42000020" in str(caught.value)

        for length in (0, api.MAX_WINDOW_BYTES + 1):
            with pytest.raises(api.BoardRunError) as caught:
                session.state(memory_length=length)
            assert caught.value.reason == "window-refused"


def test_every_refusal_has_a_reason_and_every_reason_is_documented():
    """A refusal that reached a caller with an unlisted slug would be one the
    transport had no status for."""
    seen = set()
    for board in catalogue.catalogue():
        if board.runnable:
            continue
        with pytest.raises(api.BoardRunError) as caught:
            api.runtime_for(board.name)
        seen.add(caught.value.reason)
    assert seen <= set(api.REASONS), seen - set(api.REASONS)
    # `chip-not-described` is asserted by
    # `test_a_chip_nothing_describes_is_refused_even_with_a_built_core`
    # instead: no board in the real catalogue can produce it any more, so
    # that one synthesises the case. See `UNDESCRIBED`.
    assert "core-not-built" in seen

    with pytest.raises(ValueError, match="unknown refusal reason"):
        api.BoardRunError("made-up", "message")



# --- over HTTP, on a real loopback socket ---------------------------------
#
# `webui/emulator.py`'s suite says why there is so little here: the behaviour
# and every refusal are tested above, against the session. What is worth
# testing at the boundary is only what exists at the boundary -- the Origin
# check on an upload, the body ceiling, and that each of the nine refusals
# arrives as itself with its own status rather than as one flat 400.

import base64
import http.client
import json
import threading
import urllib.error
import urllib.request

from webui import emulator_server


@pytest.fixture
def live_server():
    """A real server on a real loopback port, stopped afterwards."""
    needs_core()
    try:
        server = emulator_server.build_server("127.0.0.1", 0)
    except Exception as error:  # pragma: no cover - environment, not logic
        pytest.skip(f"cannot start the server: {error}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(base_url: str, path: str, body: dict, origin: str | None = None):
    request = urllib.request.Request(
        base_url + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    if origin is not None:
        request.add_header("Origin", origin)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def get(base_url: str, path: str):
    with urllib.request.urlopen(base_url + path, timeout=10) as response:
        return json.loads(response.read())


def upload(image: bytes = None, **extra) -> dict:
    body = {"image": base64.b64encode(blink_bytes() if image is None else image).decode()}
    body.update(extra)
    return body


def test_a_board_and_an_image_load_over_http(live_server):
    """The headline through the transport the page will use."""
    report = post(live_server, "/api/board/load",
                  upload(board=BOARD, base=hex(BLINK_LOAD)))
    assert report["board"] == BOARD
    assert report["chip"] == "RP2040"
    assert report["vector_table"] == BLINK_LOAD
    assert report["stack_pointer"] == 0x20042000
    assert report["bytes"] == BLINK.stat().st_size


def test_a_loaded_board_runs_and_can_be_looked_at_over_http(live_server):
    post(live_server, "/api/board/load", upload(board=BOARD, base=BLINK_LOAD))
    out = rp2040.SIO + rp2040.SIO_GPIO_OUT
    oe = rp2040.SIO + rp2040.SIO_GPIO_OE

    before = get(live_server, "/api/board/state")
    result = post(live_server, "/api/board/run", {"steps": 5000})
    after = get(live_server, f"/api/board/state?words={hex(out)},{hex(oe)}")

    assert result == {"steps": 5000, "status": "running", "detail": ""}
    assert before["pc"] == BLINK_LOAD + 8
    assert after["pc"] != before["pc"]
    # The whole point, read back through the transport: the pin is an output
    # and the blink has driven it.
    assert [w["address"] for w in after["words"]] == [out, oe]
    assert after["words"][1]["value"] & LED, "GP25 is an output"
    assert after["memory"]["at"] == BLINK_LOAD, "the window still defaults to the image"


def test_a_peripheral_address_is_not_a_memory_window(live_server):
    """`in_range` is false for a mapped register by design and `read_block`
    refuses one, so a window over SIO would fault. The refusal says so and
    names the argument that does work."""
    post(live_server, "/api/board/load", upload(board=BOARD, base=BLINK_LOAD))
    with pytest.raises(urllib.error.HTTPError) as caught:
        get(live_server, f"/api/board/state?at={hex(rp2040.SIO + rp2040.SIO_GPIO_OUT)}")
    answer = json.loads(caught.value.read())
    assert answer["reason"] == "window-outside-the-map"
    assert "words=" in answer["error"]


def test_an_upload_from_another_origin_is_refused(live_server):
    """This is the route that takes a file, so it is the one that matters. A
    page you happen to be visiting can POST to loopback; the Origin check is
    what stops it driving the board."""
    with pytest.raises(urllib.error.HTTPError) as caught:
        post(live_server, "/api/board/load",
             upload(board=BOARD, base=BLINK_LOAD), origin="http://evil.example")
    assert caught.value.code == 403

    # And nothing was loaded by the attempt.
    with pytest.raises(urllib.error.HTTPError) as refused:
        get(live_server, "/api/board/state")
    assert json.loads(refused.value.read())["error"].startswith("no board is loaded")

    # The server's own origin is still accepted, so the check is not simply off.
    assert post(live_server, "/api/board/load",
                upload(board=BOARD, base=BLINK_LOAD),
                origin=live_server)["board"] == BOARD


def test_each_refusal_arrives_as_itself(live_server):
    """The part worth having. One flat 400 would tell someone to fix their
    firmware when what they need is `python tools/build_core.py`."""
    wrong_family = uf2_block(0x42000020, blink_bytes(), ESP32C3_FAMILY, 0, 1)
    cases = (
        (upload(board="Raspberry Pi Pico", base=BLINK_LOAD), 404, "unknown-board"),
        (upload(board="XIAO-MG24-DIP", base=BLINK_LOAD), 409, "core-not-built"),
        # **`chip-not-described` is not in this list, and cannot be.** It used
        # to be the ESP32-C3, then the ESP32-C6, and each replacement lasted
        # until somebody described that chip. OH-57 described the last two, so
        # no board in the real catalogue is core-built-and-undescribed --
        # every remaining chip needs a core that is not built and answers
        # `core-not-built` instead. It is asserted over the transport in
        # `test_the_chip_not_described_refusal_arrives_as_itself`, against a
        # board synthesised for the purpose rather than a fourth board name.
        (upload(board=BOARD, base=0x42000020), 400, "outside-the-board-map"),
        (upload(b"\x00" * 64, board=BOARD, base=0x10000000), 400, "no-vector-table"),
        (upload(wrong_family, board=BOARD), 400, "nothing-for-this-chip"),
        (upload(board=BOARD), 400, "unreadable-artefact"),
    )
    for body, status, reason in cases:
        with pytest.raises(urllib.error.HTTPError) as caught:
            post(live_server, "/api/board/load", body)
        answer = json.loads(caught.value.read())
        assert caught.value.code == status, (reason, answer)
        assert answer["reason"] == reason, answer
        assert answer["error"], "and the message that carries the values"


def test_the_chip_not_described_refusal_arrives_as_itself(
    live_server, monkeypatch, tmp_path
):
    """The refusal that left `test_each_refusal_arrives_as_itself`, still
    checked at the transport where its 409 lives.

    Separate rather than inlined there, because it needs the catalogue replaced
    and every other case in that list needs the real one.
    """
    only_undescribed(monkeypatch, tmp_path)
    with pytest.raises(urllib.error.HTTPError) as caught:
        post(live_server, "/api/board/load", upload(board=UNDESCRIBED, base=BLINK_LOAD))
    answer = json.loads(caught.value.read())
    assert caught.value.code == 409, answer
    assert answer["reason"] == "chip-not-described", answer
    assert answer["error"], "and the message that carries the values"


def test_every_reason_the_api_can_raise_has_a_status():
    """A refusal with no entry here would arrive as a bare 400 and lose the
    distinction the mapping exists to keep."""
    assert set(api.REASONS) == set(emulator_server.BOARD_ERROR_STATUS)


def test_an_oversized_body_is_refused_from_its_header(live_server):
    """Judged from Content-Length before a byte is allocated. Reading a
    declared length and then deciding it was too big is the failure mode this
    avoids, and this is the one route anybody uploads a file to."""
    host, port = live_server.removeprefix("http://").split(":")
    connection = http.client.HTTPConnection(host, int(port), timeout=10)
    connection.putrequest("POST", "/api/board/load")
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", str(emulator_server.MAX_BODY_BYTES + 1))
    connection.endheaders()
    connection.send(b"{}")          # far less than declared, and never read
    response = connection.getresponse()
    body = json.loads(response.read())
    connection.close()
    assert response.status == 413
    assert str(emulator_server.MAX_BODY_BYTES) in body["error"]


def test_an_upload_that_is_not_base64_is_refused(live_server):
    """`validate=True`, so rubbish is refused here rather than quietly
    discarded and handed to a firmware parser as a short file."""
    for image in ("not base64 at all!!", "", 17):
        with pytest.raises(urllib.error.HTTPError) as caught:
            post(live_server, "/api/board/load", {"board": BOARD, "image": image})
        assert caught.value.code == 400
        assert "image" in json.loads(caught.value.read())["error"]


def test_an_image_larger_than_any_board_is_refused(live_server):
    oversized = b"\x00" * (emulator_server.MAX_IMAGE_BYTES + 1)
    with pytest.raises(urllib.error.HTTPError) as caught:
        post(live_server, "/api/board/load", upload(oversized, board=BOARD))
    assert caught.value.code == 400
    assert str(emulator_server.MAX_IMAGE_BYTES) in json.loads(caught.value.read())["error"]


def test_running_or_looking_before_loading_says_what_to_do_first(live_server):
    with pytest.raises(urllib.error.HTTPError) as caught:
        post(live_server, "/api/board/run", {"steps": 10})
    assert caught.value.code == 400
    assert "POST /api/board/load" in json.loads(caught.value.read())["error"]

    with pytest.raises(urllib.error.HTTPError) as caught:
        get(live_server, "/api/board/state")
    assert caught.value.code == 400
    assert "POST /api/board/load" in json.loads(caught.value.read())["error"]


def test_a_second_load_releases_the_first_core():
    """A BoardSession owns a native allocation, and loading a second image is
    the most ordinary thing a person does here. Tested against the contract --
    `replace` calls `close` -- rather than by reaching into ctypes."""
    class Closes:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    slot = emulator_server.BoardSlot()
    first, second = Closes(), Closes()
    slot.replace(first)
    slot.replace(second)
    assert first.closed, "the displaced session was not released"
    assert not second.closed
    assert slot.session is second


def test_the_board_routes_refuse_a_caller_with_no_slot():
    """`handle_api` keeps `boards` optional so the i8086 callers that predate
    it still work. A board route reached that way refuses rather than making
    a slot nobody could step twice."""
    with pytest.raises(emulator_server.ApiError, match="needs a board slot"):
        emulator_server.handle_api(
            None, "/api/board/run", {}, {}
        )


# --- what the board printed -------------------------------------------------
#
# `uart/hello.bin` is the second committed arm-none-eabi-gcc image in the
# repository, and it is the one that makes the headline sentence sayable: a
# person loads firmware and reads what it printed. Everything below runs those
# bytes unmodified.

#: The UART image and where `hello.ld` links it. Same convention as blink.
HELLO = REPO / "tests" / "cortexm0" / "uart" / "hello.bin"
HELLO_LOAD = 0x10000100

#: A SAMD21 board and its own image. Used for the no-UART case, because a
#: board that models no UART is a real state -- **16 of the 26**, measured
#: through `api.description_for` over `catalogue.board_names()` on
#: 2026-09-04 -- and asserting it against a synthesised module would prove
#: nothing.
#:
#: The number moved and was wrong before it moved: this said 25 when the Uno
#: and the two XIAO RP2040s already reported one, so the figure was 23, and
#: OH-161 took it to 16 by giving the seven ESP32-C3, C5 and C6 entries a
#: transmit FIFO. A SAMD21 is still the right board for this test, which is
#: why the number is the only thing that changed.
QUIET_BOARD = "XIAO-SAMD21-DIP"
QUIET_IMAGE = REPO / "tests" / "cortexm0" / "samd21" / "blink.bin"

#: Long enough for hello.bin to reach the end of its string. Measured, not
#: guessed: the run below asserts the whole thing arrived.
PRINT_BUDGET = 200_000


def needs_uart_image() -> None:
    needs_core()
    if not HELLO.is_file():
        pytest.skip(f"{HELLO} is missing")


def printed(session: api.BoardSession) -> dict:
    return session.state()["uart"]


def test_a_board_that_printed_reports_what_it_printed():
    """The headline, at the seam: real image in, the text it wrote out.

    Through `state()` rather than by calling `rp2040.uart0_output` directly,
    because the browser has no other way to reach it and the point of this
    ticket is that the wire carries it.
    """
    needs_uart_image()
    with api.load_firmware(BOARD, HELLO.read_bytes(), base=HELLO_LOAD) as session:
        assert printed(session)["text"] == "", "something was transmitted before a step"
        session.run(PRINT_BUDGET)
        view = printed(session)

    assert view["present"] is True
    assert view["text"] == "hello, world\n"
    assert view["bytes"] == 13
    assert view["undecodable_bytes"] == 0
    assert view["dropped_bytes"] == 0


def test_the_uart_view_is_cumulative_so_a_console_must_replace_not_append():
    """Two polls with no run between them return the same text.

    This is the decision the wire shape records, asserted rather than
    described. A delta would make a GET answer differently on two identical
    calls, and with two tabs polling each would consume bytes the other never
    saw. The cost is that a console appending would print every line twice,
    which is why the docstring and this test both say `replaces`.
    """
    needs_uart_image()
    with api.load_firmware(BOARD, HELLO.read_bytes(), base=HELLO_LOAD) as session:
        session.run(PRINT_BUDGET)
        first = printed(session)
        second = printed(session)
        assert first == second, "a second poll returned something different"

        session.run(1000)
        third = printed(session)
        assert third["text"].startswith(first["text"]), (
            "later output did not extend earlier output; this is not cumulative"
        )


def test_a_byte_that_is_not_text_does_not_take_the_endpoint_down():
    """Firmware printing binary is ordinary and must not break `state`.

    The bytes go through the modelled UART data register, the same way the
    program's own writes do, so this exercises the real path rather than a
    stub. 0xEF and 0xFF are not valid UTF-8 in that order; the `!` after them
    proves decoding resumed rather than giving up at the first bad byte.
    """
    needs_uart_image()
    with api.load_firmware(BOARD, HELLO.read_bytes(), base=HELLO_LOAD) as session:
        session.run(PRINT_BUDGET)
        for byte in (0xEF, 0xFF, ord("!")):
            session.cpu.write_word(rp2040.UART0 + rp2040.UART_DR, byte)
        view = printed(session)

    assert view["undecodable_bytes"] == 2
    assert view["bytes"] == 16
    assert view["text"].startswith("hello, world\n")
    assert view["text"].endswith("!"), "decoding stopped at the first bad byte"
    assert "ef" in view["text"] and "ff" in view["text"], (
        f"the byte values were thrown away rather than shown: {view['text']!r}"
    )


def test_a_board_with_no_uart_model_says_so_rather_than_showing_an_empty_console():
    """`present: false` is a claim about the model. An empty string would be a
    claim about the program, and they are different facts -- one of them is
    "this board cannot print" and the other is "it ran and chose not to"."""
    needs_core()
    if not QUIET_IMAGE.is_file():
        pytest.skip(f"{QUIET_IMAGE} is missing")

    with api.load_firmware(QUIET_BOARD, QUIET_IMAGE.read_bytes(), base=0) as session:
        session.run(BUDGET)
        view = printed(session)

    assert view["present"] is False
    assert "text" not in view, (
        "a board with no UART returned text, which a console would render as "
        "output the program did not produce"
    )
    assert "samd21" in view["note"] and "models no UART" in view["note"]


def test_the_uart_view_is_bounded_and_says_what_it_dropped():
    """The one field a *program* can grow without bound.

    Everything else in `state` is fixed-size or already capped. A program
    printing in a loop would hand the browser megabytes, so the oldest bytes
    go and the count of them is reported -- a console frozen at boot with no
    explanation is worse than one that says how much it lost.
    """
    needs_uart_image()
    with api.load_firmware(BOARD, HELLO.read_bytes(), base=HELLO_LOAD) as session:
        session.run(PRINT_BUDGET)
        for _ in range(api.MAX_UART_BYTES + 40):
            session.cpu.write_word(rp2040.UART0 + rp2040.UART_DR, ord("x"))
        view = printed(session)

    assert view["bytes"] == 13 + api.MAX_UART_BYTES + 40
    assert view["dropped_bytes"] == 53
    assert len(view["text"]) == api.MAX_UART_BYTES
    assert view["text"].endswith("x")
    assert not view["text"].startswith("hello"), (
        "the newest bytes were dropped instead of the oldest; a console would "
        "be stuck showing boot output forever"
    )


def test_the_state_route_carries_the_uart_to_the_wire():
    """Through `handle_board_api`, since that is what the browser calls."""
    needs_uart_image()
    slot = emulator_server.BoardSlot()
    try:
        slot.replace(api.load_firmware(BOARD, HELLO.read_bytes(), base=HELLO_LOAD))
        emulator_server.handle_board_api(
            slot, "/api/board/run", {}, {"steps": PRINT_BUDGET}
        )
        state = emulator_server.handle_board_api(slot, "/api/board/state", {}, {})
    finally:
        slot.replace(None)

    assert state["uart"]["text"] == "hello, world\n"
    assert set(state["uart"]) == {
        "present", "bytes", "dropped_bytes", "text", "undecodable_bytes",
    }, "the wire shape in emulator_server's docstring no longer matches"


def test_the_step_route_moves_the_board_one_instruction():
    """**`BoardSession.step` existed and no route exposed it** (OH-140): the
    8086 could be single-stepped from the page and a board could not.
    Driven through the routes with the load route\'s own wire shape, and
    the stepped state comes back in the step reply -- one round-trip per
    step, the same economy the clock\'s run ticks keep."""
    import base64
    slot = emulator_server.BoardSlot()
    emulator_server.handle_board_api(slot, "/api/board/load", {}, {
        "board": BOARD,
        "image": base64.b64encode(blink_bytes()).decode(),
        "base": hex(BLINK_LOAD),
    })
    try:
        before = emulator_server.handle_board_api(
            slot, "/api/board/state", {}, {})
        after = emulator_server.handle_board_api(
            slot, "/api/board/step", {}, {})
        assert after["pc"] != before["pc"], "one step moved nothing"
        assert after["registers"], "the stepped state did not come back"
        # And the count is honoured: three more steps land somewhere else.
        again = emulator_server.handle_board_api(
            slot, "/api/board/step", {}, {"count": 3})
        assert again["pc"] != after["pc"]
    finally:
        slot.session.close()


# --- what the outside drives onto the pads (OH-161 step 3) -------------------
#
# The XIAO ESP32-C3's committed bare-metal blink, which drives GPIO8 and
# never touches GPIO3 -- `D1` -- so GPIO3 is as reset leaves it: input on, no
# pull (`esp32c3.IO_MUX_PADS`). What it reads is the drive and nothing else.

from webui.boards import esp32c3  # noqa: E402

C3_BOARD = "XIAO-ESP32-C3-DIP"
C3_BLINK = REPO / "tests" / "riscv32" / "c3blink" / "blink.bin"
D1 = 1 << esp32c3.HEADER["D1"]


def needs_riscv32() -> None:
    """Skip loudly where riscv32 is not built. `needs_core` asks after
    cortexm0, and an ESP32 runs on the other core: with riscv32 missing and
    cortexm0 built, a test guarded by `needs_core` failed loading instead of
    skipping (OH-161's slice-B review, which found it on the bench test)."""
    target = targets.find("riscv32")
    if target is None or not target.selectable:
        pytest.skip("riscv32 is not built; run python tools/build_core.py")


def c3_session() -> api.BoardSession:
    needs_riscv32()
    if not C3_BLINK.is_file():
        pytest.skip(f"{C3_BLINK} is missing")
    return api.load_firmware(C3_BOARD, C3_BLINK.read_bytes(), base=esp32c3.IROM)


def gpio_in(session: api.BoardSession) -> int:
    return session.cpu.read_word(esp32c3.GPIO + esp32c3.GPIO_IN)


def test_a_drive_reaches_the_pin_and_is_recorded_when_it_took_effect():
    """Each drive is stamped with the instructions retired before it --
    `run` and `step` both count -- and says everything the outside does:
    the third call names no pad, so nothing drives `D1` and it floats."""
    with c3_session() as session:
        session.run(100)
        session.drive({"D1": "high"})
        assert gpio_in(session) & D1
        session.step(5)
        session.drive({"D1": "low"})
        assert not gpio_in(session) & D1
        session.run(20)
        session.drive({"D1": "high"})
        session.drive({})
        assert not gpio_in(session) & D1
        assert session.inputs == [
            (100, {"D1": "high"}, {}, {}), (105, {"D1": "low"}, {}, {}),
            (125, {"D1": "high"}, {}, {}), (125, {}, {}, {})]
        assert session.retired == 125


def test_the_record_is_not_the_callers_dict():
    """A caller that reuses its dict for the next drive must not rewrite the
    record of the last one; the record keeps a copy of what was said."""
    with c3_session() as session:
        levels = {"D1": "high"}
        volts = {"D0": 1.65}
        session.drive(levels, volts)
        levels["D1"] = "low"
        volts["D0"] = 1.1
        assert session.inputs == [(0, {"D1": "high"}, {"D0": 1.65}, {})]


def test_open_is_a_pad_nothing_drives_and_not_a_low_one():
    """`D9` is GPIO9, which comes out of reset pulled up (TRM Table 5.12-1,
    Reset "3"): driven low it reads 0, and left open its pull reads 1."""
    d9 = 1 << esp32c3.HEADER["D9"]
    with c3_session() as session:
        session.drive({"D9": "low"})
        assert not gpio_in(session) & d9
        session.drive({"D9": "open"})
        assert gpio_in(session) & d9, "open: nothing beats the pull-up"


def test_a_level_that_is_not_one_of_the_three_is_refused_by_name():
    with c3_session() as session:
        with pytest.raises(ValueError) as caught:
            session.drive({"D1": "1"})
    assert "'1'" in str(caught.value) and "'open'" in str(caught.value), (
        str(caught.value))


def test_a_pad_that_reaches_no_gpio_is_refused_with_the_pads_that_do():
    """`3V3_OUT` is a pad of every XIAO ESP32-C3 and no GPIO: driving it
    would say something about a rail, which is the bench's to solve."""
    with c3_session() as session:
        with pytest.raises(ValueError) as caught:
            session.drive({"3V3_OUT": "high"})
        assert session.inputs == [], "a refused drive is not recorded"
    assert "'3V3_OUT'" in str(caught.value) and "'D1'" in str(caught.value), (
        str(caught.value))


def test_two_labels_of_one_gpio_driven_two_ways_are_refused(monkeypatch):
    """No XIAO here names one GPIO twice, and an Uno's `A4` and `SDA` do:
    the day such a board reads its inputs, the two must agree. A second
    label for GPIO3 stands in for it."""
    monkeypatch.setitem(esp32c3.HEADER, "ALSO_D1", esp32c3.HEADER["D1"])
    with c3_session() as session:
        session.drive({"D1": "high", "ALSO_D1": "high"})
        assert gpio_in(session) & D1
        with pytest.raises(ValueError) as caught:
            session.drive({"D1": "high", "ALSO_D1": "low"})
    assert "'D1'" in str(caught.value) and "'ALSO_D1'" in str(caught.value), (
        str(caught.value))


def test_a_board_whose_description_reads_no_input_refuses_a_drive():
    """The XIAO RP2040's description maps SIO's `GPIO_IN` as a stored
    zero and gives no `drive_pins`; a drive there would be believed and
    ignored."""
    needs_core()
    with api.load_firmware(BOARD, blink_bytes(), base=BLINK_LOAD) as session:
        with pytest.raises(ValueError) as caught:
            session.drive({"D0": "high"})
    assert BOARD in str(caught.value), str(caught.value)


def test_a_manifest_row_is_driven_by_its_own_pad_labels():
    """A row's labels are its own board file's, resolved to the pad's
    `chip_index` as `row_levels` reads them, and not the XIAO's `HEADER`.
    On the Adafruit QT Py ESP32-C3 the pad `A1` reaches GPIO3, which the
    XIAO calls `D1` -- a label this board has no pad for. Its committed
    image drives SDA, GPIO5, and leaves GPIO3 as reset leaves it."""
    needs_riscv32()
    board = "Adafruit QT Py ESP32-C3"
    image = REPO / "tests" / "webui" / "qtpy_esp32c3" / "qtpy_blink.bin"
    if not image.is_file():
        pytest.skip(f"{image} is missing")
    with api.load_firmware(board, image.read_bytes(), base=esp32c3.IROM) as session:
        session.drive({"A1": "high"})
        assert gpio_in(session) & D1, "A1 is GPIO3 on this board"
        with pytest.raises(ValueError) as caught:
            session.drive({"D1": "high"})
    assert "'D1'" in str(caught.value) and "'A1'" in str(caught.value), (
        str(caught.value))


def test_the_names_drive_accepts_are_the_names_pin_levels_answers_under():
    """`drive` resolves a name to a GPIO with its own copy of the table
    `pin_levels` reads through -- the fourth restatement of a row's half that
    `level_keys`' docstring counts -- so the two are held to one answer here,
    on every board in the catalogue whose description reads input: a name
    one accepts and the other does not report is a pad the page could drive
    and never see, or see and never drive. Found by OH-161's step-3 review."""
    from webui import pinmap

    checked = []
    for board in catalogue.catalogue():
        description = api.description_for(board.name)
        if getattr(description, "drive_pins", None) is None:
            continue
        layout = pinmap.load(board.name)
        accepted = frozenset(api.drive_table(board.name, description, layout))
        keys = api.level_keys(board.name, description, layout)
        assert accepted == keys, (board.name, sorted(accepted ^ keys))
        checked.append(board.name)
    assert {"XIAO-ESP32-C3-DIP", "XIAO-ESP32-C5-DIP", "Adafruit QT Py ESP32-C3",
            "SparkFun Thing Plus ESP32-C5"} <= set(checked), checked


def test_a_row_with_no_board_file_refuses_a_drive_by_name(monkeypatch):
    """A manifest row resolves its pads through its own board file; without
    one there is nothing to resolve a name against, and the refusal names
    the board rather than raising an `AttributeError` on `None`."""
    needs_riscv32()
    from webui import pinmap

    board = "Adafruit QT Py ESP32-C3"
    image = REPO / "tests" / "webui" / "qtpy_esp32c3" / "qtpy_blink.bin"
    if not image.is_file():
        pytest.skip(f"{image} is missing")
    with api.load_firmware(board, image.read_bytes(), base=esp32c3.IROM) as session:
        monkeypatch.setattr(pinmap, "load", lambda name: None)
        with pytest.raises(ValueError) as caught:
            session.drive({"A1": "high"})
        assert session.inputs == []
    assert board in str(caught.value) and "board file" in str(caught.value), (
        str(caught.value))


def test_a_drive_on_an_output_pad_is_recorded_and_the_pin_reads_what_it_drives():
    """The blink drives GPIO8, `D8`, as an output. Driving `D8` low from
    outside while the blink holds it high is accepted and recorded, and the
    core ignores it: `IN` follows `OUT`, and what a pin and a part fighting
    over one node do is the bench's to solve."""
    d8 = 1 << esp32c3.HEADER["D8"]
    with c3_session() as session:
        for _ in range(20_000):
            session.step()
            if session.cpu.read_word(esp32c3.GPIO + esp32c3.GPIO_OUT) & d8:
                break
        session.drive({"D8": "low"})
        assert gpio_in(session) & d8, "the output's own level, not the drive"
        assert session.inputs[-1] == (session.retired, {"D8": "low"}, {}, {})


#: A sketch whose output depends on WHEN each drive lands: it echoes `D1` to
#: `D10` and prints each level it sees change, so a drive that landed an
#: instruction early or late moves the run.
REPLAY_SKETCH = """
int last = -1;
void setup() { pinMode(D1, INPUT_PULLUP); pinMode(D10, OUTPUT); }
void loop() {
  int level = digitalRead(D1);
  digitalWrite(D10, level);
  if (level != last) { Serial.print(level); last = level; }
}
"""


def test_the_image_and_the_record_of_drives_replay_the_run():
    """**The replay claim `BoardSession.inputs` makes, run.** A sketch is
    driven between run chunks and single steps, then a fresh session is
    given the same image and the record, one instruction at a time: each
    drive must land at the same instruction -- the program counter it found
    the first time -- and the run must end with the same instruction count,
    program counter, pin levels and printed text. Found missing by OH-161's
    step-3 review."""
    needs_riscv32()
    from webui import compile as compiler

    try:
        built = compiler.build(C3_BOARD, REPLAY_SKETCH)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    base = compiler.recipe_for(C3_BOARD).base

    def ending(session: api.BoardSession) -> tuple:
        return (session.retired, session.cpu.pc,
                api.pin_levels(session.runtime, session.cpu),
                session.state()["uart"]["text"])

    landed = []
    with api.load_firmware(C3_BOARD, built.image, base=base) as session:
        session.run(300)
        for chunk, levels, steps in ((None, {"D1": "low"}, 7), (213, {"D1": "open"}, 1),
                                     (None, {"D1": "low"}, 0), (150, {}, 0)):
            if chunk:
                session.run(chunk)
            landed.append(session.cpu.pc)
            session.drive(levels)
            if steps:
                session.step(steps)
        session.run(400)
        record = list(session.inputs)
        first = ending(session)
    assert "0" in first[3] and "1" in first[3], f"the drives moved nothing: {first[3]!r}"

    with api.load_firmware(C3_BOARD, built.image, base=base) as replay:
        for (at, levels, volts, devices), pc in zip(record, landed):
            while replay.retired < at:
                replay.step()
            assert replay.cpu.pc == pc, (
                f"the drive stamped {at} lands at pc {replay.cpu.pc:#x}, "
                f"where the run had it at {pc:#x}")
            replay.drive(levels, volts, devices)
        while replay.retired < first[0]:
            replay.step()
        assert ending(replay) == first
        assert replay.inputs == record


# --- what the outside holds a pin at, as the ADC converts it (OH-161 step 4) --

ADC_ONETIME = esp32c3.APB_SARADC + esp32c3.APB_SARADC_ONETIME_SAMPLE


def adc1_code(session: api.BoardSession, gpio: int) -> int:
    """Convert ADC1's channel for `gpio` at 12 dB as firmware would, through
    the description's own addresses, and answer the code."""
    word = (esp32c3.ONETIME_SAR1 | esp32c3.ADC1_CHANNELS[gpio] << esp32c3.ONETIME_CHANNEL_SHIFT
            | 3 << esp32c3.ONETIME_ATTEN_SHIFT)
    session.cpu.write_word(ADC_ONETIME, word)
    session.cpu.write_word(ADC_ONETIME, word | esp32c3.ONETIME_START)
    return session.cpu.read_word(esp32c3.APB_SARADC + esp32c3.APB_SARADC_SAR1_DATA)


def test_a_voltage_reaches_the_adc_and_is_recorded_beside_the_levels():
    """`D0` is GPIO2, ADC1's channel 2. Held at 1.65 V it converts to 1536,
    and the record keeps the levels and the volts of each drive together; a
    drive with no volts holds nothing, and the pin converts to 0."""
    d0 = esp32c3.HEADER["D0"]
    with c3_session() as session:
        session.run(50)
        session.drive({"D0": "open"}, {"D0": 1.65})
        assert adc1_code(session, d0) == 1536
        session.run(10)
        session.drive({"D1": "low"})
        assert adc1_code(session, d0) == 0, "a drive without volts holds nothing"
        assert session.inputs == [
            (50, {"D0": "open"}, {"D0": 1.65}, {}), (60, {"D1": "low"}, {}, {})]


def test_a_voltage_that_is_not_a_finite_number_of_volts_or_more_is_refused():
    """Each refused with its value, before anything is driven or recorded:
    a voltage below ground, not a number, not finite, or a bool, which
    Python would otherwise take for 1 V; an integer too large for a float,
    which `json.loads` accepts up to 4300 digits and which raised
    `OverflowError` past every handler until the step 4 review; a pad that
    reaches no GPIO; and a `volts` that is not a map."""
    with c3_session() as session:
        for volts, said in (({"D0": -0.5}, "-0.5"), ({"D0": "1.65"}, "'1.65'"),
                            ({"D0": float("nan")}, "nan"), ({"D0": float("inf")}, "inf"),
                            ({"D0": True}, "True"), ({"D0": 10 ** 400}, "1" + "0" * 400),
                            ({"3V3_OUT": 3.3}, "'3V3_OUT'"),
                            ([("D0", 1.65)], "[('D0', 1.65)]")):
            with pytest.raises(ValueError) as caught:
                session.drive({"D1": "high"}, volts)
            assert said in str(caught.value), (volts, str(caught.value))
        assert session.inputs == [], "a refused drive is not recorded"
        assert not gpio_in(session) & D1, "nor driven"


def test_a_voltage_the_description_refuses_leaves_the_levels_undriven(monkeypatch):
    """`hold_volts` runs before `drive_pins`, so a voltage the description
    refuses leaves the levels of the same call undriven as well as
    unrecorded: a level applied and not recorded is a run no replay
    reproduces. No name `drive_table` resolves on any board in the
    catalogue is refused there today, so the refusal is put in."""
    def refuses(cpu, volts):
        raise ValueError(f"refused {dict(volts)!r}")

    with c3_session() as session:
        monkeypatch.setattr(esp32c3, "hold_volts", refuses)
        with pytest.raises(ValueError):
            session.drive({"D1": "high"}, {"D0": 1.65})
        assert session.inputs == [], "a refused drive is not recorded"
        assert not gpio_in(session) & D1, "nor driven"


def test_two_labels_of_one_gpio_held_at_two_voltages_are_refused(monkeypatch):
    monkeypatch.setitem(esp32c3.HEADER, "ALSO_D0", esp32c3.HEADER["D0"])
    with c3_session() as session:
        session.drive({}, {"D0": 1.0, "ALSO_D0": 1.0})
        with pytest.raises(ValueError) as caught:
            session.drive({}, {"D0": 1.0, "ALSO_D0": 2.0})
    assert "'D0'" in str(caught.value) and "'ALSO_D0'" in str(caught.value), (
        str(caught.value))


def test_every_description_that_reads_input_converts_a_voltage_too():
    """**The page posts volts wherever it posts levels**: `circuit.js`
    answers both on a board whose supply states input levels, which is
    exactly where the description reads input
    (`test_a_supply_states_input_levels_exactly_where_its_board_reads_input`).
    So a description with `drive_pins` and no `hold_volts` would have every
    post the page made refused, levels and all. Held over the catalogue;
    the XIAO ESP32-C5 joined at OH-161's step 4, before which this failed
    on it, and the bench test on the C5 with it."""
    checked = []
    for board in catalogue.catalogue():
        description = api.description_for(board.name)
        if getattr(description, "drive_pins", None) is None:
            continue
        assert getattr(description, "hold_volts", None) is not None, board.name
        checked.append(board.name)
    assert {"XIAO-ESP32-C3-DIP", "XIAO-ESP32-C5-DIP", "XIAO-ESP32-C6-DIP"} <= set(checked), checked


def test_every_gpio_a_drive_resolves_is_a_pad_its_description_accepts():
    """`drive` holds the voltages before it drives the levels, so
    `drive_pins` refusing a GPIO after `hold_volts` had applied would leave
    the voltages held and unrecorded. Each refuses exactly a GPIO outside its
    description's `IO_MUX_PADS`, so that cannot happen while every GPIO
    `drive_table` resolves is inside it: through `HEADER` on a XIAO, through
    its own board file on a manifest row. Held over the catalogue, as OH-161
    step 4's confirmation pass enumerated it by hand."""
    from webui import pinmap

    checked = []
    for board in catalogue.catalogue():
        description = api.description_for(board.name)
        if getattr(description, "drive_pins", None) is None:
            continue
        pads = getattr(description, "IO_MUX_PADS", None)
        assert pads is not None, (board.name, description.__name__, "no IO_MUX_PADS")
        table = api.drive_table(board.name, description, pinmap.load(board.name))
        outside = {name: gpio for name, gpio in table.items() if gpio not in pads}
        assert not outside, (board.name, outside)
        checked.append(board.name)
    assert {"XIAO-ESP32-C3-DIP", "XIAO-ESP32-C5-DIP", "XIAO-ESP32-C6-DIP",
            "Adafruit QT Py ESP32-C3", "SparkFun Thing Plus ESP32-C5"} <= set(checked), checked


def test_volts_for_a_description_that_converts_none_are_refused(monkeypatch):
    """A description that reads input and has no `hold_volts` would believe
    a voltage and convert nothing; levels alone are still driven there.
    Taken away once the board is installed, since `install_adc` holds
    nothing through it."""
    with c3_session() as session:
        monkeypatch.delattr(esp32c3, "hold_volts")
        session.drive({"D1": "high"})
        with pytest.raises(ValueError) as caught:
            session.drive({"D1": "low"}, {"D0": 1.65})
        assert session.inputs == [(0, {"D1": "high"}, {}, {})]
    assert C3_BOARD in str(caught.value) and "1.65" in str(caught.value), (
        str(caught.value))


#: A sketch whose output depends on WHEN each voltage lands: it prints every
#: code A0 converts to that differs from the last.
ANALOG_REPLAY_SKETCH = """
int last = -1;
void setup() { }
void loop() {
  int code = analogRead(A0);
  if (code != last) { Serial.println(code); last = code; }
}
"""


def test_the_image_and_a_record_of_drives_with_volts_replay_the_run():
    """The replay claim, with voltages in it: drives that hold `D0` -- A0 --
    at three voltages and at none, between run chunks and single steps,
    replayed into a fresh session one instruction at a time. Each drive must
    land at the program counter it found the first time, and the run must
    end with the same instruction count, program counter, pin levels and
    printed codes, with the same record."""
    needs_riscv32()
    from webui import compile as compiler

    try:
        built = compiler.build(C3_BOARD, ANALOG_REPLAY_SKETCH)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    base = compiler.recipe_for(C3_BOARD).base

    def ending(session: api.BoardSession) -> tuple:
        return (session.retired, session.cpu.pc,
                api.pin_levels(session.runtime, session.cpu),
                session.state()["uart"]["text"])

    landed = []
    with api.load_firmware(C3_BOARD, built.image, base=base) as session:
        session.run(300)
        for chunk, levels, volts, steps in (
                (None, {"D0": "open"}, {"D0": 1.65}, 7),
                (213, {"D0": "open"}, {"D0": 1.1}, 1),
                (300, {"D0": "low"}, {"D0": 0.3}, 0),
                (150, {}, None, 0)):
            if chunk:
                session.run(chunk)
            landed.append(session.cpu.pc)
            session.drive(levels, volts)
            if steps:
                session.step(steps)
        session.run(400)
        record = list(session.inputs)
        first = ending(session)
    assert first[3].split() == ["0", "1536", "1024", "279", "0"], (
        f"the volts did not each print: {first[3]!r}")

    with api.load_firmware(C3_BOARD, built.image, base=base) as replay:
        for (at, levels, volts, devices), pc in zip(record, landed):
            while replay.retired < at:
                replay.step()
            assert replay.cpu.pc == pc, (
                f"the drive stamped {at} lands at pc {replay.cpu.pc:#x}, "
                f"where the run had it at {pc:#x}")
            replay.drive(levels, volts, devices)
        while replay.retired < first[0]:
            replay.step()
        assert ending(replay) == first
        assert replay.inputs == record


# --- the bench's drive, over HTTP (OH-161 step 3, slice B) -------------------
#
# `POST /api/board/drive` is how the page's bench reaches `BoardSession.drive`
# -- `webui/static/board3d.js` posts what `circuit.js` solved onto the
# inputs. Driven here through the server's real path: a loopback socket, the
# Origin check, the method table, the lock and the handler.


def load_c3_blink(base_url: str) -> None:
    """The XIAO ESP32-C3's committed blink, loaded over HTTP."""
    needs_riscv32()
    if not C3_BLINK.is_file():
        pytest.skip(f"{C3_BLINK} is missing")
    post(base_url, "/api/board/load", upload(
        image=C3_BLINK.read_bytes(), board=C3_BOARD, base=hex(esp32c3.IROM)))


def gpio_in_over_http(base_url: str) -> int:
    """`GPIO_IN` as the page would watch it, through `words=`."""
    state = get(base_url, f"/api/board/state?words={esp32c3.GPIO + esp32c3.GPIO_IN:#x}")
    return state["words"][0]["value"]


def test_a_drive_reaches_the_pin_through_the_server(live_server):
    """The bench's whole map, posted, lands on the pins and is answered with
    the drive as the session recorded it: when, and what. `D9` comes out of
    reset pulled up, so driving it low and then leaving it open shows the
    drive and its end; `D1` floats, so driven high it reads 1 and open 0."""
    load_c3_blink(live_server)
    d9 = 1 << esp32c3.HEADER["D9"]
    said = post(live_server, "/api/board/drive",
                {"board": C3_BOARD, "levels": {"D1": "high", "D9": "low"}})
    assert said == {"board": C3_BOARD, "retired": 0,
                    "levels": {"D1": "high", "D9": "low"}, "volts": {}}
    level = gpio_in_over_http(live_server)
    assert level & D1 and not level & d9, hex(level)
    post(live_server, "/api/board/run", {"steps": 100})
    said = post(live_server, "/api/board/drive",
                {"board": C3_BOARD, "levels": {"D1": "open", "D9": "open"}})
    assert said["retired"] == 100
    level = gpio_in_over_http(live_server)
    assert not level & D1 and level & d9, hex(level)


def test_each_refused_drive_arrives_as_drive_refused(live_server):
    """`drive`'s `ValueError`s, and the route's own refusal of a bench solved
    for another board, each arrive as a 400 with the `drive-refused` slug
    and the values in the message -- and leave the pins as they were."""
    load_c3_blink(live_server)
    before = gpio_in_over_http(live_server)
    for levels, volts, board, named in (
            ({"D1": "1"}, None, C3_BOARD, "'1'"),
            ({"3V3_OUT": "high"}, None, C3_BOARD, "'3V3_OUT'"),
            ({"D1": "high"}, None, "XIAO-ESP32-C6-DIP", "XIAO-ESP32-C6-DIP"),
            ({"D1": "high"}, {"D0": -1}, C3_BOARD, "-1"),
            ({"D1": "high"}, {"D0": "1.65"}, C3_BOARD, "'1.65'"),
            ({"D1": "high"}, {"D0": 10 ** 400}, C3_BOARD, "1" + "0" * 400)):
        with pytest.raises(urllib.error.HTTPError) as caught:
            post(live_server, "/api/board/drive",
                 {"board": board, "levels": levels, "volts": volts})
        answer = json.loads(caught.value.read())
        assert caught.value.code == 400, answer
        assert answer["reason"] == "drive-refused", answer
        assert named in answer["error"], answer
    assert gpio_in_over_http(live_server) == before, "a refused drive moved a pin"


def test_a_drive_on_a_board_that_reads_no_input_is_refused_by_name(live_server):
    """The XIAO RP2040's description reads no input, so its session refuses
    every drive, and the route says so as `drive-refused`."""
    post(live_server, "/api/board/load", upload(board=BOARD, base=hex(BLINK_LOAD)))
    with pytest.raises(urllib.error.HTTPError) as caught:
        post(live_server, "/api/board/drive", {"board": BOARD, "levels": {"D0": "high"}})
    answer = json.loads(caught.value.read())
    assert caught.value.code == 400 and answer["reason"] == "drive-refused", answer
    assert BOARD in answer["error"], answer


def test_a_drive_that_is_not_a_map_of_levels_is_refused_naming_the_field(live_server):
    """Not a refusal of the drive -- there is no drive to refuse -- so a
    plain 400 naming the field and the value it got, and no slug.

    **And a body `json.loads` refuses for its size rather than its syntax**:
    an integer past Python's 4300-digit limit for converting one is a plain
    `ValueError`, not the `JSONDecodeError` the parse used to catch alone,
    and it closed the connection with no reply. Sent as bytes, because
    `json.dumps` refuses that integer too; 5 KB is under `MAX_BODY_BYTES`."""
    load_c3_blink(live_server)
    for body, field, got in (
            ({"board": C3_BOARD, "levels": ["D1", "high"]}, "levels", "['D1', 'high']"),
            ({"board": C3_BOARD, "levels": {}, "volts": [1.65]}, "volts", "[1.65]"),
            ({"board": 7, "levels": {"D1": "high"}}, "board", "got 7"),
            ({"levels": {"D1": "high"}}, "board", "got None")):
        with pytest.raises(urllib.error.HTTPError) as caught:
            post(live_server, "/api/board/drive", body)
        answer = json.loads(caught.value.read())
        assert caught.value.code == 400, answer
        assert field in answer["error"] and "reason" not in answer, answer
        assert got in answer["error"], answer
    digits = (b'{"board": "' + C3_BOARD.encode() + b'", "levels": {}, '
              b'"volts": {"D0": 1' + b"0" * 4999 + b"}}")
    request = urllib.request.Request(
        live_server + "/api/board/drive", data=digits,
        headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    answer = json.loads(caught.value.read())
    assert caught.value.code == 400, answer
    assert "body is not JSON" in answer["error"] and "4300" in answer["error"], answer
    assert "reason" not in answer, answer


def test_a_drive_is_post_only(live_server):
    """It changes the machine, so a GET -- an `<img>` in another tab -- is a
    405 and drives nothing (OH-141's table)."""
    load_c3_blink(live_server)
    before = gpio_in_over_http(live_server)
    with pytest.raises(urllib.error.HTTPError) as caught:
        get(live_server, "/api/board/drive")
    assert caught.value.code == 405
    assert "POST" in json.loads(caught.value.read())["error"]
    assert gpio_in_over_http(live_server) == before


#: `pinMode(D1, INPUT_PULLUP)` and D10 copying it: the slice's watched sketch.
ECHO_SKETCH = """
void setup() { pinMode(D1, INPUT_PULLUP); pinMode(D10, OUTPUT); }
void loop() { digitalWrite(D10, digitalRead(D1)); }
"""


def test_a_sketch_reads_what_the_bench_drove_through_the_server(live_server):
    """**The slice, end to end over HTTP**: a sketch compiled for the XIAO
    ESP32-C3, loaded and run through the routes the page uses, copies D1 to
    D10. Open, the pull-up holds D1 high and D10 follows; driven low through
    `/api/board/drive`, D10 goes low; open again, high. D10 is read the way
    the page reads it, from `/api/board/state`'s `pins`."""
    from webui import compile as compiler

    needs_riscv32()
    try:
        built = compiler.build(C3_BOARD, ECHO_SKETCH)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    post(live_server, "/api/board/load", upload(
        image=built.image, board=C3_BOARD,
        base=hex(compiler.recipe_for(C3_BOARD).base)))

    def d10_after(levels: dict) -> str:
        if levels is not None:
            post(live_server, "/api/board/drive", {"board": C3_BOARD, "levels": levels})
        post(live_server, "/api/board/run", {"steps": 2_000})
        return get(live_server, "/api/board/state")["pins"]["D10"]

    assert d10_after(None) == "high", "the pull-up did not hold an open D1 high"
    assert d10_after({"D1": "low"}) == "low"
    assert d10_after({"D1": "open"}) == "high"
    assert d10_after({"D1": "low", "D2": "open"}) == "low"


def test_a_sketch_converts_the_voltage_the_bench_held_through_the_server(live_server):
    """**Step 4 over HTTP**: `ANALOG_REPLAY_SKETCH` prints each code A0
    converts to; the bench's map with `D0` -- A0 -- held at 1.65 V, posted
    to `/api/board/drive`, is answered with the volts as the session
    recorded them, and the console the page reads from `/api/board/state`
    prints 1536, then 1024 at 1.1 V."""
    from webui import compile as compiler

    needs_riscv32()
    try:
        built = compiler.build(C3_BOARD, ANALOG_REPLAY_SKETCH)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))
    assert built.ok, built.diagnostics
    post(live_server, "/api/board/load", upload(
        image=built.image, board=C3_BOARD,
        base=hex(compiler.recipe_for(C3_BOARD).base)))
    post(live_server, "/api/board/run", {"steps": 2_000})
    said = post(live_server, "/api/board/drive",
                {"board": C3_BOARD, "levels": {"D0": "open"}, "volts": {"D0": 1.65}})
    assert said == {"board": C3_BOARD, "retired": 2_000,
                    "levels": {"D0": "open"}, "volts": {"D0": 1.65}}
    post(live_server, "/api/board/run", {"steps": 2_000})
    post(live_server, "/api/board/drive",
         {"board": C3_BOARD, "levels": {"D0": "open"}, "volts": {"D0": 1.1}})
    post(live_server, "/api/board/run", {"steps": 2_000})
    assert get(live_server, "/api/board/state")["uart"]["text"] == "0\r\n1536\r\n1024\r\n"


# --- a doorbell's refusal comes after the instruction that rang it retired ----
#
# ABI 7's ring (OH-161 step 5) is the first stop that follows a retired
# instruction. These sessions are a bare RV32 core with one doorbell and no
# board description, because the counting is the session's and not a chip's;
# the I2C controller that uses it arrives in the next slice.

RING_BELL = 0x60013004
RING_RAM = 0x80000000
#: lui a4, 0x60013 / addi a5, x0, 0x20 / sw a5, 4(a4) -- the store rings -- and
#: then five nops (addi x0, x0, 0).
RING_PROGRAM = [0x60013737, 0x02000793, 0x00F72223] + [0x00000013] * 5


def ring_session(service) -> api.BoardSession:
    import types

    from core.riscv32 import abi as riscv32_abi

    cpu = riscv32_abi.Cpu()
    cpu.add_region(RING_RAM, 0x1000)
    cpu.map_doorbell(RING_BELL, value=0, ring_mask=0x20, write_trigger=0x20)
    cpu.on_ring(RING_BELL, service)
    cpu.write_block(RING_RAM, b"".join(
        word.to_bytes(4, "little") for word in RING_PROGRAM))
    cpu.set_regs([0] * 32, pc=RING_RAM)
    runtime = types.SimpleNamespace(abi=riscv32_abi, board="ring-test",
                                    chip="rv32")
    return api.BoardSession(runtime, cpu, None, None)


def test_a_run_through_a_serviced_ring_counts_the_ringing_store_once():
    needs_riscv32()
    with ring_session(lambda cpu, address: None) as session:
        result = session.run(8)
        assert (result.steps, result.status) == (8, "running"), result
        assert session.retired == 8


def test_a_run_stopped_by_a_refused_ring_counts_the_store_that_rang():
    needs_riscv32()
    from core.riscv32 import abi as riscv32_abi

    def refuse(cpu, address):
        raise riscv32_abi.DeviceRefusal("the device refuses this")

    with ring_session(refuse) as session:
        result = session.run(8)
        assert (result.steps, result.status) == (3, "stopped"), result
        assert "the device refuses this" in result.detail
        assert session.retired == 3, "lui, addi and the store that rang"
        assert session.cpu.pc == RING_RAM + 12, "the store retired"


def test_a_step_stopped_by_a_refused_ring_counts_the_store_that_rang():
    needs_riscv32()
    from core.riscv32 import abi as riscv32_abi

    def refuse(cpu, address):
        raise riscv32_abi.DeviceRefusal("the device refuses this")

    with ring_session(refuse) as session:
        with pytest.raises(riscv32_abi.Refused):
            session.step(8)
        assert session.status == "stopped"
        assert session.retired == 3


def test_a_service_that_breaks_faults_the_session_and_counts_the_store():
    """A host-side bug in a service is the session's "faulted", as a core's
    HostFault is, and the ringing instruction retired and is counted: the
    KeyError once escaped `run`, leaving the status "running" with the PC
    moved."""
    needs_riscv32()
    from core.riscv32 import abi as riscv32_abi

    def key_error(cpu, address):
        {}["missing"]

    def core_error(cpu, address):
        cpu.hold_readable(address, b"\x01")  # the doorbell is no FIFO

    for service in (key_error, core_error):
        with ring_session(service) as session:
            result = session.run(8)
            assert (result.steps, result.status) == (3, "faulted"), result
            assert session.status == "faulted" and session.retired == 3
            assert "pc=0x80000008" in result.detail, result.detail
            assert session.run(8).steps == 0, "a faulted session runs no further"

        with ring_session(service) as session:
            with pytest.raises(riscv32_abi.ServiceFault):
                session.step(8)
            assert session.status == "faulted" and session.retired == 3


def test_watching_a_fifo_never_changes_what_the_firmware_reads():
    """`state(words=[DATA])` was a `read_word`, which pops: the page's poll
    ate the byte the firmware was to read, unrecorded in `inputs`, so a
    replay diverged. It peeks now."""
    needs_riscv32()
    import types

    from core.riscv32 import abi as riscv32_abi
    from core.riscv32 import machine

    data, gate = 0x60013000 + 0x1C, 0x60013000 + 0x54
    cpu = riscv32_abi.Cpu()
    cpu.add_region(RING_RAM, 0x1000)
    cpu.map_register(gate, 1 << 21)
    cpu.map_fifo(data, enable=gate, enable_mask=1 << 21)
    cpu.set_regs([0] * 32, pc=RING_RAM)
    runtime = types.SimpleNamespace(
        abi=riscv32_abi, machine=machine, board="fifo-test", chip="rv32",
        description=types.ModuleType("bare_description"), core="riscv32")
    placement = types.SimpleNamespace(window=RING_RAM)
    with api.BoardSession(runtime, cpu, None, placement) as session:
        # Empty first: that word alone says why, and the poll still brings
        # the registers, the memory and the console (which, with a FIFO
        # empty most of the time, is every poll but a few).
        state = session.state(words=[data])
        word, = state["words"]
        assert word["address"] == data and word["value"] is None, word
        assert "holds nothing to read" in word["why"], word
        assert state["registers"] and state["pc"] == RING_RAM
        assert len(state["memory"]["bytes"]) == 64 and state["uart"]

        cpu.hold_readable(data, b"\x31\x32")
        for _ in range(3):
            watched = session.state(words=[data])["words"]
            assert watched == [{"address": data, "value": 0x31}]
        assert [cpu.read_word(data) for _ in range(2)] == [0x31, 0x32], (
            "the firmware still reads every byte, in order")


# --- a device on the I2C pads, and the record that replays it (OH-161 step 5) --
#
# The programs are hand-assembled stores (`lui`, `addi`, `sw`, `lw`), so the
# transaction is the C3's own doorbell and not a harness poking a register.


def _lui(rd: int, imm20: int) -> int: return imm20 << 12 | rd << 7 | 0x37
def _addi(rd: int, rs: int, imm: int) -> int: return (imm & 0xFFF) << 20 | rs << 15 | rd << 7 | 0x13
def _sw(rs2: int, rs1: int) -> int: return rs2 << 20 | rs1 << 15 | 2 << 12 | 0x23
def _lw(rd: int, rs1: int) -> int: return rs1 << 15 | 2 << 12 | rd << 7 | 0x03


def _li(rd: int, value: int) -> list[int]:
    value &= 0xFFFFFFFF
    high = ((value + 0x800) >> 12) & 0xFFFFF
    low = value - (high << 12)
    return [_lui(rd, high), _addi(rd, rd, low)]


def _stores(*pairs: tuple[int, int]) -> list[int]:
    program: list[int] = []
    for address, value in pairs:
        program += _li(14, address) + _li(15, value) + [_sw(15, 14)]
    return program


def _read_into(register: int, address: int) -> list[int]:
    return _li(14, address) + [_lw(register, 14)]


I2C_SDA, I2C_SCL = esp32c3.HEADER["D4"], esp32c3.HEADER["D5"]
I2C_BASE = esp32c3.I2C


def _pad(gpio: int) -> int: return esp32c3.IO_MUX + esp32c3.IO_MUX_GPIO0 + gpio * esp32c3.IO_MUX_STRIDE


def _i2c_wiring() -> list[tuple[int, int]]:
    func = 1 << esp32c3.IO_MUX_MCU_SEL_SHIFT | esp32c3.IO_MUX_FUN_IE
    return [
        (esp32c3.I2C_GATE[0], esp32c3.I2C_GATE[1]),
        (_pad(I2C_SDA), func), (_pad(I2C_SCL), func),
        (esp32c3.GPIO + esp32c3.GPIO_FUNC_OUT_SEL_CFG0 + 4 * I2C_SDA, esp32c3.I2CEXT0_SDA_IDX),
        (esp32c3.GPIO + esp32c3.GPIO_FUNC_OUT_SEL_CFG0 + 4 * I2C_SCL, esp32c3.I2CEXT0_SCL_IDX),
        (esp32c3.GPIO + esp32c3.GPIO_FUNC_IN_SEL_CFG0 + 4 * esp32c3.I2CEXT0_SDA_IDX,
         esp32c3.GPIO_SIG_IN_SEL | I2C_SDA),
        (esp32c3.GPIO + esp32c3.GPIO_FUNC_IN_SEL_CFG0 + 4 * esp32c3.I2CEXT0_SCL_IDX,
         esp32c3.GPIO_SIG_IN_SEL | I2C_SCL),
    ]


def _id_read(pointer: int, address: int = 0x18) -> list[tuple[int, int]]:
    """Write `pointer` to the part, then read two bytes back: two lists, run."""
    op = {"RSTART": 6, "WRITE": 1, "READ": 3, "STOP": 2}  # i2c_ll.h:72-76
    write = [op["RSTART"] << 11, op["WRITE"] << 11 | 2 | 1 << 8, op["STOP"] << 11]
    read = [op["RSTART"] << 11, op["WRITE"] << 11 | 1 | 1 << 8, op["READ"] << 11 | 1,
            op["READ"] << 11 | 1 | 1 << 10, op["STOP"] << 11]
    out: list[tuple[int, int]] = []
    for words, data in ((write, [address << 1, pointer]), (read, [address << 1 | 1])):
        out += [(I2C_BASE + esp32c3.I2C_CTR, esp32c3.I2C_MS_MODE),
                (I2C_BASE + esp32c3.I2C_INT_CLR, 0x3FFFF)]
        out += [(I2C_BASE + esp32c3.I2C_DATA, byte) for byte in data]
        out += [(I2C_BASE + esp32c3.I2C_COMD0 + 4 * n, word) for n, word in enumerate(words)]
        out += [(I2C_BASE + esp32c3.I2C_CTR, esp32c3.I2C_MS_MODE | esp32c3.I2C_TRANS_START)]
    return out


MCP9808_ON_D4_D5 = {"part": "MCP9808", "sda": "D4", "scl": "D5", "vdd": 3.3,
                    "address_pins": {"A0": "low", "A1": "low", "A2": "low"},
                    "celsius": 25.0}


def _i2c_session(program: list[int]) -> api.BoardSession:
    needs_riscv32()
    image = b"".join(word.to_bytes(4, "little") for word in program)
    return api.load_firmware(C3_BOARD, image, base=esp32c3.IROM)


def test_a_device_drive_answers_the_firmware_and_the_record_replays_it():
    """The id read through the controller, then the part taken off the bus by
    a second drive, then the same read: NACK. A fresh session given the image
    and the record, driven at the same instructions, ends the same."""
    first = (_stores(*_i2c_wiring()) + _stores(*_id_read(6))
             + _read_into(16, I2C_BASE + esp32c3.I2C_DATA)
             + _read_into(17, I2C_BASE + esp32c3.I2C_DATA))
    second = _stores(*_id_read(6)) + _read_into(18, I2C_BASE + esp32c3.I2C_INT_RAW)
    program = first + second

    def ending(session: api.BoardSession) -> tuple:
        return (session.retired, session.cpu.pc, tuple(session.cpu.get_regs().as_list()))

    with _i2c_session(program) as session:
        session.drive({}, None, {"u1": MCP9808_ON_D4_D5})
        assert session.run(len(first)).status == "running"
        regs = session.cpu.get_regs().as_list()
        assert (regs[16], regs[17]) == (0x00, 0x54), "the part answered"
        assert set(session.devices) == {"u1"}
        session.drive({}, None, {})
        assert session.devices == {}, "a part the bench removed is dropped"
        assert session.run(len(second)).status == "running"
        nack = session.cpu.get_regs().as_list()[18]
        assert nack & esp32c3.I2C_INT_NACK, f"INT_RAW {nack:#x}: nobody answered"
        record = list(session.inputs)
        stamps = [entry[0] for entry in record]
        done = ending(session)
    assert stamps == [0, len(first)]
    assert record[0][3] == {"u1": MCP9808_ON_D4_D5} and record[1][3] == {}

    with _i2c_session(program) as replay:
        for at, levels, volts, devices in record:
            while replay.retired < at:
                replay.step()
            replay.drive(levels, volts, devices)
        while replay.retired < done[0]:
            replay.step()
        assert ending(replay) == done
        assert replay.inputs == record


def test_the_record_keeps_its_own_copy_of_the_devices():
    with _i2c_session(_stores(*_i2c_wiring())) as session:
        posted = {"u1": dict(MCP9808_ON_D4_D5, address_pins=dict(MCP9808_ON_D4_D5["address_pins"]))}
        session.drive({}, None, posted)
        posted["u1"]["celsius"] = 99.0
        posted["u1"]["address_pins"]["A0"] = "high"
        assert session.inputs[-1][3]["u1"]["celsius"] == 25.0
        assert session.inputs[-1][3]["u1"]["address_pins"]["A0"] == "low"


def test_a_part_keeps_its_pointer_between_drives_and_the_straps_are_read_again():
    with _i2c_session(_stores(*_i2c_wiring())) as session:
        session.drive({}, None, {"u1": MCP9808_ON_D4_D5})
        part = session.devices["u1"]
        part.start(False)
        part.write(7)
        part.stop()
        session.drive({}, None, {"u1": dict(MCP9808_ON_D4_D5,
                                            address_pins={"A0": "high", "A1": "low", "A2": "high"})})
        assert session.devices["u1"].pointer == 7, "the pointer survived the drive"
        assert session.devices["u1"].address == 0x18 | 0b101, "the straps were read again"


def test_a_device_the_drive_cannot_read_is_refused_with_its_values_and_wires_nothing():
    needs_riscv32()
    bad = {
        "a part nobody makes": (dict(MCP9808_ON_D4_D5, part="SSD1306"), "SSD1306"),
        "a pad that is no pad": (dict(MCP9808_ON_D4_D5, sda="D99"), "D99"),
        "both lines on one pad": (dict(MCP9808_ON_D4_D5, scl="D4"), "one GPIO"),
        "a supply that is no number": (dict(MCP9808_ON_D4_D5, vdd="3.3"), "'3.3'"),
        "a negative supply": (dict(MCP9808_ON_D4_D5, vdd=-1.0), "-1.0"),
        "a temperature that is a bool": (dict(MCP9808_ON_D4_D5, celsius=True), "True"),
        "a supply between VPOR and 2.7": (dict(MCP9808_ON_D4_D5, vdd=2.5), "2.5"),
        "an open address pin": (dict(MCP9808_ON_D4_D5,
                                     address_pins={"A0": "open", "A1": "low", "A2": "low"}),
                                "'open'"),
        "one address pin": (dict(MCP9808_ON_D4_D5, address_pins={"A0": "low"}), "A0"),
    }
    with _i2c_session(_stores(*_i2c_wiring())) as session:
        for name, (device, value) in bad.items():
            with pytest.raises(ValueError) as caught:
                session.drive({}, None, {"u1": device})
            assert value in str(caught.value), (name, str(caught.value))
            assert session.inputs == [] and session.devices == {}, (
                name, "a refused drive is not recorded and wires nothing")
        with pytest.raises(ValueError) as caught:
            session.drive({}, None, {"u1": MCP9808_ON_D4_D5, "u2": MCP9808_ON_D4_D5})
        assert "0x18" in str(caught.value), "two parts at one address on one pair"


def test_a_description_with_no_i2c_refuses_devices_by_name(monkeypatch):
    needs_riscv32()
    with _i2c_session(_stores(*_i2c_wiring())) as session:
        monkeypatch.delattr(esp32c3, "hold_bus")
        with pytest.raises(ValueError) as caught:
            session.drive({}, None, {"u1": MCP9808_ON_D4_D5})
        assert "no I2C bus" in str(caught.value) and "u1" in str(caught.value)


def test_a_refused_drive_leaves_a_kept_part_as_it_was():
    with _i2c_session(_stores(*_i2c_wiring())) as session:
        session.drive({}, None, {"u1": MCP9808_ON_D4_D5})
        kept = session.devices["u1"]
        kept.start(False)
        kept.write(7)
        kept.stop()
        moved = dict(MCP9808_ON_D4_D5, address_pins={"A0": "high", "A1": "low", "A2": "low"})
        with pytest.raises(ValueError):
            session.drive({}, None, {"u1": moved, "u2": dict(MCP9808_ON_D4_D5, part="SSD1306")})
        assert session.devices["u1"] is kept
        assert (kept.address, kept.pointer) == (0x18, 7), "held anew only on success"
        assert len(session.inputs) == 1
