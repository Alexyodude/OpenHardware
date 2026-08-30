# OpenHardware — reaching a build somebody already made.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## The question OH-10 left open, and how it is answered without asking
#
# The ticket says the compile-safety decision the user made on 2026-08-25 was
# about running a compiler, not about reading a caller's filesystem, and that
# the difference should be put to them rather than assumed.
#
# It does not need putting if the answer is **off unless the person running the
# server said otherwise**. `--artefacts DIR` is the only way this answers
# anything, and a request can never name a directory — it only chooses among
# what came back. That is the same shape `webui/compile.py` already keeps: the
# operator decides what is reachable, the request picks from it.
#
# So the conservative default needs no new decision, and the widening of it
# still can be asked for later without any of this changing.

import pathlib

import pytest

from webui import emulator_server


@pytest.fixture
def search():
    """The module-level search, restored afterwards.

    It is module state because it is a property of how the server was STARTED
    — a request cannot reach it, which is the security property the whole
    route rests on. That makes it exactly the kind of thing a test must put
    back.
    """
    before = emulator_server.SEARCH_ROOTS.roots
    yield emulator_server.SEARCH_ROOTS
    emulator_server.SEARCH_ROOTS.roots = before


def ask(route: str = "/api/board/artefacts", payload: dict | None = None) -> dict:
    return emulator_server.handle_board_api(
        emulator_server.BoardSlot(), route, {}, payload or {}
    )


# --- off by default ---------------------------------------------------------


def test_the_search_is_off_unless_the_server_was_told_otherwise(search):
    """Nothing on a caller's disk is read because a page asked."""
    search.roots = None
    assert ask()["enabled"] is False


def test_being_off_names_the_flag_that_turns_it_on(search):
    """A route that exists and is disabled and a route that does not exist are
    different facts, and only one of them is actionable."""
    search.roots = None
    assert "--artefacts" in ask()["note"]


def test_off_and_empty_are_different_answers(search):
    """`enabled: false` is "nobody asked the server to look". An empty list is
    "it looked and found nothing". A page that showed one dropdown for both
    would tell a person their builds are missing when the server was never
    pointed at them."""
    search.roots = None
    off = ask()
    search.allow([str(pathlib.Path(__file__).parent)])
    on = ask()

    assert off["enabled"] is False
    assert on["enabled"] is True
    assert on["artefacts"] == [], "this directory holds tests, not builds"


# --- what it offers ---------------------------------------------------------


def test_a_platformio_build_is_found_and_described(search, tmp_path):
    """The shape `tools/import_firmware.py` reports, passed through.

    `role` is on the wire because an ESP environment emits three images for
    three addresses, and offering them as three programs is wrong.
    """
    build = tmp_path / ".pio" / "build" / "uno"
    build.mkdir(parents=True)
    (build / "firmware.hex").write_bytes(b":00000001FF\n")
    search.allow([str(tmp_path)])

    found = ask()["artefacts"]
    assert len(found) == 1
    assert found[0]["name"] == "firmware.hex"
    assert found[0]["target"] == "uno"
    assert found[0]["role"] == "application"


def test_a_format_that_carries_its_own_address_does_not_ask_for_one(search, tmp_path):
    """**This is "without typing a base address by hand".** ELF, UF2 and Intel
    HEX all say where they belong; a page uses `needs_base` to decide whether
    to insist on the field at all."""
    build = tmp_path / ".pio" / "build" / "uno"
    build.mkdir(parents=True)
    (build / "firmware.hex").write_bytes(b":00000001FF\n")
    search.allow([str(tmp_path)])
    assert ask()["artefacts"][0]["needs_base"] is False


def test_a_raw_bin_still_asks_for_one(search, tmp_path):
    """The one shape that cannot say where it belongs. Claiming otherwise
    would load it at zero and run something that is not a program."""
    build = tmp_path / ".pio" / "build" / "uno"
    build.mkdir(parents=True)
    (build / "firmware.bin").write_bytes(b"\x00" * 16)
    search.allow([str(tmp_path)])
    assert ask()["artefacts"][0]["needs_base"] is True


def test_the_newest_build_is_offered_first(search, tmp_path):
    """The one somebody wants is almost always the one they just built, and a
    list of forty `firmware.elf` in path order makes them read all forty."""
    import os
    import time

    for name, age in (("old", 10_000), ("new", 0)):
        build = tmp_path / ".pio" / "build" / name
        build.mkdir(parents=True)
        artefact = build / "firmware.hex"
        artefact.write_bytes(b":00000001FF\n")
        when = time.time() - age
        os.utime(artefact, (when, when))
    search.allow([str(tmp_path)])

    assert [a["target"] for a in ask()["artefacts"]] == ["new", "old"]


# --- the boundary -----------------------------------------------------------


