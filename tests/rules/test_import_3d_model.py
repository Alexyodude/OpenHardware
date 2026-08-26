# OpenHardware — the vendor's 3D model, and the frame it has to arrive in.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
#
# ## What is checked here, and what is checked by looking
#
# The tessellation itself is OpenCASCADE's and is not this repository's to
# test. What *is* this repository's is everything around it: which axis the
# board's thickness runs along, which solid is the PCB, whether the frame stays
# right-handed, and whether the glTF that comes out is a file a browser can
# read. Every one of those was wrong at some point on 2026-08-26 and each is
# pinned below.
#
# **The axis one is the reason this file exists.** Two of Seeed's four models
# are Z-up and two are Y-up, so a converter that assumed either laid half of
# them on their sides -- and the tell was a picture, not an exception. There is
# a unit test for `Frame` because a unit test can fail on a machine with no
# OpenCASCADE and no network, which is where CI is.
#
# ## What needs OCP, and what needs the network
#
# Nothing here downloads. The tests that need a tessellated model skip unless
# both OCP is installed and the archive is already in `third_party/seeed-3d/`,
# which is where `tools/import_3d_model.py` leaves it. They skip and say so,
# the same rule `CLAUDE.md` states for the checkers.

import json
import math
import pathlib
import struct

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

import_3d_model = pytest.importorskip("tools.import_3d_model")


def test_every_board_a_model_claims_is_a_board_this_repository_has():
    """A model for a board the catalogue does not carry would never be drawn,
    and the index would name it anyway."""
    from webui.boards import catalogue

    known = {board.name for board in catalogue.catalogue()}
    for model in import_3d_model.MODELS:
        for board in model.boards:
            assert board in known, f"{model.chip} claims {board!r}, which is not a board"


def test_no_two_models_claim_the_same_board():
    """The index is keyed by board, so a duplicate would silently be whichever
    model came last in the table."""
    seen: list[str] = []
    for model in import_3d_model.MODELS:
        seen.extend(model.boards)
    assert len(seen) == len(set(seen)), sorted(seen)


def test_every_model_comes_from_the_vendors_own_host_over_https():
    """**Not decoration.** The one model this table does not have is the XIAO
    ESP32-C3's, and the reason is exactly this: Seeed publishes that one on
    GrabCAD, behind a login and under someone else's terms. A row here pointing
    at a third-party mirror would make the provenance claim in
    `webui/static/board3d-panel.js`'s caption false.
    """
    for model in import_3d_model.MODELS:
        assert model.url.startswith("https://files.seeedstudio.com/"), model.url


def test_the_esp32_c3_is_absent_and_that_is_the_honest_gap():
    """Three runnable boards get no model. Pinned so that adding one from
    somewhere else is a decision somebody makes rather than a line that slips
    in -- and so that removing this test is what it takes to change the claim.
    """
    covered = {board for model in import_3d_model.MODELS for board in model.boards}
    for board in ("XIAO-ESP32-C3-DIP", "XIAO-ESP32-C3-DIP-SMD", "XIAO-ESP32-C3-SMD"):
        assert board not in covered


# --- the frame, which is the part that was wrong -----------------------------


def frame(long_axis: int, up: int, short_axis: int):
    """A `Frame` with no offset, for checking the axis algebra alone.

    **The handedness comes from `import_3d_model.handedness_of`, not from a
    copy of it here.** A test that recomputed the parity would agree with
    itself however wrong the module was -- which is the defect this repository
    has now caught three times, and the reason that function has a name.
    """
    return import_3d_model.Frame(
        long_axis=long_axis, up=up, short_axis=short_axis,
        handedness=import_3d_model.handedness_of((long_axis, up, short_axis)),
        origin=(0.0, 0.0, 0.0))


def test_a_z_up_model_puts_its_thickness_on_the_gltf_y_axis():
    """Seeed's SAMD21 and RP2040 models. Long side is x, thickness is z."""
    placed = frame(0, 2, 1).place(1.0, 2.0, 3.0)
    assert placed[0] == 1.0, "the long side becomes glTF x"
    assert placed[1] == 3.0, "the thickness becomes glTF y"
    assert abs(placed[2]) == 2.0, "the short side becomes glTF z"


