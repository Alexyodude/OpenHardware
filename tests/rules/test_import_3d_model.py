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


def test_the_audit_returns_exactly_the_colours_it_could_not_name(capsys):
    """**What the composer lists on the page as drawn in no named material**
    (OH-163), so it has to be every unnamed colour and nothing else.

    `report_finishes` printed the default and returned nothing, so the only
    place a reader could learn that a surface was grey for want of evidence
    was a terminal. Two named colours and two unnamed ones, of different
    sizes, so a return that dropped the counts, kept a named colour or
    dropped an unnamed one would each show here.
    """
    from tools.import_3d_model import FINISHES, Mesh, report_finishes

    one = ([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
           [0.0, 0.0, 1.0] * 3, [0, 1, 2])
    two = (one[0] * 2, one[1] * 2, [0, 1, 2, 3, 4, 5])
    mesh = Mesh({"#b58136": one, "#050505": two,
                 "#123456": one, "#654321": two})
    assert {"#b58136", "#050505"} <= set(FINISHES)
    assert not {"#123456", "#654321"} & set(FINISHES)

    unnamed = report_finishes(mesh)

    assert unnamed == {"#654321": 2, "#123456": 1}, unnamed
    printed = capsys.readouterr().out
    assert printed.count("DEFAULT, nothing says what this is") == 2, printed


def test_the_index_carries_each_composed_boards_unnamed_colours(
        tmp_path, monkeypatch):
    """**`default_finish` reaches the file the page fetches** (OH-163).

    The composer writes the colours `FINISHES` cannot name into a board's
    extras, and `write_index` copied `drawn`, `modelled` and `absent` out of
    those extras into `index.json` and left this one behind -- so the list
    stopped at a `.glb` nothing reads extras out of. One composed board
    written with a known list, the index written over it, and the board's
    entry must carry the list unchanged.
    """
    from tools import import_3d_model
    from tools.import_3d_model import Mesh, write_glb, write_index

    monkeypatch.setattr(import_3d_model, "OUT", tmp_path)
    triangle = ([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0] * 3, [0, 1, 2])
    unnamed = {"#123456": 1, "#654321": 7}
    write_glb(Mesh({"#123456": triangle}), tmp_path / "Probe-Board.glb",
              "Probe Board", "test", (1.0, 1.0, 1.0),
              extras={"composed": True, "default_finish": unnamed})

    index = write_index((("Probe Board", "probe-chip", "Probe-Board"),))

    entry = json.loads(index.read_text(encoding="utf-8"))["boards"]["Probe Board"]
    assert entry.get("default_finish") == unnamed, (
        f"the index entry is {entry}, without the board's unnamed colours")


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


def test_no_metal_is_darker_than_a_metal_reflects():
    """**The near-black argument, as a rule over the whole table** (OH-163).

    A metal's base colour IS its reflectance, and no metal used in electronics
    reflects under about half -- the argument `FINISHES` gives for calling its
    near-blacks dielectrics. Read the other way it says what may be a metal:
    nothing with every channel under half. That is why `#1d1d1d` stays at the
    default although KiCad's own palette calls it `MET-ALUMINUM` -- metalness
    1.0 on an 11% base would draw a black mirror -- and why `#4e4e4e`, which
    `tools/model_from_datasheet.py` calls a steel lid, does too.
    """
    from tools.import_3d_model import FINISHES

    for colour, finish in FINISHES.items():
        if finish.metalness == 1.0:
            brightest = max(int(colour[at:at + 2], 16) for at in (1, 3, 5))
            assert brightest >= 128, (
                f"{colour} is a metal in FINISHES, and its brightest channel "
                f"is {brightest} of 255: darker than any metal reflects")


#: KiCad StepUp's material palette as each `.wrl` at kicad-packages3D tag
#: 9.0.0 opens with it: name -> diffuse colour, sRGB, copied as written there.
KICAD_PALETTE = {
    "PIN-01": (0.824, 0.82, 0.781),
    "CAP-CERAMIC-06": (0.379, 0.27, 0.215),
    "CAP-CERAMIC-05": (0.273, 0.273, 0.273),
    "IC-LABEL-01": (0.691, 0.664, 0.598),
    "PLASTIC-GREEN-01": (0.340, 0.680, 0.445),
    "PLASTIC-BLUE-01": (0.137, 0.402, 0.727),
    "BOARD-BLACK-03": (0.16, 0.16, 0.16),
    "PLASTIC-WHITE-01": (0.895, 0.891, 0.813),
    "MET-ALUMINUM": (0.372322, 0.371574, 0.373173),
    "MET-SILVER": (0.50754, 0.50754, 0.50754),
}


def test_kicads_own_names_for_the_colours_it_cites():
    """**A citation of KiCad's palette is arithmetic, so it is checked as
    arithmetic** (OH-163).

    A KiCad STEP carries the same sRGB numbers its `.wrl` palette names, and
    OpenCASCADE's reader makes them linear before `colour_of` writes a hex --
    so a palette entry converts to exactly one key. Every `FINISHES` entry
    that cites a palette name in backticks must be the key that name converts
    to: an entry citing the wrong name, or a key mistyped, fails here. The
    conversion is pinned on `PIN-01`, which has been `#a5a392` -- every
    component's leg -- since that entry was written.
    """
    from tools.import_3d_model import FINISHES

    def key(srgb):
        def linear(c):
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        return "#" + "".join(f"{round(linear(c) * 255):02x}" for c in srgb)

    assert key(KICAD_PALETTE["PIN-01"]) == "#a5a392"
    cited = {}
    for colour, finish in FINISHES.items():
        for name, srgb in KICAD_PALETTE.items():
            if f"`{name}`" in finish.why:
                assert colour == key(srgb), (
                    f"{colour}'s evidence cites KiCad's `{name}`, which is "
                    f"{key(srgb)}, not {colour}")
                cited[name] = colour
    assert cited == {
        "CAP-CERAMIC-06": "#1e0f0a", "CAP-CERAMIC-05": "#0f0f0f",
        "IC-LABEL-01": "#6f6651", "PLASTIC-GREEN-01": "#186b2a",
        "PLASTIC-BLUE-01": "#04227c", "BOARD-BLACK-03": "#060606",
        "PLASTIC-WHITE-01": "#c6c4a0",
    }, cited
    assert key(KICAD_PALETTE["MET-ALUMINUM"]) == "#1d1d1d"
    assert "#1d1d1d" not in FINISHES, (
        "#1d1d1d is KiCad's MET-ALUMINUM and darker than any metal reflects: "
        "the two readings disagree, so it takes the default")
    assert key(KICAD_PALETTE["MET-SILVER"]) == "#383838"
    assert "#383838" not in FINISHES, (
        "#383838 is KiCad's MET-SILVER and, at 22% linear, darker than any "
        "metal reflects: the two readings disagree, so it takes the default")


def test_kicads_white_is_a_body_and_not_a_metal():
    """**`#c6c4a0` was the tactile switch's 'metal cover', and it is not a
    metal** (OH-163's review).

    `FINISHES` read the TS42's two colours off their values -- the bright one
    the steel cover, the dark one the moulded actuator -- and had them the
    wrong way round. On the cached B3S-1000 STEP this colour is the round
    plunger on top, 3.57 mm across, and KiCad's palette calls it
    `PLASTIC-WHITE-01`. It also paints KiCad's chip LED bodies, the
    WS2812B-Mini's housing and the resistors' substrate, so at metalness 1.0
    every composed board carrying any of them drew those as polished metal.
    """
    from tools.import_3d_model import FINISHES

    assert FINISHES["#c6c4a0"].metalness == 0.0, (
        f"#c6c4a0 is a metal in FINISHES ({FINISHES['#c6c4a0']}); it is a "
        f"moulded or fired body on every model that carries it")


def test_kicads_silver_is_listed_at_the_default_with_its_reason():
    """**`#383838` is the switch's cover and still not named** (OH-163's
    review): KiCad's palette calls it `MET-SILVER`, and on the B3S-1000 it is
    the 6 x 6.6 mm cover, a metal by name and by place -- at 22% linear
    reflectance, below anything a metal reflects. Two readings that disagree
    leave a colour at the default, as `#1d1d1d`'s do, and the table's own
    list of colours examined and left there has to say so, with the reason.
    """
    source = (REPO / "tools" / "import_3d_model.py").read_text(encoding="utf-8")
    examined = source.split("**Examined for OH-163 and left at the default**",
                            1)[1].split("**Four entries were written", 1)[0]
    entry = examined.split("`#383838`", 1)
    assert len(entry) == 2, (
        f"#383838 is not in the list of colours left at the default:{examined}")
    assert "MET-SILVER" in entry[1].split("#:   * ", 1)[0], (
        f"#383838's line does not give KiCad's name for it: {entry[1]}")


def test_the_label_colour_lies_on_top_of_every_body_that_carries_it():
    """**`#6f6651` was 'very probably an exposed thermal pad'; it is on top.**

    OH-163 named it as KiCad's `IC-LABEL-01`, the orientation mark printed on
    a package, and a mark is only a mark if it is on the top face: an exposed
    pad would be at the bottom, under the body, where the solder is. Checked on
    every KiCad model fetched into the cache, so a model added later that
    styles a pad or a lead with this colour fails here rather than shading
    a metal as ink. A mark may stand just proud of the top or sit just sunk
    into it, as a moulded dimple does -- 0.10 mm deep on the QFN-56 -- so
    `on_top_mm` allows a little more than that below the top.

    Skips without OCP or without a fetched model, as the header says.
    """
    pytest.importorskip("OCP")
    from tools.import_3d_model import DEFLECTION, Frame, handedness_of, read, tessellate

    mark, on_top_mm = "#6f6651", 0.15
    steps = sorted((REPO / "third_party" / "seeed-3d").glob("component-*.step"))
    if not steps:
        pytest.skip("no KiCad model fetched; run tools/compose_board_3d.py")
    frame = Frame(long_axis=0, up=1, short_axis=2,
                  handedness=handedness_of((0, 1, 2)), origin=(0.0, 0.0, 0.0))
    carrying = []
    for step in steps:
        shape, styles, _document = read(step)
        groups = tessellate(shape, styles, DEFLECTION, frame).groups
        if mark not in groups:
            continue
        heights = groups[mark][0][2::3]
        top = max(z for colour, (positions, _n, _i) in groups.items()
                  if colour != mark for z in positions[2::3])
        assert min(heights) >= top - on_top_mm, (
            f"{step.name}: {mark} reaches down to {min(heights):.3f} mm and "
            f"the rest of the model's top is {top:.3f}: not a mark on top")
        carrying.append(step.name)
    if not carrying:
        pytest.skip(f"no fetched model carries {mark}")


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


def _gltf(glb: pathlib.Path):
    """The JSON chunk and the binary chunk of a `.glb`, as a pair.

    `read_extras` in the importer reads the first few hundred bytes and stops;
    this needs the buffer too, so it is its own eight lines rather than a
    parameter added to a function whose whole point is not to read the buffer.
    """
    raw = glb.read_bytes()
    length, _kind = struct.unpack_from("<II", raw, 12)
    return json.loads(raw[20:20 + length].decode("utf-8")), raw[20 + length + 8:]


def _read(doc, body, index):
    """One accessor's values, as a list of tuples."""
    accessor = doc["accessors"][index]
    view = doc["bufferViews"][accessor["bufferView"]]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    letter = {5126: "f", 5125: "I", 5123: "H"}[accessor["componentType"]]
    wide = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[accessor["type"]]
    count = accessor["count"] * wide
    flat = struct.unpack_from(f"<{count}{letter}", body, start)
    return [flat[i:i + wide] for i in range(0, count, wide)]


# --- a seam is not an edge --------------------------------------------------


def test_a_periodic_surfaces_seam_is_given_one_normal():
    """**The wrap line, which is the whole reason `weld_seams` exists.**

    OCC meshes a cylinder as ONE periodic face and duplicates the vertices
    where its parametrisation comes back round to zero. Each copy then gets the
    average of only the triangles on its own side, so a surface that is smooth
    comes back with a hard shading line down it -- and at `ANGULAR`'s 0.5 rad
    that line is a whole facet's worth of normal, about 28 degrees, dropped on
    a single edge.

    Two vertices at one point, 20 degrees apart, which is what a seam looks
    like. They must come out equal, and pointing between where they started.
    """
    from tools.import_3d_model import weld_seams

    tilt = math.radians(10.0)
    positions = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    normals = [math.sin(-tilt), math.cos(tilt), 0.0,
               math.sin(tilt), math.cos(tilt), 0.0]
    assert weld_seams(positions, normals) == 2
    assert normals[0:3] == normals[3:6]
    # Between the two, which for a symmetric pair is straight up.
    assert normals[0] == pytest.approx(0.0, abs=1e-12)
    assert normals[1] > 0


def test_a_corner_where_three_faces_meet_stays_sharp():
    """**The case that stops this being a smoothing pass.**

    A cube's corner is three vertices at one point whose normals are 90 degrees
    apart, and averaging them would round off an edge that is genuinely square
    -- turning every chip package on the board into a bar of soap. Each of the
    three sits 54.7 degrees from their mean, well past `SMOOTH_DEGREES`, so all
    three are left exactly as they were.
    """
    from tools.import_3d_model import weld_seams

    positions = [1.0, 2.0, 3.0] * 3
    normals = [1.0, 0.0, 0.0,
               0.0, 1.0, 0.0,
               0.0, 0.0, 1.0]
    before = list(normals)
    assert weld_seams(positions, normals) == 0
    assert normals == before


def test_a_forty_five_degree_chamfer_is_not_smoothed_away():
    """The nearest real edge to the threshold, checked from the other side.

    `SMOOTH_DEGREES` is 20 from the mean, so 40 across a pair. A chamfer meets
    its face at 45 degrees, which puts each normal 22.5 degrees out -- past it,
    and deliberately so: the bevel on a DIP package and the rim of a capacitor
    lid are both this shape, and both are meant to catch the light as an edge.
    """
    from tools.import_3d_model import weld_seams

    half = math.radians(22.5)
    positions = [0.0, 0.0, 0.0] * 2
    normals = [math.sin(-half), math.cos(half), 0.0,
               math.sin(half), math.cos(half), 0.0]
    before = list(normals)
    assert weld_seams(positions, normals) == 0
    assert normals == before


def test_two_vertices_a_hair_apart_are_two_vertices():
    """Coincident means coincident, not nearby.

    The key rounds to 0.1 um, three orders below `DEFLECTION`'s 50 um chord
    error, so nothing the tessellator emits as two distinct points can land in
    one bucket. A millimetre apart is very distinct.
    """
    from tools.import_3d_model import weld_seams

    # 0.2 mm, which is four times `DEFLECTION`'s chord error and a distance
    # the tessellator really does produce between neighbours. A key rounded to
    # whole millimetres would put these two in one bucket and merge a pair of
    # vertices that are nothing to do with each other.
    positions = [0.0, 0.0, 0.0, 0.2, 0.0, 0.0]
    normals = [0.0, 1.0, 0.0, 0.05, 1.0, 0.0]
    before = list(normals)
    assert weld_seams(positions, normals) == 0
    assert normals == before


def test_the_weld_keeps_the_area_weighting_it_was_given():
    """Summed, not averaged, and the difference is a real one.

    `accumulate_normals` leaves each normal scaled by twice the area of the
    triangles that produced it, which is the standard weighting and the better
    average. Summing a seam's two halves gives the vertex what it would have
    had if the face had never been cut; averaging their directions would throw
    that away and weight a sliver the same as a quad.
    """
    from tools.import_3d_model import weld_seams

    # **Neither weight is 1, which is what makes this test able to fail.** The
    # first version used 9 and 1: a version that normalised before summing
    # produced 9 + 1 = 10 as well, because the cluster is SEEDED with the first
    # normal unscaled and only later members would have been divided. Two
    # weights that are both unequal to one separate the two behaviours -- 13
    # against 10.
    positions = [0.0, 0.0, 0.0] * 2
    normals = [0.0, 9.0, 0.0, 0.0, 4.0, 0.0]
    assert weld_seams(positions, normals) == 2
    assert normals == [0.0, 13.0, 0.0, 0.0, 13.0, 0.0]


def test_the_shipped_meshes_have_almost_no_seams_left():
    """The measurement, on the files the page actually fetches.

    Counted before the weld existed: 509 coincident pairs in the Arduino Uno's
    `#a5a392` group whose normals disagreed by more than a degree, the worst
    22.1 degrees apart, and 178 more in `#050505`. What is left is the handful
    where three or more surfaces genuinely meet, which this must NOT merge.
    """
    model = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not model.is_file():
        pytest.skip("no composed Uno; run tools/compose_board_3d.py")
    doc, body = _gltf(model)
    worst: dict[str, int] = {}
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            name = doc["materials"][primitive["material"]]["name"]
            points = _read(doc, body, primitive["attributes"]["POSITION"])
            normals = _read(doc, body, primitive["attributes"]["NORMAL"])
            at: dict[tuple, list] = {}
            for point, normal in zip(points, normals):
                at.setdefault(tuple(round(v, 4) for v in point), []).append(normal)
            unwelded = 0
            for group in at.values():
                if len(group) < 2:
                    continue
                spread = max(
                    math.degrees(math.acos(max(-1.0, min(1.0, sum(
                        a * b for a, b in zip(group[i], group[j]))))))
                    for i in range(len(group)) for j in range(i + 1, len(group)))
                if 1.0 < spread < 25.0:
                    unwelded += 1
            worst[name] = unwelded
    assert worst.get("#a5a392", 0) <= 20, worst
    assert worst.get("#050505", 0) <= 20, worst


def test_the_tessellator_welds_what_it_meshes():
    """**That `weld_seams` is correct and that anything CALLS it are two claims.**

    The tests above drive the function directly, which leaves the whole of it
    removable from `tessellate` without one of them noticing -- caught by
    mutation on 2026-08-28, where stubbing the call out left every unit test
    green because the shipped `.glb` on disk was already welded and nothing
    re-meshed anything.

    So this runs the real tessellator over the real STEP. The axial resistor is
    the cheapest shape in the corpus that has a periodic face: a cylinder body
    on two cylindrical leads, 1,950 triangles, and 378 vertices on a seam.
    """
    from tools.import_3d_model import CACHE, DEFLECTION, part_frame, read, tessellate

    step = CACHE / "part-R_Axial_DIN0207_L6_3mm_D2_5mm_P7_62mm_Horizontal.step"
    if not step.is_file():
        pytest.skip("no cached STEP; run tools/import_3d_model.py --parts")
    shape, styles, _document = read(step)
    mesh = tessellate(shape, styles, DEFLECTION, part_frame(shape))

    unwelded = 0
    for positions, normals, _indices in mesh.groups.values():
        at: dict[tuple, list[tuple[float, float, float]]] = {}
        for vertex in range(0, len(positions), 3):
            at.setdefault(tuple(round(positions[vertex + axis], 4)
                                for axis in range(3)), []).append(
                tuple(normals[vertex + axis] for axis in range(3)))
        for group in at.values():
            if len(group) < 2:
                continue
            spread = max(
                math.degrees(math.acos(max(-1.0, min(1.0, sum(
                    a * b for a, b in zip(group[i], group[j]))))))
                for i in range(len(group)) for j in range(i + 1, len(group)))
            # Between a degree and the smoothing threshold is the band that
            # `weld_seams` exists to empty: closer than that is already one
            # surface, wider is a real edge it must leave alone.
            if 1.0 < spread < 25.0:
                unwelded += 1
    assert unwelded == 0, f"{unwelded} seams came out of the tessellator unwelded"

    # And the real edges survived, or this passed by flattening the part.
    sharp = 0
    for positions, normals, _indices in mesh.groups.values():
        at = {}
        for vertex in range(0, len(positions), 3):
            at.setdefault(tuple(round(positions[vertex + axis], 4)
                                for axis in range(3)), []).append(
                tuple(normals[vertex + axis] for axis in range(3)))
        for group in at.values():
            if len(group) < 2:
                continue
            spread = max(
                math.degrees(math.acos(max(-1.0, min(1.0, sum(
                    a * b for a, b in zip(group[i], group[j]))))))
                for i in range(len(group)) for j in range(i + 1, len(group)))
            if spread >= 25.0:
                sharp += 1
    assert sharp > 50, (
        f"only {sharp} sharp edges left in a part with square-cut leads and a "
        f"body that meets them at a right angle; the weld has rounded it off"
    )


# --- a PCB is two layers ----------------------------------------------------


def test_only_the_solder_masks_are_coated():
    """**A coat is a claim about a substance, not a way of making things shiny.**

    Solder mask is pigmented epoxy under a cured, near-transparent surface --
    two layers, which is why a board brightens as you tilt it and a moulded body
    does not. Everything else in this table is one layer and must stay that way:
    a coated DIP package or a coated header pin would be this repository
    inventing a material, which is the failure `FINISHES` exists to avoid.
    """
    from tools.import_3d_model import FINISHES

    coated = {colour for colour, finish in FINISHES.items() if finish.coat}
    # `#1b1b1b` is BOARD_MASK, added by OH-97: the XIAO family's mask, whose
    # COLOUR is a judgement and whose being a mask is not. It belongs here for
    # the same reason the other two do, and this list is what stops a coat
    # spreading to a part that is one layer.
    #
    # OH-163 added the composed boards' other masks and every composed
    # board's ROUTING, which is the same film with copper behind it -- each
    # one a mask, as `test_every_composed_boards_mask_and_routing_is_a_solder_mask`
    # holds against the compositions themselves.
    assert coated == {
        "#313d63", "#116517", "#1b1b1b",
        "#e2180f", "#9f180f", "#cd3c25", "#233e2b",
        "#2a2a2a", "#4c5f99", "#ff2517", "#f62517", "#ff5d39", "#366043",
    }, coated
    for colour in coated:
        assert "solder mask" in FINISHES[colour].why, (
            f"{colour} is coated and its evidence does not say it is a mask"
        )


def test_a_coat_defaults_to_none_so_no_old_entry_changed():
    """Every finish written before the coat existed keeps exactly its material.

    `Finish` gained two fields, and a default of anything but zero would have
    silently restated thirteen measured surfaces. The glTF says the same thing
    a second way: a material with no coat carries no extension at all.
    """
    from tools.import_3d_model import DEFAULT_FINISH, Finish

    plain = Finish(0.0, 0.5, "a" * 50)
    assert (plain.coat, plain.coat_roughness) == (0.0, 0.0)
    assert DEFAULT_FINISH.coat == 0.0


def test_the_coat_is_written_as_the_registered_extension(tmp_path):
    """`KHR_materials_clearcoat`, not a private key.

    These files are glTF and other things read them -- and `extensionsUsed` is
    a promise about the document, so it is declared when something uses it and
    absent when nothing does. A file listing an extension no material carries
    is a file that lies about itself in a way every validator believes.
    """
    from tools.import_3d_model import FINISHES, Mesh, write_glb

    triangle = ([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
                [0, 1, 2])
    for colours, expect in ((["#313d63"], True), (["#a5a392"], False)):
        target = tmp_path / f"{colours[0][1:]}.glb"
        write_glb(Mesh({c: triangle for c in colours}), target,
                  "probe", "test", (1.0, 1.0, 1.0))
        raw = target.read_bytes()
        length, _kind = struct.unpack_from("<II", raw, 12)
        document = json.loads(raw[20:20 + length].decode("utf-8"))
        material = document["materials"][0]
        assert ("KHR_materials_clearcoat" in material.get("extensions", {})) is expect
        assert ("extensionsUsed" in document) is expect
        if expect:
            coat = material["extensions"]["KHR_materials_clearcoat"]
            assert coat["clearcoatFactor"] == FINISHES[colours[0]].coat
            assert coat["clearcoatRoughnessFactor"] == \
                FINISHES[colours[0]].coat_roughness


def test_the_shipped_board_carries_its_coat_and_nothing_else_does():
    """The measurement, on the file the page actually fetches."""
    model = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not model.is_file():
        pytest.skip("no composed Uno; run tools/compose_board_3d.py")
    document, _body = _gltf(model)
    assert document.get("extensionsUsed") == ["KHR_materials_clearcoat"]
    coated = {material["name"] for material in document["materials"]
              if "KHR_materials_clearcoat" in material.get("extensions", {})}
    # The mask and its routing, which is the mask over copper (OH-163).
    assert coated == {"#313d63", "#4c5f99"}, coated


# --- an albedo is linear, and a CAD file's colours are not ------------------


def test_an_srgb_byte_becomes_the_linear_value_gltf_asks_for():
    """**This was `channel / 255`, which is a different colour.**

    glTF defines `baseColorFactor` as linear and three.js reads it as linear,
    so writing an sRGB byte there made every albedo in every model too bright
    -- and differently too bright per channel, because the transfer function is
    a curve. That is what flattens a colour toward grey.

    Checked at the ends, at the knee, and at the standard's own midpoint: 0.5
    sRGB is 0.2140 linear, which is the number this function exists to produce
    instead of 0.5.
    """
    from tools.import_3d_model import linear

    assert linear(0) == 0.0
    assert linear(255) == pytest.approx(1.0)
    # Below the knee the curve is a straight 1/12.92, and 10/255 is below it.
    assert linear(10) == pytest.approx((10 / 255) / 12.92)
    # Above it, the power law. **0.2140 is the number everyone quotes and it is
    # the answer for an input of exactly 0.5** -- byte 128 is 0.50196, which
    # comes out at 0.21586. The first version of this test asserted 0.2140 for
    # byte 128 and failed: the constant was right for a different input, which
    # is the same class of mistake as the bug being fixed.
    assert linear(128) == pytest.approx(0.21586, abs=1e-5)
    assert ((0.5 + 0.055) / 1.055) ** 2.4 == pytest.approx(0.2140, abs=5e-4)
    assert linear(128) != pytest.approx(128 / 255, abs=0.05), (
        "the conversion is not happening at all"
    )
    # It is a monotonic darkening: never brighter than the sRGB value it came
    # from, and never negative.
    for byte in range(0, 256, 7):
        assert 0.0 <= linear(byte) <= byte / 255 + 1e-12


def test_the_written_albedos_are_linear_and_not_the_bytes():
    """The measurement that started this, on the file the page fetches.

    The Arduino Uno's solder mask is #313d63. Written as bytes over 255 that is
    (0.192, 0.239, 0.388) -- six, five and three times too bright, and half as
    saturated as the colour actually is. The board came out matte and greyish
    and it was reported twice.
    """
    model = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not model.is_file():
        pytest.skip("no composed Uno; run tools/compose_board_3d.py")
    from tools.import_3d_model import linear

    document, _body = _gltf(model)
    for material in document["materials"]:
        name = material["name"]
        want = [linear(int(name[at:at + 2], 16)) for at in (1, 3, 5)]
        got = material["pbrMetallicRoughness"]["baseColorFactor"][:3]
        assert got == pytest.approx(want, abs=1e-6), name
        raw = [int(name[at:at + 2], 16) / 255 for at in (1, 3, 5)]
        # **A channel of 0x00 or 0xff is a FIXED POINT of the sRGB
        # transform** -- linear(0) is 0 and linear(255) is 1 -- so a colour
        # made only of those, like the #0000ff a fetched LED lens brought in
        # with OH-119, is identical in both encodings and cannot satisfy an
        # inequality. The equality assertion above still fully checks such
        # colours; this one only has meaning where the transform bends.
        bent = any(int(name[at:at + 2], 16) not in (0x00, 0xFF)
                   for at in (1, 3, 5))
        if max(raw) > 0.05 and bent:
            assert got != pytest.approx(raw, abs=1e-6), (
                f"{name} is still the sRGB bytes"
            )


def test_black_epoxy_renders_black_rather_than_grey():
    """The clearest single symptom, and the easiest to check.

    #050505 is as near black as a vendor writes. As a byte over 255 it reached
    the renderer as 0.0196 -- THIRTEEN TIMES its linear value -- so the DIP-28,
    the barrel jack and every header shroud were grey plastic.
    """
    model = REPO / "webui" / "static" / "models" / "Arduino-Uno.glb"
    if not model.is_file():
        pytest.skip("no composed Uno; run tools/compose_board_3d.py")
    document, _body = _gltf(model)
    epoxy = next(material for material in document["materials"]
                 if material["name"] == "#050505")
    assert max(epoxy["pbrMetallicRoughness"]["baseColorFactor"][:3]) < 0.005


def test_the_writer_converts_every_channel_and_not_just_the_file_on_disk(tmp_path):
    """**That `linear` is right and that `write_glb` CALLS it are two claims.**

    The tests above read the shipped `.glb`, which is generated and gitignored,
    so removing the conversion from the writer leaves them all green against a
    file that was built while it was still there. Caught by mutation twice now,
    on the same shape of gap that `test_the_tessellator_welds_what_it_meshes`
    exists to close for the weld.

    Three different bytes, because a mutation that converts one channel and not
    the others is a colour shift rather than a brightness one -- and that is the
    harder version of this bug to see.
    """
    from tools.import_3d_model import Mesh, linear, write_glb

    triangle = ([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0],
                [0, 1, 2])
    colour = "#1a80f0"
    out = tmp_path / "probe.glb"
    write_glb(Mesh({colour: triangle}), out, "probe", "test", (1.0, 1.0, 1.0))

    raw = out.read_bytes()
    length, _kind = struct.unpack_from("<II", raw, 12)
    document = json.loads(raw[20:20 + length].decode("utf-8"))
    written = document["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"]

    want = [linear(int(colour[at:at + 2], 16)) for at in (1, 3, 5)]
    assert written[:3] == pytest.approx(want, abs=1e-9)
    # And each channel individually differs from the byte it came from, so a
    # conversion applied to some of them fails here rather than passing.
    for channel, (value, byte) in enumerate(
            zip(written, [0x1a / 255, 0x80 / 255, 0xf0 / 255])):
        assert abs(value - byte) > 0.01, (
            f"channel {channel} is still the sRGB byte {byte:.4f}"
        )


# --- the one judged colour in the file (OH-97) -------------------------------


def test_the_board_mask_is_a_judgement_and_says_so():
    """**Every other colour here is the vendor's; this one is not.**

    Nobody publishes a XIAO's solder mask colour: Seeed's STEP files leave the
    PCB `UNSTYLED`, six of their seven board files carry a full `(stackup ...)`
    that states the mask's thickness and no colour, and their wiki does not
    mention one. So the constant has to carry the search that found nothing,
    or the next reader repeats it.

    **The stackup is the load-bearing half and it is asserted separately**,
    because it is the field KiCad actually records a mask colour in. OH-97
    cited `pcb_color` instead, which is a NET CLASS colour that has a
    schematic half and nothing to do with the board; OH-99 found that out and
    the note has to keep saying so, or the wrong citation comes back.
    """
    from tools.import_3d_model import BOARD_MASK, UNSTYLED

    source = pathlib.Path(import_3d_model.__file__).read_text(encoding="utf-8")
    note = source.split("BOARD_MASK = ", 1)[0].rsplit("UNSTYLED = ", 1)[1]
    assert BOARD_MASK != UNSTYLED, "the board is still painted 'unknown'"
    assert "JUDGEMENT" in note, "the constant does not admit what it is"
    lowered = note.lower()
    for evidence in ("kicad_pro", "alpha zero", "stackup", "wiki"):
        assert evidence in lowered, f"the search for {evidence} is not recorded"
    assert "net class" in lowered, (
        "the note no longer says pcb_color is a net class colour, so the "
        "citation OH-99 corrected can come back as evidence about the board"
    )
    assert "copper_finish" in lowered or "thickness 0.01" in lowered, (
        "the note no longer shows the stackup was filled in and left the mask "
        "colour empty, which is the whole of the absence it claims"
    )


def test_the_board_mask_is_finished_like_the_solder_mask_it_is():
    """The COLOUR is judged; that a solder mask is a cured semi-gloss coating
    is not, and it gets the same finish as the two masks whose colours were
    read from a source."""
    from tools.import_3d_model import BOARD_MASK, FINISHES

    mask = FINISHES[BOARD_MASK]
    navy = FINISHES["#313d63"]
    assert (mask.metalness, mask.roughness) == (navy.metalness, navy.roughness)
    assert (mask.coat, mask.coat_roughness) == (navy.coat, navy.coat_roughness)


def test_only_the_pcb_solid_is_repainted_and_not_every_unstyled_face():
    """**The narrow change, and the line it must not cross.**

    `UNSTYLED` means "nobody here knows what this is" and
    `test_the_unstyled_colour_is_given_no_material` keeps that true. A PCB is
    the one unstyled solid whose material is NOT a mystery -- this module
    already identifies it by shape, because the model's origin is the board's
    centre rather than the assembly's.

    So the repaint is keyed on that identification. Checked at the source,
    because doing it in a mesh would need OpenCASCADE and a vendor download.
    """
    source = pathlib.Path(import_3d_model.__file__).read_text(encoding="utf-8")
    body = source.split("def tessellate(", 1)[1].split("\ndef ", 1)[0]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "board_faces is not None and face.TShape() in board_faces" in code, (
        "the repaint is no longer restricted to the PCB solid's own faces"
    )
    assert "film_faces is not None and face.TShape() in film_faces" in code, (
        "the mask-film repaint is no longer restricted to the faces "
        "mask_film_faces_of identified"
    )
    assert "UNSTYLED" in code, "an unstyled face that is not the board lost its grey"


def test_every_shipped_board_paints_its_pcb_and_nothing_taller():
    """**The whole chain, measured on the meshes that shipped.**

    The group painted `BOARD_MASK` must be exactly the PCB the model states in
    its own extras in LENGTH and WIDTH, and its thickness plus at most the mask
    film lying on it. If the wrong solid were repainted this is what would
    catch it: a component would be black and would stand taller than the board
    it sits on.

    **The thickness is the loose one on purpose, and OH-99 is why.** The
    painted group is the board plus, where the vendor exported one, the
    solder-mask film 0.05 mm proud of each of its faces -- 1.61 mm against a
    stated 1.51 on the nRF54LM20A. Asserting equality within 0.1 mm passed
    that at exactly 0.1, on the boundary, while claiming something the code no
    longer does. A test sitting on its own tolerance is a test about to fail
    for the wrong reason, so this states the film instead of absorbing it.
    """
    from tools.import_3d_model import BOARD_MASK, MASK_FILM_MM, OUT

    seen = 0
    for mesh in sorted(OUT.glob("*.glb")):
        doc, body = _gltf(mesh)
        extras = doc["asset"].get("extras", {})
        pcb = extras.get("pcb")
        # Composed boards state their own colour and are covered by
        # tests/rules/test_compose_board_3d.py; this is the importer's half.
        if not pcb or extras.get("composed"):
            continue
        painted = [prim for m in doc["meshes"] for prim in m["primitives"]
                   if doc["materials"][prim["material"]]["name"] == BOARD_MASK]
        if not painted:
            continue
        seen += 1
        points = [p for prim in painted
                  for p in _read(doc, body, prim["attributes"]["POSITION"])]
        for axis, stated in ((0, pcb["long"]), (2, pcb["short"])):
            values = [p[axis] for p in points]
            span = max(values) - min(values)
            assert span == pytest.approx(stated, abs=0.1), (
                f"{mesh.name}: the painted group spans {span:.2f} mm on axis "
                f"{axis} against a stated PCB of {stated:.2f} -- so what was "
                f"repainted is not the board"
            )
        thick = [p[1] for p in points]
        span = max(thick) - min(thick)
        assert pcb["thickness"] - 0.1 <= span <= pcb["thickness"] + 2 * MASK_FILM_MM, (
            f"{mesh.name}: the painted group is {span:.2f} mm thick against a "
            f"stated PCB of {pcb['thickness']:.2f} -- too thin to be the board "
            f"or too thick to be the board and a film on it"
        )
    if not seen:
        pytest.skip("no imported board meshes on disk; "
                    "run python tools/import_3d_model.py --all")


def test_a_face_styled_with_nothing_is_not_a_colour_called_empty_string():
    """**The bug this cost, and the reason `colour_key` is its own function.**

    `colour_of` answers `""` for a face the file styles with nothing, and
    `None` for one it does not mention. The `or UNSTYLED` that used to sit
    here absorbed both; a rewrite that checked `is None` alone let the empty
    string through as a colour key, and it reached `int("", 16)` in the writer
    and stopped the import of every board.

    Nothing caught it, because the tests read the SHIPPED `.glb` and a
    mutation does not regenerate one. So the decision was lifted out of
    `tessellate`, which needs OpenCASCADE and a 34 MB download to run.
    """
    from tools.import_3d_model import BOARD_MASK, UNSTYLED, colour_key

    assert colour_key("", is_board=False, is_film=False) == UNSTYLED
    assert colour_key(None, is_board=False, is_film=False) == UNSTYLED
    assert colour_key("", is_board=True, is_film=False) == BOARD_MASK
    assert colour_key(None, is_board=True, is_film=False) == BOARD_MASK


def test_a_face_the_vendor_did_colour_keeps_its_colour_even_on_the_board():
    """The repaint fills a gap; it never overrides a statement. A PCB whose
    mask the vendor DID style keeps what they said, and that is the difference
    between reading a source and preferring a judgement to one.

    **Narrowed by OH-99, and narrowed with its argument rather than around
    it.** There is now exactly one face this does not hold for -- the
    solder-mask film lying on the board, which the nRF54LM20A's STEP styles
    `#143324` while its own PCB solid, the same missing fact, draws
    `BOARD_MASK`. That is not a statement being overridden: the vendor's
    stackup gives that mask a thickness and no colour, so the green is the
    exporter's default and the incoherence of answering one missing fact two
    ways in one mesh is the defect. The last assertion is what stops the
    narrowing being taken any wider.
    """
    from tools.import_3d_model import colour_key

    assert colour_key("#00ff00", is_board=True, is_film=False) == "#00ff00"
    assert colour_key("#313d63", is_board=True, is_film=False) == "#313d63"
    assert colour_key("#143324", is_board=False, is_film=False) == "#143324"
    assert colour_key("#186b2a", is_board=False, is_film=False) == "#186b2a", (
        "the nRF54LM20A's green LED is a real vendor colour on a real part "
        "and is not the mask film; only the film may be repainted"
    )


# --- the solder-mask film, the one stated colour this file repaints (OH-99) --

#: The nRF54LM20A's PCB solid and its two mask films, measured off
#: `third_party/seeed-3d/nRF54LM20A.step` on 2026-08-30 with OpenCASCADE. z is
#: that file's up axis. The films' x and y are the board's to 0.0000 mm -- not
#: nearly, exactly -- and each is a sheet at one z, 0.05 mm off a board face.
_LM20A_BOARD = ((-10.4775, -8.8900, 0.0000), (10.4775, 8.8900, 1.5100))
_LM20A_FILM_ABOVE = ((-10.4775, -8.8900, 1.5600), (10.4775, 8.8900, 1.5600))
_LM20A_FILM_BELOW = ((-10.4775, -8.8900, -0.0500), (10.4775, 8.8900, -0.0500))

#: The whole `#ffffff` silkscreen group's box in the same file, which is the
#: nearest thing to a false positive in any of the six vendor board STEPs: it
#: misses the board's footprint by 0.505 mm because lettering is not drawn to
#: the edge. Using the whole GROUP is deliberate -- if the most generous box
#: silkscreen can offer fails, every individual face of it fails.
_LM20A_SILKSCREEN = ((-9.9722, -7.9429, -0.0750), (10.0832, 8.8900, 2.0050))


def test_the_mask_film_is_the_boards_own_footprint_at_its_own_face():
    """**What identifies the film is geometry, and that is what makes
    repainting its colour safe.**

    Both sheets carry the board's own footprint to 0.0000 mm and lie 0.05 mm
    off one of its two outer planes. Neither test looks at the colour, so the
    rule cannot be accused of finding the green it went looking for.
    """
    from tools.import_3d_model import is_mask_film

    low, high = _LM20A_BOARD
    for name, (film_low, film_high) in (("above", _LM20A_FILM_ABOVE),
                                        ("below", _LM20A_FILM_BELOW)):
        assert is_mask_film(film_low, film_high, low, high, up=2), (
            f"the film {name} the nRF54LM20A's PCB is no longer recognised as "
            f"one, so its board goes back to drawing the exporter's green"
        )


def test_the_mask_film_rule_does_not_reach_the_silkscreen():
    """The other thing this vendor exports as its own body, and it must stay
    white. It is excluded by the footprint alone, with a factor of two in
    hand: 0.505 mm out against a tolerance of 0.25."""
    from tools.import_3d_model import MASK_FOOTPRINT_MM, is_mask_film

    low, high = _LM20A_BOARD
    silk_low, silk_high = _LM20A_SILKSCREEN
    assert not is_mask_film(silk_low, silk_high, low, high, up=2)
    # The LARGEST miss is what decides it: one edge outside the tolerance is
    # enough to reject, so that is the margin the tolerance has to clear.
    miss = max(abs(silk_low[0] - low[0]), abs(silk_high[0] - high[0]))
    assert miss > 2 * MASK_FOOTPRINT_MM, (
        f"the silkscreen now misses the board's footprint by only {miss:.3f} "
        f"mm, so the tolerance no longer has room and could swallow it"
    )


def test_the_mask_film_rule_leaves_the_boards_own_edge_alone():
    """A face reaching from the bottom plane to the top one has the board's
    footprint and is the board's EDGE, not a film on it. This is why both ends
    of a face are measured against the same plane rather than the nearer one
    each -- the cheaper test passes this and would repaint the board's rim."""
    from tools.import_3d_model import is_mask_film

    low, high = _LM20A_BOARD
    assert not is_mask_film(low, high, low, high, up=2)


def test_the_mask_film_rule_leaves_a_board_sized_thing_standing_above_it():
    """A shield can or a lid covering the whole board is not the mask. The
    footprint cannot tell them apart; the height can, and that is the second
    condition's whole job."""
    from tools.import_3d_model import is_mask_film

    low, high = _LM20A_BOARD
    lid_low = (low[0], low[1], high[2] + 1.9)
    lid_high = (high[0], high[1], high[2] + 2.0)
    assert not is_mask_film(lid_low, lid_high, low, high, up=2)


def test_the_solder_mask_film_takes_the_colour_of_the_board_it_lies_on():
    """**The film and the board are the same missing fact**, and answering it
    two ways inside one mesh is what OH-99 was filed for: the nRF54LM20A drew
    `#143324` over a board already drawing `BOARD_MASK`. The film gets the
    board's colour whatever the file styles it, because the vendor's stackup
    gives that mask a thickness and no colour."""
    from tools.import_3d_model import BOARD_MASK, colour_key

    assert colour_key("#143324", is_board=False, is_film=True) == BOARD_MASK
    assert colour_key("", is_board=False, is_film=True) == BOARD_MASK
    assert colour_key(None, is_board=False, is_film=True) == BOARD_MASK


def test_the_film_tolerances_say_what_they_were_measured_against():
    """Both numbers are judgements about tolerance, so both have to carry
    their measurement -- the same rule `BOARD_MASK` itself is held to."""
    from tools.import_3d_model import MASK_FILM_MM, MASK_FOOTPRINT_MM

    source = pathlib.Path(import_3d_model.__file__).read_text(encoding="utf-8")
    note = source.split("MASK_FILM_MM = ", 1)[0].rsplit("BOARD_MASK = ", 1)[1]
    assert 0.0 < MASK_FOOTPRINT_MM < 0.505, (
        "the footprint tolerance now reaches the silkscreen, which misses the "
        "board's own footprint by 0.505 mm"
    )
    assert 0.0 < MASK_FILM_MM < 1.51, (
        "the film tolerance now spans the whole board, so its two outer "
        "planes are no longer distinguishable"
    )
    for evidence in ("0.0000 mm", "six vendor board STEPs", "0.05 mm proud"):
        assert evidence in note, f"the measurement {evidence!r} is not recorded"


def test_the_shipped_nrf54lm20a_lost_its_green_board_and_kept_its_green_led():
    """**Both halves of OH-99, measured on the mesh that ships.**

    `#143324` is the exporter's default solder-mask colour -- it is (0.08,
    0.20, 0.14) in floats to two decimals, a constant typed into a program --
    and no board mesh may carry it any more. `#186b2a` is a different green
    on a real part, the RGB LED, and it MUST survive: a repaint that took it
    too would be the overreach this rule is written narrowly to avoid.
    """
    from tools.import_3d_model import OUT

    seen = 0
    for mesh in sorted(OUT.glob("*.glb")):
        doc, _body = _gltf(mesh)
        extras = doc["asset"].get("extras", {})
        if not extras.get("pcb") or extras.get("composed"):
            continue
        seen += 1
        names = {material["name"] for material in doc["materials"]}
        assert "#143324" not in names, (
            f"{mesh.name} still draws the exporter's default solder-mask "
            f"green over a board that draws BOARD_MASK"
        )
        if mesh.stem == "nRF54LM20A":
            assert "#186b2a" in names, (
                "the nRF54LM20A's green LED went with the film; the repaint "
                "is supposed to reach two faces and no part"
            )
    if not seen:
        pytest.skip("no imported board meshes on disk; "
                    "run python tools/import_3d_model.py --all")


def test_the_pcb_solids_own_faces_are_never_taken_for_a_film_on_it():
    """**The guard that keeps a vendor who DID style their board safe.**

    The PCB solid's own top face passes every test in `is_mask_film`: it has
    the board's footprint, because it IS the board's footprint, and it lies at
    exactly one of its two outer planes. `mask_film_faces_of` excludes
    `board_faces` for that reason, and without the exclusion the rule would
    repaint the board itself -- which is the one thing OH-97 argued it must
    not do to a board whose mask a vendor had coloured.

    **Built here rather than read off a vendor STEP**, because the mutation
    that drops the exclusion changes nothing on any of the six files we have:
    all six leave the PCB solid unstyled, so it takes `BOARD_MASK` either way
    and the meshes come out byte-identical. Two boxes is what makes the
    difference observable at all.

    The film is deliberately 0.1 mm inside the board on each edge rather than
    flush with it, so this exercises `MASK_FOOTPRINT_MM` as a tolerance and
    leaves the PCB the unambiguous winner of `pcb_solid`'s largest-area test.
    """
    try:
        from OCP.BRep import BRep_Builder
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.gp import gp_Pnt
        from OCP.TopoDS import TopoDS_Compound
    except ImportError:
        pytest.skip("OpenCASCADE is not installed")

    from tools.import_3d_model import board_faces_of, mask_film_faces_of

    board = BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), 20.0, 17.0, 1.5).Shape()
    film = BRepPrimAPI_MakeBox(gp_Pnt(0.1, 0.1, 1.55), 19.8, 16.8, 0.01).Shape()
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, board)
    builder.Add(compound, film)

    board_faces = board_faces_of(compound)
    films = mask_film_faces_of(compound, board_faces)
    assert films, (
        "the film lying on the board was not found at all, so a board that "
        "ships one goes back to drawing the exporter's colour over it"
    )
    assert not (films & board_faces), (
        "the PCB solid's own faces were taken for a film on it, so the rule "
        "would repaint a board whose mask the vendor DID colour"
    )


