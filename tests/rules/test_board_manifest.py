# OpenHardware - a board that is not a XIAO footprint, as a row (OH-176).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import dataclasses
import itertools
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from tools import (
    board_manifest,
    board_sources,
    eagle,
    import_board,
    import_pindefs,
    import_schematic,
    kicad,
)
from tools.board_manifest import ROWS, ManifestError
from webui import pinmap
from webui.boards import catalogue

#: The real directory, kept before any test points `BOARDS_DIR` elsewhere.
COMMITTED = board_manifest.BOARDS_DIR


def _fetched(row: board_manifest.Row) -> None:
    """Skip, naming what is missing, where a row's inputs were never fetched,
    or where its variant can be read only by a preprocessor this machine does
    not have -- the refusal names the command that installs it (OH-181)."""
    try:
        board_manifest.check(row)
    except ManifestError as exc:
        if "not on disk" not in str(exc) and "only the preprocessor can say" not in str(exc):
            raise
        pytest.skip(f"SKIPPED: {exc}")


def _committed(row: board_manifest.Row) -> dict:
    return json.loads((COMMITTED / f"{row.board}.json").read_text(encoding="utf-8"))


# --- a row whose inputs are not there is refused, naming them ----------------


def test_a_row_whose_cad_file_is_missing_is_refused_naming_it(tmp_path, monkeypatch):
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    row = dataclasses.replace(ROWS[0], board="Nowhere", cad="Hardware/Missing.brd")
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    message = str(caught.value)
    assert f"third_party/{row.source}/Hardware/Missing.brd" in message, message
    assert f"python tools/get_board_sources.py {row.source}" in message, message
    assert list(tmp_path.iterdir()) == []


def test_a_row_whose_variant_is_missing_is_refused_naming_it(tmp_path, monkeypatch):
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    row = dataclasses.replace(ROWS[0], board="Nowhere", variant="no_such_variant")
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    message = str(caught.value)
    assert (f"third_party/bsp/{row.package}/variants/no_such_variant/pins_arduino.h"
            in message), message
    assert list(tmp_path.iterdir()) == []


def test_a_row_naming_a_source_the_registry_does_not_hold_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    row = dataclasses.replace(ROWS[0], board="Nowhere", source="no-such-source")
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    assert "no-such-source" in str(caught.value), caught.value
    assert list(tmp_path.iterdir()) == []


def test_a_row_selecting_an_element_with_no_header_pads_writes_nothing(tmp_path, monkeypatch):
    """The inputs are all there and the CAD still cannot answer."""
    _fetched(ROWS[0])
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    monkeypatch.setattr(board_manifest, "ROWS", (dataclasses.replace(ROWS[0], select=("U1",)),))
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(board_manifest.ROWS[0])
    assert "'U1'" in str(caught.value), caught.value
    assert list(tmp_path.iterdir()) == []


def test_a_row_naming_a_chip_its_variant_is_not_built_for_is_refused():
    """The chip is the row's claim, and the package's `boards.txt` checks it."""
    _fetched(ROWS[0])
    row = dataclasses.replace(ROWS[0], chip="ESP32-C3")
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(row)
    assert "build.mcu=['esp32c6']" in str(caught.value), caught.value


def test_a_package_whose_pin_number_is_not_the_gpio_is_refused():
    """`seeed-samd`'s `D6 = 6` is an index into its own table, not a pin."""
    row = dataclasses.replace(ROWS[0], package="seeed-samd")
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(row)
    assert "whose Arduino pin number is the GPIO" in str(caught.value), caught.value


def test_a_label_the_variant_does_not_number_is_refused_by_the_check():
    """`LED_BUILTIN` on this variant is `SOC_GPIO_PIN_COUNT + PIN_RGB_LED`,
    an expression and not a pin, so `LED` has no number to give."""
    _fetched(ROWS[0])
    row = dataclasses.replace(ROWS[0], labels=ROWS[0].labels + ("LED",))
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(row)
    assert "'LED' is registered as an extra label" in str(caught.value), caught.value


def test_a_licence_the_cad_file_does_not_state_is_refused():
    _fetched(ROWS[0])
    row = dataclasses.replace(ROWS[0], licence_statement=("FRAME1", "Public domain"))
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(row)
    assert "does not read 'Public domain'" in str(caught.value), caught.value


# --- a row that fails leaves webui/boards/ as it was --------------------------


def _bad_label_row(tmp_path, monkeypatch) -> tuple[board_manifest.Row, bytes]:
    """The committed file copied into a scratch `BOARDS_DIR`, and a registered
    row whose label the variant does not number, as a hand edit to ROWS makes."""
    committed = (COMMITTED / f"{ROWS[0].board}.json").read_bytes()
    (tmp_path / f"{ROWS[0].board}.json").write_bytes(committed)
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    bad = dataclasses.replace(ROWS[0], labels=ROWS[0].labels + ("LED",))
    monkeypatch.setattr(board_manifest, "ROWS", (bad,))
    monkeypatch.setitem(import_pindefs.BOARDS, bad.board, import_pindefs.Board(
        bad.chip,
        (import_pindefs.arduino_flat(bad.package, bad.variant, extras=bad.labels),),
        reasons=bad.reasons,
    ))
    return bad, committed


def test_a_failing_row_exits_two_and_leaves_the_file_it_would_replace(tmp_path, monkeypatch, capsys):
    _fetched(ROWS[0])
    bad, committed = _bad_label_row(tmp_path, monkeypatch)
    assert board_manifest.main([]) == 2
    assert "'LED'" in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir()] == [f"{bad.board}.json"]
    assert (tmp_path / f"{bad.board}.json").read_bytes() == committed


def test_a_row_past_the_check_still_writes_nothing_when_the_pins_fail(tmp_path, monkeypatch, capsys):
    """The check is not what protects the file: with it switched off, the
    pin join fails on the same label, and nothing has been written yet."""
    _fetched(ROWS[0])
    bad, committed = _bad_label_row(tmp_path, monkeypatch)
    monkeypatch.setattr(board_manifest, "check", lambda entry: None)
    assert board_manifest.main([]) == 2
    assert "'LED'" in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir()] == [f"{bad.board}.json"]
    assert (tmp_path / f"{bad.board}.json").read_bytes() == committed


# --- a package whose boards.txt spells the part another way ------------------


def test_an_arduino_pico_row_is_checked_against_build_chip():
    """arduino-pico's `build.mcu` is `cortex-m0plus`; the part is `build.chip`."""
    if not (import_pindefs.BSP_DIR / "arduino-pico" / "boards.txt").is_file():
        pytest.skip("SKIPPED: arduino-pico is not fetched; run python tools/import_pindefs.py --fetch")
    _fetched(ROWS[0])
    pico = dataclasses.replace(
        ROWS[0], chip="RP2040", package="arduino-pico", variant="rpipico", labels=("LED",)
    )
    _fetched(pico)
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(dataclasses.replace(pico, chip="RP2350"))
    assert "build.chip=['rp2040']" in str(caught.value), caught.value


def test_a_part_under_a_menu_is_read_once_per_option():
    """`rpipico2` names no top-level `build.chip`; each `arch` option names one."""
    table = import_pindefs.BSP_DIR / "arduino-pico" / "boards.txt"
    if not table.is_file():
        pytest.skip("SKIPPED: arduino-pico is not fetched; run python tools/import_pindefs.py --fetch")
    assert board_manifest.chips_building(table, "rpipico2", "build.chip") == {
        "rp2350", "rp2350-riscv"}


# --- only a registered row is written ----------------------------------------


def test_a_row_not_in_rows_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    """import_pindefs registers ROWS as it loads, so a row built elsewhere has
    no pin registration to fill it: it is refused, naming why."""
    _fetched(ROWS[0])
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(dataclasses.replace(ROWS[0], board="Nowhere"))
    assert "only a row in ROWS is written" in str(caught.value), caught.value
    assert list(tmp_path.iterdir()) == []


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
        assert committed["derivation"].startswith(
            "Generated by `python tools/board_manifest.py`"), committed["derivation"]
        fields = ("label", "pin", "x", "y", "group", "pad")
        assert [{k: pad[k] for k in fields} for pad in committed["pads"]] == [
            {k: pad[k] for k in fields} for pad in generated["pads"]
        ], row.board


def test_a_row_names_no_artwork_file():
    """OH-179: `image.file` named an SVG nothing generates. A row's `image`
    is the width and height `webui/pinmap.py` reads, and no file."""
    for row in ROWS:
        _fetched(row)
        assert set(board_manifest.geometry(row)["image"]) == {"width", "height"}, row.board
        assert set(_committed(row)["image"]) == {"width", "height"}, row.board
        assert pinmap.load(row.board).width == _committed(row)["image"]["width"]


def test_a_row_written_into_an_empty_directory_is_the_committed_file(tmp_path, monkeypatch):
    """`write()` whole, as `python tools/board_manifest.py` runs it, into a
    directory holding no chip module: the chip's module is read from where
    the modules are, not from where the file is written. Compared byte for
    byte, newlines normalised because this worktree checks files out CRLF."""
    for row in ROWS:
        _fetched(row)
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    for row in ROWS:
        path = board_manifest.write(row)
        assert path == tmp_path / f"{row.board}.json"
        committed = (COMMITTED / f"{row.board}.json").read_bytes()
        assert path.read_bytes().replace(b"\r\n", b"\n") == committed.replace(
            b"\r\n", b"\n"), row.board


def row_named(name: str) -> board_manifest.Row:
    return next(row for row in ROWS if row.board == name)


