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
import re

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


def test_a_chip_that_merely_extends_a_known_one_is_not_that_chip():
    """The ESP32-C61 is a real Espressif part and is not an ESP32-C6.

    Without a delimiter check, `startswith` matched any name beginning with a
    known chip, so this resolved to ESP32-C6 and would have been silently
    given the wrong instruction set -- the same failure class as the
    ESP32-C3-DIP bug the table-matching rewrite was meant to fix.
    """
    with pytest.raises(catalogue.CatalogueError):
        catalogue.chip_for("XIAO-ESP32-C61-DIP")


def test_a_suffixed_chip_name_is_not_the_chip_it_starts_with():
    with pytest.raises(catalogue.CatalogueError):
        catalogue.chip_for("XIAO-RP2040X-SMD")


def test_a_longer_number_is_not_the_shorter_one():
    with pytest.raises(catalogue.CatalogueError):
        catalogue.chip_for("XIAO-MG240-DIP")


def test_the_delimiter_check_does_not_break_the_names_that_do_resolve():
    """The check must not be so strict it rejects real boards. All four
    awkward shapes still work: two-word package, underscored package,
    inconsistent case, and a plain name."""
    assert catalogue.chip_for("XIAO-ESP32-C3-DIP-SMD") == "ESP32-C3"
    assert catalogue.chip_for("XIAO-ESP32-S3-SMD_PAD") == "ESP32-S3"
    assert catalogue.chip_for("XIAO-nRF54LM20A-SMD") == "nRF54LM20A"
    assert catalogue.chip_for("XIAO-RP2040-DIP") == "RP2040"


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
    """A built core is not a working board: with no memory map and no
    peripherals there is nothing for an image to run against.

    **Written against a synthetic directory, and that is the point.** This used
    to name the SAMD21, which shared `cortexm0` with the RP2040 and had no
    description -- a real example, and a perishable one. `webui/boards/samd21.py`
    landed on 2026-08-25 and the example evaporated, taking the coverage with
    it: there is now no chip in the tree whose core is built and whose
    description is missing.

    A test that depends on which board happens to be undescribed stops testing
    the rule the moment somebody does the work. So this builds the case instead
    of finding it, and keeps holding as the remaining boards are described.
    """
    (tmp_path / "XIAO-SAMD21-DIP.json").write_text("{}", encoding="utf-8")
    board, = catalogue.catalogue(tmp_path)
    assert board.chip == "SAMD21"
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


def test_the_cortexm0_row_left_the_backlog_when_the_samd21_was_described():
    """`cortexm0` used to sit in this backlog, because SAMD21 had no board
    description -- a different job from writing an instruction set, and the
    reason `missing_cores` reports `exists` at all. Writing
    `webui/boards/samd21.py` on 2026-08-25 emptied that row, because both of
    the chips over this core are now described.

    **Only that is asserted here, and the narrowness was learned the hard
    way.** The first version of this test also claimed every *remaining* row
    needs a core written -- true when it was typed, and false within the hour,
    because another session added `core/riscv32/` and its row began reporting
    `exists: True`. That is the same mistake as the test this one replaced:
    pinning a fact about the tree that somebody else's work invalidates. The
    claim below is about this ticket's own change and nothing else.
    """
    assert "cortexm0" not in {row["core"] for row in catalogue.missing_cores()}


