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


def test_every_pad_is_where_the_vendors_board_file_puts_it():
    """Read the elements again, straight off the vendor's file, and match every
    committed pad to one of them by number and millimetres: EAGLE's Y points
    up, the file's down, and the file adds `MARGIN_MM` on each side. Keyed by
    element and number, because two elements can both have a pad 1."""
    for row in ROWS:
        _fetched(row)
        board = eagle.read_board(board_manifest.cad_path(row))
        min_x, _, _, max_y = board.extent_mm()
        margin = import_board.MARGIN_MM
        vendor = {
            (name, pad.number): pad
            for name in row.select
            for pad in board.element(name).pads_of("thru_hole")
        }
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


#: Pad number to GPIO for each chip, as `(package, value)` in a row's CAD,
#: that a row whose nets name no `IO<n>` places. Transcribed from Espressif's
#: datasheets, which are not fetched here:
#:   ESP32-C3FH4     ESP32-C3 Series Datasheet v2.4, "ESP32-C3 Consolidated
#:                   Pin Overview": Pin No. against IO MUX Function 1.
CHIP_PADS = {
    ("QFN32_5MM", "ESP32-C3FH4"): {
        "4": 0, "5": 1, "6": 2, "8": 3, "9": 4, "10": 5, "12": 6, "13": 7,
        "14": 8, "15": 9, "16": 10, "18": 11, "19": 12, "20": 13, "21": 14,
        "22": 15, "23": 16, "24": 17, "25": 18, "26": 19, "27": 20, "28": 21,
    },
}


def _chip(row: board_manifest.Row) -> tuple[eagle.Board, eagle.Element | None, dict]:
    """The row's board, and the one element on it `CHIP_PADS` describes."""
    path = board_manifest.cad_path(row)
    parts = ET.parse(path).getroot().findall("drawing/board/elements/element")
    known = [(part.get("name"), CHIP_PADS[key]) for part in parts
             if (key := (part.get("package"), part.get("value"))) in CHIP_PADS]
    assert len(known) <= 1, (row.board, known)
    board = eagle.read_board(path)
    if not known:
        return board, None, {}
    name, pads = known[0]
    return board, board.element(name), pads


def _gpios_reached(board: eagle.Board, chip: eagle.Element, pads: dict, net: str) -> list[int]:
    """The GPIOs of the chip's pads on `net`, or, where there are none, on
    the net beyond a two-pad part in series: the QT Py's TX reaches its
    ESP32-C3 through R4."""
    direct = [pads[pad.number] for pad in chip.pads if pad.net == net and pad.number in pads]
    if direct:
        return direct
    beyond = []
    for part in board.elements:
        nets = [pad.net for pad in part.pads]
        if part is not chip and len(nets) == 2 and net in nets:
            other = nets[1 - nets.index(net)]
            beyond += [pads[pad.number] for pad in chip.pads
                       if pad.net == other and pad.number in pads]
    return beyond


def test_every_resolved_pin_is_the_gpio_a_second_vendor_statement_names():
    """Two vendors, one answer. Where the vendor's net names `IO<n>`, as
    SparkFun's `IO16/TX` does, the net is the second statement. Where it
    does not, as Adafruit's `TX` does not, it is the chip pad the net
    reaches, read against Espressif's pin table in `CHIP_PADS`. Every
    resolved pad is checked one way or both, and every way agrees."""
    for row in ROWS:
        _fetched(row)
        board, chip, pads = _chip(row)
        resolved = [pad for pad in _committed(row)["pads"] if pad["chip_pin"]]
        assert resolved, row.board
        for pad in resolved:
            stated = [int(found.group(1)) for part in pad["label"].split("/")
                      if (found := re.fullmatch(r"IO(\d+)", part))]
            reached = _gpios_reached(board, chip, pads, pad["label"]) if chip else []
            assert stated or reached, (row.board, pad["label"], "nothing checks it")
            assert set(stated + reached) == {pad["chip_index"]}, (
                row.board, pad["label"], stated, reached, pad["chip_index"])


def test_no_supply_pad_reaches_a_gpio_of_its_chip():
    """What makes a label a supply (`SUPPLY_LABELS` in
    tests/rules/test_import_pindefs.py), checked on each row whose chip
    `CHIP_PADS` describes."""
    from tests.rules.test_import_pindefs import SUPPLY_LABELS

    checked = []
    for row in ROWS:
        _fetched(row)
        board, chip, pads = _chip(row)
        if chip is None:
            continue
        for pad in _committed(row)["pads"]:
            label = pad["label"]
            if label.split("/")[0].upper() in SUPPLY_LABELS or label.upper() in SUPPLY_LABELS:
                assert not [one.number for one in chip.pads
                            if one.net == label and one.number in pads], (row.board, label)
                checked.append((row.board, label))
    assert checked, "no row's chip is in CHIP_PADS, so nothing was checked"


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