def _placed(row: board_manifest.Row, name: str) -> kicad.Placement:
    """The one footprint of a KiCad row's board file with this reference."""
    (placed,) = [one for one in kicad.read_board(board_manifest.cad_path(row)).placements
                 if one.reference == name]
    return placed


def _pins_stated(row: board_manifest.Row) -> dict[str, list[list[str]]]:
    """Per selected element, the pads each pin connects to, read straight off
    the vendor's schematic: part, then its library's device, then `<connect>`.
    A KiCad row names no schematic, and its board file states the same by
    number: a footprint's through-hole pads of one number are one pin."""
    if row.schematic is None:
        stated = {}
        for name in row.select:
            numbers = [pad.number for pad in _placed(row, name).pads if pad.kind == "thru_hole"]
            stated[name] = [[number] * numbers.count(number)
                            for number in dict.fromkeys(numbers)]
        return stated
    path = board_sources.source(row.source).dest(board_manifest.REPO) / row.schematic
    root = ET.parse(path).getroot().find("drawing/schematic")
    stated = {}
    for name in row.select:
        part = root.find(f"parts/part[@name='{name}']")
        (device,) = root.findall(
            f"libraries/library[@name='{part.get('library')}']/devicesets/deviceset"
            f"[@name='{part.get('deviceset')}']/devices/device[@name='{part.get('device')}']")
        stated[name] = [c.get("pad").split() for c in device.findall("connects/connect")]
    return stated


def test_every_pin_the_schematic_states_is_one_pad():
    """The QT Py's castellated pins are two pads each, `1` and `1C`, and its
    schematic connects both to one pin: 14 pins, not 28 pads. The rule that
    places the one pad is stated in the file whenever it merged anything."""
    for row in ROWS:
        _fetched(row)
        stated = _pins_stated(row)
        committed = _committed(row)
        merged = sum(len(pads) - 1 for pins in stated.values() for pads in pins)
        assert len(committed["pads"]) == sum(len(pins) for pins in stated.values()), row.board
        rule = ("Where the schematic's device connects one pin to several pads, they "
                "are one pad here, at the pad its <connect> names first; "
                f"{merged} pads were merged so." if row.schematic is not None else
                "Where a footprint gives several pads on one net one number, they are "
                "one pin and one pad here, at the first of them KiCad does not flag "
                f"castellated")
        assert (rule in committed["derivation"]) == bool(merged), (row.board, merged)
        assert (f"{merged} pads were merged so." in committed["derivation"]) == bool(
            merged), (row.board, merged)
    assert len(_committed(row_named("Adafruit QT Py ESP32-C3"))["pads"]) == 14
    # Each of the Glyph Mini's 23 pins is a hole and a castellated half-hole.
    assert len(_committed(row_named("PCBCUPID Glyph Mini RP2040"))["pads"]) == 23


def test_the_feathers_two_33v_pins_stay_two_pads():
    """Two pins on one net, each its own `<connect>`: two pads."""
    row = row_named("Adafruit Feather ESP32-C6")
    _fetched(row)
    assert [["14"], ["15"]] == [pads for pads in _pins_stated(row)["JP1"]
                                if pads in (["14"], ["15"])]
    assert sorted(pad["pad"] for pad in _committed(row)["pads"]
                  if pad["label"] == "3.3V") == ["14", "15"]


def test_a_row_whose_schematic_is_missing_is_refused_naming_it(tmp_path, monkeypatch):
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    row = dataclasses.replace(ROWS[0], board="Nowhere", schematic="Hardware/Missing.sch")
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    message = str(caught.value)
    assert f"third_party/{row.source}/Hardware/Missing.sch" in message, message
    assert f"python tools/get_board_sources.py {row.source}" in message, message
    assert list(tmp_path.iterdir()) == []


def test_a_schematic_that_places_no_part_of_that_name_is_refused():
    """The pilot's schematic asked for an Adafruit header's name."""
    _fetched(ROWS[0])
    with pytest.raises(ManifestError) as caught:
        board_manifest.connects(dataclasses.replace(ROWS[0], select=("JP1",)))
    assert "places no part 'JP1'" in str(caught.value), caught.value


def test_every_pad_is_where_the_vendors_board_file_puts_it():
    """Read the elements again, straight off the vendor's file, and match every
    committed pad to one of them by number and millimetres: EAGLE's Y points
    up, the file's down, and the file adds `MARGIN_MM` on each side. Keyed by
    element and number, because two elements can both have a pad 1. The pad
    kept for a pin is the first its schematic `<connect>` names. A KiCad
    board's Y already runs down, each pad is placed by its footprint's
    position and turn, and the pad kept for a pin is its whole hole, the one
    KiCad does not flag castellated."""
    margin = import_board.MARGIN_MM
    for row in ROWS:
        _fetched(row)
        firsts = {(name, pads[0]) for name, pins in _pins_stated(row).items() for pads in pins}
        # (element, number) -> (x, y) in the file's millimetres, and the net.
        vendor: dict[tuple[str, str], tuple[float, float, str]] = {}
        if row.schematic is None:
            min_x, min_y, _, _ = kicad.read_board(board_manifest.cad_path(row)).extent_mm()
            for name in row.select:
                placed = _placed(row, name)
                for pad in placed.pads:
                    if (pad.kind == "thru_hole" and not pad.castellated
                            and (name, pad.number) not in vendor):
                        x, y = kicad.pad_on_board(placed, pad)
                        vendor[(name, pad.number)] = (
                            x - min_x + margin, y - min_y + margin, pad.net)
        else:
            board = eagle.read_board(board_manifest.cad_path(row))
            min_x, _, _, max_y = board.extent_mm()
            vendor = {
                (name, pad.number): (pad.x_mm - min_x + margin, max_y - pad.y_mm + margin,
                                     pad.net)
                for name in row.select
                for pad in board.element(name).pads_of("thru_hole")
                if (name, pad.number) in firsts
            }
        assert set(vendor) == firsts, row.board
        committed = _committed(row)
        scale = committed["px_per_mm"]
        matched = []
        for pad in committed["pads"]:
            hits = [
                key for key, (x, y, _) in vendor.items()
                if key[1] == pad["pad"]
                and abs(pad["x"] / scale - x) <= 0.05 / scale
                and abs(pad["y"] / scale - y) <= 0.05 / scale
            ]
            assert len(hits) == 1, (row.board, pad, hits)
            assert pad["label"] == vendor[hits[0]][2], (row.board, pad["pad"])
            if row.schematic is None:
                # A KiCad board's pads are grouped by their footprint.
                assert pad["group"] == hits[0][0], (row.board, pad)
            matched.append(hits[0])
        assert sorted(matched) == sorted(vendor), row.board


def test_the_licence_is_what_the_vendors_own_files_state():
    """SparkFun's registry licence is inferred from a sibling repository, so
    that board quotes the sentence its own CAD file places; a row whose
    registry licence was read from a file it fetches quotes that file."""
    stated = []
    for row in ROWS:
        _fetched(row)
        evidence = _committed(row)["source"]["licence_evidence"]
        assert evidence == board_manifest.licence_evidence(row)
        licence = board_sources.source(row.source).licence
        quote = row.licence_statement[1] if row.licence_statement else licence.quote
        assert repr(quote) in evidence
        # A README's word is recorded as that and no more (OH-194).
        graded = row.licence_statement is None and licence.evidence is board_sources.Evidence.STATED
        assert ("; graded stated: " in evidence) == graded, (row.board, evidence)
        stated += [row.board] if graded else []
        # A README that asks for its text in any redistribution has it, whole.
        if row.licence_statement is None and licence.notice:
            assert evidence.endswith(f"reads in full {licence.notice!r}"), row.board
            assert licence.notice.endswith(
                "All text above must be included in any redistribution"), row.board
    assert "PCBCUPID Glyph C3" in stated
    assert [row.board for row in ROWS if row.licence_statement is None
            and board_sources.source(row.source).licence.notice] == [
        "PCBCUPID Glyph C3", "PCBCUPID Glyph C6"]


def test_a_row_whose_licence_is_stated_nowhere_is_refused():
    """SparkFun's registry licence came from a sibling repository, not a file."""
    _fetched(ROWS[0])
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(dataclasses.replace(ROWS[0], licence_statement=None))
    assert "licence from no file it fetches" in str(caught.value), caught.value


def _file_licensed() -> board_manifest.Row:
    row = next(row for row in ROWS if row.licence_statement is None)
    _fetched(row)
    return row


def _registry_with(monkeypatch, name: str, **licence) -> None:
    """The registry with one source's licence fields replaced."""
    monkeypatch.setattr(board_sources, "SOURCES", tuple(
        source._replace(licence=source.licence._replace(**licence))
        if source.name == name else source
        for source in board_sources.SOURCES
    ))


def test_a_licence_file_that_does_not_read_the_registrys_words_is_refused(monkeypatch):
    row = _file_licensed()
    _registry_with(monkeypatch, row.source, quote="Attribution-ShareAlike 4.0 International")
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(row)
    assert "does not read 'Attribution-ShareAlike 4.0 International'" in str(caught.value)


def test_a_licence_file_that_does_not_read_its_notice_is_refused(monkeypatch):
    """The text a README asks any redistribution to carry is checked against
    the README as the licence line is (OH-194)."""
    row = row_named("PCBCUPID Glyph C3")
    _fetched(row)
    _registry_with(monkeypatch, row.source, notice="All text below may be dropped")
    with pytest.raises(ManifestError) as caught:
        board_manifest.check(row)
    assert "does not read 'All text below may be dropped'" in str(caught.value)


