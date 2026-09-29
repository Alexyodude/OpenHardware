# OpenHardware - a board that is not a XIAO footprint, as a row (OH-176).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import dataclasses
import json
import re

import pytest

from tools import board_manifest, eagle, import_board, import_pindefs
from tools.board_manifest import ROWS, ManifestError
from webui.boards import catalogue


def _fetched(row: board_manifest.Row) -> None:
    """Skip, naming what is missing, where a row's inputs were never fetched."""
    try:
        board_manifest.check(row)
    except ManifestError as exc:
        if "not on disk" not in str(exc):
            raise
        pytest.skip(f"SKIPPED: {exc}")


def _committed(row: board_manifest.Row) -> dict:
    path = board_manifest.BOARDS_DIR / f"{row.board}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --- a row whose inputs are not there is refused, naming them ----------------


def test_a_row_whose_cad_file_is_missing_is_refused_naming_it():
    row = dataclasses.replace(ROWS[0], board="Nowhere", cad="Hardware/Missing.brd")
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    message = str(caught.value)
    assert f"third_party/{row.source}/Hardware/Missing.brd" in message, message
    assert f"python tools/get_board_sources.py {row.source}" in message, message
    assert not (board_manifest.BOARDS_DIR / "Nowhere.json").exists()


def test_a_row_whose_variant_is_missing_is_refused_naming_it():
    row = dataclasses.replace(ROWS[0], board="Nowhere", variant="no_such_variant")
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    message = str(caught.value)
    assert (f"third_party/bsp/{row.package}/variants/no_such_variant/pins_arduino.h"
            in message), message
    assert not (board_manifest.BOARDS_DIR / "Nowhere.json").exists()


def test_a_row_naming_a_source_the_registry_does_not_hold_is_refused():
    row = dataclasses.replace(ROWS[0], board="Nowhere", source="no-such-source")
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    assert "no-such-source" in str(caught.value), caught.value
    assert not (board_manifest.BOARDS_DIR / "Nowhere.json").exists()


def test_a_row_selecting_an_element_with_no_header_pads_writes_nothing():
    """The inputs are all there and the CAD still cannot answer: refused
    before the file is opened for writing, not after."""
    _fetched(ROWS[0])
    row = dataclasses.replace(ROWS[0], board="Nowhere", select=("U1",))
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    assert "'U1'" in str(caught.value), caught.value
    assert not (board_manifest.BOARDS_DIR / "Nowhere.json").exists()


def test_a_row_naming_a_chip_its_variant_is_not_built_for_is_refused():
    """The chip is the row's claim, and the package's `boards.txt` checks it."""
    _fetched(ROWS[0])
    row = dataclasses.replace(ROWS[0], chip="ESP32-C3")
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(row)
    assert "build.mcu=esp32c3" in str(caught.value), caught.value


def test_a_package_whose_pin_number_is_not_the_gpio_is_refused():
    """`seeed-samd`'s `D6 = 6` is an index into its own table, not a pin."""
    row = dataclasses.replace(ROWS[0], package="seeed-samd")
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(row)
    assert "seeed-samd" in str(caught.value), caught.value


# --- the committed file is what its row generates ----------------------------


def test_every_row_file_is_what_import_board_writes_from_the_row():
    """The geometry half. The pin half is held, for every registered board,
    by `test_the_committed_board_files_match_the_generator`."""
    for row in ROWS:
        _fetched(row)
        generated = board_manifest.geometry(row)
        committed = _committed(row)
        for key in ("board", "px_per_mm", "image", "derivation", "source"):
            assert committed[key] == generated[key], (row.board, key)
        fields = ("label", "pin", "x", "y", "group", "pad")
        assert [{k: pad[k] for k in fields} for pad in committed["pads"]] == [
            {k: pad[k] for k in fields} for pad in generated["pads"]
        ], row.board


