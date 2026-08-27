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


# --- what each surface is made of -------------------------------------------


def test_the_unstyled_colour_is_given_no_material():
    """**The largest colour group in the corpus, and it must stay neutral.**

    `UNSTYLED` is what a face with no style of its own is painted -- 48,301
    triangles across four vendor models, counted 2026-08-27, which is more than
    every named colour on the Arduino Uno put together. Its own comment says it
    exists "rather than pretending to be a material".

    Giving it a finish would be exactly that pretence, at the largest scale
    available, and it would be the tempting thing to do because it is the group
    that would change the picture most.
    """
    from tools.import_3d_model import DEFAULT_FINISH, FINISHES, UNSTYLED, finish_for

    assert UNSTYLED not in FINISHES
    assert finish_for(UNSTYLED) is DEFAULT_FINISH


def test_a_colour_nothing_says_anything_about_keeps_the_old_material():
    """A model whose colours are not named draws today's picture, not a worse one.

    The default is what every material in every model had before `FINISHES`
    existed, so an unrecognised colour is unchanged rather than guessed at.
    """
    from tools.import_3d_model import DEFAULT_FINISH, finish_for

    assert (DEFAULT_FINISH.metalness, DEFAULT_FINISH.roughness) == (0.1, 0.6)
    assert finish_for("#123456") is DEFAULT_FINISH
    assert "nothing here can say" in DEFAULT_FINISH.why


def test_metalness_is_zero_or_one_and_never_between():
    """**A surface is a conductor or it is not.**

    `Finish`'s docstring draws the line this test enforces: metalness is
    derived from what the thing is, and the values between 0 and 1 exist for
    textures that blend two materials across one surface, which nothing here
    has. A 0.5 in this table would be a way of saying "I am not sure" in a
    field that has no vocabulary for it -- and the vocabulary for that is to
    leave the colour out and let it take the default.
    """
    from tools.import_3d_model import FINISHES

    for colour, finish in FINISHES.items():
        assert finish.metalness in (0.0, 1.0), f"{colour} is {finish.metalness}"


def test_every_finish_says_what_the_evidence_was():
    """The assignment is the part that can be wrong, so it is the part written down.

    A roughness inside a sensible band is hard to get badly wrong. Calling the
    solder mask a metal is easy to get badly wrong, and the only defence is
    that each entry says which thing in which model it is talking about.
    """
    from tools.import_3d_model import FINISHES

    for colour, finish in FINISHES.items():
        assert len(finish.why) > 40, f"{colour} has no real evidence recorded"
        assert finish.why == finish.why.strip()


def test_the_uno_is_made_of_more_than_one_material():
    """The point of the exercise, asserted on the shipped file.

    Before this the Arduino Uno's ten colours were ten copies of one material.
    Gold contacts, a nickel shell, tin legs, epoxy and solder mask are four
    metals-or-not and four roughnesses, and if the model on disk does not carry
    them then the table is a document rather than a change.
    """
    import json
    import struct

    model = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not model.is_file():
        pytest.skip("no composed Uno; run tools/compose_board_3d.py")
    raw = model.read_bytes()
    length, _kind = struct.unpack_from("<II", raw, 12)
    document = json.loads(raw[20:20 + length].decode("utf-8"))
    finishes = {
        material["name"]: (material["pbrMetallicRoughness"]["metallicFactor"],
                           material["pbrMetallicRoughness"]["roughnessFactor"])
        for material in document["materials"]
    }
    # The four the evidence is strongest for. `#b58136` is the header contacts,
    # and it earned its entry by appearing on the five pin-header packages and
    # on nothing else.
    assert finishes["#b58136"] == (1.0, 0.30)
    assert finishes["#9ea1a8"] == (1.0, 0.25)
    assert finishes["#a5a392"] == (1.0, 0.35)
    assert finishes["#050505"] == (0.0, 0.70)
    # And more than one distinct material actually reaches the file.
    assert len(set(finishes.values())) >= 5


