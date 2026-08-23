# OpenHardware — differential tests against a live PICSimLab.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""Check the client against a running simulator rather than against a stub.

Everything else under ``tests/webui/`` talks to ``stub_rcontrol.py``, which
encodes *my reading* of ``src/lib/rcontrol.cc``. A stub cannot disconfirm a
misreading: if I misunderstood the protocol, the stub misunderstands it the same
way and the suite stays green. Only a real server is ground truth, which is why
the cells in ``docs/features/webui.md`` stay ``in-progress`` until these run.

**Skipping here is dangerous, so it is opt-in.** By default these skip when no
simulator is listening, because most runs happen without one. But a skip that
looks like a pass is exactly the defect
``rules/conformance-fixtures.md`` section 4 was written about — upstream's
own ``test_blink.py`` swallows ``ConnectionError`` and passes when the simulator
never started. So set ``OPENHARDWARE_LIVE=1`` to *demand* a live simulator: with
it set, an unreachable server is a **failure**, never a skip. CI and any run
claiming these cells must set it.

    OPENHARDWARE_LIVE=1 OPENHARDWARE_RCONTROL_PORT=5000 \\
        pytest tests/webui/test_live_oracle.py -v
"""

from __future__ import annotations

import os

import pytest

from webui.api import SimulatorApi, parse_pins
from webui.rcontrol import RControlClient, RControlConnectionError

HOST = os.environ.get("OPENHARDWARE_RCONTROL_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPENHARDWARE_RCONTROL_PORT", "5000"))
REQUIRED = os.environ.get("OPENHARDWARE_LIVE") == "1"


#: Probe once with a short timeout so the common case — no simulator — skips
#: quickly, while real commands still get a generous timeout below.
_PROBE_TIMEOUT = 1.5
_COMMAND_TIMEOUT = 15.0
_probe: tuple[bool, str] | None = None


def _available() -> tuple[bool, str]:
    global _probe
    if _probe is None:
        client = RControlClient(host=HOST, port=PORT, timeout=_PROBE_TIMEOUT)
        try:
            client.connect()
            client.close()
            _probe = (True, "")
        except RControlConnectionError as exc:
            _probe = (False, str(exc))
    return _probe


def _connect() -> RControlClient:
    reachable, why = _available()
    if not reachable:
        if REQUIRED:
            pytest.fail(
                f"OPENHARDWARE_LIVE=1 demands a simulator at {HOST}:{PORT} "
                f"but none answered: {why}"
            )
        pytest.skip(
            f"no simulator at {HOST}:{PORT}; set OPENHARDWARE_LIVE=1 to require one"
        )

    client = RControlClient(host=HOST, port=PORT, timeout=_COMMAND_TIMEOUT)
    client.connect()
    return client


@pytest.fixture
def live() -> RControlClient:
    client = _connect()
    yield client
    client.close()


@pytest.fixture
def api(live: RControlClient) -> SimulatorApi:
    return SimulatorApi(live)


# --- the framing rule, against a real server --------------------------------


def test_the_banner_matches_what_rcontrol_cc_promises(live: RControlClient):
    """rcontrol.cc:217 sends this text ending in the terminator we frame on."""
    assert "PICSimLab Remote Control Interface" in live.banner
    assert live.banner.endswith("\r\n>")


def test_version_returns_something(api: SimulatorApi):
    assert api.version().strip()


# --- the parsers, against real output ---------------------------------------


def test_real_pins_output_parses(live: RControlClient):
    """Proves the parser matches the server, which reading alone did not.

    The first version of this test used `pins` and failed on every line: the
    formatter at rcontrol.cc:1095 serves `pinsl`, while `pins` is a narrow
    two-column display. Reading the source produced a confident, wrong parser;
    only the live server exposed it.
    """
    pins = parse_pins(live.command("pinsl"))
    assert pins, "a loaded board should report at least one pin"
    assert all(pin.name for pin in pins)
    assert all(pin.direction in ("I", "O") for pin in pins)


def test_supported_boards_parse(api: SimulatorApi):
    assert api.supported_boards()


def test_supported_parts_parse(api: SimulatorApi):
    assert api.supported_parts()


# --- a write is only real if a read confirms it ------------------------------


def test_writing_a_pin_is_accepted(api: SimulatorApi):
    """`set pin[]` is accepted by the server for a real pin index.

    This asserts acceptance, deliberately **not** observability. An earlier
    version asserted that `get pin[]` reflects the written value; against a live
    Arduino Uno it does not, and the honest response was to weaken the claim
    rather than keep a test that says something untrue. See
    test_pin_writes_are_not_observable_via_get_pin below.
    """
    pins = api.pins()
    api.set_pin(pins[0].index, 1)  # raises on ERROR


def test_pin_writes_are_not_observable_via_get_pin(api: SimulatorApi):
    """Pins the MCU owns do not take an external write. Documented, not wished away.

    Measured on PICSimLab 0.9.3, Arduino Uno, simavr, simulation paused:
    `set pin[04] = 0` and `set pin[04] = 1` both leave `get pin[04]` reporting
    16, unchanged. Poking MCU pins is therefore **not** the interaction path a
    browser UI can build on.

    The supported path is spare parts — `spadd`, then `set part[00].in[00]` —
    which is how PICSimLab models buttons and potentiometers. That path works
    here once `share/picsimlab -> share` exists; without the symlink a part
    placement segfaults the simulator (docs/known-issues.md 4a.1, 4a.2).

    This test pins the current, surprising behaviour so that if a future version
    makes pin writes observable, it fails and tells us the model changed.
    """
    # Nothing else may be driving the pin. This suite shares one simulator, and
    # other tests place spare parts that drive pins -- with one attached, a
    # write *is* observable and this test fails while being right about the
    # bare MCU. The claim is about a pin in isolation, so isolate it.
    api.client.try_command("spdel all")

    api.pause()
    try:
        pins = api.pins()
        target = next(
            p
            for p in pins
            if p.direction == "I" and p.type == "D" and "V" not in p.name
        )
        api.set_pin(target.index, 0)
        low = api.get_pin(target.index)
        api.set_pin(target.index, 1)
        high = api.get_pin(target.index)
    finally:
        api.run()

    assert low == high, (
        f"pin[{target.index:02}] now distinguishes 0 from 1 ({low} vs {high}). "
        f"That is an improvement, but it contradicts what was measured on "
        f"0.9.3 -- update this test and revisit whether the UI can drive pins "
        f"directly."
    )


# --- differential: the typed API must agree with raw protocol text -----------


def test_the_typed_api_agrees_with_the_raw_command(live: RControlClient):
    """Same question, two routes, one answer.

    The API layer must not quietly reinterpret what the server said.
    """
    api = SimulatorApi(live)
    raw = live.command("pinsl")
    assert len(api.pins()) == len(parse_pins(raw))


def test_pin_count_matches_the_header(live: RControlClient):
    """The header is the server's own checksum on its body."""
    response = live.command("pinsl")
    header = next(line for line in response.lines if "pins [" in line)
    promised = int(header.split()[0])
    assert len(parse_pins(response)) == promised