def test_every_pad_is_where_the_vendors_board_file_puts_it():
    """Read the elements again, straight off the vendor's file, and put every
    committed pad back into its millimetres: EAGLE's Y points up, the file's
    down, and the file adds `MARGIN_MM` on each side."""
    for row in ROWS:
        _fetched(row)
        board = eagle.read_board(board_manifest.cad_path(row))
        min_x, _, _, max_y = board.extent_mm()
        vendor = {
            pad.number: pad
            for name in row.select
            for pad in board.element(name).pads_of("thru_hole")
        }
        committed = _committed(row)
        scale = committed["px_per_mm"]
        assert sorted(vendor) == sorted(pad["pad"] for pad in committed["pads"]), row.board
        for pad in committed["pads"]:
            source = vendor[pad["pad"]]
            margin = import_board.MARGIN_MM
            assert abs(pad["x"] / scale - (source.x_mm - min_x + margin)) <= 0.05 / scale
            assert abs(pad["y"] / scale - (max_y - source.y_mm + margin)) <= 0.05 / scale
            assert pad["label"] == source.net, (row.board, pad["pad"])


# --- the pins come from the variant the row names -----------------------------


def test_every_resolved_pad_was_named_by_the_rows_variant():
    """And every label the row opts in names a pad: an opt-in that matches
    nothing is a claim in the table that the file never uses."""
    for row in ROWS:
        _fetched(row)
        report = import_pindefs.board_report(row.board)
        resolved = [pad for pad in report["pads"] if pad["chip_pin"]]
        assert resolved, row.board
        cited = f"{row.package} variants/{row.variant}/pins_arduino.h @ "
        for pad in resolved:
            assert [s[:len(cited)] for s in pad["sources"]] == [cited], pad
            assert pad["matched"] in row.labels, pad
        assert sorted({pad["matched"] for pad in resolved}) == sorted(row.labels), (
            row.board
        )


def test_every_resolved_pin_is_the_gpio_the_vendors_net_names():
    """Two vendors, one answer: the variant says `TX = 16`, and SparkFun's
    own net on that pad is `IO16/TX`. Every resolved pad is cross-checked,
    so a row whose nets name no `IO<n>` has to decide what to check instead."""
    for row in ROWS:
        _fetched(row)
        resolved = [pad for pad in _committed(row)["pads"] if pad["chip_pin"]]
        assert resolved, row.board
        for pad in resolved:
            stated = [int(found.group(1)) for part in pad["label"].split("/")
                      if (found := re.fullmatch(r"IO(\d+)", part))]
            assert stated == [pad["chip_index"]], (row.board, pad)


def test_no_row_label_keys_its_chips_module_table():
    """Each row's `assumption` says no level is read through its chip
    module's table for any pad; `webui.api.header_key` is that join."""
    from webui import api

    checked = []
    for row in ROWS:
        names = getattr(api.description_for(row.board), "PIN_NAMES", None)
        if names is None:
            continue
        committed = _committed(row)
        assert "no level is read through it for any pad here" in committed["assumption"]
        for pad in committed["pads"]:
            assert api.header_key(pad["label"], names) not in names, (row.board, pad)
        checked.append(row.board)
    assert checked, "no row's chip has a module, so nothing here was checked"


# --- the chip comes from the row --------------------------------------------


def test_every_rows_chip_is_the_catalogues():
    for row in ROWS:
        assert row.chip in catalogue.CHIPS, row
        assert catalogue.chip_for(row.board) == row.chip
        assert import_pindefs.BOARDS[row.board].chip == row.chip


def test_no_row_inherits_its_chips_evidence():
    """rules/board-claims.md §6: the register stays keyed by chip, and a row,
    which no recipe builds against its own variant, carries none of it."""
    boards = {board.name: board for board in catalogue.catalogue()}
    for row in ROWS:
        assert row.chip in catalogue.FIRMWARE_VERIFIED, row.chip
        board = boards[row.board]
        assert board.firmware_evidence is None, board
        assert board.firmware_verified is False
        assert f"variants/{row.variant}" in board.firmware_withheld
        assert "OH-179" in board.firmware_withheld
    # And the XIAO sibling keeps it: the register was not weakened.
    assert boards["XIAO-ESP32-C6-DIP"].firmware_verified is True
    assert boards["XIAO-ESP32-C6-DIP"].firmware_withheld is None
