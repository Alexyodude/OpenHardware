# OpenHardware — per-board status, and the rule that it is never asserted.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# The catalogue's whole job is to keep three questions apart -- what chip, what
# instruction set, and can it actually run something -- because blurring them
# is how a board comes to be described as working on the strength of its chip
# being famous. These tests are mostly about that separation.

import pathlib

import pytest

from tools import build_core
from webui.boards import catalogue

# --- the chip comes from the name ------------------------------------------


def test_a_plain_name_gives_its_chip():
    assert catalogue.chip_for("XIAO-RP2040-DIP") == "RP2040"


def test_a_hyphenated_chip_survives():
    assert catalogue.chip_for("XIAO-ESP32-C3-SMD") == "ESP32-C3"


def test_a_hyphenated_package_does_not_eat_the_chip():
    """The bug this rule was rewritten to fix. `DIP-SMD` is a two-word package,
    so 'everything between the prefix and the last field' yielded a chip called
    `ESP32-C3-DIP`, which then fell through to 'not in the survey' -- one board
    quietly unknown while its two siblings resolved."""
    assert catalogue.chip_for("XIAO-ESP32-C3-DIP-SMD") == "ESP32-C3"


def test_an_underscored_package_survives_too():
    assert catalogue.chip_for("XIAO-ESP32-S3-SMD_PAD") == "ESP32-S3"


def test_the_two_spellings_of_nordic_parts_both_resolve():
    """Seeed spells these inconsistently. Matching is case-insensitive so that
    `nRF54l15` and `nRF54LM20A` do not need two entries each."""
    assert catalogue.chip_for("XIAO-nRF54l15-DIP") == "nRF54l15"
    assert catalogue.chip_for("XIAO-nRF54LM20A-SMD") == "nRF54LM20A"


def test_the_board_with_a_doubled_prefix_is_named_rather_than_parsed():
    """Seeed's own footprint really is `XIAO-XIAO STM32C5-SMD`. Faithful, and
    unparseable by rule, so it is listed explicitly."""
    assert catalogue.chip_for("XIAO-XIAO STM32C5-SMD") == "STM32C5"


def test_a_board_that_is_not_a_xiao_is_named_rather_than_parsed():
    assert catalogue.chip_for("Arduino Uno") == "ATmega328P"


def test_an_unrecognised_name_raises_rather_than_guessing():
    """Silently filing a board under an invented chip is how a catalogue
    starts lying."""
    with pytest.raises(catalogue.CatalogueError):
        catalogue.chip_for("XIAO-NotAChip-DIP")


def test_a_name_without_the_prefix_says_what_to_do_about_it():
    with pytest.raises(catalogue.CatalogueError) as caught:
        catalogue.chip_for("Raspberry Pi Pico")
    assert "IRREGULAR" in str(caught.value)


# --- every real board resolves ---------------------------------------------


def test_every_board_in_the_repository_resolves_to_a_known_chip():
    """A guard on the whole catalogue: no board may fall through to unknown."""
    unknown = [b.name for b in catalogue.catalogue() if b.core == "unknown"
               and b.chip != "STM32C5"]
    assert not unknown, f"{unknown} resolved to no known instruction set"


def test_the_catalogue_covers_every_board_file():
    from tools.inventory import collect_boards

    assert len(catalogue.catalogue()) == len(collect_boards())


# --- runnable is three facts, not one --------------------------------------


def test_a_board_is_runnable_only_when_its_core_is_built_and_it_is_described():
    board = next(b for b in catalogue.catalogue() if b.chip == "RP2040")
    assert board.core_exists and board.core_built and board.described
    assert board.runnable


def test_a_built_core_without_a_board_description_is_not_runnable(tmp_path):
    """SAMD21 is the case that makes this real: it shares the cortexm0 core
    with RP2040, so its core is built -- and with no memory map and no
    peripherals there is nothing for firmware to run against."""
    board = next(b for b in catalogue.catalogue() if b.chip == "SAMD21")
    assert board.core_exists and board.core_built
    assert not board.described
    assert not board.runnable