def test_a_licence_file_that_is_not_on_disk_is_refused_naming_it(tmp_path, monkeypatch):
    row = _file_licensed()
    _registry_with(monkeypatch, row.source, file="LICENCE-nowhere.txt")
    monkeypatch.setattr(board_manifest, "BOARDS_DIR", tmp_path)
    with pytest.raises(ManifestError) as caught:
        board_manifest.write(row)
    message = str(caught.value)
    assert f"third_party/{row.source}/LICENCE-nowhere.txt" in message, message
    assert f"python tools/get_board_sources.py {row.source}" in message, message
    assert list(tmp_path.iterdir()) == []


# --- the pins: the variant by label, the vendor's CAD by copper (OH-178) -------


def _variant_numbers(row: board_manifest.Row) -> dict[str, int]:
    """What the row's variant numbers -- its `D<n>` and the labels it opts
    in -- read as import_pindefs reads it: through the preprocessor for
    arduino-pico, whose `D<n>` are in `variants/generic/common.h` (OH-181)."""
    checkout = import_pindefs.BSP_DIR / row.package
    text = (checkout / "variants" / row.variant / "pins_arduino.h").read_text(
        encoding="utf-8", errors="replace")
    pins, _ = import_pindefs.variant_source(row).pins(checkout, (text,))
    return {label: pin.index for label, pin in pins.items()}


def test_every_resolved_pad_says_which_sources_named_it():
    """OH-173's question, answered in the file: `chip_pin_from` names the
    variant where one of the pad's labels is a label it numbers -- a `D<n>`,
    or one the row opts in -- and the row's own CAD, which traces every
    resolved pad on every row. Every opted-in label names a pad: an opt-in
    that matches nothing is a claim in the table that the file never uses."""
    for row in ROWS:
        _fetched(row)
        numbers = _variant_numbers(row)
        matched = set()
        resolved = [pad for pad in _committed(row)["pads"] if pad["chip_pin"]]
        assert resolved, row.board
        for pad in _committed(row)["pads"]:
            if pad["chip_pin"] is None:
                assert "chip_pin_from" not in pad, (row.board, pad["label"])
                continue
            named = {alt for alt in import_pindefs.alternatives(pad["label"])
                     if alt in numbers}
            matched |= named & set(row.labels)
            assert pad["chip_pin_from"] == sorted(
                {row.source} | ({row.package} if named else set())), (row.board, pad)
        assert matched == set(row.labels), row.board


def _pin_functions(row: board_manifest.Row) -> dict[str, set[str]]:
    """Net -> the pin names a KiCad row's board file gives the chip's pads
    on it (`pinfunction`, its symbol's pin name), off the file's own tree.
    A footprint's value is a `(property "Value" ...)` from KiCad 8, and an
    `(fp_text value ...)` before, as in the Olimex's KiCad 7 file. A KiCad 5
    file places it as a `(module ...)`, which `kicad.board_tree` spells as a
    footprint, and gives a pad no `pinfunction`: that arrived with KiCad 6."""
    tree = kicad.board_tree(board_manifest.cad_path(row))
    (chip,) = [node for node in kicad.children(tree, "footprint")
               if node[1].split(":")[-1] == row.pin_table.package
               and [*(prop[2] for prop in kicad.children(node, "property")
                      if prop[1] == "Value"),
                    *(text[2] for text in kicad.children(node, "fp_text")
                      if text[1] == "value")] == [row.pin_table.value]]
    functions: dict[str, set[str]] = {}
    for pad in kicad.children(chip, "pad"):
        net, function = kicad.first(pad, "net"), kicad.first(pad, "pinfunction")
        if net is not None and function is not None:
            functions.setdefault(net[-1], set()).add(function[1])
    return functions


def _schematic_gpio(row: board_manifest.Row) -> dict[str, set[int]]:
    """Net -> the GPIOs the row's schematic names on the traced chip's own
    pins there: `GPIO26/AD0` on the KB2040's `A0`, and `IOA0` on the Pro
    Micro ESP32-C3's `IOA0/SCLK`, where SparkFun's ESP32-C3_MINI-1 symbol
    names its five ADC1 pins `IOA<n>` and every other GPIO `IO<n>`. Read on
    the chip's pins only: nowhere else is `IOA<n>` the chip's name for a pin.
    A KiCad row names no schematic, and its board file gives each of the
    chip's pads the pin name of the vendor's symbol, `pinfunction`:
    `GPIO26_ADC0` on the Glyph Mini's `/GPIO-26`, `IO4` on the Glyph C3's
    `/SDA`, and `MTMS/IOA2` on the SparkFun Thing Plus ESP32-C5's `IOA2`,
    whose ESP32-C5-WROOM-1 symbol names its six ADC1 pins `IOA<n>` as the
    Pro Micro's does. Read here off the file's own tree, not through a
    reader."""
    if row.schematic is None:
        named: dict[str, set[int]] = {}
        for net, functions in _pin_functions(row).items():
            named[net] = {int(found.group(1)) for function in functions
                          for part in re.split(r"[/_]", function)
                          if (found := re.fullmatch(r"(?:GPIO|IOA?)(\d+)", part))}
        return named
    board = eagle.read_board(board_manifest.cad_path(row))
    (chip,) = [element.name for element in board.elements if (element.package, element.value)
               == (row.pin_table.package, row.pin_table.value)]
    schematic = eagle.read_schematic(
        board_sources.source(row.source).dest(board_manifest.REPO) / row.schematic)
    return {net.name: {int(found.group(1)) for ref in net.pins if ref.part == chip
                       for part in ref.pin.split("/")
                       if (found := re.fullmatch(r"(?:GPIO|IOA?)(\d+)", part, re.I))}
            for net in schematic.nets}


#: Resolved pads whose one statement is the trace, each with the pin name
#: the vendor's symbol gives the chip pad its copper reaches. PCBCUPID's
#: `/uRx` and `/uTx` carry no number and no label a variant numbers, and its
#: symbol names each module's pins 30 and 31 `RXD0` and `TXD0`, the names
#: Table 3-1 gives them, which carry none either. Held to that name, so a
#: footprint numbered otherwise than the page still fails.
TRACE_ONLY = {
    ("PCBCUPID Glyph C3", "/uRx"): "RXD0",
    ("PCBCUPID Glyph C3", "/uTx"): "TXD0",
    ("PCBCUPID Glyph C6", "/uRx"): "RXD0",
    ("PCBCUPID Glyph C6", "/uTx"): "TXD0",
}


def test_every_resolved_pin_is_the_gpio_a_second_vendor_statement_names():
    """The trace is one statement, and every resolved pad has another that
    agrees: the GPIO the vendor's net name carries, as SparkFun's `IO8` and
    PCBCUPID's `/GPIO-8` and `/GPIO_8`; the variant's number for a label it
    numbers, as Adafruit's `TX`; or the GPIO the vendor's schematic names the
    chip's pin on that net, as the KB2040's `SCLK` on `GPIO18`, which its
    variant calls `SCK`, the Pro Micro ESP32-C3's `IOA0/SCLK` on its module's
    `IOA0`, and the Glyph Mini's and the Glyph C3's symbol on each chip pin.
    The pads with none are `TRACE_ONLY`, each held to its symbol's name. A
    KiCad net's `/` is written `{slash}`: SparkFun's `IO23{slash}SDA`. Olimex
    names a GPIO and then what it is for after a backslash, `/GPIO8\\USER_LED1`,
    and its KiCad 5 ESP32-C6-EVB carries no `pinfunction`, so there the net's
    own name is the second statement."""
    alone = set()
    for row in ROWS:
        _fetched(row)
        numbers = _variant_numbers(row)
        named = _schematic_gpio(row)
        for pad in _committed(row)["pads"]:
            if pad["chip_pin"] is None:
                continue
            parts = re.split(r"/|\\|\{slash\}", pad["label"])
            stated = {int(found.group(1)) for part in parts
                      if (found := re.fullmatch(r"(?:GPIO|IO)[-_]?(\d+)", part, re.I))}
            stated |= {numbers[part] for part in parts if part in numbers}
            stated |= named.get(pad["label"], set())
            if (row.board, pad["label"]) in TRACE_ONLY:
                assert stated == set(), (row.board, pad["label"], stated)
                assert _pin_functions(row)[pad["label"]] == {
                    TRACE_ONLY[(row.board, pad["label"])]}, (row.board, pad["label"])
                alone.add((row.board, pad["label"]))
                continue
            assert stated == {pad["chip_index"]}, (row.board, pad["label"], stated)
    assert alone == set(TRACE_ONLY)
    kb2040 = row_named("Adafruit KB2040")
    assert "SCLK" not in _variant_numbers(kb2040)
    assert _schematic_gpio(kb2040)["SCLK"] == {18}
    pro_micro = row_named("SparkFun Pro Micro ESP32-C3")
    assert _schematic_gpio(pro_micro)["IOA0/SCLK"] == {0}
    glyph = _schematic_gpio(row_named("PCBCUPID Glyph Mini RP2040"))
    assert (glyph["/GPIO-26"], glyph["/GPIO-15"], glyph["+3V3"]) == ({26}, {15}, set())


def _trace(row: board_manifest.Row, text: str | None = None,
           table: board_manifest.PinTable | None = None) -> dict:
    """The row's own CAD traced by the reader `import_pindefs` registers it
    through, for its format."""
    path = board_manifest.cad_path(row)
    return import_pindefs.TRACED_READERS[path.suffix.lower()](
        (path.read_text(encoding="utf-8") if text is None else text,),
        path=path, select=row.select, table=table or row.pin_table)