def test_the_writer_applies_the_finish_rather_than_a_constant(tmp_path):
    """**The code path, not the file on disk.**

    `test_the_uno_is_made_of_more_than_one_material` reads the shipped glTF,
    which is the right thing to assert and the wrong thing to rely on: the
    models are generated and gitignored, so that test passes on a stale file
    however `write_glb` is edited. This one drives the writer.

    Two colours, one in the table and one not, so both branches are exercised
    in a single call.
    """
    from tools.import_3d_model import DEFAULT_FINISH, FINISHES, Mesh, write_glb

    named = "#b58136"
    unnamed = "#123456"
    assert named in FINISHES and unnamed not in FINISHES
    triangle = ([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
                [0, 1, 2])
    mesh = Mesh({named: triangle, unnamed: triangle})
    out = tmp_path / "probe.glb"
    write_glb(mesh, out, "probe", "test", (1.0, 1.0, 1.0))

    raw = out.read_bytes()
    length, _kind = struct.unpack_from("<II", raw, 12)
    document = json.loads(raw[20:20 + length].decode("utf-8"))
    got = {
        material["name"]: (material["pbrMetallicRoughness"]["metallicFactor"],
                           material["pbrMetallicRoughness"]["roughnessFactor"])
        for material in document["materials"]
    }
    assert got[named] == (FINISHES[named].metalness, FINISHES[named].roughness)
    assert got[unnamed] == (DEFAULT_FINISH.metalness, DEFAULT_FINISH.roughness)
    # And the two really are different, or this proves nothing.
    assert got[named] != got[unnamed]

def test_a_part_with_no_forward_direction_writes_none():
    """**Absent, not `from: null`**, and the two are different claims.

    A resistor conducts either way, so `Electrical.forward` is `None` for it and
    `extras()` leaves the keys out entirely. `webui/static/parts.js` then reads
    `undefined` for `from` and `to`, and `analyse` never asks a non-diode for
    them. Writing `null` would put a key in the file inviting a reader to look
    for a direction that does not exist -- the same reasoning `convert_part`
    already applies to `electrical` itself for a part with no model at all.
    """
    from tools.import_3d_model import LED_ELECTRICAL, RESISTOR_ELECTRICAL

    diode = LED_ELECTRICAL.extras()
    assert (diode["from"], diode["to"]) == ("anode", "cathode")
    resistor = RESISTOR_ELECTRICAL.extras()
    assert "from" not in resistor and "to" not in resistor
    assert resistor["kind"] == "resistor" and resistor["ohms"] == 231.0


def test_the_resistors_body_is_not_a_metal_and_its_leads_still_are():
    """The two colours the axial resistor has, and they are not the same thing.

    `#c07635` is the lacquered body and `#a5a392` is the lead, which is the
    colour the table already calls "every component's LEG". A resistor drawn as
    a metal cylinder would be the finishes table saying something false about
    the one part whose material is easiest to check by looking at it.
    """
    from tools.import_3d_model import FINISHES

    assert FINISHES["#c07635"].metalness == 0.0
    assert FINISHES["#a5a392"].metalness == 1.0
    assert "resistor" in FINISHES["#c07635"].why


def test_the_resistor_the_importer_writes_carries_its_value_and_no_lens():
    """**The whole pipeline, on the file the page actually fetches.**

    Every other check of the resistor is of a constant in Python or a fragment
    in node. This one reads the glTF between them, because that is where a part
    stops being a table and becomes something a browser loads: the value has to
    survive `Electrical.extras`, the JSON chunk and `dressPart`.

    `lens: null` is the assertion worth having. A resistor shows nothing, and a
    part that named a lens would light one of its own surfaces to say a current
    was flowing -- which is inventing a display the part does not have, one step
    short of the ungrounded LED this area was rebuilt to stop.
    """
    from tools.import_3d_model import PARTS, read_extras

    part = next(p for p in PARTS if p.library == "Resistor_THT")
    glb = REPO / "webui" / "static" / "models" / "parts" / f"{part.slug}.glb"
    if not glb.is_file():
        pytest.skip("no imported resistor; run tools/import_3d_model.py --parts")
    extras = read_extras(glb)
    assert extras["lens"] is None
    assert extras["label"] == part.label
    assert extras["electrical"]["kind"] == "resistor"
    assert extras["electrical"]["ohms"] == 231.0
    assert "from" not in extras["electrical"]
    assert [lead["name"] for lead in extras["terminals"]] == ["lead A", "lead B"]
    # The leads are 7.62 mm apart by the part's own name, and the tips come out
    # of the mesh rather than out of that name -- so this is the two agreeing.
    left, right = (lead["at"][0] for lead in extras["terminals"])
    assert right - left == pytest.approx(7.62, abs=0.05)


def test_the_resistor_is_drawn_as_a_lacquered_body_on_metal_leads():
    """The finishes reach the file, on the part the table gained an entry for.

    `test_the_uno_is_made_of_more_than_one_material` makes the same check on
    the composed board. This is the smallest model in the tree that has two
    genuinely different materials in it, so it is the cheapest place for the
    body-versus-lead assignment to fail visibly.
    """
    from tools.import_3d_model import FINISHES, PARTS

    part = next(p for p in PARTS if p.library == "Resistor_THT")
    glb = REPO / "webui" / "static" / "models" / "parts" / f"{part.slug}.glb"
    if not glb.is_file():
        pytest.skip("no imported resistor; run tools/import_3d_model.py --parts")
    raw = glb.read_bytes()
    length, _kind = struct.unpack_from("<II", raw, 12)
    document = json.loads(raw[20:20 + length].decode("utf-8"))
    got = {
        material["name"]: (material["pbrMetallicRoughness"]["metallicFactor"],
                           material["pbrMetallicRoughness"]["roughnessFactor"])
        for material in document["materials"]
    }
    assert set(got) == {"#c07635", "#a5a392"}
    assert got["#c07635"] == (FINISHES["#c07635"].metalness,
                              FINISHES["#c07635"].roughness)
    assert got["#a5a392"] == (FINISHES["#a5a392"].metalness,
                              FINISHES["#a5a392"].roughness)
    assert got["#c07635"] != got["#a5a392"]

def test_a_part_that_names_a_lens_it_has_lost_still_refuses_to_convert():
    """**The guard OH-80 made conditional, and it has to still fire.**

    `convert_part` refuses a part whose named lens is not a colour in the mesh,
    because that is a file having changed underneath a part that is supposed to
    light up. Making the check skip a part with no lens is one edit away from
    making it skip everything, and the difference is invisible until a model
    changes months later.

    So both halves are exercised in one call each: the resistor names none and
    converts, and the same part with a colour the mesh does not have is
    refused. `--check` writes nothing; the STEP comes out of the cache.
    """
    import dataclasses

    from tools.import_3d_model import CACHE, DEFLECTION, PARTS, convert_part

    part = next(p for p in PARTS if p.library == "Resistor_THT")
    if not (CACHE / f"part-{part.slug}.step").is_file():
        pytest.skip("no cached STEP; run tools/import_3d_model.py --parts")

    assert convert_part(part, DEFLECTION, check=True) == 0
    with pytest.raises(SystemExit) as refused:
        convert_part(dataclasses.replace(part, lens="#abcdef"),
                     DEFLECTION, check=True)
    assert "#abcdef" in str(refused.value)
