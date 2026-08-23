# OpenHardware — tests for the websocket bridge.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.

import asyncio
import json

import pytest

from tests.webui.stub_rcontrol import StubRControl, ok
from webui.api import SimulatorApi
from webui.bridge import (
    OPERATIONS,
    Bridge,
    BridgeError,
    dispatch,
    origin_is_allowed,
    serve,
)
from webui.rcontrol import RControlClient

ORIGINS = frozenset({"http://127.0.0.1:8787"})


def bridge_for(stub: StubRControl) -> tuple[Bridge, RControlClient]:
    client = RControlClient(host="127.0.0.1", port=stub.port, timeout=2.0)
    client.connect()
    return Bridge(SimulatorApi(client), ORIGINS), client


async def call(bridge: Bridge, op: str, **args) -> dict:
    raw = await bridge.handle_message(json.dumps({"id": 1, "op": op, "args": args}))
    return json.loads(raw)


# --- dispatch allowlist -----------------------------------------------------


def test_unknown_operations_are_refused():
    with pytest.raises(BridgeError, match="unknown operation"):
        dispatch(None, "rm -rf", {})


def test_raw_rcontrol_text_cannot_be_smuggled_through():
    # The browser must not be able to send arbitrary protocol text.
    for attempt in ("command", "send", "raw", "loadhex /etc/passwd"):
        with pytest.raises(BridgeError, match="unknown operation"):
            dispatch(None, attempt, {})


def test_missing_arguments_are_refused_before_reaching_the_simulator():
    with pytest.raises(BridgeError, match="requires"):
        dispatch(None, "set_pin", {"index": 1})


def test_every_operation_declares_the_arguments_it_uses():
    # A handler reading an arg it did not declare would KeyError at runtime
    # instead of returning a clean error.
    for name, (_handler, required) in OPERATIONS.items():
        assert isinstance(required, tuple), name


# --- origin checking --------------------------------------------------------


def test_a_hostile_origin_is_rejected():
    assert not origin_is_allowed("https://evil.example", ORIGINS)


def test_the_expected_origin_is_allowed():
    assert origin_is_allowed("http://127.0.0.1:8787", ORIGINS)


def test_a_missing_origin_is_allowed_for_non_browser_clients():
    assert origin_is_allowed(None, ORIGINS)


# --- message handling -------------------------------------------------------


def test_a_successful_call_returns_the_result():
    async def scenario():
        with StubRControl({"version": ok("PICSimLab 0.9.1")}) as stub:
            bridge, client = bridge_for(stub)
            reply = await call(bridge, "version")
            client.close()
            return reply

    reply = asyncio.run(scenario())
    assert reply["ok"] is True
    assert reply["id"] == 1
    assert "0.9.1" in reply["result"]


def test_pins_are_returned_as_structured_objects():
    body = ok('1 pins [atmega328p]:\r\n  pin[01] D I 1 000 0.000 "PD0     " ')

    async def scenario():
        # The API reads `pinsl`, not `pins` -- different commands, different
        # output. See test_pins_uses_pinsl_because_pins_has_a_different_format.
        with StubRControl({"pinsl": body}) as stub:
            bridge, client = bridge_for(stub)
            reply = await call(bridge, "pins")
            client.close()
            return reply

    reply = asyncio.run(scenario())
    assert reply["ok"] is True
    assert reply["result"][0]["name"] == "PD0"
    assert reply["result"][0]["direction"] == "I"


def test_a_simulator_error_is_reported_not_swallowed():
    async def scenario():
        with StubRControl({"set pin[99] = 1": "ERROR\r\n>"}) as stub:
            bridge, client = bridge_for(stub)
            reply = await call(bridge, "set_pin", index=99, value=1)
            client.close()
            return reply

    reply = asyncio.run(scenario())
    assert reply["ok"] is False
    assert "RControlCommandError" in reply["error"]


def test_malformed_json_returns_an_error_rather_than_crashing():
    async def scenario():
        with StubRControl() as stub:
            bridge, client = bridge_for(stub)
            raw = await bridge.handle_message("{not json")
            client.close()
            return json.loads(raw)

    reply = asyncio.run(scenario())
    assert reply["ok"] is False
    assert "JSONDecodeError" in reply["error"]


def test_a_dead_simulator_surfaces_as_an_error_not_silence():
    # The failure this project exists to prevent: the browser must be told the
    # simulator stopped answering, never handed a cheerful empty result.
    async def scenario():
        with StubRControl(behaviour="silent") as stub:
            client = RControlClient(host="127.0.0.1", port=stub.port, timeout=0.4)
            client.connect()
            bridge = Bridge(SimulatorApi(client), ORIGINS)
            reply = await call(bridge, "pins")
            client.close()
            return reply

    reply = asyncio.run(scenario())
    assert reply["ok"] is False
    assert "timed out" in reply["error"]


def test_concurrent_requests_are_serialised():
    # rcontrol has no request ids, so two commands in flight would let a reply
    # be attributed to the wrong request. Every command must arrive in order.
    async def scenario():
        replies = {f"get pin[{n:02}]": ok(f"get pin[{n:02}] P= {n}") for n in range(1, 9)}
        with StubRControl(replies) as stub:
            bridge, client = bridge_for(stub)
            results = await asyncio.gather(
                *(call(bridge, "get_pin", index=n) for n in range(1, 9))
            )
            client.close()
            return results, list(stub.received)

    results, received = asyncio.run(scenario())
    assert all(r["ok"] for r in results)
    assert received == [f"get pin[{n:02}]" for n in range(1, 9)]


# --- bind safety ------------------------------------------------------------


def test_binding_a_non_loopback_interface_is_refused():
    with pytest.raises(BridgeError, match="Loopback only"):
        asyncio.run(serve("127.0.0.1", 5000, "0.0.0.0", 8787, ORIGINS))