def test_every_pin_table_is_what_its_page_numbers_once_each():
    """A pad is a GPIO, a named pad with none, or left out, and never two;
    no GPIO twice; every pad within the pins the page numbers; and the PDF
    it was read from named by an address and a whole sha256."""
    for table in {row.pin_table for row in ROWS}:
        assert table.url.startswith("https://") and table.url.endswith(".pdf"), table.value
        assert re.fullmatch(r"[0-9a-f]{64}", table.pdf_sha256), table.value
        gpio, other = dict(table.gpio), dict(table.not_gpio)
        assert len(gpio) == len(table.gpio) and len(other) == len(table.not_gpio), table.value
        assert not set(gpio) & set(other), table.value
        assert len(set(gpio.values())) == len(gpio), table.value
        assert {int(pad) for pad in (*gpio, *other)} <= set(range(1, table.pins + 1)), (
            table.value)
        # A footprint's other name for a pin is for a pin the page numbers.
        assert {int(number) for _, number in table.footprint_pads} <= set(
            range(1, table.pins + 1)), table.value


def test_two_tables_read_off_one_page_agree_on_every_pad_both_transcribe():
    """One datasheet page, two placements of the part: the ESP32-C6-MINI-1
    as Adafruit's library places it and as SparkFun's does. Each table keeps
    the GPIO rows its own boards reach, and a pad both transcribe is the
    same pin in both, with the same cite, pin count and sha256."""
    pages: dict[str, list[board_manifest.PinTable]] = {}
    for table in {row.pin_table for row in ROWS}:
        pages.setdefault(table.url, []).append(table)
    shared = [tables for tables in pages.values() if len(tables) > 1]
    assert shared, "no page is read for two placements, so this checks nothing"
    for tables in shared:
        assert len({(t.cite, t.pdf_sha256, t.pins) for t in tables}) == 1, tables
        for one, other in itertools.combinations(tables, 2):
            first = {**dict(one.gpio), **dict(one.not_gpio)}
            second = {**dict(other.gpio), **dict(other.not_gpio)}
            assert {pad: first[pad] for pad in set(first) & set(second)} == {
                pad: second[pad] for pad in set(first) & set(second)}, (one.value, other.value)


def test_the_kb2040s_p1_is_the_central_pad_its_rp2040_page_numbers_57():
    """`RP2040_QFN56.footprint_pads` reads the footprint's `P$1` as the
    page's 57, "Common ground connection via central pad". `P$1` is the one
    pad of the part the footprint does not number, it sits at the centre of
    the 56 it does, and without the table saying so the KB2040's GND is
    refused as a pad the table does not transcribe."""
    row = row_named("Adafruit KB2040")
    _fetched(row)
    board = eagle.read_board(board_manifest.cad_path(row))
    (chip,) = [element for element in board.elements if (element.package, element.value)
               == (row.pin_table.package, row.pin_table.value)]
    ring = [pad for pad in chip.pads if pad.number.isdigit()]
    (central,) = [pad for pad in chip.pads if not pad.number.isdigit()]
    assert central.number == "P$1"
    assert sorted(int(pad.number) for pad in ring) == list(range(1, 57))
    assert (round(central.x_mm - sum(pad.x_mm for pad in ring) / 56, 3),
            round(central.y_mm - sum(pad.y_mm for pad in ring) / 56, 3)) == (0, 0)
    assert dict(row.pin_table.not_gpio)[dict(row.pin_table.footprint_pads)["P$1"]] == "GND"
    with pytest.raises(import_pindefs.PindefError, match="'GND' reaches IC2 pad P\\$1, which"):
        _trace(row, table=dataclasses.replace(row.pin_table, footprint_pads=()))


def test_every_gpio_row_of_a_table_is_a_pad_some_header_reaches():
    """A table keeps only the GPIO rows some board uses (OH-178), across
    every row that shares it: a row nothing reaches is a transcription
    nothing checks. Its pads with no GPIO are all listed, from the same page,
    so that a pad left out is refused rather than read as none."""
    reached: dict[board_manifest.PinTable, set[int]] = {}
    for row in ROWS:
        _fetched(row)
        reached.setdefault(row.pin_table, set()).update(
            found.pin.index for found in _trace(row).values() if found.pin)
    for table, gpios in reached.items():
        assert gpios == {gpio for _, gpio in table.gpio}, table.value


def test_no_supply_pad_names_a_pin_or_is_on_a_gpio_pad_of_its_chip():
    """What makes a label a supply (`SUPPLY_LABELS` in
    tests/rules/test_import_pindefs.py): its pad names no chip pin, and its
    net is on no GPIO pad of the chip. Through a resistor 3.3V reaches a GPIO
    by a pull-up on all three boards, and on each that GPIO's net holds three
    or more contacts, so the series rule alone keeps the rail off it here;
    the stop at a chip pad with no GPIO is held by the reader's own test,
    `test_a_net_on_a_chip_pad_the_table_gives_no_gpio_names_none_and_stops_there`."""
    from tests.rules.test_import_pindefs import SUPPLY_LABELS

    checked = []
    for row in ROWS:
        _fetched(row)
        if row.schematic is None:
            (chip,) = [placed for placed in kicad.read_board(board_manifest.cad_path(row)).placements
                       if (placed.name, placed.value)
                       == (row.pin_table.package, row.pin_table.value)]
        else:
            board = eagle.read_board(board_manifest.cad_path(row))
            (chip,) = [element for element in board.elements if (element.package, element.value)
                       == (row.pin_table.package, row.pin_table.value)]
        gpio = dict(row.pin_table.gpio)
        for pad in _committed(row)["pads"]:
            label = pad["label"]
            if label.split("/")[0].upper() in SUPPLY_LABELS or label.upper() in SUPPLY_LABELS:
                assert pad["chip_pin"] is None, (row.board, label)
                assert not [one.number for one in chip.pads
                            if one.net == label and one.number in gpio], (row.board, label)
                checked.append(row.board)
    assert set(checked) == {row.board for row in ROWS}


def test_the_qt_pys_tx_is_traced_through_its_resistor():
    """R4, a resistor by name and value, is the one part a trace crosses."""
    row = row_named("Adafruit QT Py ESP32-C3")
    _fetched(row)
    assert _trace(row)["TX"].via.startswith("TX -> R4 (1k) -> U2 pad 28 = GPIO21 (")


def test_a_net_renamed_for_another_gpio_is_refused_on_the_pilot():
    """The ticket's condition: a deliberately wrong net name is refused
    rather than resolved. SparkFun's `IO8` renamed `IO12`: its copper still
    reaches U1's pad 10, GPIO8."""
    row = row_named("SparkFun Thing Plus ESP32-C6")
    _fetched(row)
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    assert text.count('<signal name="IO8">') == 1
    with pytest.raises(import_pindefs.PindefError,
                       match=r"'IO12' is named for GPIO12 and its copper reaches "
                             r"U1 pad 10 = GPIO8"):
        _trace(row, text.replace('<signal name="IO8">', '<signal name="IO12">'))


# --- a row from a KiCad board file (OH-192) -----------------------------------


def test_a_kicad_row_names_no_schematic_and_an_eagle_row_needs_one():
    """Which pads are one pin: a `.kicad_pcb` says so by its pads' numbers,
    and an EAGLE `.brd` only through its schematic's device connects. A
    KiCad row naming a schematic, or an EAGLE row naming none, is refused
    before anything is read."""
    glyph = row_named("PCBCUPID Glyph Mini RP2040")
    with pytest.raises(ManifestError, match="is a KiCad board, whose pads carry their "
                                            "own numbers and nets"):
        board_manifest.check(dataclasses.replace(glyph, schematic="glyph.kicad_sch"))
    with pytest.raises(ManifestError, match=r"Thing_Plus_ESP32_C6\.brd is not a KiCad "
                                            r"board, .* the row names no schematic"):
        board_manifest.check(dataclasses.replace(ROWS[0], schematic=None))


def test_the_glyph_minis_pins_are_its_traced_copper_and_its_variant_names_no_pad():
    """Its pads are labelled by net, `/GPIO-0` and so on, and its variant --
    read through `common.h` -- numbers `D0` to `D29` and no label any pad
    carries, so every pin is the copper's: twenty pads each reach one RP2040
    GPIO directly. GND and +3V3 reach pads the page gives no GPIO, and /5V
    reaches none of the chip's."""
    row = row_named("PCBCUPID Glyph Mini RP2040")
    _fetched(row)
    numbers = _variant_numbers(row)
    assert {f"D{n}" for n in range(30)} <= set(numbers)
    pads = {pad["label"]: pad for pad in _committed(row)["pads"]}
    assert not [label for label in pads
                if set(import_pindefs.alternatives(label)) & set(numbers)]
    gpios = {label: pad["chip_index"] for label, pad in pads.items() if pad["chip_pin"]}
    assert gpios == {f"/GPIO-{n}": n for n in (*range(16), 26, 27, 28, 29)}
    assert {tuple(pads[label]["chip_pin_from"]) for label in gpios} == {(row.source,)}
    assert pads["/5V"]["why_null"] == import_pindefs.NOT_TRACED
    for label in ("GND", "+3V3"):
        assert pads[label]["why_null"].startswith(
            f"no GPIO: the vendor's board file traces {label} -> IC1 "), pads[label]
    traced = _trace(row)
    for label, gpio in gpios.items():
        assert traced[label].via.startswith(f"{label} -> IC1 pad "), traced[label].via
        assert f" = GPIO{gpio} (" in traced[label].via, traced[label].via