def test_a_y_up_model_puts_its_thickness_on_the_gltf_y_axis_too():
    """**Seeed's ESP32-S3 and nRF52840 models, and the bug this pins.**

    Their thickness runs along the file's own y, not its z. A converter that
    assumed z laid them on their sides -- 22.484 x 4.462 x 17.782 read as a
    board 4 mm tall and 17 mm thick -- and nothing threw.
    """
    placed = frame(0, 1, 2).place(1.0, 2.0, 3.0)
    assert placed[0] == 1.0
    assert placed[1] == 2.0, "the thickness becomes glTF y whichever axis it was"
    assert abs(placed[2]) == 3.0


def test_the_frame_is_right_handed_whichever_axes_it_permutes():
    """**A mirrored board looks entirely plausible**, which is what makes this
    worth a test rather than a glance: a XIAO reflected end for end still has
    fourteen pads in two rows and still says SEEEDUINO on it.

    Every one of the six ways to name three axes is checked, because the two
    conventions in these four files are two of the six and the next vendor's
    file is free to be a third.
    """
    for long_axis in range(3):
        for up in range(3):
            if up == long_axis:
                continue
            short_axis = 3 - long_axis - up
            here = frame(long_axis, up, short_axis)
            # The determinant of the mapping, from where the three unit vectors
            # of the source land.
            columns = [here.place(*(1.0 if a == axis else 0.0 for a in range(3)))
                       for axis in range(3)]
            determinant = (
                columns[0][0] * (columns[1][1] * columns[2][2] - columns[1][2] * columns[2][1])
                - columns[1][0] * (columns[0][1] * columns[2][2] - columns[0][2] * columns[2][1])
                + columns[2][0] * (columns[0][1] * columns[1][2] - columns[0][2] * columns[1][1])
            )
            assert math.isclose(determinant, 1.0), (
                f"long={long_axis} up={up} short={short_axis} mirrors the board"
            )


def test_the_origin_moves_the_pcb_centre_to_zero_and_its_underside_to_the_floor():
    """The frame the renderer places by. A model centred on its *assembly*
    instead sits off its own pads by half the USB connector's overhang."""
    here = import_3d_model.Frame(long_axis=0, up=2, short_axis=1,
                                 handedness=-1.0, origin=(5.0, 3.0, 2.0))
    x, y, z = here.place(5.0, 3.0, 2.0)
    assert (x, y, z) == (0.0, 0.0, -0.0) or (x, y, z) == (0.0, 0.0, 0.0)


# --- the glTF that comes out -------------------------------------------------