def test_the_composed_copper_is_a_conductor_and_the_silkscreen_is_not():
    """**203-400 pads a board shipped as a dielectric** (OH-120).

    `compose_board_3d.COPPER` had no `FINISHES` entry, so every pad,
    castellation and via the composer draws took DEFAULT_FINISH -- metalness
    0.10, "nothing here can say what this surface is" -- and rendered matte
    tan beside header pins at 1.0. And the same number gates the carve:
    `carvePins` claims only `metalness > 0.5`, so an SMD XIAO's pads -- which
    ARE castellated copper, there being no header part -- had no candidate
    geometry at all, by material, before any question of geometry.

    The keys are asserted against the composer's own constants so neither can
    drift: a renamed colour with a stale FINISHES key is this bug again with
    an extra step.
    """
    from tools import compose_board_3d as compose
    from tools.import_3d_model import FINISHES

    copper = FINISHES[compose.COPPER]
    assert copper.metalness == 1.0, "a plated pad is a conductor"
    assert copper.metalness > 0.5, (
        "below carvePins' gate, so no castellation could ever be claimed"
    )
    silk = FINISHES[compose.SILKSCREEN]
    assert silk.metalness == 0.0, "screen-printed epoxy ink is an insulator"
    assert compose.COPPER == "#c8a253" and compose.SILKSCREEN == "#e9e9e4", (
        "the constants moved; move the FINISHES keys with them or the "
        "finishes silently detach again"
    )