def test_a_net_renamed_for_another_gpio_is_refused_on_the_glyph_mini():
    """The KiCad row's cross-check, as the pilot's: PCBCUPID's `/GPIO-3`
    renamed `/GPIO-30` throughout the file. Its copper still reaches IC1's
    pad 5, GPIO3, and the file saying two things is refused."""
    row = row_named("PCBCUPID Glyph Mini RP2040")
    _fetched(row)
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    assert '"/GPIO-3"' in text and '"/GPIO-30"' not in text
    with pytest.raises(import_pindefs.PindefError,
                       match=r"'/GPIO-30' is named for GPIO30 and its copper reaches "
                             r"IC1 pad 5 = GPIO3"):
        _trace(row, text.replace('"/GPIO-3"', '"/GPIO-30"'))


def test_the_glyph_minis_pad_57_is_the_central_pad_its_rp2040_page_numbers_57():
    """The footprint numbers its central pad 57, as the page does, so the
    Glyph Mini's table needs no `footprint_pads`: 57 sits at the centre of
    the 56 around it, the footprint's 16 unnumbered pads are paste on no
    net, and GND reaches the page's 57."""
    row = row_named("PCBCUPID Glyph Mini RP2040")
    _fetched(row)
    assert row.pin_table.footprint_pads == ()
    (chip,) = [placed for placed in kicad.read_board(board_manifest.cad_path(row)).placements
               if (placed.name, placed.value) == (row.pin_table.package, row.pin_table.value)]
    ring = [pad for pad in chip.pads if pad.number.isdigit() and int(pad.number) <= 56]
    (central,) = [pad for pad in chip.pads if pad.number == "57"]
    assert sorted(int(pad.number) for pad in ring) == list(range(1, 57))
    assert (round(central.x_mm - sum(pad.x_mm for pad in ring) / 56, 3),
            round(central.y_mm - sum(pad.y_mm for pad in ring) / 56, 3)) == (0, 0)
    unnumbered = [pad for pad in chip.pads if not pad.number]
    assert len(unnumbered) == 16
    assert {(pad.net, pad.layers) for pad in unnumbered} == {("", ("B.Paste",))}
    assert dict(row.pin_table.not_gpio)["57"] == "GND"
    assert "; pad 57 = GND (" in _trace(row)["GND"].via


# --- the KiCad ESP32 rows (OH-194) --------------------------------------------


def test_a_net_renamed_for_another_gpio_is_refused_on_the_glyph_c3():
    """PCBCUPID spells a GPIO net `/GPIO_8` on this board, and the name check
    reads that spelling: renamed `/GPIO_18`, its copper still reaches U4 pad
    22, GPIO8, and the file saying two things is refused."""
    row = row_named("PCBCUPID Glyph C3")
    _fetched(row)
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    assert '"/GPIO_8"' in text and '"/GPIO_18"' not in text
    with pytest.raises(import_pindefs.PindefError,
                       match=r"'/GPIO_18' is named for GPIO18 and its copper reaches "
                             r"U4 pad 22 = GPIO8"):
        _trace(row, text.replace('"/GPIO_8"', '"/GPIO_18"'))


def test_every_unconnected_pad_is_alone_on_its_net():
    """The reason a KiCad row gives a pad on a net KiCad names
    `unconnected-(...)`, read off its board file: no other pad of any
    footprint is on that net. The Glyph C3's J2 pad 8, and the SparkFun
    Thing Plus ESP32-C5's U3 pads 3 and 13."""
    checked = []
    for row in ROWS:
        for label, why in row.reasons:
            if not label.startswith("unconnected-("):
                continue
            _fetched(row)
            on = [(placed.reference, pad.number)
                  for placed in kicad.read_board(board_manifest.cad_path(row)).placements
                  for pad in placed.pads if pad.net == label]
            assert len(on) == 1 and on[0][0] in row.select, (row.board, on)
            assert "this pad is the only pad on its net" in why, row.board
            assert f"reaches no pin of the {row.chip} or of anything else" in why, row.board
            checked.append((row.board, *on[0]))
    assert checked == [("PCBCUPID Glyph C3", "J2", "8"),
                       ("SparkFun Thing Plus ESP32-C5", "U3", "3"),
                       ("SparkFun Thing Plus ESP32-C5", "U3", "13")], checked


def test_a_net_renamed_for_another_gpio_is_refused_on_the_thing_plus_c5():
    """SparkFun's `IO8/PICO`, which KiCad writes `IO8{slash}PICO`: the name
    check reads the part before the escape. Renamed `IO18{slash}PICO`, its
    copper still reaches U1 pad 10, GPIO8, and the file saying two things is
    refused."""
    row = row_named("SparkFun Thing Plus ESP32-C5")
    _fetched(row)
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    assert '"IO8{slash}PICO"' in text and '"IO18{slash}PICO"' not in text
    with pytest.raises(import_pindefs.PindefError, match=re.escape(
            "'IO18{slash}PICO' is named for GPIO18 and its copper reaches "
            "U1 pad 10 = GPIO8")):
        _trace(row, text.replace('"IO8{slash}PICO"', '"IO18{slash}PICO"'))


def test_the_thing_plus_c5s_jumpered_and_enable_pads_are_what_its_file_draws():
    """`Net-(JP11-B)`'s reason, read off the board file: the net holds this
    header pad and pad 2 of JP11, a Jumper_2_NO valued DO, whose pad 1 is on
    LED_DO with pad 1 of D2, a WS2812B whose symbol names that pin DOUT; no
    pad of the module is on either net. And `EN`'s: the net holds this pad,
    U2's pin its symbol names EN -- an RT9080-3.3 whose VOUT is on 3.3V --
    and R4 (100k), whose other pad is on VIN, and no pad of U1."""
    row = row_named("SparkFun Thing Plus ESP32-C5")
    _fetched(row)
    tree = kicad.parse_sexp(board_manifest.cad_path(row).read_text(encoding="utf-8"))
    placed = {}
    for node in kicad.children(tree, "footprint"):
        (reference,) = [prop[2] for prop in kicad.children(node, "property")
                        if prop[1] == "Reference"]
        (value,) = [prop[2] for prop in kicad.children(node, "property")
                    if prop[1] == "Value"]
        placed[reference] = (node[1], value, {
            pad[1]: (kicad.first(pad, "net")[-1] if kicad.first(pad, "net") else None,
                     kicad.first(pad, "pinfunction")[1] if kicad.first(pad, "pinfunction")
                     else None)
            for pad in kicad.children(node, "pad")})

    def on(net: str) -> set[tuple[str, str]]:
        return {(reference, number) for reference, (_, _, pads) in placed.items()
                for number, (where, _) in pads.items() if where == net}

    assert on("Net-(JP11-B)") == {("U3", "26"), ("JP11", "2")}
    assert placed["JP11"][:2] == ("SparkFun-Jumper:Jumper_2_NO", "DO")
    assert placed["JP11"][2]["1"][0] == "LED_DO"
    assert on("LED_DO") == {("JP11", "1"), ("D2", "1")}
    assert placed["D2"][1] == "WS2812B" and placed["D2"][2]["1"][1] == "DOUT"
    why = dict(row.reasons)["Net-(JP11-B)"]
    for words in ("pad 2 of the jumper JP11 (Jumper_2_NO, value DO)",
                  "pad 1 is on LED_DO with the DOUT of the WS2812B D2"):
        assert words in why, words
    assert on("EN") == {("U3", "11"), ("U2", "3"), ("R4", "2")}
    assert placed["U2"][1] == "RT9080-3.3" and placed["U2"][2]["3"] == ("EN", "EN")
    assert placed["U2"][2]["5"] == ("3.3V", "VOUT")
    assert placed["R4"][1] == "100k" and placed["R4"][2]["1"][0] == "VIN"
    why = dict(row.reasons)["EN"]
    for words in ("U2's `EN` (an RT9080-3.3, whose `VOUT` is the 3.3V net)",
                  "R4 (100k), whose other pad is on VIN", "on no pad of U1"):
        assert words in why, words
    # The module's nine central pads are all named EPAD, the page's 29.
    epad = [pad for pad in _placed(row, "U1").pads if pad.number == "EPAD"]
    assert len(epad) == 9 and {pad.net for pad in epad} == {"GND"}
    assert dict(row.pin_table.footprint_pads) == {"EPAD": "29"}
    assert dict(row.pin_table.not_gpio)["29"] == "EPAD"
    assert "; pad EPAD = EPAD (" in _trace(row)["GND"].via