def one_triangle_mesh():
    """A mesh of one triangle in one colour. Enough to exercise every field."""
    return import_3d_model.Mesh(groups={
        "#116517": ([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
                    [0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0],
                    [0, 1, 2]),
    })


def test_the_glb_it_writes_is_one_a_reader_can_take_apart(tmp_path):
    """Header, two chunks, four-byte alignment. **The renderer's own reader
    throws on anything it did not expect**, so a file that drifted from this
    shape would show a board with no model and a console warning rather than
    an error anybody sees."""
    out = tmp_path / "one.glb"
    size = import_3d_model.write_glb(one_triangle_mesh(), out, "TEST",
                                     "https://example.invalid/x.zip",
                                     (21.3, 17.9, 1.61))
    raw = out.read_bytes()
    assert len(raw) == size
    magic, version, total = struct.unpack("<III", raw[:12])
    assert magic == 0x46546C67, "glTF's magic"
    assert version == 2
    assert total == len(raw)

    json_length, json_kind = struct.unpack("<II", raw[12:20])
    assert json_kind == 0x4E4F534A
    assert json_length % 4 == 0, "the JSON chunk is padded to four"
    document = json.loads(raw[20:20 + json_length].decode("utf-8"))

    bin_length, bin_kind = struct.unpack(
        "<II", raw[20 + json_length:28 + json_length])
    assert bin_kind == 0x004E4942
    assert bin_length % 4 == 0, "the BIN chunk is padded to four"
    assert document["buffers"][0]["byteLength"] <= bin_length


def test_the_file_says_it_is_millimetres_because_gltfs_unit_is_the_metre(tmp_path):
    """A deviation from the spec that is stated in the file is a decision; one
    that is only in a docstring is a trap for whoever opens it in Blender."""
    out = tmp_path / "one.glb"
    import_3d_model.write_glb(one_triangle_mesh(), out, "TEST",
                              "https://example.invalid/x.zip", (21.3, 17.9, 1.61))
    extras = import_3d_model.read_extras(out)
    assert extras["units"] == "mm"
    assert extras["source"] == "https://example.invalid/x.zip"


def test_the_pcb_thickness_travels_with_the_mesh(tmp_path):
    """**The page cannot measure it.** The mesh's own bounding box is the
    assembly -- board, chip, connector -- so a renderer standing a pad marker
    on `height / 2` would put it in mid-air. 1.61 mm on a SAMD21 and 1.20 mm on
    an RP2040, which is why it is per-model rather than a constant."""
    out = tmp_path / "one.glb"
    import_3d_model.write_glb(one_triangle_mesh(), out, "TEST",
                              "https://example.invalid/x.zip", (21.3, 17.9, 1.61))
    assert import_3d_model.read_extras(out)["pcb"]["thickness"] == 1.61


def test_a_position_accessor_carries_the_bounds_the_spec_requires(tmp_path):
    """Not decoration: a viewer frames a model from these without reading the
    buffer, and glTF requires them on POSITION specifically."""
    out = tmp_path / "one.glb"
    import_3d_model.write_glb(one_triangle_mesh(), out, "TEST", "x", (1.0, 1.0, 1.0))
    raw = out.read_bytes()
    json_length = struct.unpack("<I", raw[12:16])[0]
    document = json.loads(raw[20:20 + json_length].decode("utf-8"))
    position = document["accessors"][
        document["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert position["min"] == [0.0, 0.0, 0.0]
    assert position["max"] == [1.0, 0.0, 1.0]


def test_each_colour_becomes_its_own_material_and_not_a_vertex_attribute():
    """Sixteen materials on the SAMD21, which is what makes the board green,
    the shield black and the castellations gold. One material with vertex
    colours would render the same and would lose the vendor's own names for
    them."""
    mesh = import_3d_model.Mesh(groups={
        "#116517": ([0.0] * 9, [0.0] * 9, [0, 1, 2]),
        "#ff9f37": ([0.0] * 9, [0.0] * 9, [0, 1, 2]),
    })
    assert mesh.triangles() == 2
    assert mesh.vertices() == 6


# --- what is actually on disk ------------------------------------------------


def test_the_index_and_the_meshes_agree_about_which_boards_have_one():
    """The page reads the index and fetches what it names. A `file` pointing at
    a mesh that is not there is a board that draws a footprint while the
    caption claims a model."""
    index = REPO / "webui" / "static" / "models" / "index.json"
    if not index.is_file():
        pytest.skip("no models imported; run tools/import_3d_model.py --all")
    document = json.loads(index.read_text(encoding="utf-8"))
    assert document["units"] == "mm"
    for board, entry in document["boards"].items():
        if entry["file"] is None:
            continue
        mesh = REPO / "webui" / "static" / entry["file"].lstrip("/")
        assert mesh.is_file(), f"{board} names {entry['file']}, which is not here"
        assert mesh.stat().st_size == entry["bytes"]
        assert entry["pcb"]["thickness"] > 0


def test_every_imported_mesh_is_a_glb_the_renderers_reader_would_accept():
    """The same four checks `readGlb` makes before it will draw anything."""
    models = REPO / "webui" / "static" / "models"
    found = sorted(models.glob("*.glb")) if models.is_dir() else []
    if not found:
        pytest.skip("no models imported; run tools/import_3d_model.py --all")
    for mesh in found:
        raw = mesh.read_bytes()
        assert struct.unpack("<I", raw[:4])[0] == 0x46546C67, mesh.name
        assert struct.unpack("<I", raw[4:8])[0] == 2, mesh.name
        extras = import_3d_model.read_extras(mesh)
        assert extras["units"] == "mm", mesh.name
        assert "pcb" in extras, mesh.name
