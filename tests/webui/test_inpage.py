# OpenHardware - the in-tab transport answers as the loopback server does.
#
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 the OpenHardware authors. See LICENSE.
"""`webui.inpage.InPage` against `webui/emulator_server.py`, request for request.

The static site's whole claim is that only the transport changed: the page
posts the same requests, and a Worker answers them with the same Python. The
oracle is therefore differential -- each request goes to a real server on a
loopback port and to an `InPage`, both fresh, and the two must agree on the
status and on every byte of the decoded JSON. A refusal is a request too, so
the list carries one of each kind the page can meet.

Three routes are meant to differ and each has its own test: `/api/boards`
(never buildable in a tab), `/api/board/compile` and `/api/board/artefacts`
(both need the server's machine).

This runs the NATIVE cores, so it says the mapping around `handle_api` is the
server's. That the same Python gives the same answers on the wasm cores under
Pyodide is `test_site_pyodide.py`'s.
"""

from __future__ import annotations

import base64
import http.client
import json
import pathlib
import threading

import pytest

from core.i8086 import abi
from webui import emulator, emulator_server, inpage

TESTS = pathlib.Path(__file__).resolve().parents[1]

#: Prints "hello, world\n" on UART0, linked past the RP2040's boot2.
HELLO = TESTS / "cortexm0" / "uart" / "hello.bin"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


#: (verb, target, body): every route the page calls, then every refusal it
#: can meet, in an order that leaves each machine in the state the next needs.
STEPS = (
    ("GET", "/api/targets", ""),
    ("GET", "/api/samples", ""),
    ("GET", "/api/state?at=0x100&len=16", ""),
    ("POST", "/api/load", json.dumps({"hex": emulator.SAMPLES[0].hex})),
    ("POST", "/api/step", "{}"),
    ("POST", "/api/run", json.dumps({"steps": 1000})),
    ("GET", "/api/state", ""),
    ("POST", "/api/reset", "{}"),
    ("POST", "/api/load", json.dumps({"hex": emulator.SAMPLES[2].hex})),
    ("POST", "/api/run", ""),
    ("GET", "/api/state?at=0x200&len=8", ""),
    ("GET", "/api/run", ""),
    ("POST", "/api/load", json.dumps({"hex": "zz"})),
    ("POST", "/api/run", "not json"),
    ("POST", "/api/run", "[1, 2]"),
    ("POST", "/api/run", json.dumps({"steps": "many"})),
    ("GET", "/api/state?at=zz", ""),
    ("GET", "/api/no-such-route", ""),
    ("GET", "/api/board/state", ""),
    ("POST", "/api/board/load", json.dumps({"board": "No Such Board",
                                            "image": b64(b"\x00" * 8)})),
    ("POST", "/api/board/load", json.dumps({"board": "XIAO-RP2040-DIP",
                                            "image": "!!not base64!!"})),
    ("POST", "/api/board/load", json.dumps({"board": "XIAO-RP2040-DIP",
                                            "image": b64(b"\x00" * 8)})),
    ("POST", "/api/board/load", json.dumps({"board": "XIAO-RP2040-DIP",
                                            "image": b64(HELLO.read_bytes()),
                                            "base": "0x10000100"})),
    ("POST", "/api/board/run", json.dumps({"steps": 20000})),
    ("GET", "/api/board/state?at=0x20000000&len=16", ""),
    ("GET", "/api/board/pins", ""),
    ("GET", "/api/board/pins?board=Arduino%20Uno", ""),
    ("POST", "/api/board/step?words=0xd0000004", json.dumps({"count": 1})),
    ("POST", "/api/board/drive", json.dumps({"board": "Arduino Uno",
                                             "levels": {}})),
    ("GET", "/api/board/drive", ""),
)


@pytest.fixture(scope="module")
def core():
    """The native i8086 core, or skip the module saying why."""
    try:
        return abi.load()
    except abi.AbiError as exc:
        pytest.skip(f"i8086 core unavailable: {exc}")