def test_every_composed_boards_mask_and_routing_is_a_solder_mask():
    """**Every trace on every composed board drew at DEFAULT_FINISH** (OH-163).

    The composer draws a board's slab in its composition's mask colour and
    each trace in `mask_over_copper` of it, so both are solder mask by
    construction -- and neither hex is written anywhere but `FINISHES`, each
    computed from a board file. So this walks the compositions rather than a
    list: a board added with a new mask, or a mask read differently, fails
    here instead of drawing grey. A manifest board whose file is not fetched
    has no colour yet, and is the only one passed over.
    """
    from tools import compose_board_3d as compose
    from tools.import_3d_model import FINISHES

    checked = []
    for spec in compose.COMPOSITIONS:
        if not (spec.colour.startswith("#") and len(spec.colour) == 7):
            continue
        for what, colour in (("mask", spec.colour),
                             ("routing", compose.mask_over_copper(spec.colour))):
            finish = FINISHES.get(colour)
            assert finish is not None, (
                f"{spec.board}'s {what}, {colour}, has no FINISHES entry and "
                f"draws at DEFAULT_FINISH")
            assert (finish.metalness, finish.coat > 0) == (0.0, True), (
                f"{spec.board}'s {what}, {colour}, is metalness "
                f"{finish.metalness} coat {finish.coat}: not a solder mask")
            assert "solder mask" in finish.why, (spec.board, what, colour)
        checked.append(spec.board)
    assert checked, "no composition has a colour to check"


