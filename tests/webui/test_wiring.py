# OpenHardware — tests for the schema-aware wiring API.
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2, or (at your option) any later version.

import pytest

from tests.webui.stub_rcontrol import StubRControl, ok
from webui.api import SimulatorApi
from webui.parts.schema import PartSchema, load_all_schemas
from webui.rcontrol import RControlClient

import pathlib

SCHEMAS = load_all_schemas(
    pathlib.Path(__file__).resolve().parents[2] / "webui" / "parts" / "schemas"
)
BUTTONS: PartSchema = SCHEMAS["Push Buttons"]
FRESH = "0,0,0,0,0,0,0,0,1,0,8"


def api_for(stub: StubRControl):
    client = RControlClient(host="127.0.0.1", port=stub.port, timeout=2.0)
    client.connect()
    return SimulatorApi(client), client


def test_part_count_probes_until_error():
    # There is no count command; sprdcfg N errors past the last part.
    replies = {"sprdcfg 0": ok(FRESH), "sprdcfg 1": ok(FRESH), "sprdcfg 2": "ERROR\r\n>"}
    with StubRControl(replies) as stub:
        api, client = api_for(stub)
        assert api.part_count() == 2
        client.close()


def test_part_count_is_zero_when_the_first_probe_errors():
    with StubRControl({"sprdcfg 0": "ERROR\r\n>"}) as stub:
        api, client = api_for(stub)
        assert api.part_count() == 0
        client.close()


def test_place_part_returns_the_new_index():
    replies = {
        "sprdcfg 0": "ERROR\r\n>",
        'spadd "Push Buttons" 100 200': ok(),
    }
    with StubRControl(replies) as stub:
        api, client = api_for(stub)
        assert api.place_part("Push Buttons", 100, 200) == 0
        client.close()
    assert 'spadd "Push Buttons" 100 200' in stub.received


def test_read_wiring_maps_labels_to_values():
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        wiring = api.read_wiring(0, BUTTONS)
        client.close()
    assert wiring["B1"] == 0
    assert wiring["active"] == 1
    assert wiring["Size"] == 8


def test_connect_rewrites_only_the_named_field():
    # The quotes matter: rcontrol.cc:1307 scans `%d "%511[^"]"`, so an
    # unquoted config never reaches the part.
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        api.connect(0, BUTTONS, "B3", 7)
        client.close()
    assert 'spwrcfg 0 "0,0,7,0,0,0,0,0,1,0,8"' in stub.received


def test_disconnect_sets_the_field_to_zero():
    wired = "0,0,7,0,0,0,0,0,1,0,8"
    with StubRControl({"sprdcfg 0": ok(wired)}) as stub:
        api, client = api_for(stub)
        api.disconnect(0, BUTTONS, "B3")
        client.close()
    assert 'spwrcfg 0 "0,0,0,0,0,0,0,0,1,0,8"' in stub.received


def test_connecting_a_setting_field_is_refused():
    # Wiring an angle to a GPIO is nonsense; the schema's roles exist to stop it.
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        with pytest.raises(Exception, match="not a pin"):
            api.connect(0, BUTTONS, "Size", 3)
        client.close()


def test_a_config_of_the_wrong_arity_raises():
    # Arity is the cheapest check that a schema matches the running part.
    with StubRControl({"sprdcfg 0": ok("1,2,3")}) as stub:
        api, client = api_for(stub)
        with pytest.raises(Exception, match="arity"):
            api.read_wiring(0, BUTTONS)
        client.close()


def test_an_unknown_label_raises():
    with StubRControl({"sprdcfg 0": ok(FRESH)}) as stub:
        api, client = api_for(stub)
        with pytest.raises(Exception, match="no field labelled"):
            api.connect(0, BUTTONS, "nonexistent", 1)
        client.close()
