# OpenHardware — tests for the typed API over rcontrol.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pytest

from tests.webui.stub_rcontrol import StubRControl, ok
from webui.api import ApiError, SimulatorApi, parse_pins, parse_quoted_list
from webui.rcontrol import RControlClient, Response

# Exactly the shape rcontrol.cc:1091 and :1095 emit.
PINS_BODY = (
    "3 pins [atmega328p]:\r\n"
    '  pin[01] D I 1 000 0.000 "PD0     " \r\n'
    '  pin[02] A O 0 145 3.300 "PC0     " \r\n'
    '  pin[03] D O 1 000 5.000 "PB5     " '
)


def api_for(stub: StubRControl) -> tuple[SimulatorApi, RControlClient]:
    client = RControlClient(host="127.0.0.1", port=stub.port, timeout=2.0)
    client.connect()
    return SimulatorApi(client), client


def response(body: str) -> Response:
    return Response(ok=True, body=body, raw=body + "\r\nOk\r\n>")


# --- pin parsing ------------------------------------------------------------


def test_pins_parse_every_documented_field():
    pins = parse_pins(response(PINS_BODY))
    assert len(pins) == 3

    first, second, third = pins
    assert (first.index, first.type, first.direction) == (1, "D", "I")
    assert first.value == 1 and first.name == "PD0"
    assert first.is_input

    assert second.type == "A" and second.direction == "O"
    assert second.oavalue_raw == 145  # verbatim; rcontrol sends oavalue - 55
    assert second.avalue == pytest.approx(3.300)
    assert not second.is_input

    assert third.avalue == pytest.approx(5.0)


def test_a_pin_count_mismatch_raises():
    # The header is a checksum on the body. Trusting one while ignoring the
    # other would let a truncated reply look like a short board.
    body = PINS_BODY.replace("3 pins", "9 pins")
    with pytest.raises(ApiError, match="promised 9"):
        parse_pins(response(body))


def test_a_reply_with_no_header_raises_rather_than_guessing():
    body = '  pin[01] D I 1 000 0.000 "PD0     " '
    with pytest.raises(ApiError, match="no header"):
        parse_pins(response(body))


def test_an_unparseable_pin_line_raises():
    body = "1 pins [x]:\r\n  pin[01] this is not the format"
    with pytest.raises(ApiError, match="unparseable"):
        parse_pins(response(body))


def test_a_board_with_no_pins_is_valid():
    assert parse_pins(response("0 pins [none]:")) == []


# --- quoted list parsing ----------------------------------------------------


def test_quoted_lists_are_parsed():
    body = 'Supported Spare Parts:\r\n"LED", "Push Button", "Potentiometer", '
    assert parse_quoted_list(response(body)) == ["LED", "Push Button", "Potentiometer"]


def test_an_empty_quoted_list_is_empty_not_an_error():
    assert parse_quoted_list(response("Supported Spare Parts:\r\n")) == []


# --- command construction ---------------------------------------------------
# These assert the exact wire text, because the server parses by substring
# (`strstr(cmd, " pin[")`) and is unforgiving about the bracket forms.


def test_pin_writes_use_the_two_digit_form_the_server_scans_for():
    with StubRControl() as stub:
        api, client = api_for(stub)
        api.set_pin(7, 1)
        api.set_apin(3, 3.3)
        api.set_board_input(12, 0)
        api.set_part_input(2, 5, 1)
        client.close()
    assert stub.received == [
        "set pin[07] = 1",
        "set apin[03] = 3.3",
        "set board.in[12] = 0",
        "set part[2].in[5] = 1",
    ]


def test_reads_use_the_documented_forms():
    replies = {
        "get pin[04]": ok("get pin[04] PD4= 1"),
        "get apin[02]": ok("get apin[02] AN2= 2.500"),
        "get board.out[01]": ok("get board.out[01] LD1= 1"),
        "get part[0].out[1]": ok("get part[0].out[1] LED= 0"),
    }
    with StubRControl(replies) as stub:
        api, client = api_for(stub)
        assert api.get_pin(4) == pytest.approx(1)
        assert api.get_apin(2) == pytest.approx(2.5)
        assert api.get_board_output(1) == pytest.approx(1)
        assert api.get_part_output(0, 1) == pytest.approx(0)
        client.close()


def test_run_control_sends_the_documented_commands():
    with StubRControl() as stub:
        api, client = api_for(stub)
        api.run()
        api.pause()
        api.reset()
        api.load_firmware("/tmp/blink.hex")
        client.close()
    assert stub.received == ["sim 1", "sim 0", "reset", "loadhex /tmp/blink.hex"]


def test_part_lifecycle_commands():
    with StubRControl({"splist": ok('"LED", "Buzzer", ')}) as stub:
        api, client = api_for(stub)
        assert api.supported_parts() == ["LED", "Buzzer"]
        api.add_part("LED")
        api.remove_part(3)
        client.close()
    assert stub.received == ["splist", "spadd LED", "spdel 3"]


def test_a_get_reply_with_no_value_raises():
    with StubRControl({"get pin[01]": ok("nothing useful here")}) as stub:
        api, client = api_for(stub)
        with pytest.raises(ApiError, match="no `= value`"):
            api.get_pin(1)
        client.close()