def test_each_glyph_module_is_read_against_its_own_modules_page():
    """PCBCUPID places the Glyph C3's module under a footprint its library
    calls `ESP32-H2-MINI-1_EXP`, valued `ESP32-C3-MINI-1-N4`, and the Glyph
    C6's as `ESP32-C6-MINI-1_EXP`, `ESP32-C6-MINI-1-N4`. What makes each
    MINI-1 page the one to read it against: the symbol's name on every pad
    the table transcribes is the page's `IO<n>` for that pad's GPIO, or
    `RXD0` and `TXD0` on 30 and 31, and the nine pads named `49_1` to `49_9`
    are GND, as the page's 49 is."""
    for board, footprint in (("PCBCUPID Glyph C3", "ESP32C3:ESP32-H2-MINI-1_EXP"),
                             ("PCBCUPID Glyph C6", "ESP32C6:ESP32-C6-MINI-1_EXP")):
        row = row_named(board)
        _fetched(row)
        table = row.pin_table
        tree = kicad.parse_sexp(board_manifest.cad_path(row).read_text(encoding="utf-8"))
        (chip,) = [node for node in kicad.children(tree, "footprint") if node[1] == footprint]
        function = {pad[1]: kicad.first(pad, "pinfunction")[1]
                    for pad in kicad.children(chip, "pad")}
        expected = {pad: f"IO{gpio}" for pad, gpio in table.gpio} | {
            "30": "RXD0", "31": "TXD0"}
        assert {pad: function[pad] for pad in expected} == expected, board
        split = [pad for pad, _ in table.footprint_pads]
        assert split == [f"49_{n}" for n in range(1, 10)], board
        assert {function[pad].rstrip("_0123456789") for pad in split} == {"GND"}, board
        assert dict(table.not_gpio)["49"] == "GND", board


def test_a_net_renamed_for_another_gpio_is_refused_on_the_olimex_c3():
    """Olimex names a net for its GPIO and then its use, `/GPIO7\\I2C_SDA`,
    and the name check reads the part before the backslash: renamed
    `/GPIO17\\I2C_SDA`, its copper still reaches U3 pad 21, GPIO7, and the
    file saying two things is refused."""
    row = row_named("Olimex ESP32-C3-DevKit-Lipo")
    _fetched(row)
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    # KiCad stores the backslash doubled.
    assert '"/GPIO7\\\\I2C_SDA"' in text and '"/GPIO17\\\\I2C_SDA"' not in text
    with pytest.raises(import_pindefs.PindefError, match=re.escape(
            "'/GPIO17\\\\I2C_SDA' is named for GPIO17 and its copper reaches "
            "U3 pad 21 = GPIO7")):
        _trace(row, text.replace('"/GPIO7\\\\I2C_SDA"', '"/GPIO17\\\\I2C_SDA"'))


def test_the_olimex_c3s_pins_are_its_traced_copper_and_its_variant_names_no_pad():
    """Revision D, the newest of the four the repository publishes: its
    variant numbers `TX`, `SDA`, `A0` and the like and no `D<n>`, and no
    label any pad carries, so every pin is the copper's. Each of its thirteen
    GPIO pads is on a net Olimex names for that GPIO, before a backslash and
    what the pin is for."""
    row = row_named("Olimex ESP32-C3-DevKit-Lipo")
    _fetched(row)
    assert '(rev "D")' in board_manifest.cad_path(row).read_text(encoding="utf-8")
    checkout = import_pindefs.BSP_DIR / row.package
    constants = import_pindefs.read_c_pin_constants(
        (checkout / "variants" / row.variant / "pins_arduino.h").read_text(encoding="utf-8"))
    assert constants and not [label for label in constants if re.fullmatch(r"D\d+", label)]
    assert _variant_numbers(row) == {}
    pads = {pad["label"]: pad for pad in _committed(row)["pads"]}
    gpios = {label: pad["chip_index"] for label, pad in pads.items() if pad["chip_pin"]}
    assert sorted(gpios.values()) == [*range(11), 20, 21]
    for label, gpio in gpios.items():
        assert re.split(r"[/\\]", label)[1] == f"GPIO{gpio}", label
        assert pads[label]["chip_pin_from"] == [row.source], label


def test_a_net_renamed_for_another_gpio_is_refused_on_the_olimex_c6_evb():
    """KiCad 5 writes a net's name bare, `/GPIO8\\USER_LED1`, with one
    backslash, where KiCad 7 quotes it and doubles it; the name check reads
    it all the same. Renamed `/GPIO18\\USER_LED1`, its copper still reaches
    U3 pad 10, GPIO8, and the file saying two things is refused."""
    row = row_named("Olimex ESP32-C6-EVB")
    _fetched(row)
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    assert " /GPIO8\\USER_LED1)" in text and "/GPIO18\\USER_LED1" not in text
    with pytest.raises(import_pindefs.PindefError, match=re.escape(
            "'/GPIO18\\\\USER_LED1' is named for GPIO18 and its copper reaches "
            "U3 pad 10 = GPIO8")):
        _trace(row, text.replace("/GPIO8\\USER_LED1", "/GPIO18\\USER_LED1"))


def test_the_olimex_c6_evbs_pins_are_its_traced_copper_and_its_variant_names_no_pad():
    """Revision A, the only one, in KiCad 5: its variant numbers
    `LED_BUILTIN`, `TX`, `SDA`, `A0` and the like and no `D<n>`, and no label
    any pad carries, so every pin is the copper's. Each of EXT1's GPIO pads
    is on a net Olimex names for that GPIO, alone or before a backslash and
    what the pin is for; the rest are its rails, its grounds and /ESP_EN,
    which reaches the module's EN."""
    row = row_named("Olimex ESP32-C6-EVB")
    _fetched(row)
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    assert text.startswith("(kicad_pcb (version 20171130)") and "(rev A)" in text
    checkout = import_pindefs.BSP_DIR / row.package
    constants = import_pindefs.read_c_pin_constants(
        (checkout / "variants" / row.variant / "pins_arduino.h").read_text(encoding="utf-8"))
    assert constants and not [label for label in constants if re.fullmatch(r"D\d+", label)]
    assert _variant_numbers(row) == {}
    pads = _committed(row)["pads"]
    resolved = [pad for pad in pads if pad["chip_pin"]]
    assert sorted(pad["chip_index"] for pad in resolved) == [0, 8, 9, 16, 17]
    for pad in resolved:
        assert re.split(r"[/\\]", pad["label"])[1] == f"GPIO{pad['chip_index']}", pad
        assert pad["chip_pin_from"] == [row.source], pad
    rest = {pad["label"]: pad["why_null"] for pad in pads if not pad["chip_pin"]}
    assert sorted(pad["label"] for pad in pads if not pad["chip_pin"]) == [
        "+3.3V", "+5V", "/ESP_EN", "GND", "GND"]
    assert "/ESP_EN -> U3 pad 3 = EN" in rest["/ESP_EN"], rest["/ESP_EN"]


def test_the_olimex_c6_evbs_paste_apertures_are_on_no_net_and_are_no_pin():
    """U3, the ESP32-C6-WROOM-1, carries eight pads numbered `Past`: paste
    apertures over its ground pad, each on `F.Paste` alone and on no net.
    The number is all they share with a pin, and KiCad numbers no pad on no
    copper layer, nor an unplated hole (`PAD::CanHaveNumber` at 7.0.0), so
    the trace reads none: not as eight pads of one pin, and not as a contact
    of a net even where one is put on a header's."""
    row = row_named("Olimex ESP32-C6-EVB")
    _fetched(row)
    u3 = _placed(row, "U3")
    assert (u3.name, u3.value) == (row.pin_table.package, row.pin_table.value)
    past = [pad for pad in u3.pads if not pad.number.isdigit()]
    assert len(past) == 8, [pad.number for pad in past]
    assert {(pad.number, pad.net, pad.layers) for pad in past} == {("Past", "", ("F.Paste",))}
    assert {int(pad.number) for pad in u3.pads if pad.number.isdigit()} == set(
        range(1, row.pin_table.pins + 1))
    assert not [found.via for found in _trace(row).values() if "Past" in found.via]
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    aperture = "(pad Past smd rect (at -0.25 1.71 270) (size 0.8 0.8) (layers F.Paste))"
    assert text.count(aperture) == 1
    moved = text.replace(aperture, aperture[:-1] + " (net 42 /GPIO8\\USER_LED1))")
    assert _trace(row, moved) == _trace(row)
    for kind, layers in (("smd", ("F.Paste",)), ("np_thru_hole", ("*.Cu", "*.Mask"))):
        assert import_pindefs._numbered(kicad.Pad("1", kind, 0, 0, 1, 1, layers=layers)) == ""
    assert import_pindefs._numbered(kicad.Pad("1", "smd", 0, 0, 1, 1, layers=("F.Cu",))) == "1"


def test_a_rows_variant_may_number_no_d_pin_only_where_the_row_opts_in_no_label():
    """`read_row_pins`, which a row's flat variant is read by. A XIAO's is
    still read by `read_flat_pins`, which refuses a file with no `D<n>`."""
    text = "static const uint8_t TX = 21;\nstatic const uint8_t SDA = 8;\n"
    assert import_pindefs.read_row_pins((text,)) == {}
    assert import_pindefs.read_row_pins((text,), extras=("SDA",)) == {
        "SDA": import_pindefs.ChipPin("GPIO8", 8)}
    with pytest.raises(import_pindefs.PindefError, match="'LED' is registered"):
        import_pindefs.read_row_pins((text,), extras=("LED",))
    with pytest.raises(import_pindefs.PindefError, match="numbers no pin at all"):
        import_pindefs.read_row_pins(("#include <stdint.h>\n",))
    with pytest.raises(import_pindefs.PindefError, match="no D<n> constants"):
        import_pindefs.read_flat_pins((text,))
    # No label opted in and a D<n> numbered: read as read_flat_pins reads it.
    numbered = text + "static const uint8_t D0 = 20;\n"
    assert import_pindefs.read_row_pins((numbered,)) == import_pindefs.read_flat_pins(
        (numbered,)) == {"D0": import_pindefs.ChipPin("GPIO20", 20)}