@pytest.fixture
def server(core):
    """A real loopback server, as `python webui/emulator_server.py` starts it."""
    live = emulator_server.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=live.serve_forever, daemon=True)
    thread.start()
    try:
        yield live.server_address[:2]
    finally:
        live.shutdown()
        live.server_close()
        thread.join(timeout=5)


def over_http(address: tuple[str, int], verb: str, target: str,
              body: str) -> tuple[int, object]:
    """One request to the server, its status and decoded JSON."""
    connection = http.client.HTTPConnection(*address, timeout=30)
    try:
        headers = {"Content-Type": "application/json"} if verb == "POST" else {}
        connection.request(verb, target, body=body.encode() if verb == "POST" else None,
                           headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def in_page(page: inpage.InPage, verb: str, target: str,
            body: str) -> tuple[int, object]:
    status, text = page.answer(verb, target, body)
    return status, json.loads(text)


def test_every_request_the_page_makes_is_answered_as_the_server_answers_it(server):
    page = inpage.InPage()
    for verb, target, body in STEPS:
        expected = over_http(server, verb, target, body)
        got = in_page(page, verb, target, body)
        assert got == expected, f"{verb} {target} {body[:60]!r}"


def test_the_board_the_steps_load_does_print_on_its_uart(core):
    """A guard on the test above: agreeing on a board that never ran would
    prove nothing, so the steps must actually reach a running core."""
    page = inpage.InPage()
    page.answer("POST", "/api/board/load", json.dumps({
        "board": "XIAO-RP2040-DIP", "image": b64(HELLO.read_bytes()),
        "base": "0x10000100"}))
    page.answer("POST", "/api/board/run", json.dumps({"steps": 20000}))
    status, state = in_page(page, "GET", "/api/board/state", "")
    assert (status, state["uart"]["text"]) == (200, "hello, world\n")


def test_no_board_is_buildable_in_a_tab_and_the_rest_of_the_list_is_the_servers(server):
    status, listed = in_page(inpage.InPage(), "GET", "/api/boards", "")
    expected_status, expected = over_http(server, "GET", "/api/boards", "")
    assert status == expected_status == 200
    assert {board["buildable"] for board in listed["boards"]} == {False}
    assert listed == {**expected, "boards": [{**board, "buildable": False}
                                             for board in expected["boards"]]}


def test_compiling_answers_that_it_needs_the_server(core):
    status, reply = in_page(inpage.InPage(), "POST", "/api/board/compile",
                            json.dumps({"board": "Arduino Uno", "source": ""}))
    assert (status, reply) == (400, {"error": inpage.NO_COMPILER})


def test_compiling_by_get_is_refused_as_a_mutation_first(server):
    assert (in_page(inpage.InPage(), "GET", "/api/board/compile", "")
            == over_http(server, "GET", "/api/board/compile", ""))


def test_artefact_search_is_off_and_names_the_server(core):
    status, reply = in_page(inpage.InPage(), "GET", "/api/board/artefacts", "")
    assert (status, reply) == (200, {"enabled": False, "note": inpage.NO_SEARCH,
                                     "artefacts": []})


def test_a_body_past_the_ceiling_is_refused_as_the_server_refuses_it(server, monkeypatch):
    monkeypatch.setattr(emulator_server, "MAX_BODY_BYTES", 64)
    body = json.dumps({"hex": "90" * 64})
    expected = over_http(server, "POST", "/api/load", body)
    assert expected[0] == 413
    assert in_page(inpage.InPage(), "POST", "/api/load", body) == expected


def test_a_verb_the_server_has_no_handler_for_is_501(core):
    status, reply = in_page(inpage.InPage(), "PUT", "/api/run", "{}")
    assert (status, reply) == (501, {"error": "unsupported method 'PUT'"})