def test_a_path_outside_the_allowed_roots_is_refused(search, tmp_path):
    """The path came back from this server a moment ago — and a request is
    still a request. Nothing stops a caller sending a different one."""
    search.allow([str(tmp_path)])
    with pytest.raises(emulator_server.ApiError) as caught:
        emulator_server.SEARCH_ROOTS.resolve(str(pathlib.Path(__file__)))
    assert "not under any directory" in str(caught.value)


def test_a_sibling_directory_sharing_a_prefix_is_refused(search, tmp_path):
    """**Not `startswith`.** A root of `.../build` would otherwise admit
    `.../build-secrets`, which is the classic prefix mistake and is why this
    compares path components."""
    allowed = tmp_path / "build"
    allowed.mkdir()
    sibling = tmp_path / "build-secrets"
    sibling.mkdir()
    secret = sibling / "key.txt"
    secret.write_text("no", encoding="utf-8")
    search.allow([str(allowed)])

    with pytest.raises(emulator_server.ApiError):
        emulator_server.SEARCH_ROOTS.resolve(str(secret))


def test_a_path_that_climbs_out_with_dot_dot_is_refused(search, tmp_path):
    """`resolve()` flattens it before the comparison, so the check sees where
    the path actually leads rather than how it is spelled."""
    allowed = tmp_path / "build"
    allowed.mkdir()
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("no", encoding="utf-8")
    search.allow([str(allowed)])

    with pytest.raises(emulator_server.ApiError):
        emulator_server.SEARCH_ROOTS.resolve(str(allowed / ".." / "elsewhere.txt"))


def test_loading_by_path_is_refused_while_the_search_is_off(search):
    """Otherwise the flag would gate the listing and not the reading, which is
    the half that matters."""
    search.roots = None
    with pytest.raises(emulator_server.ApiError) as caught:
        ask("/api/board/load-artefact",
            {"board": "Arduino Uno", "path": str(pathlib.Path(__file__))})
    assert "--artefacts" in str(caught.value)


def test_a_directory_is_not_a_file(search, tmp_path):
    search.allow([str(tmp_path)])
    with pytest.raises(emulator_server.ApiError) as caught:
        emulator_server.SEARCH_ROOTS.resolve(str(tmp_path))
    assert "not a file" in str(caught.value)


# --- end to end -------------------------------------------------------------


def test_a_discovered_build_loads_onto_a_board(search, tmp_path):
    """OH-10's headline, and the whole of it: a build somebody made elsewhere,
    found by this server and running on a board, with no file dialog and no
    address typed."""
    pytest.importorskip("core.avr.abi")
    from webui import compile as compiler
    from webui.boards import atmega328p

    try:
        recipe = compiler.recipe_for("Arduino Uno")
        compiler.toolchain_root(recipe)
        compiler.framework_root(recipe)
    except compiler.ToolchainMissing as exc:
        pytest.skip(str(exc))

    built = compiler.build("Arduino Uno", "void setup(){pinMode(13,OUTPUT);}\nvoid loop(){}")
    assert built.ok, built.diagnostics
    build = tmp_path / ".pio" / "build" / "uno"
    build.mkdir(parents=True)
    (build / "firmware.bin").write_bytes(built.image)
    search.allow([str(tmp_path)])

    offered = ask()["artefacts"]
    assert len(offered) == 1

    slot = emulator_server.BoardSlot()
    emulator_server.handle_board_api(
        slot, "/api/board/load-artefact", {},
        {"board": "Arduino Uno", "path": offered[0]["path"], "base": 0},
    )
    emulator_server.handle_board_api(slot, "/api/board/run", {}, {"steps": 5_000})
    assert slot.require().cpu.read_data(atmega328p.DDRB) & (1 << atmega328p.LED_PIN)


# --- the wiring OH-10 was actually about ------------------------------------


def test_something_under_webui_imports_the_discovery_tool():
    """The ticket's own headline: 42 tests of artefact discovery that nothing
    under `webui/` imported, so a person still picked one file by hand."""
    source = (pathlib.Path(emulator_server.__file__)).read_text(encoding="utf-8")
    assert "import_firmware" in source


def test_an_artefact_over_the_ceiling_is_refused_before_a_byte_is_read(tmp_path):
    """The body path enforced MAX_IMAGE_BYTES and this route skipped it,
    while the module docstring promised the ceiling everywhere an image
    comes in (OH-142). Checked on the stat, so an 8 GB file is refused
    without being read."""
    big = tmp_path / "huge.bin"
    big.write_bytes(b"\0" * (emulator_server.MAX_IMAGE_BYTES + 1))
    before = emulator_server.SEARCH_ROOTS.roots
    emulator_server.SEARCH_ROOTS.roots = (tmp_path,)
    try:
        with pytest.raises(emulator_server.ApiError) as caught:
            emulator_server.handle_board_api(
                emulator_server.BoardSlot(), "/api/board/load-artefact", {},
                {"board": "Arduino Uno", "path": str(big)})
        assert str(emulator_server.MAX_IMAGE_BYTES) in str(caught.value)
    finally:
        emulator_server.SEARCH_ROOTS.roots = before