def test_a_board_whose_core_does_not_exist_is_not_runnable():
    board = next(b for b in catalogue.catalogue() if b.chip == "ESP32-S3")
    assert not board.core_exists
    assert not board.runnable


def test_no_board_is_runnable_when_nothing_is_built(tmp_path, monkeypatch):
    """Deleting `build/` must take every board with it, rather than leaving a
    catalogue that still claims two boards work."""
    monkeypatch.setattr(build_core, "LIB_DIR", tmp_path / "empty")
    assert not any(b.runnable for b in catalogue.catalogue())


# --- the backlog is ordered by evidence ------------------------------------


def test_the_backlog_names_a_core_and_what_it_would_cost():
    waiting = catalogue.missing_cores()
    assert waiting, "everything cannot already be runnable"
    for row in waiting:
        assert row["boards"], f"{row['core']} blocks nothing"
        assert row["oracle"], f"{row['core']} has no oracle recorded"


def test_the_backlog_groups_by_core_rather_than_by_instruction_set_name():
    """Grouping by the ISA string split `cortexm33` into two rows and
    `riscv32` into three, so ten rows described five pieces of work."""
    cores = [row["core"] for row in catalogue.missing_cores()]
    assert len(cores) == len(set(cores)), f"a core appears twice: {cores}"
    assert "cortexm33" in cores
    row = next(r for r in catalogue.missing_cores() if r["core"] == "cortexm33")
    assert len(row["isas"]) > 1, "the RP2350 and the MG24 spell their ISA differently"


def test_the_backlog_says_which_of_its_rows_already_have_a_core():
    """`cortexm0` appears because SAMD21 has no board description -- a
    different job from the rows that need an instruction set written, and
    listing it under 'missing cores' without saying so misreads the work."""
    row = next(r for r in catalogue.missing_cores() if r["core"] == "cortexm0")
    assert row["exists"] is True
    assert all(r["exists"] is False for r in catalogue.missing_cores()
               if r["core"] != "cortexm0")


def test_the_backlog_is_ordered_by_how_many_boards_each_would_unlock():
    """The only ordering this backlog has that is not a guess."""
    counts = [len(row["boards"]) for row in catalogue.missing_cores()]
    assert counts == sorted(counts, reverse=True)


def test_the_runnable_boards_are_absent_from_the_backlog():
    waiting = {n for row in catalogue.missing_cores() for n in row["boards"]}
    for board in catalogue.catalogue():
        if board.runnable:
            assert board.name not in waiting


def test_xtensa_records_that_it_has_no_independent_oracle():
    """The reason three boards are not worth a core: QEMU-xtensa and
    binutils-xtensa share the same Tensilica archive, so agreement between
    them proves nothing."""
    row = next(r for r in catalogue.missing_cores() if r["core"] == "xtensa")
    assert "NONE" in row["oracle"]


# --- runnable is not the same claim as "firmware has run" -------------------


def test_running_firmware_is_a_separate_claim_from_being_runnable():
    """The badge said RUNS FIRMWARE for anything with a built core and a
    description. An empty `samd21.py` would have earned it."""
    for board in catalogue.catalogue():
        if board.firmware_verified:
            assert board.runnable, "cannot have run without the parts existing"


def test_only_the_board_a_real_image_ran_on_claims_to_have_run_one():
    proven = {b.chip for b in catalogue.catalogue() if b.firmware_verified}
    assert proven == {"RP2040"}


def test_every_firmware_claim_names_a_test_that_exists():
    """The claim is tied to a file so it cannot be asserted into being."""
    repo = pathlib.Path(__file__).resolve().parents[2]
    for chip, evidence in catalogue.FIRMWARE_VERIFIED.items():
        assert (repo / evidence).is_file(), f"{chip} cites a missing {evidence}"


