# OpenHardware — tests for the typed API over rcontrol.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pytest

from tests.webui.stub_rcontrol import StubRControl, ok
from webui.api import (
    ApiError,
    SimulatorApi,
    parse_comma_list,
    parse_pins,
    parse_quoted_list,
)
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


# --- regressions for three bugs a live simulator found ----------------------
# Each of these passed review and passed against the stub while being wrong.
# Only a real PICSimLab 0.9.3 exposed them, on 2026-08-10.


def test_blist_is_bare_comma_separated_not_quoted():
    """`blist` does not quote its names; only `splist` does.

    Using the quoted parser here returned [] silently -- a board list that is
    empty rather than an error, which is the failure mode this repo is built
    to catch. Verbatim from a live server:
    """
    body = (
        "Supported Boards:\r\n"
        " Arduino_Mega, Arduino_Nano, Arduino_Uno, Blue_Pill, Breadboard, "
        "Curiosity, McLab1, Remote_TCP, gpboard, uCboard,"
    )
    names = parse_comma_list(response(body))
    assert "Arduino_Uno" in names
    assert "uCboard" in names
    assert parse_quoted_list(response(body)) == [], "quoted parser must fail here"


def test_pins_uses_pinsl_because_pins_has_a_different_format():
    """`pins` and `pinsl` are different commands with different output.

    The parser follows rcontrol.cc:1095, which serves `pinsl`. `pins` is a
    narrow two-column display -- `pin[01] ( PC6/RST) < 0    pin[15] ...` --
    that this parser cannot read. Sending `pins` failed on every line live.
    """
    with StubRControl({"pinsl": ok('1 pins [x]:\r\n  pin[01] D I 1 000 0.000 "PD0     " ')}) as stub:
        api, client = api_for(stub)
        assert len(api.pins()) == 1
        client.close()
    assert stub.received == ["pinsl"]


def test_add_part_quotes_the_name_and_sends_coordinates():
    """`spadd` parses `" \\"%99[^\\"]\\" %i %i"` -- quotes and both coords required.

    The first implementation sent `spadd LED`, which the server rejected every
    time.
    """
    with StubRControl() as stub:
        api, client = api_for(stub)
        api.add_part("Push Button", 100, 250)
        client.close()
    assert stub.received == ['spadd "Push Button" 100 250']


# --- command construction ---------------------------------------------------
# These assert the exact wire text, because the server parses by substring
# (`strstr(cmd, " pin[")`) and is unforgiving about the bracket forms.


def test_every_index_is_two_digits_including_both_halves_of_a_part_accessor():
    """Both indices of `part[NN].in[MM]` are two-digit, like every other one.

    This test previously asserted `set part[2].in[5] = 1` and passed, because
    the stub answers Ok to anything and the assertion encoded the same mistake
    the code made. A live server does not: `get part[0].in[0]` returns ERROR
    and `get part[00].in[00]` returns a value.

    rcontrol.cc:809-810 reads `(ptr[5]-'0')*10 + (ptr[6]-'0')` for the part
    number and the same for the input, and echoes `part[%02i].in[%02i]`.
    """
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
        "set part[02].in[05] = 1",
    ]


def test_reads_use_the_documented_forms():
    replies = {
        "get pin[04]": ok("get pin[04] PD4= 1"),
        "get apin[02]": ok("get apin[02] AN2= 2.500"),
        "get board.out[01]": ok("get board.out[01] LD1= 1"),
        "get part[00].out[01]": ok("get part[00].out[01] LED= 0"),
    }
    with StubRControl(replies) as stub:
        api, client = api_for(stub)
        assert api.get_pin(4) == pytest.approx(1)
        assert api.get_apin(2) == pytest.approx(2.5)
        assert api.get_board_output(1) == pytest.approx(1)
        assert api.get_part_output(0, 1) == pytest.approx(0)
        client.close()


def test_an_index_too_wide_to_express_raises_rather_than_addressing_another():
    """100 cannot be written in two characters, so it must not be sent.

    Silently truncating or overflowing would address a different, valid
    element and report success -- the miswiring-reported-as-success failure
    this API already had once, with pin values wrapping mod 256.
    """
    for call in (
        lambda api: api.get_pin(100),
        lambda api: api.set_board_input(100, 1),
        lambda api: api.get_part_input(100, 0),
        lambda api: api.get_part_input(0, 100),
    ):
        with StubRControl() as stub:
            api, client = api_for(stub)
            with pytest.raises(ApiError, match="outside 0..99"):
                call(api)
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
        api.add_part("LED", 10, 20)
        api.remove_part(3)
        client.close()
    # spadd requires the quoted name and both coordinates; see add_part.
    assert stub.received == ["splist", 'spadd "LED" 10 20', "spdel 3"]


def test_a_get_reply_with_no_value_raises():
    with StubRControl({"get pin[01]": ok("nothing useful here")}) as stub:
        api, client = api_for(stub)
        with pytest.raises(ApiError, match="no `= value`"):
            api.get_pin(1)
        client.close()
