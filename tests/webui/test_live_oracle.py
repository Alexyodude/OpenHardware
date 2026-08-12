# OpenHardware — differential tests against a live PICSimLab.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.
"""Check the client against a running simulator rather than against a stub.

Everything else under ``tests/webui/`` talks to ``stub_rcontrol.py``, which
encodes *my reading* of ``src/lib/rcontrol.cc``. A stub cannot disconfirm a
misreading: if I misunderstood the protocol, the stub misunderstands it the same
way and the suite stays green. Only a real server is ground truth, which is why
the cells in ``docs/features/webui.md`` stay ``in-progress`` until these run.

**Skipping here is dangerous, so it is opt-in.** By default these skip when no
simulator is listening, because most runs happen without one. But a skip that
looks like a pass is exactly the defect
``.claude/rules/conformance-fixtures.md`` section 4 was written about — upstream's
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

    The supported path is spare parts — `spadd`, then `set part[N].in[M]` — which
    is how PICSimLab models buttons and potentiometers. That path is blocked on
    this machine because part assets are not installed, and placing a part
    without them segfaults the simulator (docs/known-issues.md).

    This test pins the current, surprising behaviour so that if a future version
    makes pin writes observable, it fails and tells us the model changed.
    """
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

    Nothing here shows a signal reaches the pin — that needs
    get part[N].in[M], which returns ERROR on a headlessly placed part
    (docs/known-issues.md 4a.5). This asserts only that the simulator stored
    what it was told.
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