def test_the_backlog_still_distinguishes_a_missing_description_from_a_missing_core(tmp_path):
    """The `exists` field the test above now sees only as False.

    Both halves have to keep working, and the true half has no example left in
    the tree, so it gets a built one -- a SAMD21 board in a directory with no
    description module beside it. Without this, `exists` could be hardcoded to
    False and the suite would not notice.
    """
    (tmp_path / "XIAO-SAMD21-DIP.json").write_text("{}", encoding="utf-8")
    row, = catalogue.missing_cores(tmp_path)
    assert row["core"] == "cortexm0"
    assert row["exists"] is True
    assert row["boards"] == ["XIAO-SAMD21-DIP"]


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
    """Pinned, so that adding a chip is a decision rather than a diff.

    This is deliberately the *second* layer. `tools/check_board_claims.py`
    already checks an entry is well-formed -- a real test, naming a real image,
    reading and stepping it. A well-formed entry can still be a wrong one, and
    editing a test whose name says what it protects is what makes adding one
    deliberate.

    SAMD21 joined RP2040 on 2026-08-25. Not because its core was already built
    -- that is the argument this pin exists to refuse, and it would have let an
    empty `samd21.py` in -- but because `tests/cortexm0/test_samd21_blink.py`
    watches a real compiled image toggle PA17.

    ATmega328P joined them the same day, under OH-52, and the argument it had
    to survive was subtler. A blink test already existed --
    `tests/avr/test_blink.py`, watching PB5 through the ABI -- and citing it
    would have been the mistake, because this table makes a claim about a
    *board* and that file never mentions one. The evidence is
    `tests/avr/test_uno_board.py`, where `api.load_firmware("Arduino Uno", ...)`
    is what runs.

    ESP32-C3 joined on 2026-08-25 under OH-48 and unlocked three boards at once
    rather than one. The argument it had to survive is the same:
    `tests/riscv32/test_rvc.py` already ran the same image and would have been
    the wrong evidence, because it drives the ABI directly and so proves the
    compressed decoder rather than the board.

    ESP32-C6 joined on 2026-08-25 under OH-57, and it is the first entry whose
    tempting wrong argument is *the previous entry*. The core was built, the C3
    board worked, and the two parts share an instruction set -- so a C6 looked
    proven before anything had run on it. It is here because
    `tests/riscv32/test_esp32c6_board.py` loads its own image at its own GPIO
    base and watches GPIO8 move; the C3's image faults on this board at its
    first store.

    ESP32-C5 joined on 2026-08-31 under OH-147, and it waited the longest
    on purpose: it was described on 2026-08-25 and this paragraph spent six
    days saying it was deliberately NOT here, because its ISA is
    `RV32IMAC + Zcb/Zcmp/Zcmt` and the core implemented none of the three
    Zc groups. The argument it had to survive is that OH-146 giving the
    core those groups was still not the evidence -- bits are not a watched
    image. It is here because `tests/riscv32/test_esp32c5_board.py` loads
    `c5blink`, an image that frames its delay with cm.push/cm.popret,
    counts through c.not and calls through cm.jalt and JVT, and watches
    GPIO8 toggle with a steady period -- so what was watched is the part's
    own instruction set, not the subset every sibling already proves.
    """
    proven = {b.chip for b in catalogue.catalogue() if b.firmware_verified}
    assert proven == {"RP2040", "SAMD21", "ATmega328P", "ESP32-C3",
                      "ESP32-C6", "ESP32-C5"}


def test_every_firmware_claim_names_a_test_that_exists():
    """The claim is tied to a file so it cannot be asserted into being."""
    repo = pathlib.Path(__file__).resolve().parents[2]
    for chip, evidence in catalogue.FIRMWARE_VERIFIED.items():
        assert (repo / evidence).is_file(), f"{chip} cites a missing {evidence}"


def test_the_firmware_evidence_actually_runs_an_image():
    """Naming any file would satisfy the check above. Each named one has to be
    a test that loads a compiled image and steps it.

    Looped over every entry rather than spelling out RP2040, which is what it
    did while RP2040 was the only one. A check written around a single key
    stops checking the moment a second key arrives -- and it arrives at exactly
    the moment the check matters most, since a new claim is the one nobody has
    read yet.
    """
    repo = pathlib.Path(__file__).resolve().parents[2]
    for chip, evidence in catalogue.FIRMWARE_VERIFIED.items():
        text = (repo / evidence).read_text(encoding="utf-8")
        images = [
            line for line in text.splitlines()
            if any(suffix in line for suffix in (".bin", ".elf", ".hex", ".uf2"))
        ]
        assert images, f"{chip}: {evidence} names no compiled image"
        assert ".read_bytes()" in text, f"{chip}: {evidence} never reads one off disk"
        # `.step(` and not `cpu.step()`. The stricter spelling was a spelling
        # rather than a rule, and it disagreed with the checker this test
        # shadows: `tools/check_board_claims.py` collects call *names* with
        # `ast`, so `session.step()` satisfies it. It has to, because the
        # ATmega328P evidence drives a board through `webui/api.py` rather than
        # a core through its ABI -- which is the stronger claim of the two, and
        # would have been refused here for naming its variable differently.
        assert ".step(" in text, f"{chip}: {evidence} never executes it"


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
        None, "/api/boards", {}, {}
    )
    assert payload["boards"] and payload["waiting"]


def test_the_boards_route_is_json_serialisable():
    """The handler's answer goes through `json.dumps` in the server. A value
    that is not serialisable is a 500 the tests never see."""
    import json

    from webui import emulator_server

    payload = emulator_server.handle_api(
        None, "/api/boards", {}, {}
    )
    json.dumps(payload)


def test_the_boards_route_carries_what_the_ui_reads():
    """Named field by field, because the UI reads them by name and a rename
    here renders an empty table rather than an error."""
    from webui import emulator_server

    payload = emulator_server.handle_api(
        None, "/api/boards", {}, {}
    )
    board = payload["boards"][0]
    for key in ("name", "chip", "isa", "core", "core_exists", "core_built",
                "described", "runnable", "firmware_verified"):
        assert key in board, f"emulator.js reads board.{key}"
    row = payload["waiting"][0]
    for key in ("core", "boards", "exists", "oracle"):
        assert key in row, f"emulator.js reads group.{key}"
    assert "firmware_evidence" in board, (
        "emulator.js names the test behind each claim in the evidence sentence"
    )