def test_a_header_pad_moved_onto_a_pad_the_table_leaves_out_is_refused():
    """The QT Py's JP1 pad 1 moved off A0 onto BOOT, U2 pad 15, which is
    GPIO9 on the page and which the table leaves out because no header
    reaches it: refused as not transcribed, under either name, rather than
    read as no GPIO."""
    row = row_named("Adafruit QT Py ESP32-C3")
    _fetched(row)
    text = board_manifest.cad_path(row).read_text(encoding="utf-8")
    pad, boot = '<contactref element="JP1" pad="1"/>', '<signal name="BOOT">'
    assert text.count(pad) == 1 and text.count(boot) == 1
    moved = text.replace(pad, "").replace(boot, boot + pad)
    for net in ("BOOT", "IO9/BOOT"):
        with pytest.raises(import_pindefs.PindefError,
                           match=r"reaches U2 pad 15, which the table from ESP32-C3 "
                                 r"Series Datasheet v2\.4, p\. 67"):
            _trace(row, moved.replace(boot, f'<signal name="{net}">'))


def test_a_variant_and_a_trace_that_disagree_leave_the_pad_disputed(monkeypatch):
    """Never resolved by preference. The Feather's table told that its SDA
    pad, 25, is GPIO20, and then that it is NC: the variant says 19 both
    times, and the pad is null with each source named beside its answer."""
    row = row_named("Adafruit Feather ESP32-C6")
    _fetched(row)
    gpio = tuple(one for one in row.pin_table.gpio if one[0] != "25")
    for table, traced in (
            (dataclasses.replace(row.pin_table, gpio=(*gpio, ("25", 20))), "GPIO20"),
            (dataclasses.replace(row.pin_table, gpio=gpio,
                                 not_gpio=(*row.pin_table.not_gpio, ("25", "NC"))), None)):
        monkeypatch.setitem(import_pindefs.BOARDS, row.board, import_pindefs.manifest_board(
            dataclasses.replace(row, pin_table=table)))
        (sda,) = [pad for pad in import_pindefs.board_report(row.board)["pads"]
                  if pad["label"] == "SDA"]
        assert (sda["chip_pin"], sda["reason"]) == (None, import_pindefs.DISPUTED)
        assert sda["disputed_by"] == [
            {"chip_pin": "GPIO19", "chip_pin_from": [row.package]},
            {"chip_pin": traced, "chip_pin_from": [row.source]}]


def test_a_pad_the_variant_names_and_the_copper_does_not_reach_is_refused(tmp_path):
    """A row's copper is traced for every pad, so the variant's word alone
    is not a pin (OH-194's review). The Thing Plus ESP32-C5's U3 pad 3 is on
    a net of its own; labelled `Z{slash}SDA`, its variant's `SDA` names
    GPIO23 and the trace reaches no pad of the chip. The pad stays null and
    `disputed_by` names both; every other pad of the board is as committed."""
    row = row_named("SparkFun Thing Plus ESP32-C5")
    _fetched(row)
    committed = _committed(row)
    moved = json.loads(json.dumps(committed))
    (pad,) = [pad for pad in moved["pads"] if pad["label"] == "unconnected-(U3-GPIO6-Pad3)"]
    pad["label"] = "Z{slash}SDA"
    (tmp_path / f"{row.board}.json").write_text(json.dumps(moved), encoding="utf-8")
    report = {entry["label"]: entry for entry in import_pindefs.board_report(
        row.board, boards_dir=tmp_path)["pads"]}
    refused = report["Z{slash}SDA"]
    assert (refused["chip_pin"], refused["index"], refused["reason"]) == (
        None, None, import_pindefs.DISPUTED)
    assert refused["disputed_by"] == [
        {"chip_pin": "GPIO23", "chip_pin_from": [row.package]},
        {"chip_pin": None, "chip_pin_from": [row.source]}]
    # The real SDA pad, on the copper, still names GPIO23 from both.
    assert report["IO23{slash}SDA"]["chip_pin"] == "GPIO23"
    assert report["IO23{slash}SDA"]["chip_pin_from"] == sorted([row.package, row.source])


def test_a_regenerated_pad_keeps_nothing_from_an_earlier_run(tmp_path):
    """`chip_pin_from`, `why_null` and `disputed_by` are written from this
    run's report or not at all."""
    row = row_named("SparkFun Thing Plus ESP32-C6")
    _fetched(row)
    committed = _committed(row)
    stale = json.loads(json.dumps(committed))
    for pad in stale["pads"]:
        pad.update({"chip_pin_from": ["stale"], "why_null": "stale",
                    "disputed_by": [{"chip_pin": "GPIO99", "chip_pin_from": ["stale"]}]})
    (tmp_path / f"{row.board}.json").write_text(json.dumps(stale), encoding="utf-8")
    filled = import_pindefs.filled_board(row.board, import_pindefs.BSP_DIR, tmp_path,
                                         modules_dir=import_pindefs.BOARDS_DIR)
    assert filled["pads"] == committed["pads"]


def test_no_null_pad_says_only_that_no_package_names_it():
    """The CAD was traced too, so a null pad says what that found: a pad of
    the chip with no GPIO, no pad of the chip (`NOT_TRACED`), or the row's
    own reason. V_USB is the pilot's `NOT_TRACED`, and the pilot's GND names
    the eight footprint pads past the page's 29."""
    for row in ROWS:
        for pad in _committed(row)["pads"]:
            if pad["chip_pin"] is None:
                assert pad["why_null"] != import_pindefs.NOT_PUBLISHED, (row.board, pad)
    pilot = {pad["label"]: pad for pad in _committed(row_named("SparkFun Thing Plus ESP32-C6"))["pads"]}
    assert pilot["V_USB"]["why_null"] == import_pindefs.NOT_TRACED
    assert pilot["GND"]["why_null"].startswith(
        "no GPIO: the vendor's board file traces GND -> U1 2 pads = GND; pad 29 = EPAD; "
        "8 pads = not a pin of the part (past the page's 29) (")


def test_every_reason_is_on_a_pad_and_carried_by_it():
    for row in ROWS:
        pads = {pad["label"]: pad for pad in _committed(row)["pads"]}
        for label, why in row.reasons:
            assert pads[label]["chip_pin"] is None, (row.board, label)
            assert pads[label]["why_null"] == why, (row.board, label)


def test_the_pilots_reasons_are_what_its_schematic_says():
    """Each reason names the pin its net reaches and says no ESP32-C6 GPIO is
    on it. Both halves read off the vendor's own schematic."""
    row = ROWS[0]
    _fetched(row)
    path = board_manifest.cad_path(row).with_suffix(".sch")
    schematic = eagle.read_schematic(path)
    nets = {net.name: net for net in schematic.nets}
    named = {"ESP_EN": ("U1", "EN"), "VREG_EN": ("U2", "EN"), "LED_DO": ("RGB", "1")}
    assert sorted(named) == sorted(label for label, _ in row.reasons)
    for label, (part, pin) in named.items():
        on_net = {(ref.part, ref.pin) for ref in nets[label].pins}
        assert (part, pin) in on_net, (label, sorted(on_net))
        assert not [ref for ref in nets[label].on("U1")
                    if import_schematic.gpio_of(ref.pin) is not None], label


def test_every_other_fact_in_the_pilots_reasons_is_read_off_its_schematic():
    """The part and pin per net are above. Each other fact the prose states
    is here: the words in the reason, and the schematic saying it."""
    row = ROWS[0]
    _fetched(row)
    schematic = eagle.read_schematic(board_manifest.cad_path(row).with_suffix(".sch"))
    nets = {net.name: net for net in schematic.nets}
    reasons = dict(row.reasons)

    def parts_on(net: str) -> set[str]:
        """The parts on a net other than the header pad the reason is for."""
        return {ref.part for ref in nets[net].pins} - {"J1"}

    # ESP_EN: "U1's `EN`, the RESET switch, R11 and C5, and U1's GPIOs are
    # its `IOn` pins".
    assert parts_on("ESP_EN") == {"U1", "RESET", "R11", "C5"}
    assert "SWITCH" in schematic.part("RESET").deviceset
    gpios = [pin for pin in schematic.pins_of("U1") if pin not in ("3V3", "EN", "GND")]
    assert gpios and all(re.search(r"(^|/)IO\d+$", pin) for pin in gpios), gpios
    for words in ("U1's `EN`", "the RESET switch, R11 and C5", "its `IOn` pins"):
        assert words in reasons["ESP_EN"], words

    # VREG_EN: "U2's `EN` (an RT9080-33GJ5, whose `OUT` is the 3.3V net)
    # and R8, and on no pin of U1".
    assert parts_on("VREG_EN") == {"U2", "R8"}
    assert schematic.part("U2").value == "RT9080-33GJ5"
    assert ("U2", "OUT") in {(ref.part, ref.pin) for ref in nets["3.3V"].pins}
    for words in ("U2's `EN` (an RT9080-33GJ5, whose `OUT` is the 3.3V net) and R8",
                  "on no pin of U1"):
        assert words in reasons["VREG_EN"], words

    # LED_DO: "this pad and pin 1 of the jumper RGB (JUMPER-SMT_2_NO), whose
    # pin 2 is the `DO` of the WS2812 D5".
    assert parts_on("LED_DO") == {"RGB"}
    assert schematic.part("RGB").deviceset == "JUMPER-SMT_2_NO"
    (beyond,) = [net for net in schematic.nets
                 if ("RGB", "2") in {(ref.part, ref.pin) for ref in net.pins}]
    assert ("D5", "DO") in {(ref.part, ref.pin) for ref in beyond.pins}
    assert schematic.part("D5").deviceset == "WS2812"
    assert ("pin 1 of the jumper RGB (JUMPER-SMT_2_NO), whose pin 2 is the `DO` "
            "of the WS2812 D5") in reasons["LED_DO"]