# --- wiring, against a live simulator ---------------------------------------


# --- the render pipeline, against a live simulator ---------------------------


def test_a_live_info_dump_parses_into_state(api: SimulatorApi):
    """The render loop's whole server side starts here, so it must parse.

    `render_model.parse_info` was written against a captured dump. This is the
    test that catches the day the real format stops matching the capture.
    """
    from webui.render_model import parse_info

    state = parse_info(api.info())
    assert state.board, "info always names a board"
    assert state.processor


def test_the_draw_list_binds_board_art_to_live_values(api: SimulatorApi):
    """Art on disk plus state from the wire must actually meet.

    This is the cell behind `webui.ui.board-canvas` and `webui.ui.led-render`:
    a region id in the shipped `.map` resolves to a value the simulator is
    reporting right now. If the naming convention ever drifts, every region
    goes unbound and this fails rather than rendering a dead board.
    """
    from webui.assets import load_board
    from webui.render_model import build, parse_info

    state = parse_info(api.info())
    model = build(state, load_board(state.board))

    assert model["regions"], "the board's art declares no regions"
    bound = [r for r in model["regions"] if r["value"] is not None]
    assert bound, (
        f"{state.board}: no region bound to live state. Reported outputs were "
        f"{[e.name for e in state.board_outputs]}; art declares "
        f"{[r['id'] for r in model['regions']]}."
    )


def test_the_on_board_led_reports_a_changing_value_while_running(api: SimulatorApi):
    """The blink firmware's LED must actually vary -- a still board is not live.

    Measured on 2026-08-12: sampling `board.out[01]` returned values spanning
    0 to 200. A single constant reading would mean the render loop is painting
    something that is not moving, which is the failure this whole differential
    suite exists to catch.

    **The value is not a raw pin state.** A later run of this same test found
    it sitting at 99-100 for two solid seconds -- almost exactly the mean of a
    0/200 square wave -- so the simulator reports something averaged, and a
    fixed number of samples at a fixed interval can legitimately see no change
    at all. The first version of this test asserted over exactly twenty samples
    and failed for that reason, not because anything was broken.

    So it polls until it sees a change, and only fails if none arrives in the
    whole window. That is still a real assertion: a dead LED never changes.

    Skips rather than fails when the board reports no outputs at all, because
    that is a property of the board, not a defect -- but an unreachable
    simulator still fails, via the `api` fixture.
    """
    import time

    from webui.render_model import parse_info

    if not parse_info(api.info()).board_outputs:
        pytest.skip("this board reports no on-board outputs to sample")

    api.run()
    deadline = time.monotonic() + 6.0
    seen = set()
    while time.monotonic() < deadline and len(seen) < 2:
        seen.add(parse_info(api.info()).board_outputs[0].value)
        time.sleep(0.05)

    assert len(seen) > 1, (
        f"the on-board output never moved off {seen} in six seconds of "
        f"running. Either the firmware is not blinking or the value is not "
        f"live -- check the simulator is actually running with `sim`."
    )


