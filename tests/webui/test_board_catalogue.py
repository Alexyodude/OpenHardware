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


def test_the_backlog_lists_instruction_sets_with_the_boards_each_blocks():
    waiting = catalogue.missing_cores()
    assert waiting, "everything cannot already be runnable"
    assert all(isinstance(v, list) and v for v in waiting.values())


def test_the_backlog_is_ordered_by_how_many_boards_each_would_unlock():
    """The only ordering this backlog has that is not a guess."""
    counts = [len(v) for v in catalogue.missing_cores().values()]
    assert counts == sorted(counts, reverse=True)


def test_the_runnable_boards_are_absent_from_the_backlog():
    waiting = {name for names in catalogue.missing_cores().values() for name in names}
    for board in catalogue.catalogue():
        if board.runnable:
            assert board.name not in waiting


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
