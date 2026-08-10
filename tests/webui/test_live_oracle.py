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
    """The `pins` parser follows rcontrol.cc:1095. This proves I read it right."""
    pins = parse_pins(live.command("pins"))
    assert pins, "a loaded board should report at least one pin"
    assert all(pin.name for pin in pins)
    assert all(pin.direction in ("I", "O") for pin in pins)


def test_supported_boards_parse(api: SimulatorApi):
    assert api.supported_boards()


def test_supported_parts_parse(api: SimulatorApi):
    assert api.supported_parts()


# --- a write is only real if a read confirms it ------------------------------


def test_writing_a_pin_is_observable(api: SimulatorApi):
    """The whole UI premise: an action must be readable back.

    If this fails, every `set` the browser issues is a no-op that reports Ok,
    which would make the interface a convincing liar.
    """
    pins = api.pins()
    target = next((p for p in pins if p.direction == "O"), pins[0])

    before = api.get_pin(target.index)
    api.set_pin(target.index, 0 if before else 1)
    after = api.get_pin(target.index)

    assert after != before, (
        f"pin[{target.index:02}] read back {after} after being set to "
        f"{0 if before else 1}; the write did not take effect"
    )


# --- differential: the typed API must agree with raw protocol text -----------


def test_the_typed_api_agrees_with_the_raw_command(live: RControlClient):
    """Same question, two routes, one answer.

    The API layer must not quietly reinterpret what the server said.
    """
    api = SimulatorApi(live)
    raw = live.command("pins")
    assert len(api.pins()) == len(parse_pins(raw))


def test_pin_count_matches_the_header(live: RControlClient):
    """The header is the server's own checksum on its body."""
    response = live.command("pins")
    header = next(line for line in response.lines if "pins [" in line)
    promised = int(header.split()[0])
    assert len(parse_pins(response)) == promised