def test_every_shipped_schema_matches_a_really_placed_part(api: SimulatorApi):
    """Place each peripheral and check the schema against what it reports.

    Arity is the cheapest strong check a schema can face (peripherals design
    §8.2): the field count of a real `sprdcfg` reply must equal the schema's.
    It catches the most likely authoring error, and it is the check that
    cannot be satisfied by reading the source wrongly, because the part
    answers for itself.

    The round-trip then proves storage and that settings survive a pin write --
    the case that found `_values` truncating `2.500000` to `2` on an LDR.

    What none of this proves is **field order**: a transposed schema
    round-trips perfectly clean (docs/known-issues.md §4b). Only a human
    re-reading the cited `sprintf` catches that.

    This places and deletes every schema'd part in one run, which is the
    pattern that triggers the intermittent crash in known-issues 4a.7. If this
    errors, check the simulator is still alive before suspecting a schema:
    `wsl -d Ubuntu-22.04 -- pgrep picsimlab`. A dead simulator makes the rest
    of this file error too, which is the intended behaviour -- an unreachable
    oracle is a failure, never a skip.
    """
    import pathlib

    from webui.parts.schema import load_all_schemas

    schemas = load_all_schemas(
        pathlib.Path(__file__).resolve().parents[2] / "webui" / "parts" / "schemas"
    )
    api.client.command("spshow 1")
    api.client.try_command("spdel all")

    problems = []
    try:
        for name, schema in sorted(schemas.items()):
            index = api.place_part(name, 60, 60)
            try:
                fields = api.read_config(index).split(",")
                if len(fields) != schema.arity:
                    problems.append(
                        f"{name}: schema {schema.arity} fields, part reported "
                        f"{len(fields)}"
                    )
                    continue
                pins = schema.pin_fields
                if not pins:
                    continue
                label = pins[0][1].label
                before = api.read_wiring(index, schema)
                api.connect(index, schema, label, 7)
                after = api.read_wiring(index, schema)
                if after[label] != 7:
                    problems.append(f"{name}: wrote 7 to {label}, read {after[label]}")
                changed = [
                    f.label
                    for f in schema.fields
                    if f.role != "pin" and after[f.label] != before[f.label]
                ]
                if changed:
                    problems.append(f"{name}: pin write disturbed settings {changed}")
            finally:
                api.client.try_command(f"spdel {index}")
    finally:
        api.client.try_command("spdel all")

    assert not problems, "\n".join(problems)


@pytest.fixture
def buttons(api):
    """Place a Push Buttons part and yield (index, schema). Cleans up after."""
    import pathlib

    from webui.parts.schema import load_all_schemas

    schemas = load_all_schemas(
        pathlib.Path(__file__).resolve().parents[2] / "webui" / "parts" / "schemas"
    )
    api.client.command("spshow 1")
    index = api.place_part("Push Buttons", 100, 100)
    yield index, schemas["Push Buttons"]
    api.client.try_command(f"spdel {index}")


def test_a_placed_part_matches_its_schema_arity(api, buttons):
    """The cheapest proof a schema describes the running part."""
    index, schema = buttons
    wiring = api.read_wiring(index, schema)
    assert len(wiring) == schema.arity


def test_a_freshly_placed_part_has_no_connections(api, buttons):
    index, schema = buttons
    wiring = api.read_wiring(index, schema)
    assert all(wiring[f.label] == 0 for _, f in schema.pin_fields)


def test_a_wiring_change_round_trips(api, buttons):
    """Write a pin, read it back. Proves configuration, NOT conduction.

    Nothing here shows a signal reaches the pin. This asserts only that the
    simulator stored what it was told.

    An earlier version of this docstring blamed `get part[N].in[M]` returning
    ERROR on a headlessly placed part. That was withdrawn on 2026-08-12: the
    index has to be zero-padded, and `get part[00].in[00]` works
    (docs/known-issues.md 4a.8). Conduction is still unproven, for the smaller
    reason that a written input value reads back 16 whether 0 or 1 was sent.
    """
    index, schema = buttons
    api.connect(index, schema, "B1", 7)
    assert api.read_wiring(index, schema)["B1"] == 7

    api.disconnect(index, schema, "B1")
    assert api.read_wiring(index, schema)["B1"] == 0


def test_settings_survive_a_pin_write(api, buttons):
    """connect() rewrites the whole string, so it must not disturb settings."""
    index, schema = buttons
    before = api.read_wiring(index, schema)
    api.connect(index, schema, "B2", 5)
    after = api.read_wiring(index, schema)
    assert after["active"] == before["active"]
    assert after["Size"] == before["Size"]