def test_the_composer_audits_its_own_finishes():
    """`report_finishes` exists so the assignment 'can be audited against the
    picture', and the composer -- which writes six of the twelve .glb files
    and every copper and silkscreen surface -- never called it. That silence
    is how OH-120 sat unnoticed for a whole session. Comment lines stripped,
    the OH-117 lesson."""
    from tools import compose_board_3d as compose

    source = pathlib.Path(compose.__file__).read_text(encoding="utf-8")
    body = source.split("def compose(", 1)[1].split("\ndef ", 1)[0]
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "report_finishes(whole)" in code, (
        "the composer stopped auditing its finishes, which is the silence "
        "OH-120 grew in"
    )


def test_the_trimmer_is_the_first_three_terminal_part():
    """**`Part.terminals` was a hard 2-tuple and this is the row that made
    it a tuple of N** (OH-126). The wiper is the MIDDLE name because it is
    Bourns' own pinout for the W style; the one cited number is the TOP of
    the '502' code's ±10% band -- 5,500, the 220 Ω resistor's own
    lower-bound argument -- and no current limit is cited, because the
    3266's limit is a quarter watt no 5 V bench can reach through 5.5 kΩ,
    so `destroys` can never claim it."""
    from tools.import_3d_model import PARTS, POT_ELECTRICAL

    pot = next(p for p in PARTS
               if p.name == "Potentiometer_Bourns_3266W_Vertical")
    assert pot.terminals == ("lead A", "wiper", "lead B")
    assert pot.electrical is POT_ELECTRICAL
    assert POT_ELECTRICAL.kind == "potentiometer"
    assert POT_ELECTRICAL.cited["ohms"][0] == 5500.0
    assert "top of" in POT_ELECTRICAL.cited["ohms"][1]
    assert "rated_amps" not in POT_ELECTRICAL.cited
    assert "absolute_amps" not in POT_ELECTRICAL.cited
    assert pot.lens is None, "a trimmer displays nothing"


