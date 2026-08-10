# OpenHardware — tests for the rcontrol protocol client.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pytest

from tests.webui.stub_rcontrol import BANNER, OK, StubRControl, ok
from webui.rcontrol import (
    RControlClient,
    RControlCommandError,
    RControlConnectionError,
    RControlProtocolError,
)


def client_for(stub: StubRControl, timeout: float = 2.0) -> RControlClient:
    return RControlClient(host="127.0.0.1", port=stub.port, timeout=timeout)


# --- connection and framing ------------------------------------------------


def test_connect_consumes_the_banner():
    with StubRControl() as stub, client_for(stub) as client:
        assert "PICSimLab Remote Control Interface" in client.banner
        assert client.banner.endswith("\r\n>")


def test_a_command_returns_a_framed_ok():
    with StubRControl() as stub, client_for(stub) as client:
        response = client.command("version")
        assert response.ok
        assert stub.received == ["version"]


def test_body_excludes_status_and_terminator():
    with StubRControl({"pins": ok("pin[01] = 1\r\npin[02] = 0")}) as stub:
        with client_for(stub) as client:
            response = client.command("pins")
        assert response.ok
        assert response.lines == ["pin[01] = 1", "pin[02] = 0"]
        assert "Ok" not in response.body
        assert ">" not in response.body


def test_a_reply_with_no_body_is_still_a_success():
    # An empty body is a real outcome, distinct from a failure.
    with StubRControl({"reset": OK}) as stub, client_for(stub) as client:
        response = client.command("reset")
        assert response.ok
        assert response.body == ""
        assert response.lines == []


def test_a_multi_chunk_reply_is_reassembled():
    big = ok("\r\n".join(f"pin[{n:02}] = 1" for n in range(2000)))
    with StubRControl({"pinsl": big}) as stub, client_for(stub) as client:
        assert len(client.command("pinsl").lines) == 2000


# --- failure modes: each must raise, never return ---------------------------


def test_error_status_raises_and_carries_the_response():
    with StubRControl({"set pin[99] = 1": "ERROR\r\n>"}) as stub:
        with client_for(stub) as client:
            with pytest.raises(RControlCommandError) as caught:
                client.command("set pin[99] = 1")
            assert caught.value.args[1].ok is False


def test_try_command_returns_the_failure_instead_of_raising():
    with StubRControl({"get part[99].in[0]": "ERROR\r\n>"}) as stub:
        with client_for(stub) as client:
            response = client.try_command("get part[99].in[0]")
        assert response.ok is False


def test_silence_raises_rather_than_returning_empty():
    # The defect this whole module exists to prevent: a simulator that never
    # answers must not look like a simulator that answered with nothing.
    with StubRControl(behaviour="silent") as stub:
        with client_for(stub, timeout=0.4) as client:
            with pytest.raises(RControlConnectionError, match="timed out"):
                client.command("pins")


def test_a_peer_closing_mid_message_raises():
    with StubRControl(behaviour="close_early") as stub:
        with client_for(stub, timeout=2.0) as client:
            with pytest.raises(RControlConnectionError, match="closed before"):
                client.command("pins")


def test_an_unknown_status_word_raises_a_protocol_error():
    with StubRControl({"pins": "something\r\nMAYBE\r\n>"}) as stub:
        with client_for(stub) as client:
            with pytest.raises(RControlProtocolError, match="expected"):
                client.command("pins")


def test_connecting_to_a_closed_port_raises():
    with StubRControl() as stub:
        port = stub.port
    client = RControlClient(host="127.0.0.1", port=port, timeout=0.4)
    with pytest.raises(RControlConnectionError, match="cannot reach"):
        client.connect()


def test_a_server_that_never_sends_a_banner_raises():
    with StubRControl(behaviour="no_banner") as stub:
        client = client_for(stub, timeout=1.0)
        with pytest.raises(RControlConnectionError):
            client.connect()


# --- misuse ----------------------------------------------------------------


def test_commanding_before_connecting_raises():
    client = RControlClient(port=1)
    with pytest.raises(Exception, match="not connected"):
        client.command("version")


def test_a_multiline_command_is_rejected():
    # Two commands in one send would desynchronise the framing.
    with StubRControl() as stub, client_for(stub) as client:
        with pytest.raises(ValueError, match="single line"):
            client.command("pins\nversion")


def test_connecting_twice_raises():
    with StubRControl() as stub, client_for(stub) as client:
        with pytest.raises(Exception, match="already connected"):
            client.connect()


def test_close_is_idempotent():
    with StubRControl() as stub:
        client = client_for(stub)
        client.connect()
        client.close()
        client.close()
