# OpenHardware - a board that is not a XIAO footprint, as a row (OH-176).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import dataclasses
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
)
from tools.board_manifest import ROWS, ManifestError
from webui import pinmap
from webui.boards import catalogue

#: The real directory, kept before any test points `BOARDS_DIR` elsewhere.
COMMITTED = board_manifest.BOARDS_DIR


def _fetched(row: board_manifest.Row) -> None:
    """Skip, naming what is missing, where a row's inputs were never fetched."""
    try:
        board_manifest.check(row)
    except ManifestError as exc:
        if "not on disk" not in str(exc):
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
    board_manifest.check(pico)
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


def _pins_stated(row: board_manifest.Row) -> dict[str, list[list[str]]]:
    """Per selected element, the pads each pin connects to, read straight off
    the vendor's schematic: part, then its library's device, then `<connect>`."""
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
                f"{merged} pads were merged so.")
        assert (rule in committed["derivation"]) == bool(merged), (row.board, merged)
    assert len(_committed(row_named("Adafruit QT Py ESP32-C3"))["pads"]) == 14


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
    kept for a pin is the first its schematic `<connect>` names."""
    for row in ROWS:
        _fetched(row)
        board = eagle.read_board(board_manifest.cad_path(row))
        min_x, _, _, max_y = board.extent_mm()
        margin = import_board.MARGIN_MM
        firsts = {(name, pads[0]) for name, pins in _pins_stated(row).items() for pads in pins}
        vendor = {
            (name, pad.number): pad
            for name in row.select
            for pad in board.element(name).pads_of("thru_hole")
            if (name, pad.number) in firsts
        }
        assert len(vendor) == len(firsts), row.board
        committed = _committed(row)
        scale = committed["px_per_mm"]
        matched = []
        for pad in committed["pads"]:
            hits = [
                key for key, source in vendor.items()
                if key[1] == pad["pad"]
                and abs(pad["x"] / scale - (source.x_mm - min_x + margin)) <= 0.05 / scale
                and abs(pad["y"] / scale - (max_y - source.y_mm + margin)) <= 0.05 / scale
            ]
            assert len(hits) == 1, (row.board, pad, hits)
            assert pad["label"] == vendor[hits[0]].net, (row.board, pad["pad"])
            matched.append(hits[0])
        assert sorted(matched) == sorted(vendor), row.board


def test_the_licence_is_what_the_vendors_own_files_state():
    """SparkFun's registry licence is inferred from a sibling repository, so
    that board quotes the sentence its own CAD file places; a row whose
    registry licence was read from a file it fetches quotes that file."""
    for row in ROWS:
        _fetched(row)
        evidence = _committed(row)["source"]["licence_evidence"]
        assert evidence == board_manifest.licence_evidence(row)
        quote = (row.licence_statement[1] if row.licence_statement
                 else board_sources.source(row.source).licence.quote)
        assert repr(quote) in evidence


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
    variant = import_pindefs.BSP_DIR / row.package / "variants" / row.variant
    return import_pindefs.read_c_pin_constants(
        (variant / "pins_arduino.h").read_text(encoding="utf-8", errors="replace"))


def test_every_resolved_pad_says_which_sources_named_it():
    """OH-173's question, answered in the file: `chip_pin_from` names the
    variant where one of the pad's labels is a label the row opts in, and the
    row's own CAD, which traces every resolved pad on these three rows. Every
    opted-in label names a pad: an opt-in that matches nothing is a claim in
    the table that the file never uses."""
    for row in ROWS:
        _fetched(row)
        matched = set()
        resolved = [pad for pad in _committed(row)["pads"] if pad["chip_pin"]]
        assert resolved, row.board
        for pad in _committed(row)["pads"]:
            if pad["chip_pin"] is None:
                assert "chip_pin_from" not in pad, (row.board, pad["label"])
                continue
            named = {alt for alt in import_pindefs.alternatives(pad["label"])
                     if alt in row.labels}
            matched |= named
            assert pad["chip_pin_from"] == sorted(
                {row.source} | ({row.package} if named else set())), (row.board, pad)
        assert matched == set(row.labels), row.board


def test_every_resolved_pin_is_the_gpio_a_second_vendor_statement_names():
    """The trace is one statement, and every resolved pad has another that
    agrees: the GPIO the vendor's net name carries, as SparkFun's `IO8`, or
    the variant's number for a label the row opts in, as Adafruit's `TX`."""
    for row in ROWS:
        _fetched(row)
        numbers = _variant_numbers(row)
        for pad in _committed(row)["pads"]:
            if pad["chip_pin"] is None:
                continue
            parts = pad["label"].split("/")
            stated = {int(found.group(1)) for part in parts
                      if (found := re.fullmatch(r"(?:GPIO|IO)(\d+)", part, re.I))}
            stated |= {numbers[part] for part in parts if part in row.labels}
            assert stated == {pad["chip_index"]}, (row.board, pad["label"], stated)


def _trace(row: board_manifest.Row, text: str | None = None,
           table: board_manifest.PinTable | None = None) -> dict:
    path = board_manifest.cad_path(row)
    return import_pindefs.read_eagle_traced(
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


def test_no_row_label_keys_its_chips_module_table():
    """Each row's `assumption` says no level is read through its chip
    module's table for any pad; `webui.api.header_key` is that join. It
    says a level is read at the pad's own `chip_index` instead, which
    `webui.api.row_levels` does (OH-179)."""
    from webui import api

    checked = []
    for row in ROWS:
        names = getattr(api.description_for(row.board), "PIN_NAMES", None)
        if names is None:
            continue
        committed = _committed(row)
        assert "no level is read through it for any pad here" in committed["assumption"]
        assert "reads a pad's level at its own `chip_index`" in committed["assumption"]
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
    withheld = boards["SparkFun Thing Plus ESP32-C6"].firmware_withheld
    assert "variants/sparkfun_esp32c6_thing_plus" in withheld, withheld
    assert "BOARD_FIRMWARE_VERIFIED names no test" in withheld, withheld
    assert boards["Adafruit Feather ESP32-C6"].firmware_verified is True
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
