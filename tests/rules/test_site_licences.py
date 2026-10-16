# OpenHardware - what the static site may publish (OH-241).
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`tools/site_licences.py`: a model ships only where its licence allows it.

The models themselves are gitignored and built per machine, so most of these
hold the decision on a small index made here; the last holds every model
this machine has to a row.
"""

from __future__ import annotations

import pytest

from tools import board_sources, site_licences

KICAD = site_licences.KICAD_PACKAGES3D
UNO = {"file": "/models/Arduino-Uno.glb", "source": "Arduino's own EAGLE board file"}
RP2040 = {"file": "/models/RP2040.glb", "source": "https://files.seeedstudio.com/..."}
LED = {"file": "/models/parts/LED_D3_0mm.glb",
       "source": f"{KICAD}-/raw/master/LED_THT.3dshapes/LED_D3.0mm.step"}


def index(boards: dict[str, dict], parts: list[dict] = ()) -> dict:
    return {"units": "mm", "boards": boards,
            "parts": {"source": "KiCad", "libraries": {"LED_THT": list(parts)}}}


def test_every_shipped_row_names_a_board_file_read_under_a_shippable_licence():
    sources = {source.name: source.licence for source in board_sources.SOURCES}
    shipped = [row for row in site_licences.BOARD_MODELS.values()
               if isinstance(row, site_licences.Ships)]
    assert shipped
    for row in shipped:
        licence = sources[row.source]
        assert licence.evidence is board_sources.Evidence.OPENED, row.source
        assert licence.name in site_licences.SHIPPABLE, row.source


def test_a_row_whose_licence_is_only_stated_is_refused():
    with pytest.raises(site_licences.NotShippable, match="stated"):
        site_licences.board_licence(site_licences.Ships("pcbcupid-glyph-c3"))


def test_a_row_under_a_licence_outside_the_shippable_set_is_refused():
    with pytest.raises(site_licences.NotShippable, match="Apache-2.0"):
        site_licences.board_licence(site_licences.Ships("olimex-esp32-poe"))


def test_a_row_naming_no_source_is_refused():
    with pytest.raises(site_licences.NotShippable, match="no-such-board"):
        site_licences.board_licence(site_licences.Ships("no-such-board"))


def test_every_notice_a_row_asks_for_is_pinned():
    named = {key for row in site_licences.BOARD_MODELS.values()
             if isinstance(row, site_licences.Ships) for key in row.notices}
    assert named == set(site_licences.NOTICE_TEXTS)


def test_the_models_drawing_adafruit_cad_parts_carry_its_notice():
    """PROVENANCE.md section 4: the MIT notice travels with each such .glb."""
    carrying = {name for name, row in site_licences.BOARD_MODELS.items()
                if isinstance(row, site_licences.Ships)
                and "Adafruit_CAD_Parts" in row.notices}
    assert carrying == {"Adafruit-QT-Py-ESP32-C3.glb", "Adafruit-Feather-ESP32-C6.glb",
                        "Adafruit-KB2040.glb"}


def test_a_model_with_no_row_stops_the_selection_by_name():
    with pytest.raises(site_licences.UnlistedModel, match="New-Board.glb"):
        site_licences.select(index({}), ["New-Board.glb"])


def test_a_withheld_board_is_left_out_of_the_index_and_the_files():
    selection = site_licences.select(
        index({"Arduino Uno": UNO, "XIAO-RP2040-DIP": RP2040}),
        ["Arduino-Uno.glb", "RP2040.glb"])
    assert list(selection.index["boards"]) == ["Arduino Uno"]
    assert selection.files == ["Arduino-Uno.glb"]
    assert list(selection.withheld) == ["RP2040.glb"]


def test_kicad_parts_ship_with_the_boards():
    selection = site_licences.select(index({"Arduino Uno": UNO}, [LED]),
                                     ["Arduino-Uno.glb", "parts/LED_D3_0mm.glb"])
    assert selection.files == ["Arduino-Uno.glb", "parts/LED_D3_0mm.glb"]
    assert selection.index["parts"]["libraries"] == {"LED_THT": [LED]}


def test_a_part_from_outside_kicads_library_is_refused():
    elsewhere = {**LED, "source": "https://example.com/LED.step"}
    with pytest.raises(site_licences.UnlistedModel, match="example.com"):
        site_licences.select(index({}, [elsewhere]), ["parts/LED_D3_0mm.glb"])


def test_an_index_naming_a_model_that_is_not_on_disk_is_refused():
    with pytest.raises(site_licences.UnlistedModel, match="Arduino-Uno.glb"):
        site_licences.select(index({"Arduino Uno": UNO}), [])


def test_the_model_notice_names_the_licence_the_board_and_the_mit_text_whole():
    kb2040 = {"file": "/models/Adafruit-KB2040.glb", "source": "Adafruit's"}
    selection = site_licences.select(index({"Adafruit KB2040": kb2040}),
                                     ["Adafruit-KB2040.glb"])
    mit = "MIT License\n\nCopyright (c) 2016 Adafruit Industries\n\nPermission is hereby granted"
    notice = site_licences.model_notice(selection, {"Adafruit_CAD_Parts": mit})
    assert site_licences.CC_BY_SA_4 in notice
    assert "https://github.com/adafruit/Adafruit-KB2040-PCB.git" in notice
    assert "CC BY-SA 3.0 Unported" in notice
    assert mit in notice


def test_the_runtime_notice_carries_every_licence_text_whole():
    titles = [*site_licences.RUNTIME_TEXTS, *site_licences.EMSCRIPTEN_TEXTS]
    texts = {title: f"the whole text of {title}\nsecond line" for title in titles}
    notice = site_licences.runtime_notice(texts)
    assert [title for title in titles if texts[title] not in notice] == []


def test_every_model_built_on_this_machine_has_a_row():
    """The models are gitignored, so this holds what is here: a model built
    since the table was written fails here before a build meets it."""
    present = [name for name in site_licences.on_disk() if "/" not in name]
    if not present:
        pytest.skip("no models built on this machine: python tools/compose_board_3d.py")
    assert [name for name in present if name not in site_licences.BOARD_MODELS] == []