def test_every_element_the_script_fills_exists_in_the_page():
    """`$("some-id")` in the script, `id="some-id"` in the page.

    The seam between the two is where this repository has twice shipped a panel
    a green suite said was fine -- §3.8 of the 2026-08-25 handoff, where a
    dict-to-list change left the Boards view blank while 340 tests passed.
    Nothing between the script and the markup was checked, and nothing here
    checks it except this.

    Written as a sweep rather than a list of the ids that exist today, so it
    covers the next one somebody adds without being edited.
    """
    static = pathlib.Path(__file__).resolve().parents[2] / "webui" / "static"
    script = (static / "emulator.js").read_text(encoding="utf-8")
    page = (static / "emulator.html").read_text(encoding="utf-8")

    wanted = set(re.findall(r"""\$\(["']([\w-]+)["']\)""", script))
    assert wanted, "found no $(\"id\") calls; the pattern above has gone stale"
    present = set(re.findall(r"""\bid=["']([\w-]+)["']""", page))
    missing = sorted(wanted - present)
    assert not missing, (
        f"emulator.js fills elements the page does not have: {missing}. "
        f"replaceChildren on null throws, and the panel renders empty."
    )


def test_the_two_lists_of_non_boards_agree():
    """`catalogue.NOT_A_BOARD` and `contract.NOT_A_BOARD` are the same fact
    written twice, because `contract` imports `catalogue` and the reverse
    import would not resolve.

    Two copies of one list is the arrangement that rots quietly, so this pins
    them -- and a helper added to `webui/boards/` fails here until both know
    about it, rather than surfacing as a phantom chip in `described_chips()`
    the way `contract` itself did.
    """
    from webui.boards import contract

    assert catalogue.NOT_A_BOARD == contract.NOT_A_BOARD


def test_the_stm32c5_is_a_cortex_m33_part_and_not_an_unknown_one():
    """**Pinned so the question is not re-opened from scratch.**

    This board was recorded as "unknown -- part not confirmed to exist" from
    2026-08-24, which was an honest report of a search and not a fact about
    silicon: nobody could place "STM32C5" among ST's families. OH-65 checked
    again and it is real — ST announced it in March 2026, a Cortex-M33 part
    positioned as a faster low-cost sibling to the Cortex-M0+ STM32C0.

    The corroboration that carries the weight is not a wiki. It is that
    Seeed's own KiCad library ships `XIAO-STM32C5-SMD.kicad_mod` in a commit
    dated 2026-07-15, four months after the announcement, from the vendor who
    would be building the board. A vendor does not draw a footprint for a part
    that does not exist.

    So the board is no longer blocked on identification. It is blocked on
    OH-36's oracle, exactly like the other eight Cortex-M33 boards — and it
    makes that nine.
    """
    isa, core = catalogue.CHIPS["STM32C5"]
    assert core == "cortexm33", "the part is identified; do not put it back to unknown"
    assert "Cortex-M33" in isa


def test_the_cortex_m33_boards_are_nine_and_wait_on_one_oracle():
    """Counted rather than listed, so adding an Armv8-M board moves it.

    The number is worth asserting because it is the size of a single blocked
    ticket: nine boards of twenty-six, none of which can run until OH-36 has
    something to check a core against.
    """
    waiting = [b for b in catalogue.catalogue() if b.core == "cortexm33"]
    assert len(waiting) == 9, sorted(b.name for b in waiting)
    assert not any(b.runnable for b in waiting), "one claims to run without a core"


def test_every_board_states_whether_a_sketch_can_be_built_for_it():
    """**The picker offered Build on all 26 boards and 9 runnable ones
    400ed only after the attempt** (OH-140). `buildable` rides /api/boards
    -- stated at the route because `compile` imports the catalogue and
    layering points one way -- and the Uno and the SAMD21s are the boards
    with recipes today, which the recipe table itself says."""
    from webui import compile as compile_service
    from webui import emulator_server
    payload = emulator_server.handle_api(None, "/api/boards", {}, {})
    for entry in payload["boards"]:
        assert isinstance(entry["buildable"], bool), entry["board" if "board" in entry else "name"]
        assert entry["buildable"] == (entry["chip"] in compile_service.RECIPES)
    by_name = {entry["name"]: entry for entry in payload["boards"]}
    assert by_name["Arduino Uno"]["buildable"] is True
    assert by_name["XIAO-RP2040-DIP"]["buildable"] is False, (
        "the RP2040 has no recipe yet; if one landed, update this and OH-140"
    )