def test_a_ceramic_block_is_a_dielectric_in_its_own_colour():
    """OH-155: the two ceramic parts stop borrowing `#c6c4a0`, which `FINISHES`
    then called the switch cover's steel (OH-163 found it is the plunger).

    `FINISHES` is keyed by colour, and `#c6c4a0` is on thirteen of the
    seventeen shipped boards -- both ESP32-C3s among them, which carry neither
    a tactile switch nor a ceramic part -- so it could not be re-declared for
    two of its users without changing the other eleven. A ceramic therefore
    needs its own key, and the key needs a dielectric's metalness, which is
    what the parameter means rather than a choice. The roughness IS a choice,
    and the entry has to say so in the same voice `BOARD_MASK` uses.
    """
    from tools.import_3d_model import CERAMIC, FINISHES
    from tools.model_from_datasheet import SLABS

    assert CERAMIC in FINISHES
    assert CERAMIC != "#c6c4a0", "a ceramic in a vendor colour's own hex is the defect"
    assert FINISHES[CERAMIC].metalness == 0.0
    assert "judgement" in FINISHES[CERAMIC].why, (
        "the roughness is a stated choice and the entry must say which kind "
        "of number it is"
    )
    ceramic = {spec.package for spec in SLABS if spec.colour == CERAMIC}
    assert ceramic == {"CAF-50P160X80-6N", "ANT2P-5.2x2x1.1MM"}, ceramic
    borrowers = [spec.package for spec in SLABS if spec.colour == "#c6c4a0"]
    assert not borrowers, f"still shaded in the borrowed #c6c4a0: {borrowers}"