def test_the_pockets_v_batt_reason_is_its_divider_as_its_files_draw_it():
    """"V_BATT on R13 (1M), whose other net, IO1/V_BATT_2, holds U1's
    `XTAL_32K_N/IO1` (pad 13) and R14 (1M) to GND": each fact read off the
    Qwiic Pocket's schematic, pad 13 off its board file, and the words in
    the reason. The trace stops there, which is why the row says it."""
    row = row_named("SparkFun Qwiic Pocket ESP32-C6")
    _fetched(row)
    schematic = eagle.read_schematic(
        board_sources.source(row.source).dest(board_manifest.REPO) / row.schematic)
    nets = {net.name: {(ref.part, ref.pin) for ref in net.pins} for net in schematic.nets}
    (r13_far,) = [pin for part, pin in nets["V_BATT"] if part == "R13"]
    (divided,) = [name for name, on in nets.items()
                  if ("R13", "1" if r13_far == "2" else "2") in on]
    assert divided == "IO1/V_BATT_2"
    assert {part for part, _ in nets[divided]} == {"R13", "R14", "U1"}
    assert ("U1", "XTAL_32K_N/IO1") in nets[divided]
    assert {schematic.part("R13").value, schematic.part("R14").value} == {"1M"}
    assert {part for part, _ in nets["GND"]} >= {"R14"}
    board = eagle.read_board(board_manifest.cad_path(row))
    (u1,) = [element for element in board.elements if element.name == "U1"]
    assert [pad.number for pad in u1.pads if pad.net == divided] == ["13"]
    with pytest.raises(KeyError):
        _trace(row)["V_BATT"]
    why = dict(row.reasons)["V_BATT"]
    for words in ("puts V_BATT on R13 (1M)", "other net, IO1/V_BATT_2",
                  "U1's `XTAL_32K_N/IO1` (pad 13)", "R14 (1M) to GND"):
        assert words in why, words


def test_the_c6_recipes_variant_numbers_the_pilots_sda_and_scl_as_other_gpios():
    """rules/board-claims.md §6: built with the variant the ESP32-C6 recipe
    reads, the pilot's `SDA` and `SCL` would be other GPIOs than its own
    variant names."""
    from webui import compile as compiler

    row = ROWS[0]
    _fetched(row)
    (include,) = compiler.RECIPES[row.chip].bsp_includes

    def sda_scl(variant):
        text = (variant / "pins_arduino.h").read_text(encoding="utf-8", errors="replace")
        pins = import_pindefs.read_flat_pins((text,), extras=("SDA", "SCL"))
        return pins["SDA"].index, pins["SCL"].index

    theirs = sda_scl(compiler.BOARD_SUPPORT / include)
    ours = sda_scl(import_pindefs.BSP_DIR / row.package / "variants" / row.variant)
    assert theirs[0] != ours[0] and theirs[1] != ours[1], (theirs, ours)


def test_no_row_pad_is_read_through_its_chips_module_table():
    """Each row's `assumption` says no level is read through its chip
    module's table for any pad, and that a level is read at the pad's own
    `chip_index` instead, which `webui.api.row_levels` does (OH-179). The
    page's other join is `webui.api.pad_view`: it keys and captions a row's
    pad by the pad's own label and file, never by the module's table.

    That table can key a row's labels: the KB2040's `D0` is one of its keys,
    which on the XIAO RP2040 it is keyed for is GPIO26, while the KB2040's
    own `D0` is GPIO0 (OH-181)."""
    from webui import api

    checked = []
    for row in ROWS:
        description = api.description_for(row.board)
        if getattr(description, "PIN_NAMES", None) is None:
            continue
        committed = _committed(row)
        assert "no level is read through it for any pad here" in committed["assumption"]
        assert "reads a pad's level at its own `chip_index`" in committed["assumption"]
        view = api.pad_view(row.board, description, None)
        assert [(pad["pin"], pad["chip_pin"]) for pad in view["pads"]] == [
            (api.header_key(pad["label"], {}), pad["chip_pin"])
            for pad in committed["pads"]], row.board
        checked.append(row.board)
    kb2040 = {pad["label"]: pad for pad in _committed(row_named("Adafruit KB2040"))["pads"]}
    xiao = api.description_for("Adafruit KB2040").PIN_NAMES
    assert (xiao["D0"], kb2040["D0"]["chip_pin"]) == ("GPIO26", "GPIO0")
    assert "Adafruit KB2040" in checked


# --- the chip comes from the row --------------------------------------------


def test_every_rows_chip_is_the_catalogues():
    for row in ROWS:
        assert row.chip in catalogue.CHIPS, row
        assert catalogue.chip_for(row.board) == row.chip
        assert import_pindefs.BOARDS[row.board].chip == row.chip


def test_no_row_inherits_its_chips_evidence(monkeypatch):
    """rules/board-claims.md §6 and §7: the register stays keyed by chip, and
    a row carries none of it -- only its own `BOARD_FIRMWARE_VERIFIED` entry,
    or nothing and the reason."""
    boards = {board.name: board for board in catalogue.catalogue()}
    for row in ROWS:
        assert row.chip in catalogue.FIRMWARE_VERIFIED, row.chip
        board = boards[row.board]
        own = catalogue.BOARD_FIRMWARE_VERIFIED.get(row.board)
        assert board.firmware_evidence == own, board
        assert board.firmware_evidence != catalogue.FIRMWARE_VERIFIED[row.chip]
        assert (board.firmware_withheld is None) == (own is not None), board
    assert boards["Adafruit Feather ESP32-C6"].firmware_verified is True
    assert boards["SparkFun Thing Plus ESP32-C6"].firmware_verified is True
    # With its own entry (OH-185) taken out, it is withheld again, naming its
    # own variant, and its chip's entry is still not its own.
    monkeypatch.delitem(catalogue.BOARD_FIRMWARE_VERIFIED, "SparkFun Thing Plus ESP32-C6")
    pilot = {b.name: b for b in catalogue.catalogue()}["SparkFun Thing Plus ESP32-C6"]
    assert pilot.firmware_evidence is None, pilot
    assert "variants/sparkfun_esp32c6_thing_plus" in pilot.firmware_withheld, pilot
    assert "BOARD_FIRMWARE_VERIFIED names no test" in pilot.firmware_withheld, pilot
    # And the XIAO sibling keeps the chip's: the register was not weakened.
    assert boards["XIAO-ESP32-C6-DIP"].firmware_verified is True
    assert boards["XIAO-ESP32-C6-DIP"].firmware_withheld is None


# --- a row may not quietly replace a board named elsewhere -------------------


def test_a_name_both_irregular_and_a_row_is_refused(monkeypatch):
    monkeypatch.setitem(catalogue.IRREGULAR, ROWS[0].board, "ATmega328P")
    with pytest.raises(catalogue.CatalogueError) as caught:
        catalogue.chip_for(ROWS[0].board)
    assert "name it in one place" in str(caught.value), caught.value


def test_a_row_named_like_a_registered_board_stops_import_pindefs_loading():
    """Checked in a fresh interpreter, because the guard runs as the module
    loads and this one has already loaded it."""
    script = (
        "import dataclasses\n"
        "from tools import board_manifest as m\n"
        "m.ROWS = m.ROWS + (dataclasses.replace(m.ROWS[0], board='XIAO-RP2040-DIP'),)\n"
        "import tools.import_pindefs\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=board_manifest.REPO,
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0, result.stdout
    assert "a row may not replace a board" in result.stderr, result.stderr
    assert "XIAO-RP2040-DIP" in result.stderr, result.stderr


# --- one answer to "is this a manifest board" (OH-183) ------------------------


def test_find_is_each_row_by_its_name_and_none_for_any_other_board():
    for entry in ROWS:
        assert board_manifest.find(entry.board) is entry
        assert board_manifest.row(entry.board) is entry
    rows = {entry.board for entry in ROWS}
    others = [name for name in catalogue.board_names() if name not in rows]
    assert others, "every board file is a row, so nothing here is asked of None"
    assert [name for name in others if board_manifest.find(name) is not None] == []
    assert board_manifest.find("Nowhere") is None
    with pytest.raises(ManifestError, match="no row called 'Nowhere'"):
        board_manifest.row("Nowhere")


def test_the_api_the_compiler_and_the_catalogue_each_ask_find(tmp_path, monkeypatch):
    """A row that only `find` knows, with `ROWS` emptied, is a row to each
    of the four places that walked `ROWS` for themselves: `api.is_row`,
    `recipe_for`, `chip_for` and `catalogue`."""
    from webui import api
    from webui import compile as compiler

    fake = dataclasses.replace(ROWS[0], board="Only Find Knows", chip="SAMD21")
    monkeypatch.setattr(board_manifest, "ROWS", ())
    monkeypatch.setattr(board_manifest, "find",
                        lambda name: fake if name == fake.board else None)
    assert api.is_row(fake.board)
    assert catalogue.chip_for(fake.board) == "SAMD21"
    with pytest.raises(compiler.UnknownBoard,
                       match="Only Find Knows is a row in tools/board_manifest.py"):
        compiler.recipe_for(fake.board)
    (tmp_path / f"{fake.board}.json").write_text("{}", encoding="utf-8")
    (board,) = catalogue.catalogue(tmp_path)
    assert board.chip == "SAMD21" and board.firmware_evidence is None
    assert f"variants/{fake.variant}" in board.firmware_withheld, board.firmware_withheld