def test_the_firmware_evidence_actually_runs_an_image():
    """Naming any file would satisfy the check above. The named one has to be
    a test that loads a compiled image and steps it."""
    repo = pathlib.Path(__file__).resolve().parents[2]
    text = (repo / catalogue.FIRMWARE_VERIFIED["RP2040"]).read_text(encoding="utf-8")
    assert "blink.bin" in text and "cpu.step()" in text


# --- the description convention --------------------------------------------


def test_a_chip_is_described_when_a_module_of_that_name_exists():
    """`rp2040.py` describing an RP2040 is a convention rather than a registry,
    so adding a chip is adding one file."""
    assert "RP2040" in catalogue.described_chips()


def test_the_catalogue_module_is_not_mistaken_for_a_board_description():
    assert "CATALOGUE" not in catalogue.described_chips()
    assert "__INIT__" not in catalogue.described_chips()


def test_board_names_come_from_the_files_rather_than_a_list(tmp_path):
    (tmp_path / "Some-Board.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    assert catalogue.board_names(tmp_path) == ["Some-Board"]


def test_the_json_a_ui_receives_carries_all_three_facts_separately():
    payload = catalogue.catalogue()[0].as_json()
    for key in ("chip", "isa", "core_exists", "core_built", "described", "runnable"):
        assert key in payload, f"the UI cannot distinguish without {key}"


def test_the_boards_directory_is_where_this_looks(tmp_path):
    assert catalogue.BOARDS_DIR == pathlib.Path(catalogue.__file__).resolve().parent


# --- the copy the UI shows --------------------------------------------------


def test_the_targets_copy_does_not_still_claim_formats_one_to_four():
    """A guard on prose, because prose is what goes stale.

    The panel said "implements Thumb formats 1-4 only" and stayed saying it
    after formats 5-19 landed -- true when written, wrong within the day, and
    invisible to every test in the suite. Caught by looking at the rendered
    page, which is why this now has a test.
    """
    page = (pathlib.Path(__file__).resolve().parents[2]
            / "webui" / "static" / "emulator.html").read_text(encoding="utf-8")
    assert "formats 1–4 only" not in page
    assert "not</em> enough to run a board" not in page


def test_the_targets_copy_does_not_claim_every_chip_lacks_a_core():
    """Two chips have one now: RP2040 and SAMD21 share cortexm0."""
    page = (pathlib.Path(__file__).resolve().parents[2]
            / "webui" / "static" / "emulator.html").read_text(encoding="utf-8")
    assert "Every chip in the tables below has no core directory at all" not in page


# --- the route the UI actually calls ----------------------------------------
#
# There was none of this, and the gap cost exactly what it was always going to.
# `missing_cores` changed from a dict to a list, `emulator_server` kept calling
# `.items()`, 340 tests passed, and the Boards view rendered empty with an
# ERR_EMPTY_RESPONSE in the console. Nothing between the catalogue and the
# browser was under test.


def test_the_boards_route_answers_without_raising():
    from webui import emulator_server

    payload = emulator_server.handle_api(
        None, emulator_server.Selection(), "/api/boards", {}, {}
    )
    assert payload["boards"] and payload["waiting"]


def test_the_boards_route_is_json_serialisable():
    """The handler's answer goes through `json.dumps` in the server. A value
    that is not serialisable is a 500 the tests never see."""
    import json

    from webui import emulator_server

    payload = emulator_server.handle_api(
        None, emulator_server.Selection(), "/api/boards", {}, {}
    )
    json.dumps(payload)


def test_the_boards_route_carries_what_the_ui_reads():
    """Named field by field, because the UI reads them by name and a rename
    here renders an empty table rather than an error."""
    from webui import emulator_server

    payload = emulator_server.handle_api(
        None, emulator_server.Selection(), "/api/boards", {}, {}
    )
    board = payload["boards"][0]
    for key in ("name", "chip", "isa", "core", "core_exists", "core_built",
                "described", "runnable", "firmware_verified"):
        assert key in board, f"emulator.js reads board.{key}"
    row = payload["waiting"][0]
    for key in ("core", "boards", "exists", "oracle"):
        assert key in row, f"emulator.js reads group.{key}"
